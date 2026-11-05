"""Local-only HTTP interface for the document workspace."""
import argparse
import base64
import binascii
import json
import secrets
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from . import __version__
from .common import ValidationError, digest
from .formats import MAX_UPLOAD_BYTES
from .service import Workspace
from .tabular_import import MAX_BYTES as MAX_TABLE_BYTES
from .tabular_import import parse_csv, parse_xlsx
from .report_export import word_report, table_report, ledger_report
from .backup import create_backup
from .sales_ledger import map_columns
from .service_status import status as model_status

STATIC = Path(__file__).parent / "static"
MAX_REQUEST = 33 * 1024 * 1024


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, workspace):
        if address[0] != "127.0.0.1":
            raise ValueError("此版本仅允许绑定127.0.0.1")
        self.workspace = workspace
        self.token = secrets.token_urlsafe(32)
        self.operation_lock = threading.RLock()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "EvidenceLocal/" + __version__
    timeout = 15

    def log_message(self, format, *args):
        # Filenames, source content and local tokens do not enter console logs.
        pass

    def respond(self, status, content, content_type, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        if filename:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename, safe=""))
        self.end_headers()
        self.wfile.write(content)

    def json(self, value, status=200):
        self.respond(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def allowed(self, mutation=False):
        port = self.server.server_port
        hosts = (f"127.0.0.1:{port}", f"localhost:{port}")
        if self.headers.get("Host") not in hosts:
            self.json({"error": "仅允许本机地址访问"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in tuple("http://" + host for host in hosts):
            self.json({"error": "拒绝跨站请求"}, 403)
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.json({"error": "拒绝跨站请求"}, 403)
            return False
        if mutation and not secrets.compare_digest(self.headers.get("X-Local-Token", ""), self.server.token):
            self.json({"error": "页面校验已失效，请刷新本机页面"}, 403)
            return False
        return True

    def dispatch(self, action):
        with self.server.operation_lock:
            try:
                action()
            except LookupError:
                self.json({"error": "资料不存在"}, 404)
            except ValidationError as error:
                self.json({"error": str(error)}, 400)
            except (ValueError, TypeError, binascii.Error):
                self.json({"error": "请求格式无效，请检查文件和字段"}, 400)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except socket.timeout:
                self.json({"error": "请求超时，请重试"}, 408)
            except Exception:
                self.json({"error": "本地处理失败，请检查数据目录和文件格式"}, 500)

    def do_GET(self):
        self.dispatch(self.get_request)

    def get_request(self):
        if not self.allowed():
            return
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/":
            content = (STATIC / "index.html").read_text(encoding="utf-8").replace("__LOCAL_TOKEN__", self.server.token)
            self.respond(200, content.encode("utf-8"), "text/html; charset=utf-8")
        elif path in ("/app.js", "/table-ui.js", "/analysis-ui.js", "/catalog-ui.js", "/ocr-ui.js", "/ledger-ui.js", "/semantic-ui.js", "/migration-ui.js", "/services-ui.js", "/style.css"):
            content_type = "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
            self.respond(200, (STATIC / path[1:]).read_bytes(), content_type)
        elif path == "/api/health":
            self.json({"status": "ok", "version": __version__, "milestone": "enterprise"})
        elif path == "/api/services":
            self.json(model_status())
        elif path == "/api/backup":
            self.respond(200,create_backup(self.server.workspace.store),'application/zip',filename='资料备份.zip')
        elif path == "/api/migration":
            with self.server.workspace.store.connect() as db:
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_reports'").fetchone()
                report=db.execute('SELECT payload FROM migration_reports ORDER BY id DESC LIMIT 1').fetchone() if exists else None
            self.json({'report':json.loads(report['payload']) if report else None})
        elif path == "/api/migration/previous-database":
            with self.server.workspace.store.connect() as db:
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_sources'").fetchone()
                row=db.execute("SELECT sha256 FROM migration_sources WHERE kind='previous_database' LIMIT 1").fetchone() if exists else None
            if not row: raise LookupError('旧版数据库不存在')
            data=self.server.workspace.store.blob(row['sha256']).read_bytes()
            if digest(data)!=row['sha256']: raise RuntimeError('旧版数据库完整性校验失败')
            self.respond(200,data,
                         'application/vnd.sqlite3',filename='previous-workspace.sqlite3')
        elif path == "/api/documents":
            self.json({"documents": self.server.workspace.documents()})
        elif path == "/api/catalog/list":
            self.json({'documents':[item | {'metadata':self.server.workspace.catalog.get(item['id'])} for item in self.server.workspace.documents()]})
        elif path == "/api/catalog":
            identifier = parse_qs(parsed.query).get('id', [''])[0]
            self.json(self.server.workspace.catalog.get(identifier))
        elif path == "/api/tables":
            self.json({"tables": self.server.workspace.tables.list()})
        elif path == "/api/table-results":
            self.json({'results':self.server.workspace.tables.results()})
        elif path == "/api/table":
            identifier=parse_qs(parsed.query).get('id',[''])[0]
            self.json(self.server.workspace.tables.preview(identifier))
        elif path == "/api/table-source":
            query=parse_qs(parsed.query)
            self.json(self.server.workspace.tables.source(query.get('id',[''])[0],query.get('location',[''])[0]))
        elif path == "/api/table-original":
            identifier=parse_qs(parsed.query).get('id',[''])[0]
            table=next((item for item in self.server.workspace.tables.list() if item['id']==identifier),None)
            if not table: raise LookupError('数据表不存在')
            content=self.server.workspace.store.blob(table['sha256']).read_bytes()
            if digest(content)!=table['sha256']: raise RuntimeError('原件完整性校验失败')
            self.respond(200,content,'application/octet-stream',filename=table['name'])
        elif path == "/api/table-metadata":
            identifier=parse_qs(parsed.query).get('id',[''])[0]
            self.json(self.server.workspace.tables.metadata(identifier))
        elif path == "/api/analyses":
            self.json({'analyses':self.server.workspace.analyses.history()})
        elif path == "/api/analysis":
            identifier = parse_qs(parsed.query).get('id', [''])[0]
            self.json(self.server.workspace.analyses.get(identifier))
        elif path == "/api/analysis-reviews":
            identifier=parse_qs(parsed.query).get('id',[''])[0]
            self.json({'reviews':self.server.workspace.analyses.reviews(identifier)})
        elif path == "/api/ocr":
            self.json({'drafts':self.server.workspace.ocr.list()})
        elif path == "/api/ledger/history":
            self.json({'snapshots':self.server.workspace.sales.history()})
        elif path == "/api/ledger/sources":
            identifier=parse_qs(parsed.query).get('id',[''])[0]
            self.json({'records':self.server.workspace.sales.sources(identifier)})
        elif path == "/api/ledger/original":
            identifier=parse_qs(parsed.query).get('id',[''])[0]
            with self.server.workspace.store.connect() as db:
                batch=db.execute('SELECT source_sha256,source_name FROM ledger_batches WHERE id=?',(identifier,)).fetchone()
            if not batch or not batch['source_sha256']: raise LookupError('批次原件不存在')
            content=self.server.workspace.store.blob(batch['source_sha256']).read_bytes()
            if digest(content)!=batch['source_sha256']: raise RuntimeError('原件完整性校验失败')
            self.respond(200,content,'application/octet-stream',filename=batch['source_name'] or '导入原件')
        elif path == "/api/ledger/recompute":
            identifier=parse_qs(parsed.query).get('id',[''])[0]
            self.json(self.server.workspace.sales.recompute(identifier))
        elif path == "/api/ledger/export":
            identifier=parse_qs(parsed.query).get('id',[''])[0]
            content=ledger_report(self.server.workspace.sales.get(identifier),self.server.workspace.sales.sources(identifier))
            self.respond(200,content,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename='订单退款核算.xlsx')
        elif path == "/api/ocr-original":
            identifier=parse_qs(parsed.query).get('id',[''])[0]
            draft=self.server.workspace.ocr.get(identifier)
            content=self.server.workspace.store.blob(draft['sha256']).read_bytes()
            if digest(content)!=draft['sha256']: raise RuntimeError('原图完整性校验失败')
            self.respond(200,content,'application/octet-stream',filename=draft['name'])
        elif path == "/api/analysis-export":
            identifier = parse_qs(parsed.query).get('id', [''])[0]
            content = word_report(self.server.workspace.analyses.get(identifier),self.server.workspace.analyses.reviews(identifier))
            self.respond(200,content,'application/vnd.openxmlformats-officedocument.wordprocessingml.document',filename='资料分析.docx')
        elif path == "/api/table-export":
            identifier = parse_qs(parsed.query).get('id', [''])[0]
            content = table_report(self.server.workspace.tables.result(identifier),self.server.workspace.tables.result_rows(identifier))
            self.respond(200,content,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename='数据统计.xlsx')
        elif path == "/api/table-result":
            identifier = parse_qs(parsed.query).get('id', [''])[0]
            self.json(self.server.workspace.tables.result(identifier))
        elif path == "/api/search":
            query = parse_qs(parsed.query, keep_blank_values=True)
            self.json(self.server.workspace.search(
                query.get("q", [""])[0],
                query.get("document_id", [""])[0] or None,
                int(query.get("limit", ["20"])[0]),
            ))
        elif path in ("/api/document-text", "/api/original"):
            document_id = parse_qs(parsed.query).get("id", [""])[0]
            if path == "/api/document-text":
                self.json(self.server.workspace.document_text(document_id))
            else:
                name, content = self.server.workspace.original(document_id)
                self.respond(200, content, "application/octet-stream", filename=name)
        else:
            self.json({"error": "页面或接口不存在"}, 404)

    def do_POST(self):
        self.dispatch(self.post_request)

    def post_request(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValidationError("请求长度无效") from None
        if not 0 < length <= MAX_REQUEST or self.headers.get("Transfer-Encoding"):
            self.json({"error": "请求为空或超过33 MiB限制"}, 413)
            return
        self.connection.settimeout(15)
        payload = self.rfile.read(length)
        if len(payload) != length:
            raise ValidationError("请求内容不完整")
        # Consume a bounded body before rejecting authorization so Windows
        # does not reset connections that still contain unread request bytes.
        if not self.allowed(mutation=True):
            return
        path = urlsplit(self.path).path
        if path not in ("/api/upload", "/api/tables", "/api/table-calculate", "/api/analyze", "/api/catalog", "/api/table-metadata", "/api/ocr", "/api/ocr-confirm", "/api/ledger/import", "/api/ledger/calculate", "/api/semantic/build", "/api/semantic/search", "/api/analysis-review"):
            self.json({"error": "接口不存在"}, 404)
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ValidationError("请求需要JSON格式")
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValidationError("请求格式无效")
        if path == '/api/semantic/build':
            self.json(self.server.workspace.semantic.build())
            return
        if path == '/api/semantic/search':
            self.json({'sources':self.server.workspace.semantic.search(data.get('query'))})
            return
        if path == '/api/ledger/calculate':
            self.json(self.server.workspace.sales.calculate(data.get('start'),data.get('end'),data.get('refund_cutoff'),
                data.get('refund_mode','cohort'),data.get('namespace',''),data.get('skus'),data.get('baseline_start'),data.get('baseline_end')),201)
            return
        if path == '/api/ledger/import':
            encoded=data.get('content')
            if not isinstance(encoded,str) or len(encoded)>((MAX_TABLE_BYTES+2)//3)*4:
                raise ValidationError('文件格式或大小无效')
            try: content=base64.b64decode(encoded,validate=True)
            except (binascii.Error,ValueError): raise ValidationError('文件内容编码无效') from None
            filename=data.get('name','')
            if not isinstance(filename,str) or not filename.lower().endswith(('.csv','.xlsx')):
                raise ValidationError('请选择 CSV 或 XLSX')
            table=parse_xlsx(content,data.get('header_row',1),data.get('sheet_name')) if filename.lower().endswith('.xlsx') else parse_csv(content,data.get('header_row',1))
            result=self.server.workspace.sales.import_records(data.get('kind'),data.get('namespace'),
                map_columns([row.values for row in table.rows]),data.get('allow_update',False),content,[row.location for row in table.rows],filename)
            self.json(result,201)
            return
        if path == '/api/ocr-confirm':
            self.json(self.server.workspace.ocr.confirm(data.get('id'),data.get('text')))
            return
        if path == '/api/catalog':
            identifier=data.get('id')
            if not isinstance(identifier,str): raise ValidationError('资料 ID 无效')
            self.json(self.server.workspace.catalog.update(identifier,data.get('metadata')))
            return
        if path == '/api/table-metadata':
            identifier=data.get('id')
            if not isinstance(identifier,str): raise ValidationError('数据表 ID 无效')
            self.json(self.server.workspace.tables.update_metadata(identifier,data.get('metadata')))
            return
        if path == '/api/analyze':
            self.json(self.server.workspace.analyses.run(data.get('question'), data.get('document_id') or None, data.get('mode','extract'),data.get('selected_ids'),data.get('calculation_ids'),data.get('lens','general'),data.get('tasks')), 201)
            return
        if path == '/api/analysis-review':
            self.json(self.server.workspace.analyses.review(data.get('id'),data.get('issue_id'),data.get('status'),data.get('note','')),201)
            return
        if path == '/api/table-calculate':
            identifier = data.get('table_id')
            if not isinstance(identifier, str):
                raise ValidationError('表格 ID 无效')
            self.json(self.server.workspace.tables.calculate(identifier, data), 201)
            return
        if not isinstance(data.get("content"), str):
            raise ValidationError("文件字段格式无效")
        encoded = data["content"]
        maximum = MAX_TABLE_BYTES if path in ('/api/tables','/api/ocr') else MAX_UPLOAD_BYTES
        if len(encoded) > ((maximum + 2) // 3) * 4:
            raise ValidationError("文件超过允许的大小")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValidationError("文件内容必须使用有效Base64编码") from None
        if path == '/api/tables':
            result = self.server.workspace.tables.import_csv(data.get('name'), content, data.get('header_row', 1), data.get('sheet_name'))
            self.json(result, 201)
            return
        if path == '/api/ocr':
            self.json(self.server.workspace.ocr.recognize(data.get('name'),content),201)
            return
        result = self.server.workspace.upload(data.get("name"), content)
        self.json(result, 200 if result["duplicate"] else 201)


def main():
    parser = argparse.ArgumentParser(description="溯证：企业资料与证据分析")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--open", action="store_true", help="打开本机浏览器")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("端口必须在0至65535之间")
    try:
        workspace = Workspace(args.data_dir)
        server = LocalServer(("127.0.0.1", args.port), workspace)
    except (OSError, ValueError) as error:
        parser.exit(1, f"启动失败：{error}\n")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"溯证已启动：{url}", flush=True)
    print("仅限本机使用，按 Ctrl+C 停止。", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

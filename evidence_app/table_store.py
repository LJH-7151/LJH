"""Persistent single-table datasets and reproducible calculation snapshots."""
import json
from .common import ValidationError, digest, now, uid
from .tabular_import import parse_csv
from .table_analysis import SourceRow, aggregate


class TableStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS enterprise_tables (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL,
                    columns_json TEXT NOT NULL, encoding TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS enterprise_table_rows (
                    table_id TEXT NOT NULL REFERENCES enterprise_tables(id),
                    position INTEGER NOT NULL, location TEXT NOT NULL, values_json TEXT NOT NULL,
                    PRIMARY KEY(table_id, position), UNIQUE(table_id, location)
                );
                CREATE TABLE IF NOT EXISTS enterprise_table_results (
                    id TEXT PRIMARY KEY, table_id TEXT NOT NULL REFERENCES enterprise_tables(id),
                    request_json TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
            ''')

    def import_csv(self, name, content, header_row=1):
        if not isinstance(name, str) or not name.lower().endswith('.csv') or len(name) > 180 or '/' in name or '\\' in name:
            raise ValidationError('请输入有效的 CSV 文件名')
        table = parse_csv(content, header_row)
        checksum = digest(content)
        original = self.store.blob(checksum)
        if not original.exists():
            try:
                with original.open('xb') as stream:
                    stream.write(content)
            except FileExistsError:
                pass
        if digest(original.read_bytes()) != checksum:
            raise RuntimeError('原件完整性校验失败')
        identifier = uid('table')
        with self.store.connect() as db:
            db.execute('INSERT INTO enterprise_tables VALUES (?,?,?,?,?,?)',
                       (identifier, name, checksum, json.dumps(table.columns, ensure_ascii=False), table.encoding, now()))
            db.executemany('INSERT INTO enterprise_table_rows VALUES (?,?,?,?)',
                           [(identifier, i, row.location, json.dumps(row.values, ensure_ascii=False))
                            for i, row in enumerate(table.rows, 1)])
        return {'id':identifier,'name':name,'sha256':checksum,'columns':list(table.columns),'row_count':len(table.rows)}

    def list(self):
        with self.store.connect() as db:
            result = db.execute('''SELECT t.*, COUNT(r.position) AS row_count FROM enterprise_tables t
                LEFT JOIN enterprise_table_rows r ON t.id=r.table_id GROUP BY t.id ORDER BY t.rowid DESC''').fetchall()
        return [{'id':r['id'],'name':r['name'],'sha256':r['sha256'],'columns':json.loads(r['columns_json']),
                 'row_count':r['row_count'],'created_at':r['created_at']} for r in result]

    def calculate(self, identifier, request):
        with self.store.connect() as db:
            table = db.execute('SELECT * FROM enterprise_tables WHERE id=?', (identifier,)).fetchone()
            if not table:
                raise LookupError('表格不存在')
            records = db.execute('SELECT location, values_json FROM enterprise_table_rows WHERE table_id=? ORDER BY position', (identifier,)).fetchall()
        rows = [SourceRow(row['location'], json.loads(row['values_json'])) for row in records]
        result = aggregate(rows, columns=json.loads(table['columns_json']), operation=request.get('operation'),
                           measure=request.get('measure'), group_by=request.get('group_by'),
                           filters=request.get('filters', []), ignore_invalid=request.get('ignore_invalid') is True)
        result.update({'id':uid('calc'),'table_id':identifier,'table_sha256':table['sha256'],'created_at':now()})
        with self.store.connect() as db:
            db.execute('INSERT INTO enterprise_table_results VALUES (?,?,?,?,?)',
                       (result['id'], identifier, json.dumps(request, ensure_ascii=False), json.dumps(result, ensure_ascii=False), result['created_at']))
        return result

    def result(self, identifier):
        with self.store.connect() as db:
            row = db.execute('SELECT result_json FROM enterprise_table_results WHERE id=?', (identifier,)).fetchone()
        if not row:
            raise LookupError('统计结果不存在')
        return json.loads(row['result_json'])

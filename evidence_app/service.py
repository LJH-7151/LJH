"""Document import, original source access, and local keyword retrieval."""
import sqlite3
from pathlib import PurePosixPath

from .common import digest, now, uid
from .document_import import parse_document
from .retrieval import search
from .storage import Store
from .table_store import TableStore
from .analysis_service import AnalysisService
from .catalog import Catalog
from .ocr_review import OcrReview
from .sales_ledger import SalesLedger
from .semantic_search import SemanticIndex


class Workspace:
    def __init__(self, root):
        self.store = Store(root)
        self.tables = TableStore(self.store)
        self.catalog = Catalog(self.store)
        self.analyses = AnalysisService(self)
        self.ocr = OcrReview(self)
        self.sales = SalesLedger(self.store)
        self.semantic = SemanticIndex(self)

    def documents(self):
        return self.store.documents()

    def search(self, query, document_id=None, limit=20):
        return search(self.store, query, document_id, limit)

    def upload(self, name, content):
        paragraphs = parse_document(name, content)
        sha256 = digest(content)
        existing = self.store.document(sha256=sha256)
        if existing:
            return {"document": existing, "duplicate": True}

        upload_id, document_id = uid("upload"), uid("doc")
        source = self.store.blob(sha256)
        if not source.exists():
            try:
                with source.open("xb") as stream:
                    stream.write(content)
            except FileExistsError:
                pass
        if digest(source.read_bytes()) != sha256:
            raise RuntimeError("原件完整性校验失败")
        chunks, locations = [], []
        position=0
        for start, end, text, location in paragraphs:
            current_line=start
            for offset in range(0,len(text),4000):
                fragment=text[offset:offset+4000]
                position+=1; identifier=uid('chunk')
                fragment_start=current_line if location is None else start
                fragment_end=current_line+fragment.rstrip('\n').count('\n') if location is None else end
                current_line+=fragment.count('\n')
                chunks.append((identifier,document_id,position,fragment_start,fragment_end,fragment))
                if location:
                    location_label=location+(f' · 字符{offset+1}–{offset+len(fragment)}' if len(text)>4000 else '')
                    locations.append((identifier,location_label))
        try:
            self.store.save(
                (upload_id, name, sha256, len(content), now()),
                (document_id, upload_id, PurePosixPath(name).stem),
                chunks, locations,
            )
        except sqlite3.IntegrityError:
            # Concurrent submissions of the same bytes converge on one record.
            existing = self.store.document(sha256=sha256)
            if existing:
                return {"document": existing, "duplicate": True}
            raise
        return {"document": self.store.document(document_id), "duplicate": False}

    def document_text(self, document_id):
        document = self.store.document(document_id)
        if not document:
            raise LookupError("资料不存在")
        return {"document": document, "chunks": self.store.chunks(document_id)}

    def original(self, document_id):
        document = self.store.document(document_id)
        if not document:
            raise LookupError("资料不存在")
        content = self.store.blob(document["sha256"]).read_bytes()
        if digest(content) != document["sha256"]:
            raise RuntimeError("原件完整性校验失败")
        return document["filename"], content

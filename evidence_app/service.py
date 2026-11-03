"""The initial upload -> source record -> source location workflow."""
import sqlite3
from pathlib import PurePosixPath

from .common import digest, now, uid
from .formats import parse_text
from .storage import Store


class Workspace:
    def __init__(self, root):
        self.store = Store(root)

    def documents(self):
        return self.store.documents()

    def upload(self, name, content):
        paragraphs = parse_text(name, content)
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
        chunks = [
            (uid("chunk"), document_id, position, start, end, text)
            for position, (start, end, text) in enumerate(paragraphs, start=1)
        ]
        try:
            self.store.save(
                (upload_id, name, sha256, len(content), now()),
                (document_id, upload_id, PurePosixPath(name).stem),
                chunks,
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

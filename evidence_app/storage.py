"""SQLite persistence, source files, and bounded local keyword lookup."""
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

APPLICATION_ID = 0x4C4A4831  # LJH1: keep this baseline separate from other schemas.
SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    size INTEGER NOT NULL CHECK(size > 0),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    upload_id TEXT NOT NULL UNIQUE REFERENCES uploads(id),
    title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    position INTEGER NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    content TEXT NOT NULL,
    UNIQUE(document_id, position)
);
CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id, position);
"""
DOCUMENT_QUERY = """
SELECT d.id, d.title, u.name AS filename, u.sha256, u.size, u.created_at,
       (SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id) AS chunk_count
FROM documents d JOIN uploads u ON u.id=d.upload_id
"""


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "workspace.sqlite3"
        with self.connect() as con:
            existing = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            app_id = con.execute("PRAGMA application_id").fetchone()[0]
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if (existing and app_id != APPLICATION_ID) or version not in (0, 1):
                raise ValueError("数据目录不属于此基础版本，请使用新的空数据目录")
            con.executescript(SCHEMA)
            con.execute(f"PRAGMA application_id={APPLICATION_ID}")
            con.execute("PRAGMA user_version=1")
        (self.root / "blobs").mkdir(exist_ok=True)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def blob(self, sha256):
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("文件哈希无效")
        return self.root / "blobs" / sha256

    def documents(self):
        with self.connect() as con:
            return [dict(row) for row in con.execute(
                DOCUMENT_QUERY + " ORDER BY u.created_at DESC, d.id DESC"
            )]

    def document(self, document_id=None, sha256=None):
        condition, value = ("d.id=?", document_id) if sha256 is None else ("u.sha256=?", sha256)
        with self.connect() as con:
            row = con.execute(DOCUMENT_QUERY + " WHERE " + condition, (value,)).fetchone()
            return dict(row) if row else None

    def chunks(self, document_id):
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM chunks WHERE document_id=? ORDER BY position",
                (document_id,),
            ).fetchall()
        result = []
        for row in rows:
            chunk = dict(row)
            start, end = chunk["start_line"], chunk["end_line"]
            chunk["location"] = f"第{start}行" if start == end else f"第{start}–{end}行"
            result.append(chunk)
        return result

    def search_chunks(self, terms, document_id, limit):
        # instr treats SQL wildcard characters as literal text. All values
        # remain bound parameters; only fixed SQL fragments are assembled.
        conditions = ["instr(lower(c.content), lower(?)) > 0" for _ in terms]
        parameters = list(terms)
        if document_id:
            conditions.append("c.document_id=?")
            parameters.append(document_id)
        source = """
            FROM chunks c
            JOIN documents d ON d.id=c.document_id
            JOIN uploads u ON u.id=d.upload_id
        """
        where = " WHERE " + " AND ".join(conditions)
        with self.connect() as con:
            total = con.execute("SELECT COUNT(*) " + source + where, parameters).fetchone()[0]
            rows = con.execute(
                """SELECT c.id AS chunk_id, c.document_id, c.position,
                          c.start_line, c.end_line, c.content,
                          d.title, u.name AS filename, u.sha256 """
                + source + where
                + " ORDER BY u.created_at DESC, d.id DESC, c.position, c.id LIMIT ?",
                [*parameters, limit],
            ).fetchall()
        return total, [dict(row) for row in rows]

    def save(self, upload, document, chunks):
        with self.connect() as con:
            con.execute(
                "INSERT INTO uploads(id,name,sha256,size,created_at) VALUES(?,?,?,?,?)",
                upload,
            )
            con.execute("INSERT INTO documents(id,upload_id,title) VALUES(?,?,?)", document)
            con.executemany(
                "INSERT INTO chunks(id,document_id,position,start_line,end_line,content) VALUES(?,?,?,?,?,?)",
                chunks,
            )

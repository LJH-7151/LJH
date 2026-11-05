"""Create a portable SQLite snapshot and verify each original by content hash."""
import io
import json
import sqlite3
import zipfile
from .common import ValidationError, digest, now


def create_backup(store):
    snapshot=sqlite3.connect(':memory:')
    try:
        with store.connect() as source:
            source.backup(snapshot)
        database=snapshot.serialize()
        hashes={row[0] for row in snapshot.execute('SELECT sha256 FROM uploads')}
        tables=snapshot.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='enterprise_tables'").fetchone()
        if tables:
            hashes.update(row[0] for row in snapshot.execute('SELECT sha256 FROM enterprise_tables'))
        ocr=snapshot.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ocr_drafts'").fetchone()
        if ocr:
            hashes.update(row[0] for row in snapshot.execute('SELECT sha256 FROM ocr_drafts'))
        ledger=snapshot.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger_batches'").fetchone()
        if ledger:
            hashes.update(row[0] for row in snapshot.execute('SELECT source_sha256 FROM ledger_batches WHERE source_sha256 IS NOT NULL'))
        migration=snapshot.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_sources'").fetchone()
        if migration:
            hashes.update(row[0] for row in snapshot.execute('SELECT sha256 FROM migration_sources'))
    finally:
        snapshot.close()
    if len(database) > 512*1024*1024:
        raise ValidationError('数据库过大，无法生成内存备份')
    output=io.BytesIO()
    metadata={'created_at':now(),'database_sha256':digest(database),'blobs':sorted(hashes),'format':'evidence-backup-1'}
    total=len(database)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('workspace.sqlite3',database)
        for sha in sorted(hashes):
            content=store.blob(sha).read_bytes()
            if digest(content) != sha:
                raise ValidationError('原始资料完整性校验失败，停止备份')
            total += len(content)
            if total > 512*1024*1024:
                raise ValidationError('备份超过512 MiB，请分开备份')
            archive.writestr('blobs/'+sha,content)
        archive.writestr('backup.json',json.dumps(metadata,ensure_ascii=False,indent=2))
    return output.getvalue()

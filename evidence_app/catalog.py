"""Editable document metadata with an immutable change history."""
import json
from datetime import date
from .common import ValidationError, now, uid

FIELDS=('entity','category','department','period','scope','source','version','supersedes','tags','published_at','effective_start','effective_end')


class Catalog:
    def __init__(self, store):
        self.store=store
        with store.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS enterprise_metadata (
                document_id TEXT PRIMARY KEY REFERENCES documents(id), payload TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1))
              );
              CREATE TABLE IF NOT EXISTS enterprise_metadata_events (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                before_json TEXT NOT NULL, after_json TEXT NOT NULL, created_at TEXT NOT NULL
              );
            ''')

    def get(self, identifier):
        with self.store.connect() as db:
            if not db.execute('SELECT 1 FROM documents WHERE id=?',(identifier,)).fetchone():
                raise LookupError('资料不存在')
            row=db.execute('SELECT payload,archived FROM enterprise_metadata WHERE document_id=?',(identifier,)).fetchone()
        return (json.loads(row['payload']) | {'archived':bool(row['archived'])}) if row else {'archived':False}

    def update(self, identifier, changes):
        if not isinstance(changes,dict) or any(key not in FIELDS+('archived',) for key in changes):
            raise ValidationError('资料元数据无效')
        for key,value in changes.items():
            if key=='archived':
                if type(value) is not bool: raise ValidationError('归档状态无效')
            elif not isinstance(value,str) or len(value)>500 or '\x00' in value:
                raise ValidationError('资料元数据无效')
            elif key in ('published_at','effective_start','effective_end') and value:
                try:
                    if date.fromisoformat(value).isoformat()!=value: raise ValueError()
                except ValueError: raise ValidationError('日期需使用 YYYY-MM-DD') from None
        with self.store.connect() as db:
            if not db.execute('SELECT 1 FROM documents WHERE id=?',(identifier,)).fetchone():
                raise LookupError('资料不存在')
            old=db.execute('SELECT payload,archived FROM enterprise_metadata WHERE document_id=?',(identifier,)).fetchone()
            before=(json.loads(old['payload']) | {'archived':bool(old['archived'])}) if old else {'archived':False}
            after=before | changes
            if after.get('effective_start') and after.get('effective_end') and after['effective_start']>=after['effective_end']:
                raise ValidationError('生效结束日期必须晚于开始日期')
            previous=after.get('supersedes','')
            visited={identifier}
            while previous:
                if previous in visited: raise ValidationError('版本关联不能形成循环')
                visited.add(previous)
                if not db.execute('SELECT 1 FROM documents WHERE id=?',(previous,)).fetchone():
                    raise ValidationError('关联的旧版本不存在')
                row=db.execute('SELECT payload FROM enterprise_metadata WHERE document_id=?',(previous,)).fetchone()
                previous=json.loads(row['payload']).get('supersedes','') if row else ''
            payload={k:v for k,v in after.items() if k!='archived'}
            db.execute('INSERT OR REPLACE INTO enterprise_metadata VALUES (?,?,?)',
                       (identifier,json.dumps(payload,ensure_ascii=False),int(after['archived'])))
            db.execute('INSERT INTO enterprise_metadata_events VALUES (?,?,?,?,?)',
                       (uid('meta'),identifier,json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),now()))
        return after

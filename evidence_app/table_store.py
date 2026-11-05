"""Persistent single-table datasets and reproducible calculation snapshots."""
import json
import re
from datetime import date
from .common import ValidationError, digest, now, uid
from .catalog import FIELDS
from .tabular_import import parse_csv, parse_xlsx
from .table_analysis import SourceRow, aggregate, _number


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
                CREATE TABLE IF NOT EXISTS enterprise_table_metadata_events (
                    id TEXT PRIMARY KEY, table_id TEXT NOT NULL REFERENCES enterprise_tables(id),
                    before_json TEXT NOT NULL, after_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
            ''')
            columns={row['name'] for row in db.execute('PRAGMA table_info(enterprise_tables)')}
            if 'metadata_json' not in columns:
                db.execute("ALTER TABLE enterprise_tables ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")

    def import_csv(self, name, content, header_row=1, sheet_name=None):
        if not isinstance(name, str) or not name.lower().endswith(('.csv','.xlsx')) or len(name) > 180 or '/' in name or '\\' in name:
            raise ValidationError('请输入有效的 CSV 或 XLSX 文件名')
        table = parse_xlsx(content, header_row, sheet_name) if name.lower().endswith('.xlsx') else parse_csv(content, header_row)
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
            db.execute('INSERT INTO enterprise_tables (id,name,sha256,columns_json,encoding,created_at) VALUES (?,?,?,?,?,?)',
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
                 'metadata':json.loads(r['metadata_json']),
                 'row_count':r['row_count'],'created_at':r['created_at']} for r in result]

    def metadata(self,identifier):
        with self.store.connect() as db:
            row=db.execute('SELECT metadata_json FROM enterprise_tables WHERE id=?',(identifier,)).fetchone()
        if not row: raise LookupError('数据表不存在')
        return json.loads(row['metadata_json'])

    def update_metadata(self,identifier,changes):
        if not isinstance(changes,dict) or any(key not in FIELDS+('archived',) for key in changes): raise ValidationError('数据表属性无效')
        for key,value in changes.items():
            if key=='archived':
                if type(value) is not bool: raise ValidationError('归档状态无效')
            elif not isinstance(value,str) or len(value)>500 or '\x00' in value: raise ValidationError('数据表属性无效')
            elif key in ('published_at','effective_start','effective_end') and value:
                try:
                    if date.fromisoformat(value).isoformat()!=value: raise ValueError()
                except ValueError: raise ValidationError('日期需使用 YYYY-MM-DD') from None
        with self.store.connect() as db:
            row=db.execute('SELECT metadata_json FROM enterprise_tables WHERE id=?',(identifier,)).fetchone()
            if not row: raise LookupError('数据表不存在')
            before=json.loads(row['metadata_json']); after=before | changes
            if after.get('effective_start') and after.get('effective_end') and after['effective_start']>=after['effective_end']:
                raise ValidationError('生效结束日期必须晚于开始日期')
            previous=after.get('supersedes',''); visited={identifier}
            while previous:
                if previous in visited: raise ValidationError('版本关联不能形成循环')
                visited.add(previous)
                old=db.execute('SELECT metadata_json FROM enterprise_tables WHERE id=?',(previous,)).fetchone()
                if not old: raise ValidationError('关联的旧版本不存在')
                previous=json.loads(old['metadata_json']).get('supersedes','')
            db.execute('UPDATE enterprise_tables SET metadata_json=? WHERE id=?',(json.dumps(after,ensure_ascii=False),identifier))
            db.execute('INSERT INTO enterprise_table_metadata_events VALUES (?,?,?,?,?)',
                       (uid('meta'),identifier,json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),now()))
        return after

    def preview(self,identifier):
        with self.store.connect() as db:
            table=db.execute('SELECT * FROM enterprise_tables WHERE id=?',(identifier,)).fetchone()
            if not table: raise LookupError('数据表不存在')
            rows=db.execute('SELECT location,values_json FROM enterprise_table_rows WHERE table_id=? ORDER BY position',(identifier,)).fetchall()
        columns=json.loads(table['columns_json']); profile={name:{'present':0,'numeric':0,'missing':0} for name in columns}; sample=[]
        for index,row in enumerate(rows):
            values=json.loads(row['values_json'])
            if index<30: sample.append({'location':row['location'],'values':values})
            for name in columns:
                value=values.get(name,'')
                if not str(value).strip(): profile[name]['missing']+=1; continue
                profile[name]['present']+=1
                try: _number(value); profile[name]['numeric']+=1
                except ValidationError: pass
        for name,stats in profile.items():
            identifier=bool(re.search(r'编号|代码|编码|订单|电话|证件|(^id$)|(_id$)',name,re.I))
            stats['type']='number' if stats['present'] and stats['numeric']/stats['present']>=0.8 and not identifier else 'text'
        return {'id':identifier,'name':table['name'],'sha256':table['sha256'],'columns':columns,
                'row_count':len(rows),'profile':profile,'rows':sample}

    def calculate(self, identifier, request):
        with self.store.connect() as db:
            table = db.execute('SELECT * FROM enterprise_tables WHERE id=?', (identifier,)).fetchone()
            if not table:
                raise LookupError('表格不存在')
            if json.loads(table['metadata_json']).get('archived'):
                raise ValidationError('已归档的数据表不能新建统计')
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

    def result_rows(self, identifier):
        result=self.result(identifier)
        locations={location for group in result['groups'] for location in group['source_locations']}
        locations.update(result.get('missing_locations',[])); locations.update(result.get('invalid_locations',[]))
        locations.update(result.get('unattributed_locations',[]))
        with self.store.connect() as db:
            records=db.execute('SELECT location,values_json FROM enterprise_table_rows WHERE table_id=? ORDER BY position',(result['table_id'],)).fetchall()
        return [{'location':row['location'],'values':json.loads(row['values_json'])} for row in records if row['location'] in locations]

    def results(self):
        with self.store.connect() as db:
            rows=db.execute('SELECT result_json FROM enterprise_table_results ORDER BY rowid DESC LIMIT 100').fetchall()
        return [json.loads(row['result_json']) for row in rows]

    def source(self,identifier,location):
        if not isinstance(location,str) or len(location)>500: raise ValidationError('来源位置无效')
        with self.store.connect() as db:
            row=db.execute('''SELECT t.name,t.sha256,r.location,r.values_json FROM enterprise_table_rows r
                JOIN enterprise_tables t ON t.id=r.table_id WHERE r.table_id=? AND r.location=?''',(identifier,location)).fetchone()
        if not row: raise LookupError('来源行不存在')
        return {'table_id':identifier,'name':row['name'],'sha256':row['sha256'],
                'location':row['location'],'values':json.loads(row['values_json'])}

    def search(self, query, limit=30, table_ids=None):
        if not isinstance(query,str) or not query.strip() or len(query)>200 or len(query.split())>8:
            raise ValidationError('请输入1至200字符、最多8个词')
        if type(limit) is not int or not 1<=limit<=50:
            raise ValidationError('返回数量无效')
        terms=[term.casefold() for term in query.split()]
        matches=[]
        with self.store.connect() as db:
            cursor=db.execute('''SELECT t.id,t.name,t.sha256,t.metadata_json,r.position,r.location,r.values_json
                                 FROM enterprise_table_rows r JOIN enterprise_tables t ON t.id=r.table_id
                                 ORDER BY t.rowid DESC,r.position''')
            for row in cursor:
                metadata=json.loads(row['metadata_json'])
                if metadata.get('archived'): continue
                if table_ids is not None and row['id'] not in table_ids:
                    continue
                values=json.loads(row['values_json'])
                content='；'.join(f'{key}：{value}' for key,value in values.items())
                if all(term in content.casefold() for term in terms):
                    matches.append({'id':row['id']+':'+str(row['position']),'document_id':row['id'],
                        'title':row['name'],'sha256':row['sha256'],'location':row['location'],
                        'content':content,'metadata':metadata | {'category':metadata.get('category','数据表')}})
                    if len(matches)>=limit: break
        return matches

"""Copy supported sources from the earlier local workspace into a new one.

The earlier database and all its hashed originals are retained for audit. The
source is read-only and the destination must be empty. No network is used.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence_app.common import ValidationError, digest
from evidence_app.service import Workspace


def main():
    parser=argparse.ArgumentParser(description='从旧工作空间复制资料到新的空目录')
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    source=args.source.resolve(); target=args.destination.resolve()
    if source==target or source in target.parents or target in source.parents:
        parser.error('来源与目标必须是互不包含的独立目录')
    if not (source/'workspace.sqlite3').is_file(): parser.error('来源数据库不存在')
    if target.exists() and any(target.iterdir()): parser.error('目标必须为空目录')
    source_db=sqlite3.connect((source/'workspace.sqlite3').as_uri()+'?mode=ro',uri=True)
    source_db.row_factory=sqlite3.Row
    snapshot=sqlite3.connect(':memory:')
    source_db.backup(snapshot)
    snapshot.row_factory=sqlite3.Row
    source_db.close()
    schema={row[1] for row in snapshot.execute('PRAGMA table_info(documents)')}
    if not {'id','upload_id','metadata','status'} <= schema:
        parser.error('来源不是支持的旧版企业工作空间')
    database=snapshot.serialize()
    workspace=Workspace(target)
    with workspace.store.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS migration_sources (sha256 TEXT PRIMARY KEY, kind TEXT NOT NULL)')
    def preserve(content,kind):
        sha=digest(content); path=workspace.store.blob(sha)
        if not path.exists(): path.write_bytes(content)
        if digest(path.read_bytes())!=sha: raise RuntimeError('原始数据校验失败')
        with workspace.store.connect() as db:
            db.execute('INSERT OR IGNORE INTO migration_sources VALUES (?,?)',(sha,kind))
        return sha
    database_sha=preserve(database,'previous_database')
    blobs=source/'blobs'
    if blobs.is_dir():
        for path in blobs.iterdir():
            if path.is_file() and len(path.name)==64:
                content=path.read_bytes()
                if digest(content)!=path.name: raise RuntimeError('旧原件哈希不一致')
                preserve(content,'previous_original')
    rows=snapshot.execute('''SELECT d.id,d.metadata,d.status,u.name,u.sha FROM documents d
        JOIN uploads u ON u.id=d.upload_id ORDER BY d.rowid''').fetchall()
    mapping={}; metadata={}; skipped=[]; tables=documents=0
    for row in rows:
        raw=workspace.store.blob(row['sha']).read_bytes()
        name=row['name']; suffix=Path(name).suffix.lower(); old=json.loads(row['metadata'])
        if row['status']!='ready':
            skipped.append({'id':row['id'],'reason':'待复核资料保留在旧数据库及原件中'})
            continue
        try:
            if suffix in ('.csv','.xlsx'):
                result=workspace.tables.import_csv(name,raw,int(old.get('header_row') or 1))
                mapping[row['id']]={'kind':'table','id':result['id']}; metadata[row['id']]=old; tables+=1
            elif suffix in ('.txt','.md','.docx','.pdf'):
                result=workspace.upload(name,raw)
                if result['duplicate']:
                    skipped.append({'id':row['id'],'reason':'相同内容合并；完整版本保留在旧数据库'})
                mapping[row['id']]={'kind':'document','id':result['document']['id']}
                metadata[row['id']]=old; documents+=1
            else:
                skipped.append({'id':row['id'],'reason':'格式需人工复核，原件保留'})
        except (ValidationError,ValueError,OSError):
            skipped.append({'id':row['id'],'reason':'解析失败，原件保留并需人工复核'})
    for old_id,old in metadata.items():
        item=mapping[old_id]
        values={field:str(old.get(field,'')) for field in ('entity','category','department','period','scope','source','version','tags')}
        previous=mapping.get(old.get('supersedes',''))
        if previous and previous['kind']==item['kind']: values['supersedes']=previous['id']
        values['archived']=old.get('archived') is True
        if item['kind']=='document': workspace.catalog.update(item['id'],values)
        else: workspace.tables.update_metadata(item['id'],values)
    migrated_queries=0; query_skips=[]; dataset_map={}
    if snapshot.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='datasets'").fetchone():
        with workspace.store.connect() as db:
            for dataset in snapshot.execute('SELECT id,document_id FROM datasets'):
                mapped=mapping.get(dataset['document_id'],{})
                if mapped.get('kind')!='table': continue
                old_rows=snapshot.execute('SELECT row_number,payload FROM dataset_rows WHERE dataset_id=? ORDER BY row_number',(dataset['id'],)).fetchall()
                new_rows=db.execute('SELECT location,values_json FROM enterprise_table_rows WHERE table_id=? ORDER BY position',(mapped['id'],)).fetchall()
                if len(old_rows)!=len(new_rows): continue
                positions={}; consistent=True
                for old_row,new_row in zip(old_rows,new_rows):
                    old_values=json.loads(old_row['payload']); new_values=json.loads(new_row['values_json'])
                    if {k:str(v) for k,v in old_values.items()}!={k:str(v) for k,v in new_values.items()}:
                        consistent=False; break
                    positions[old_row['row_number']]=new_row['location']
                if consistent: dataset_map[dataset['id']]={'table_id':mapped['id'],'positions':positions}
            for old_query in snapshot.execute('SELECT id,payload FROM dataset_queries ORDER BY rowid'):
                item=json.loads(old_query['payload']); dataset=dataset_map.get(item.get('dataset_id'))
                if not dataset:
                    query_skips.append(old_query['id']); continue
                positions=dataset['positions']; table=db.execute('SELECT sha256 FROM enterprise_tables WHERE id=?',(dataset['table_id'],)).fetchone()
                selected=item.get('source_row_numbers',[])
                try:
                    groups=[{'group':str(group['group']),'value':str(group['value']),'count':group['count'],
                             'source_locations':[positions[number] for number in group.get('source_rows',[])]}
                            for group in item.get('rows',[])]
                    attributed={location for group in groups for location in group['source_locations']}
                    unattributed=[positions[number] for number in selected if positions[number] not in attributed]
                except (KeyError,TypeError):
                    query_skips.append(old_query['id']); continue
                operation={'avg':'average'}.get(item.get('aggregation'),item.get('aggregation'))
                converted={'id':item['id'],'table_id':dataset['table_id'],'table_sha256':table['sha256'],
                    'operation':operation,'measure':item.get('measure'),'group_by':item.get('group_by') or None,
                    'filters':item.get('filters',[]),'selected':item.get('selected_row_count',len(selected)),
                    'missing':item.get('missing',0),'invalid':item.get('invalid',0),'groups':groups,
                    'missing_locations':[],'invalid_locations':[],'unattributed_locations':unattributed,
                    'created_at':item.get('created',''),'previous_result':item}
                db.execute('INSERT OR IGNORE INTO enterprise_table_results VALUES (?,?,?,?,?)',
                    (converted['id'],dataset['table_id'],json.dumps({'migrated':True}),json.dumps(converted,ensure_ascii=False),converted['created_at']))
                migrated_queries+=1
    archived=0
    if snapshot.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='enterprise_analyses'").fetchone():
        with workspace.store.connect() as db:
            for row in snapshot.execute('SELECT id,question,lens,manifest,result,created FROM enterprise_analyses ORDER BY rowid'):
                result=json.loads(row['result']); manifest=json.loads(row['manifest'])
                sources=[{'id':item.get('id',''),'document_id':item.get('document_id',''),
                          'title':item.get('title','旧版来源'),'sha256':item.get('sha',''),
                          'location':item.get('location',''),'content':item.get('content',''),
                          'metadata':item.get('metadata',{})} for item in result.get('sources',[])]
                converted={'id':row['id'],'question':row['question'],'mode':'migrated',
                    'created_at':row['created'],'sources':sources,'conclusions':result.get('conclusions',[]),
                    'conflicts':[],'legacy_conflicts':result.get('conflicts',[]),
                    'gaps':result.get('gaps',[]),'actions':result.get('actions',[]),
                    'limitations':result.get('limitations',[])+['此档案来自旧版快照，引用和计算口径保留原记录。'],
                    'previous_manifest':manifest,'model_calls':result.get('model_calls',0)}
                db.execute('INSERT OR IGNORE INTO analysis_archives VALUES (?,?,?,?)',
                           (row['id'],row['question'],json.dumps(converted,ensure_ascii=False),row['created']))
                archived+=1
    summary={'previous_database_sha256':database_sha,'source_documents':len(rows),'documents_imported':documents,
             'tables_imported':tables,'analyses_imported':archived,'queries_imported':migrated_queries,
             'queries_skipped':query_skips,'skipped':skipped,'mapping':mapping,
             'note':'旧数据库与原件保留在迁移工作空间及其备份中；旧版分析和核算记录以原数据库快照保留。'}
    with workspace.store.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS migration_reports (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('INSERT INTO migration_reports(payload) VALUES (?)',(json.dumps(summary,ensure_ascii=False),))
    print(json.dumps({key:summary[key] for key in ('previous_database_sha256','source_documents','documents_imported','tables_imported','analyses_imported','queries_imported')},ensure_ascii=False))
    print('待复核数量:',len(skipped))
    print('未转换旧统计数量:',len(query_skips))
    snapshot.close()


if __name__=='__main__': main()

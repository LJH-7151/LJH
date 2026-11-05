import json
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from uuid import uuid4

from evidence_app.common import digest
from evidence_app.service import Workspace


class MigrationTests(unittest.TestCase):
    def test_previous_workspace_is_read_only_and_auditable(self):
        root=Path(__file__).resolve().parents[1]
        work=root/'output'/'tests'/('migration-'+uuid4().hex)
        source=work/'old'; target=work/'new'; (source/'blobs').mkdir(parents=True)
        raw='部门,金额\n销售,10\n'.encode(); sha=digest(raw); (source/'blobs'/sha).write_bytes(raw)
        db=sqlite3.connect(source/'workspace.sqlite3')
        db.executescript('''CREATE TABLE uploads(id TEXT,name TEXT,sha TEXT);
            CREATE TABLE documents(id TEXT,upload_id TEXT,metadata TEXT,status TEXT);
            CREATE TABLE datasets(id TEXT,document_id TEXT);
            CREATE TABLE dataset_rows(dataset_id TEXT,row_number INTEGER,payload TEXT);
            CREATE TABLE dataset_queries(id TEXT,payload TEXT);
            CREATE TABLE enterprise_analyses(id TEXT,question TEXT,lens TEXT,manifest TEXT,result TEXT,created TEXT);''')
        db.execute('INSERT INTO uploads VALUES (?,?,?)',('up','sample.csv',sha))
        db.execute('INSERT INTO documents VALUES (?,?,?,?)',('doc','up','{}','ready'))
        db.execute('INSERT INTO datasets VALUES (?,?)',('ds','doc'))
        db.execute('INSERT INTO dataset_rows VALUES (?,?,?)',('ds',2,json.dumps({'部门':'销售','金额':'10'},ensure_ascii=False)))
        query={'id':'q1','dataset_id':'ds','aggregation':'sum','measure':'金额','group_by':'部门',
               'selected_row_count':1,'missing':0,'invalid':0,'source_row_numbers':[2],
               'rows':[{'group':'销售','value':'10','count':1,'source_rows':[2]}],'created':'2026-10-01'}
        db.execute('INSERT INTO dataset_queries VALUES (?,?)',('q1',json.dumps(query,ensure_ascii=False)))
        result={'sources':[],'conclusions':[],'conflicts':[],'limitations':[]}
        db.execute('INSERT INTO enterprise_analyses VALUES (?,?,?,?,?,?)',('a1','问题','general','{}',json.dumps(result),'2026-10-01'))
        db.commit(); db.close()
        before=digest((source/'workspace.sqlite3').read_bytes())
        subprocess.run([sys.executable,str(root/'tools/import_previous_workspace.py'),str(source),str(target)],check=True,capture_output=True)
        self.assertEqual(digest((source/'workspace.sqlite3').read_bytes()),before)
        workspace=Workspace(target)
        self.assertEqual(len(workspace.tables.list()),1)
        self.assertEqual(workspace.tables.result('q1')['groups'][0]['source_locations'],['CSV 第2行'])
        self.assertEqual(workspace.analyses.get('a1')['mode'],'migrated')
        with workspace.store.connect() as current:
            saved=current.execute("SELECT sha256 FROM migration_sources WHERE kind='previous_database'").fetchone()[0]
        self.assertTrue(workspace.store.blob(saved).is_file())


if __name__=='__main__': unittest.main()

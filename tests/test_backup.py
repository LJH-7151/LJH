import io
import json
import zipfile
from pathlib import Path
from uuid import uuid4

from evidence_app.common import digest
from evidence_app.service import Workspace
from support import HTTPFixture


class BackupTests(HTTPFixture):
    def test_backup_is_consistent_and_can_be_reopened(self):
        status, original=self.upload('人工合成资料'.encode(),'test.txt')
        self.assertEqual(status,201)
        table=self.server.workspace.tables.import_csv('test.csv',b'name,value\na,3\n')
        calc=self.server.workspace.tables.calculate(table['id'],{'operation':'sum','measure':'value'})
        status, _, data=self.request('GET','/api/backup')
        self.assertEqual(status,200)
        destination=self.test_root/('restore-'+uuid4().hex)
        destination.mkdir()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names=archive.namelist()
            self.assertTrue(all(name=='workspace.sqlite3' or name=='backup.json' or name.startswith('blobs/') for name in names))
            metadata=json.loads(archive.read('backup.json'))
            self.assertEqual(digest(archive.read('workspace.sqlite3')),metadata['database_sha256'])
            archive.extractall(destination)
        restored=Workspace(destination)
        self.assertEqual(restored.documents()[0]['id'],original['document']['id'])
        self.assertEqual(restored.tables.result(calc['id']),calc)

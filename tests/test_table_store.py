import unittest
from pathlib import Path
from uuid import uuid4

from evidence_app.common import ValidationError
from evidence_app.service import Workspace


class TableStoreTests(unittest.TestCase):
    def test_reopen_preserves_original_and_calculation(self):
        root = Path(__file__).resolve().parents[1] / 'output' / 'tests' / ('table-' + uuid4().hex)
        workspace = Workspace(root)
        data = '部门,金额\n销售,0.10\n销售,0.20\n'.encode()
        dataset = workspace.tables.import_csv('模拟.csv', data)
        result = workspace.tables.calculate(dataset['id'], {'operation':'sum','measure':'金额','group_by':'部门'})
        reopened = Workspace(root)
        self.assertEqual(reopened.tables.list()[0]['row_count'], 2)
        self.assertEqual(reopened.store.blob(dataset['sha256']).read_bytes(), data)
        self.assertEqual(reopened.tables.result(result['id']), result)
        self.assertEqual(result['groups'][0]['value'], '0.30')
        self.assertEqual(result['groups'][0]['source_locations'], ['CSV 第2行', 'CSV 第3行'])

    def test_invalid_import_has_no_database_record(self):
        root = Path(__file__).resolve().parents[1] / 'output' / 'tests' / ('table-' + uuid4().hex)
        workspace = Workspace(root)
        with self.assertRaises(ValidationError):
            workspace.tables.import_csv('invalid.csv', b'a,b\n1\n')
        self.assertEqual(workspace.tables.list(), [])


if __name__ == '__main__':
    unittest.main()

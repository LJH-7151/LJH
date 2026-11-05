import unittest

from evidence_app.common import ValidationError
from evidence_app.tabular_import import parse_csv
from evidence_app.table_analysis import aggregate


class CsvImportTests(unittest.TestCase):
    def test_multiline_quoted_cell_preserves_physical_lines(self):
        table = parse_csv('期间,备注,金额\n一月,"第一行\n第二行",12.30\n二月,正常,7.70\n'.encode())
        self.assertEqual(table.rows[0].location, 'CSV 第2–3行')
        self.assertEqual(table.rows[1].location, 'CSV 第4行')
        result = aggregate(table.rows, columns=table.columns, operation='sum', measure='金额')
        self.assertEqual(result['groups'][0]['value'], '20.00')
        self.assertEqual(result['groups'][0]['source_locations'], ['CSV 第2–3行', 'CSV 第4行'])

    def test_encoding_and_header(self):
        table = parse_csv('说明\n月份,金额\n一月,23\n'.encode('gb18030'), header_row=2)
        self.assertEqual(table.encoding, 'gb18030')
        self.assertEqual(table.rows[0].values['月份'], '一月')

    def test_bad_input_is_rejected(self):
        for raw in (b'a,a\n1,2\n', b'a,b\n1\n', b'a,b\n"unterminated', b'a,\x00\n1,2'):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                parse_csv(raw)
        with self.assertRaises(ValidationError):
            parse_csv(b'a\n1\n', header_row=100)


if __name__ == '__main__':
    unittest.main()

import unittest
import io
import zipfile

from evidence_app.common import ValidationError
from evidence_app.tabular_import import parse_csv, parse_xlsx
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


class XlsxImportTests(unittest.TestCase):
    def workbook(self, value='<v>10.25</v>', extra=''):
        files = {
            'xl/workbook.xml': '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="经营" sheetId="1" r:id="r1"/></sheets></workbook>''',
            'xl/_rels/workbook.xml.rels': '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>''',
            'xl/worksheets/sheet1.xml': '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>部门</t></is></c><c r="B1" t="inlineStr"><is><t>金额</t></is></c></row><row r="3"><c r="A3" t="inlineStr"><is><t>销售</t></is></c><c r="B3"><f>5+5.25</f>''' + value + '''</c></row></sheetData>''' + extra + '''</worksheet>''',
        }
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            for name, data in files.items(): archive.writestr(name,data)
        return buffer.getvalue()

    def test_cached_formula_and_row_position(self):
        table=parse_xlsx(self.workbook(), sheet_name='经营')
        self.assertEqual(table.rows[0].location,'经营 第3行')
        self.assertEqual(table.rows[0].values['金额'],'10.25')
        result=aggregate(table.rows,columns=table.columns,operation='sum',measure='金额')
        self.assertEqual(result['groups'][0]['value'],'10.25')

    def test_no_formula_cache_or_merged_cells(self):
        for raw in (self.workbook(value=''),self.workbook(extra='<mergeCells/>')):
            with self.assertRaises(ValidationError): parse_xlsx(raw)
        with self.assertRaises(ValidationError): parse_xlsx(self.workbook(),sheet_name='不存在')

    def test_excel_dates_and_hidden_rows(self):
        original=self.workbook()
        output=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(output,'w') as dest:
            for name in source.namelist():
                data=source.read(name)
                if name.endswith('sheet1.xml'):
                    data=data.replace(b'<c r="B3"><f>5+5.25</f><v>10.25</v></c>',b'<c r="B3" s="1"><v>2</v></c>')
                dest.writestr(name,data)
            dest.writestr('xl/styles.xml','''<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>''')
        table=parse_xlsx(output.getvalue())
        self.assertEqual(table.rows[0].values['金额'],'1900-01-02')
        output=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(output,'w') as dest:
            for name in source.namelist():
                data=source.read(name)
                if name.endswith('sheet1.xml'): data=data.replace(b'<row r="3">',b'<row r="3" hidden="1">')
                dest.writestr(name,data)
        with self.assertRaises(ValidationError): parse_xlsx(output.getvalue())


if __name__ == '__main__':
    unittest.main()

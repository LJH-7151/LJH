import io
import unittest
import zipfile

from evidence_app.common import ValidationError
from evidence_app.document_import import parse_document
from support import HTTPFixture


def sample():
    xml = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
      <w:p><w:r><w:t>合成合同付款期限30天</w:t></w:r></w:p>
      <w:tbl><w:tr><w:tc><w:p><w:r><w:t>甲方</w:t></w:r></w:p></w:tc>
      <w:tc><w:p><w:r><w:t>模拟公司</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      </w:body></w:document>'''
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('word/document.xml', xml)
    return stream.getvalue()


class DocumentImportTests(unittest.TestCase):
    def test_legacy_chinese_text_encoding(self):
        chunks=parse_document('sample.txt','虚构合同。'.encode('gb18030'))
        self.assertEqual(chunks[0][2],'虚构合同。')

    def test_bad_document_is_rejected(self):
        with self.assertRaises(ValidationError):
            parse_document('invalid.docx', b'not a zip')
        self.assertEqual([item[3] for item in parse_document('sample.docx', sample())],
                         ['正文第1段', '表格1第1行'])

    def test_pdf_text_has_page_reference_and_blank_needs_review(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),
                                 NameObject('/Subtype'):NameObject('/Type1'),
                                 NameObject('/BaseFont'):NameObject('/Helvetica')})
        fonts = DictionaryObject({NameObject('/F1'):writer._add_object(font)})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):fonts})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 20 200 Td (Sample contract) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        output = io.BytesIO()
        writer.write(output)
        parsed = parse_document('sample.pdf', output.getvalue())
        self.assertIn('Sample contract', parsed[0][2])
        self.assertEqual(parsed[0][3], '第1页')
        blank = PdfWriter()
        blank.add_blank_page(width=100, height=100)
        output = io.BytesIO()
        blank.write(output)
        with self.assertRaisesRegex(ValidationError, 'OCR'):
            parse_document('blank.pdf', output.getvalue())


class DocumentHTTPTests(HTTPFixture):
    def test_long_text_is_bounded_and_reconstructable(self):
        content=('A'*3998+'\n'+'B'*4010).encode()
        status, uploaded=self.upload(content,name='long.txt')
        self.assertEqual(status,201)
        _,detail=self.json_request('GET',self.document_path('/api/document-text',uploaded['document']))
        self.assertEqual(''.join(chunk['content'] for chunk in detail['chunks']),content.decode())
        self.assertEqual(detail['chunks'][0]['start_line'],1)
        self.assertEqual(detail['chunks'][-1]['end_line'],2)

    def test_docx_original_and_evidence_locations(self):
        raw = sample()
        status, uploaded = self.upload(raw, name='sample.docx')
        self.assertEqual(status, 201)
        document = uploaded['document']
        status, detail = self.json_request('GET', self.document_path('/api/document-text', document))
        self.assertEqual(status, 200)
        self.assertEqual([item['location'] for item in detail['chunks']], ['正文第1段', '表格1第1行'])
        status, result = self.json_request('GET', '/api/search?q=%E4%BB%98%E6%AC%BE')
        self.assertEqual(status, 200)
        self.assertEqual(result['results'][0]['location'], '正文第1段')
        status, _, downloaded = self.request('GET', self.document_path('/api/original', document))
        self.assertEqual((status, downloaded), (200, raw))

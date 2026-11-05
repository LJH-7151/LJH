import io
import unittest
import zipfile

from evidence_app.report_export import table_report, word_report
from evidence_app.tabular_import import parse_xlsx


class ExportTests(unittest.TestCase):
    def test_excel_keeps_all_locations_and_formula_text(self):
        data={'operation':'sum','measure':'金额','table_sha256':'abc','selected':2,'missing':0,'invalid':0,
              'groups':[{'group':'=1+1','value':'12','count':2,'source_locations':['表1 第2行','表1 第3行']}]}
        raw=table_report(data,[{'location':'表1 第2行','values':{'客户':'=SUM(1,1)'}}, {'location':'表1 第3行','values':{'客户':'模拟'}}])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            sheet=archive.read('xl/worksheets/sheet1.xml').decode()
        self.assertNotIn('<f>',sheet)
        self.assertIn('表1 第2行',sheet)
        self.assertIn('表1 第3行',sheet)
        self.assertIn('=SUM(1,1)',sheet)
        table=parse_xlsx(raw)
        self.assertEqual(table.rows[0].values['分组'],'=1+1')

    def test_word_contains_original_and_citation(self):
        data={'question':'合同','created_at':'2026','conclusions':[{'text':'30天','citations':[{'id':'e','quote':'期限30天'}]}],
              'sources':[{'id':'e','title':'合同','location':'第1页','sha256':'abc'}], 'limitations':['待核对']}
        with zipfile.ZipFile(io.BytesIO(word_report(data))) as archive:
            content=archive.read('word/document.xml').decode()
        self.assertIn('期限30天',content)
        self.assertIn('第1页',content)

    def test_word_includes_gaps_and_review_history(self):
        data={'question':'合同','created_at':'2026','conclusions':[],'sources':[],'limitations':[],
              'gaps':[{'title':'缺少底稿','reason':'没有凭证','material':'原始记录'}]}
        review=[{'created_at':'2026','status':'confirmed','note':'人工已核对'}]
        with zipfile.ZipFile(io.BytesIO(word_report(data,review))) as archive:
            content=archive.read('word/document.xml').decode()
        self.assertIn('缺少底稿',content)
        self.assertIn('人工已核对',content)


if __name__=='__main__': unittest.main()

import json
from unittest.mock import patch

from evidence_app.common import ValidationError
from support import HTTPFixture


class AnalysisTests(HTTPFixture):
    def test_natural_question_retains_missing_evidence_as_gap(self):
        self.upload('虚构合同金额为100万元。'.encode(), 'sample.txt')
        result=self.server.workspace.analyses.run('经营表现和利润如何？')
        self.assertTrue(result['sources'])
        self.assertTrue(any('利润' in gap['title'] for gap in result['gaps']))
        issue=result['gaps'][0]
        review=self.server.workspace.analyses.review(result['id'],issue['id'],'confirmed','已核对模拟资料')
        self.assertEqual(self.server.workspace.analyses.reviews(result['id'])[0],review)
        self.assertEqual(self.server.workspace.analyses.get(result['id']),result)

    def test_custom_tasks_define_retrieval(self):
        self.upload('虚构合同金额为100万元。'.encode(), 'sample.txt')
        result=self.server.workspace.analyses.run('项目复核',tasks=['合同金额'])
        self.assertEqual(result['tasks'][0]['task'],'合同金额')
        self.assertTrue(result['sources'])
        with self.assertRaises(ValidationError): self.server.workspace.analyses.run('项目复核',tasks=[])

    def test_table_sources_are_included_and_traceable(self):
        table=self.server.workspace.tables.import_csv('sample.csv','客户,金额\n虚构客户,100\n'.encode())
        result=self.server.workspace.analyses.run('虚构客户')
        self.assertEqual(result['sources'][0]['document_id'],table['id'])
        self.assertEqual(result['sources'][0]['location'],'CSV 第2行')
        self.assertIn('金额：100',result['sources'][0]['content'])
        self.assertEqual(self.server.workspace.analyses.run('虚构客户',selected_ids=[])['sources'],[])
        self.assertEqual(self.server.workspace.analyses.run('虚构客户',selected_ids=[table['id']])['sources'][0]['document_id'],table['id'])
        calculation=self.server.workspace.tables.calculate(table['id'],{'operation':'sum','measure':'金额'})
        result=self.server.workspace.analyses.run('客户',selected_ids=[table['id']],calculation_ids=[calculation['id']])
        self.assertTrue(any(item['id']==calculation['id'] for item in result['sources']))
        with self.assertRaises(ValidationError):
            self.server.workspace.analyses.run('客户',selected_ids=[],calculation_ids=[calculation['id']])

    def test_archive_preserves_source_and_reopens(self):
        status, doc = self.upload('合同付款期限为30天。'.encode(), 'sample.txt')
        self.assertEqual(status, 201)
        status, result = self.json_request('POST','/api/analyze',{'question':'付款期限'}, {'X-Local-Token':self.server.token})
        self.assertEqual(status,201)
        self.assertEqual(result['sources'][0]['content'],'合同付款期限为30天。')
        self.assertEqual(result['conclusions'][0]['citations'][0]['quote'],result['sources'][0]['content'])
        self.stop_server(); self.start_server()
        status, saved = self.json_request('GET','/api/analysis?id='+result['id'])
        self.assertEqual((status,saved),(200,result))

    def test_invalid_model_citation_is_rejected(self):
        self.upload('合同付款期限为30天。'.encode(), 'sample.txt')
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*args):
                payload={'conclusions':[{'text':'付款期限60天','citations':[{'id':'forged','quote':'60天'}]}]}
                return json.dumps({'choices':[{'message':{'content':json.dumps(payload)}}]}).encode()
        class FakeOpener:
            def open(self,*args,**kwargs): return FakeResponse()
        with patch('evidence_app.analysis_service.build_opener', return_value=FakeOpener()):
            with self.assertRaises(ValidationError):
                self.server.workspace.analyses.run('付款期限',mode='local_model')

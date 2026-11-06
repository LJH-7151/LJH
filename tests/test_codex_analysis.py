import io
import json
import unittest
import zipfile
from unittest.mock import patch

from evidence_app.codex_analysis import _validate
from evidence_app.report_export import word_report, analysis_spreadsheet
from evidence_app.common import ValidationError
from support import HTTPFixture


class CodexAnalysisTests(HTTPFixture):
    def test_automatic_customer_metrics_are_scoped_and_cited(self):
        table = self.server.workspace.tables.import_csv('metrics.csv', '期间,签约客户数（户）\n2026-01,12\n2026-02,15\n'.encode())
        self.server.workspace.tables.import_csv('other.csv', '期间,签约客户数（户）\n2026-01,999\n'.encode())
        def model(store, question, sources, inventory):
            self.assertEqual(len(inventory), 1)
            source = next(s for s in sources if s.get('metadata', {}).get('category') == '计算证据')
            return ([{'text': '客户数上升', 'citations': [{'id': source['id'], 'quote': source['content']}]}], [{'text': '跟踪转化'}])
        with patch('evidence_app.codex_analysis.synthesize', side_effect=model):
            result = self.server.workspace.analyses.run('企业发展客户分析', mode='codex', selected_ids=[table['id']], external_confirmed=True)
        self.assertEqual(len(result['calculation_ids']), 1)
        calculation = next(s for s in result['sources'] if s.get('metadata', {}).get('category') == '计算证据')
        changes = json.loads(calculation['content'])['period_changes']
        self.assertEqual(changes[0]['change'], '3')
        self.assertEqual(changes[0]['percent'], '25.00')
        self.assertTrue(all(s['document_id'] == table['id'] for s in result['sources']))
        self.assertEqual(result['actions'][0]['text'], '跟踪转化')
        self.assertFalse(result['gaps'])
        self.assertEqual(result, self.server.workspace.analyses.get(result['id']))
        with zipfile.ZipFile(io.BytesIO(word_report(result))) as report:
            self.assertIn('word/media/chart1.png', report.namelist())
            self.assertIn('客户数上升', report.read('word/document.xml').decode())
            self.assertIn('跟踪转化', report.read('word/document.xml').decode())
        with zipfile.ZipFile(io.BytesIO(analysis_spreadsheet(result))) as report:
            self.assertIn('跟踪转化', report.read('xl/worksheets/sheet2.xml').decode())
            self.assertIn('客户数上升', report.read('xl/worksheets/sheet1.xml').decode())

    def test_codex_requires_explicit_consent_before_running(self):
        with patch('evidence_app.codex_analysis.synthesize') as model:
            with self.assertRaises(ValidationError):
                self.server.workspace.analyses.run('企业发展分析', mode='codex')
            model.assert_not_called()

    def test_http_consent_and_excel_download(self):
        self.upload('模拟客户数为12户。'.encode(), 'sample.txt')
        request={'question':'客户数','mode':'codex'}
        headers={'X-Local-Token':self.server.token}
        status,_=self.json_request('POST','/api/analyze',request,headers)
        self.assertEqual(status,400)
        def model(store, question, sources, inventory):
            source=sources[0]
            return ([{'text':'客户数为12户','citations':[{'id':source['id'],'quote':source['content']}]}],
                    [{'text':'跟踪客户数','owner':'销售负责人'}])
        request['external_confirmed']=True
        with patch('evidence_app.codex_analysis.synthesize',side_effect=model):
            status,analysis=self.json_request('POST','/api/analyze',request,headers)
        self.assertEqual(status,201)
        status,headers,raw=self.request('GET','/api/analysis-export?id='+analysis['id']+'&format=xlsx')
        self.assertEqual(status,200)
        with zipfile.ZipFile(io.BytesIO(raw)) as report:
            self.assertIn('销售负责人',report.read('xl/worksheets/sheet2.xml').decode())

    def test_action_evidence_must_be_valid(self):
        payload={'conclusions':[{'text':'正常','citations':[{'id':'a','quote':'原文'}]}],
                 'actions':[{'text':'建议','evidence_ids':['unknown']}]}
        with self.assertRaises(ValueError):
            _validate(payload, [{'id':'a','content':'原文'}])

    def test_rejects_invented_citation(self):
        with self.assertRaises(ValueError):
            _validate({'conclusions': [{'text':'错误', 'citations':[{'id':'a','quote':'不存在'}]}]}, [{'id':'a','content':'原文'}])

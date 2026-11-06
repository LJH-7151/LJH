import io
import json
import unittest
import zipfile
from unittest.mock import patch

from evidence_app.codex_analysis import _validate
from evidence_app.report_export import word_report
from support import HTTPFixture


class CodexAnalysisTests(HTTPFixture):
    def test_automatic_customer_metrics_are_scoped_and_cited(self):
        table = self.server.workspace.tables.import_csv('metrics.csv', '期间,签约客户数（户）\n2026-01,12\n2026-02,15\n'.encode())
        self.server.workspace.tables.import_csv('other.csv', '期间,签约客户数（户）\n2026-01,999\n'.encode())
        def model(store, question, sources):
            source = next(s for s in sources if s.get('metadata', {}).get('category') == '计算证据')
            return ([{'text': '客户数上升', 'citations': [{'id': source['id'], 'quote': source['content']}]}], [{'text': '跟踪转化'}])
        with patch('evidence_app.codex_analysis.synthesize', side_effect=model):
            result = self.server.workspace.analyses.run('企业发展客户分析', mode='codex', selected_ids=[table['id']])
        self.assertEqual(len(result['calculation_ids']), 1)
        self.assertTrue(all(s['document_id'] == table['id'] for s in result['sources']))
        self.assertEqual(result['actions'][0]['text'], '跟踪转化')
        self.assertFalse(result['gaps'])
        self.assertEqual(result, self.server.workspace.analyses.get(result['id']))
        with zipfile.ZipFile(io.BytesIO(word_report(result))) as report:
            self.assertIn('word/media/chart1.png', report.namelist())
            self.assertIn('客户数上升', report.read('word/document.xml').decode())
            self.assertIn('跟踪转化', report.read('word/document.xml').decode())

    def test_rejects_invented_citation(self):
        with self.assertRaises(ValueError):
            _validate({'conclusions': [{'text':'错误', 'citations':[{'id':'a','quote':'不存在'}]}]}, [{'id':'a','content':'原文'}])

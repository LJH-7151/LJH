import json
from unittest.mock import patch

from evidence_app.common import ValidationError
from support import HTTPFixture


class OcrReviewTests(HTTPFixture):
    def test_review_required_before_search_and_backup(self):
        class Result:
            stdout=json.dumps({'text':'模拟合同 PAYMENT','language':'zh-Hans-CN'}).encode()
        with patch('evidence_app.ocr_review.subprocess.run',return_value=Result()):
            draft=self.server.workspace.ocr.recognize('image.png',b'fictional image bytes')
        self.assertEqual(draft['state'],'pending')
        self.assertEqual(self.server.workspace.search('PAYMENT')['total'],0)
        confirmed=self.server.workspace.ocr.confirm(draft['id'],'复核后的 PAYMENT')
        self.assertEqual(confirmed['state'],'confirmed')
        self.assertEqual(self.server.workspace.search('PAYMENT')['total'],1)
        with self.assertRaises(ValidationError): self.server.workspace.ocr.confirm(draft['id'],'再次确认')

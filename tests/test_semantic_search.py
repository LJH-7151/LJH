from unittest.mock import patch
from support import HTTPFixture


class SemanticTests(HTTPFixture):
    def test_index_search_and_archive(self):
        _,first=self.upload('合同付款期限'.encode(),'a.txt')
        _,second=self.upload('库存交付'.encode(),'b.txt')
        def vectors(texts):
            return [[1.0,0.0] if '合同' in text else [0.0,1.0] for text in texts]
        with patch.object(self.server.workspace.semantic,'_embed',side_effect=vectors):
            result=self.server.workspace.semantic.build()
            self.assertEqual(result['indexed'],2)
            matches=self.server.workspace.semantic.search('合同')
            self.assertEqual(matches[0]['document_id'],first['document']['id'])
            self.server.workspace.catalog.update(first['document']['id'],{'archived':True})
            matches=self.server.workspace.semantic.search('合同')
            self.assertEqual([item['document_id'] for item in matches],[second['document']['id']])

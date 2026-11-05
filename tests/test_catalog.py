from evidence_app.common import ValidationError
from support import HTTPFixture


class CatalogTests(HTTPFixture):
    def test_versions_archive_and_snapshot(self):
        _, first=self.upload('版本一付款30天'.encode(),'v1.txt')
        _, second=self.upload('版本二付款60天'.encode(),'v2.txt')
        a,b=first['document']['id'],second['document']['id']
        archive=self.server.workspace.analyses.run('付款')
        catalog=self.server.workspace.catalog
        catalog.update(b,{'version':'v2','supersedes':a,'entity':'虚构公司'})
        with self.assertRaises(ValidationError): catalog.update(a,{'supersedes':b})
        catalog.update(a,{'archived':True})
        self.assertEqual(self.server.workspace.search('付款')['total'],1)
        self.assertEqual(len(self.server.workspace.analyses.get(archive['id'])['sources']),2)
        catalog.update(a,{'archived':False})
        self.assertEqual(self.server.workspace.search('付款')['total'],2)

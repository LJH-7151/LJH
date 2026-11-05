import base64
from urllib.parse import urlencode

from support import HTTPFixture


class TableHTTPTests(HTTPFixture):
    def test_import_calculate_and_retrieve_after_restart(self):
        data = base64.b64encode('部门,金额\n销售,10.10\n销售,9.90\n'.encode()).decode()
        headers = {'X-Local-Token': self.server.token}
        status, table = self.json_request('POST', '/api/tables', {'name':'sample.csv','content':data}, headers)
        self.assertEqual(status, 201)
        self.assertEqual(table['row_count'], 2)
        status, calculation = self.json_request('POST', '/api/table-calculate',
            {'table_id':table['id'],'operation':'sum','measure':'金额','group_by':'部门'}, headers)
        self.assertEqual(status, 201)
        self.assertEqual(calculation['groups'][0]['value'], '20.00')
        self.stop_server()
        self.start_server()
        status, saved = self.json_request('GET', '/api/table-result?' + urlencode({'id':calculation['id']}))
        self.assertEqual(status, 200)
        self.assertEqual(saved, calculation)
        status, listing = self.json_request('GET', '/api/tables')
        self.assertEqual(status, 200)
        self.assertEqual(listing['tables'][0]['id'], table['id'])

    def test_rejects_missing_token_and_invalid_input(self):
        status, _ = self.json_request('POST', '/api/tables', {'name':'a.csv','content':'YQ=='})
        self.assertEqual(status, 403)
        status, _ = self.json_request('POST', '/api/table-calculate',
                                      {'table_id':'missing','operation':'count'}, {'X-Local-Token': self.server.token})
        self.assertEqual(status, 404)

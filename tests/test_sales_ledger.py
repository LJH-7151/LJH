from decimal import Decimal
import base64
import io
import zipfile
from evidence_app.common import ValidationError
from support import HTTPFixture


class SalesLedgerTests(HTTPFixture):
    def test_http_import_chinese_headers_preserves_original_and_lineage(self):
        raw='订单号,明细号,商品编码,支付金额,支付时间,订单状态\nO1,1,S1,10.00,2026-10-02,已支付\n'.encode()
        payload={'kind':'orders','namespace':'虚构','name':'orders.csv','content':base64.b64encode(raw).decode()}
        status,batch=self.json_request('POST','/api/ledger/import',payload,{'X-Local-Token':self.server.token})
        self.assertEqual(status,201)
        self.assertEqual(self.server.workspace.store.blob(batch['source_sha256']).read_bytes(),raw)
        result=self.server.workspace.sales.calculate('2026-10-01','2026-11-01','2026-10-31')
        sources=self.server.workspace.sales.sources(result['id'])
        self.assertEqual(sources[0]['origins'][0]['location'],'CSV 第2行')
        self.assertEqual(sources[0]['origins'][0]['source_sha256'],batch['source_sha256'])
        status,_,content=self.request('GET','/api/ledger/export?id='+result['id'])
        self.assertEqual(status,200)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            sheet=archive.read('xl/worksheets/sheet1.xml').decode()
        self.assertIn(batch['source_sha256'],sheet)
        self.assertIn('CSV 第2行',sheet)

    def test_duplicate_update_and_immutable_snapshot(self):
        ledger=self.server.workspace.sales
        order={'order_id':'O1','line_id':'1','sku':'S1','amount':'100.00','paid_at':'2026-10-02','status':'paid'}
        refund={'refund_id':'R1','order_id':'O1','line_id':'1','amount':'12.50','refunded_at':'2026-10-03','status':'completed'}
        self.assertEqual(ledger.import_records('orders','虚构来源',[order])['added'],1)
        self.assertEqual(ledger.import_records('orders','虚构来源',[order])['duplicate'],1)
        ledger.import_records('refunds','虚构来源',[refund])
        old=ledger.calculate('2026-10-01','2026-11-01','2026-10-31')
        self.assertEqual(Decimal(old['net']),Decimal('87.50'))
        changed=order | {'amount':'120.00'}
        with self.assertRaises(ValidationError): ledger.import_records('orders','虚构来源',[changed])
        ledger.import_records('orders','虚构来源',[changed],allow_update=True)
        current=ledger.calculate('2026-10-01','2026-11-01','2026-10-31')
        self.assertEqual(Decimal(current['net']),Decimal('107.50'))
        self.assertNotEqual(old['record_ids'],current['record_ids'])
        self.assertTrue(ledger.recompute(old['id'])['matches'])
        self.assertEqual(Decimal(ledger.recompute(old['id'])['net']),Decimal('87.50'))

    def test_over_refund_rolls_back(self):
        ledger=self.server.workspace.sales
        order={'order_id':'O1','line_id':'1','sku':'S1','amount':'10','paid_at':'2026-10-02','status':'paid'}
        ledger.import_records('orders','虚构来源',[order])
        refund={'refund_id':'R1','order_id':'O1','line_id':'1','amount':'11','refunded_at':'2026-10-03','status':'completed'}
        with self.assertRaises(ValidationError): ledger.import_records('refunds','虚构来源',[refund])
        result=ledger.calculate('2026-10-01','2026-11-01','2026-10-31')
        self.assertEqual(Decimal(result['net']),Decimal('10'))

    def test_refund_occurrence_includes_earlier_orders_and_sources(self):
        ledger=self.server.workspace.sales
        order={'order_id':'O1','line_id':'1','sku':'S1','amount':'10','paid_at':'2026-09-02','status':'paid'}
        refund={'refund_id':'R1','order_id':'O1','line_id':'1','amount':'4','refunded_at':'2026-10-03','status':'completed'}
        ledger.import_records('orders','虚构来源',[order])
        ledger.import_records('refunds','虚构来源',[refund])
        result=ledger.calculate('2026-10-01','2026-11-01','2026-10-31',refund_mode='occurred')
        self.assertEqual(Decimal(result['net']),Decimal('-4'))
        self.assertEqual(len(result['prior_order_ids']),1)
        self.assertEqual(len(ledger.sources(result['id'])),2)

    def test_growth_and_zero_baseline(self):
        ledger=self.server.workspace.sales
        orders=[{'order_id':'O1','line_id':'1','sku':'S1','amount':'100','paid_at':'2026-09-02','status':'paid'},
                {'order_id':'O2','line_id':'1','sku':'S1','amount':'150','paid_at':'2026-10-02','status':'paid'}]
        ledger.import_records('orders','虚构来源',orders)
        result=ledger.calculate('2026-10-01','2026-11-01','2026-11-01',baseline_start='2026-09-01',baseline_end='2026-10-01')
        self.assertEqual(result['growth_percent'],'50.00')
        self.assertEqual(result['average_order_value'],'150.00')
        self.assertTrue(ledger.recompute(result['baseline_id'])['matches'])
        result=ledger.calculate('2026-10-01','2026-11-01','2026-11-01',baseline_start='2026-08-01',baseline_end='2026-09-01')
        self.assertIsNone(result['growth_percent'])

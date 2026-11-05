import unittest
from decimal import Decimal

from evidence_app.common import ValidationError
from evidence_app.table_analysis import SourceRow, aggregate


class TableAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.rows = [SourceRow('表1!2', {'期间':'一月', '金额':'0.10', '部门':'销售'}),
                     SourceRow('表1!3', {'期间':'一月', '金额':'0.20', '部门':'销售'}),
                     SourceRow('表1!4', {'期间':'二月', '金额':'', '部门':'交付'}),
                     SourceRow('表1!5', {'期间':'二月', '金额':'2.00', '部门':'交付'})]
        self.columns = ['期间', '金额', '部门']

    def test_precision_and_complete_source_lineage(self):
        result = aggregate(self.rows, columns=self.columns, operation='sum', measure='金额', group_by='期间')
        first = next(row for row in result['groups'] if row['group'] == '一月')
        self.assertEqual(Decimal(first['value']), Decimal('0.30'))
        self.assertEqual(first['source_locations'], ['表1!2', '表1!3'])
        self.assertEqual(result['selected'], 4)
        self.assertEqual(result['missing'], 1)

    def test_filter_and_count_without_measure(self):
        result = aggregate(self.rows, columns=self.columns, operation='count',
                           filters=[{'column':'部门','operator':'equals','value':'交付'}])
        self.assertEqual(result['selected'], 2)
        self.assertEqual(result['groups'][0]['value'], '2')
        self.assertEqual(result['groups'][0]['source_locations'], ['表1!4', '表1!5'])

    def test_invalid_values_must_be_explicitly_ignored(self):
        rows = [SourceRow('A1', {'金额':'NaN'}), SourceRow('A2', {'金额':'4'})]
        with self.assertRaises(ValidationError):
            aggregate(rows, columns=['金额'], operation='sum', measure='金额')
        result = aggregate(rows, columns=['金额'], operation='sum', measure='金额', ignore_invalid=True)
        self.assertEqual((result['invalid'], result['groups'][0]['source_locations']), (1, ['A2']))

    def test_duplicate_location_and_unknown_filter_rejected(self):
        with self.assertRaises(ValidationError):
            aggregate(self.rows + self.rows[:1], columns=self.columns, operation='count')
        with self.assertRaises(ValidationError):
            aggregate(self.rows, columns=self.columns, operation='count',
                      filters=[{'column':'未知','operator':'equals','value':'x'}])


if __name__ == '__main__':
    unittest.main()

import copy
import importlib.util
import json
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('analyze', ROOT / 'skills/mcd-no-waste/scripts/analyze.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((ROOT / 'examples/synthetic.json').read_text())
        self.now = datetime.fromisoformat('2026-10-16T11:00:00+08:00')

    def test_breakfast_expires_before_day_ends_despite_enable(self):
        rows = module.analyze(self.payload, self.now)['coupons']
        breakfast = next(r for r in rows if '早餐' in r['title'])
        self.assertEqual(breakfast['status'], '已到期')

    def test_date_only_today_is_not_midnight_expired(self):
        c = {'tradeEndDate': '2026-10-16'}
        self.assertEqual(module.classify(c, self.now)[0], '今天到期')
        self.assertFalse(module.classify(c, self.now)[2])

    def test_unknown_and_conflicting_dates(self):
        for c in ({}, {'tradeEndDateTime': 'broken', 'tradeEndDate': '2026-10-16'},
                  {'tradeEndDateTime': '2026-10-16 10:00:00', 'tradeEndDate': '2026-10-17'}):
            self.assertEqual(module.classify(c, self.now)[0], '时间待确认')

    def test_timezone_and_exact_boundary(self):
        c = {'tradeEndDateTime': '2026-10-16T03:00:00Z'}
        self.assertEqual(module.classify(c, self.now)[0], '已到期')

    def test_no_sensitive_fields_or_false_savings(self):
        c = self.payload['coupons']['data']['coupons'][0]
        c.update(code='PRIVATE_CODE', accountId='PRIVATE_ACCOUNT', image='PRIVATE_SIGNATURE')
        self.payload['account']['data']['accountId'] = 'PRIVATE_ACCOUNT'
        output = json.dumps(module.analyze(self.payload, self.now))
        self.assertNotIn('PRIVATE_', output)
        self.assertNotIn('saving', output)

    def test_incomplete_duplicate_and_changing_pages(self):
        self.assertTrue(module.analyze(self.payload, self.now)['coverage_complete'])
        self.payload['coupons']['data']['totalPages'] = 2
        self.assertFalse(module.analyze(self.payload, self.now)['coverage_complete'])
        self.payload['coupons'] = [self.payload['coupons'], copy.deepcopy(self.payload['coupons'])]
        self.assertFalse(module.analyze(self.payload, self.now)['coverage_complete'])

    def test_error_is_not_empty_wallet(self):
        self.payload['account'] = {'code': 401, 'data': {}}
        with self.assertRaises(ValueError):
            module.analyze(self.payload, self.now)


if __name__ == '__main__':
    unittest.main()

import unittest
from datetime import date
from sqlalchemy import text
import test_auth as auth
from test_auth import SessionLocal
from app.models import Medicine


class StockPagingTests(unittest.TestCase):
    def setUp(self):
        auth.AuthTests.setUp(self)
        with SessionLocal() as db:
            db.execute(text('DROP TABLE IF EXISTS surya_stock_snapshot')); db.commit()
    login = auth.AuthTests.login
    headers = auth.AuthTests.headers

    def seed(self, count=65):
        with SessionLocal() as db:
            for index in range(count):
                db.add(Medicine(name=f'Medicine {index:03}', sku=f'SKU-{index:03}', batch_number='B1', expiry_date=date(2027,1,1), purchase_price=1, selling_price=2, stock_quantity=0 if index%2 else 3))
            db.commit()

    def test_pages_search_filters_and_global_summary(self):
        self.seed(); headers = self.headers()
        first = self.client.get('/api/v1/inventory/stock', headers=headers).json()
        second = self.client.get('/api/v1/inventory/stock', params={'page':2}, headers=headers).json()
        self.assertEqual(first['total'], 65)
        self.assertEqual(len(first['items']), 50)
        self.assertTrue(first['has_more'])
        self.assertEqual(len(second['items']), 15)
        self.assertFalse(second['has_more'])
        self.assertFalse({r['source_id'] for r in first['items']} & {r['source_id'] for r in second['items']})
        for query in ('x', '  '):
            self.assertEqual(self.client.get('/api/v1/inventory/stock/search', params={'q':query}, headers=headers).status_code, 422)
        result = self.client.get('/api/v1/inventory/stock/search', params={'q':'sku-064'}, headers=headers).json()
        self.assertEqual(result['total'], 1)
        zero = self.client.get('/api/v1/inventory/stock', params={'stock_filter':'zero'}, headers=headers).json()
        self.assertEqual(zero['total'], 32)
        self.assertEqual(self.client.get('/api/v1/inventory/stock', params={'expiry_from':'2027-01-02'}, headers=headers).json()['total'], 0)
        summary = self.client.get('/api/v1/inventory/stock/summary', headers=headers).json()
        self.assertEqual(summary, dict(units=99, positive=33, zero=32, review=0))
        self.assertEqual(self.client.get('/api/v1/inventory/stock', params={'page_size':101}, headers=headers).status_code, 422)
        self.assertEqual(self.client.get('/api/v1/inventory/stock').status_code, 401)

    def test_snapshot_union_unimported_and_literal_search(self):
        self.seed(1); headers = self.headers()
        with SessionLocal() as db:
            db.execute(text('CREATE TABLE surya_stock_snapshot (source_id TEXT, name TEXT, quantity INTEGER, source_modified_on TEXT, imported_at TEXT)'))
            db.execute(text("INSERT INTO surya_stock_snapshot VALUES ('SKU-000', 'Medicine 000', 30, NULL, NULL), ('UNIMPORTED', 'Old % item', 7, NULL, NULL)"))
            db.commit()
        def cleanup():
            with SessionLocal() as db:
                db.execute(text('DROP TABLE surya_stock_snapshot')); db.commit()
        self.addCleanup(cleanup)
        result = self.client.get('/api/v1/inventory/stock', headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['total'], 2)
        review = self.client.get('/api/v1/inventory/stock', params={'stock_filter':'review'}, headers=headers).json()
        self.assertEqual(review['total'], 1)
        self.assertIsNone(review['items'][0]['medicine_id'])
        literal = self.client.get('/api/v1/inventory/stock/search', params={'q':'% '}, headers=headers)
        # Whitespace is stripped; a single-character term is rejected.
        self.assertEqual(literal.status_code, 422)
        literal = self.client.get('/api/v1/inventory/stock/search', params={'q':'% item'}, headers=headers).json()
        self.assertEqual(literal['total'], 1)

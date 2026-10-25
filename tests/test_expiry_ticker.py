import unittest
from datetime import date, timedelta
import test_auth as auth
from test_auth import SessionLocal
from app.models import Medicine


class TickerTests(unittest.TestCase):
    setUp = auth.AuthTests.setUp
    login = auth.AuthTests.login
    headers = auth.AuthTests.headers

    def test_compact_unexpired_positive_stock_and_boundaries(self):
        today = date.today()
        with SessionLocal() as db:
            for index, (days, stock) in enumerate([(-1, 5), (0, 5), (30, 5), (31, 5), (5, 0)]):
                db.add(Medicine(name=f'Medicine {index}', sku=f'TICK-{index}', batch_number='B1', expiry_date=today+timedelta(days=days), stock_quantity=stock, purchase_price=1, selling_price=2))
            db.commit()
        response = self.client.get('/api/v1/medicines/expiring-soon', params={'today':str(today)}, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([row['name'] for row in response.json()], ['Medicine 1', 'Medicine 2'])
        self.assertEqual(set(response.json()[0]), {'id','name','batch_number','expiry_date','stock_quantity'})
        self.assertEqual(self.client.get('/api/v1/medicines/expiring-soon').status_code, 401)

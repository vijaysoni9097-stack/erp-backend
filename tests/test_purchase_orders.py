"""Purchase-order API tests against an isolated database."""
import unittest
from datetime import date, timedelta
from uuid import uuid4
from sqlalchemy import select, func
import test_auth as auth
from test_auth import SessionLocal
from app.models import Supplier, Medicine, PharmacistProfile, StockMovement
from app.models.purchase_orders import PurchaseOrder
from app.models.sync import SyncIdentity


class PurchaseOrderTests(unittest.TestCase):
    setUp = auth.AuthTests.setUp
    login = auth.AuthTests.login
    headers = auth.AuthTests.headers

    def seed(self):
        with SessionLocal() as db:
            supplier = Supplier(name='Test supplier')
            medicine = Medicine(name='Test medicine', sku='TEST-PO', batch_number='B01', expiry_date=date.today() + timedelta(days=90), purchase_price=3, selling_price=5, stock_quantity=7)
            db.add_all([supplier, medicine]); db.commit()
            return supplier.id, medicine.id

    def payload(self, supplier, medicine):
        return dict(request_id=str(uuid4()), supplier_id=supplier, currency='INR', expected_delivery=str(date.today()+timedelta(days=2)), notes='Deliver before noon', items=[dict(medicine_id=medicine, quantity=3, unit_price='12.35')])

    def test_save_list_detail_replay_and_stock_unchanged(self):
        supplier, medicine = self.seed(); headers = self.headers(); payload = self.payload(supplier, medicine)
        response = self.client.post('/api/v1/purchase-orders', json=payload, headers=headers)
        self.assertEqual(response.status_code, 201, response.text)
        order = response.json()
        self.assertEqual(order['total_amount'], '37.05')
        self.assertEqual(order['status'], 'pending_approval')
        self.assertEqual(order['items'][0]['medicine_name'], 'Test medicine')
        self.assertEqual(order['items'][0]['line_total'], '37.05')
        self.assertNotIn('request_hash', order)
        self.assertEqual(self.client.post('/api/v1/purchase-orders', json=payload, headers=headers).json()['id'], order['id'])
        self.assertEqual(self.client.get('/api/v1/purchase-orders', headers=headers).json(), [order])
        self.assertEqual(self.client.get(f"/api/v1/purchase-orders/{order['id']}", headers=headers).json(), order)
        with SessionLocal() as db:
            self.assertEqual(db.get(Medicine, medicine).stock_quantity, 7)
            self.assertEqual(db.scalar(select(func.count()).select_from(StockMovement)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(PurchaseOrder)), 1)
            db.get(Supplier, supplier).name = 'Renamed supplier'
            db.get(Medicine, medicine).name = 'Renamed medicine'; db.commit()
        saved = self.client.get(f"/api/v1/purchase-orders/{order['id']}", headers=headers).json()
        self.assertEqual(saved['supplier_name'], 'Test supplier')
        self.assertEqual(saved['items'][0]['medicine_name'], 'Test medicine')
        payload['items'][0]['quantity'] = 4
        self.assertEqual(self.client.post('/api/v1/purchase-orders', json=payload, headers=headers).status_code, 409)

    def test_validation_is_atomic(self):
        supplier, medicine = self.seed(); headers = self.headers()
        for item in [dict(medicine_id=medicine, quantity=0, unit_price='3'), dict(medicine_id=medicine, quantity=1.5, unit_price='3'), dict(medicine_id=medicine, quantity=1, unit_price='-1'), dict(medicine_id=medicine, quantity=1, unit_price='3.001')]:
            payload = self.payload(supplier, medicine); payload['items'] = [item]
            self.assertEqual(self.client.post('/api/v1/purchase-orders', json=payload, headers=headers).status_code, 422)
        for changes in [dict(items=[]), dict(supplier_id=999999), dict(items=[dict(medicine_id=999999, quantity=1, unit_price='3')]), dict(expected_delivery=str(date.today()-timedelta(days=1))), dict(currency='invalid')]:
            payload = self.payload(supplier, medicine); payload.update(changes)
            self.assertIn(self.client.post('/api/v1/purchase-orders', json=payload, headers=headers).status_code, [404, 422])
        payload = self.payload(supplier, medicine); payload['items'] *= 2
        self.assertEqual(self.client.post('/api/v1/purchase-orders', json=payload, headers=headers).status_code, 422)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(PurchaseOrder)), 0)

    def test_access(self):
        supplier, medicine = self.seed(); payload = self.payload(supplier, medicine)
        self.assertEqual(self.client.get('/api/v1/purchase-orders').status_code, 401)
        self.assertEqual(self.client.post('/api/v1/purchase-orders', json=payload).status_code, 401)
        with SessionLocal() as db:
            db.get(PharmacistProfile, 1).role = 'doctor'; db.commit()
        headers = self.headers()
        self.assertEqual(self.client.get('/api/v1/purchase-orders', headers=headers).status_code, 403)
        self.assertEqual(self.client.get('/api/v1/purchase-orders/1', headers=headers).status_code, 403)
        self.assertEqual(self.client.post('/api/v1/purchase-orders', json=payload, headers=headers).status_code, 403)

    def test_two_items_decimal_totals_and_overflow(self):
        supplier, medicine = self.seed(); headers = self.headers()
        payload = self.payload(supplier, medicine)
        payload['items'][0].update(quantity=2147483647, unit_price='9999999999.99')
        self.assertEqual(self.client.post('/api/v1/purchase-orders', json=payload, headers=headers).status_code, 422)
        with SessionLocal() as db:
            other = Medicine(name='Second medicine', sku='TEST-PO-2', batch_number='B02', expiry_date=date.today(), purchase_price=0, selling_price=0, stock_quantity=0)
            db.add(other); db.commit(); other_id = other.id
        payload = self.payload(supplier, medicine)
        payload['items'] = [dict(medicine_id=medicine, quantity=1, unit_price='0.10'), dict(medicine_id=other_id, quantity=1, unit_price='0.20')]
        response = self.client.post('/api/v1/purchase-orders', json=payload, headers=headers)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['total_amount'], '0.30')
        self.assertEqual(self.client.get('/api/v1/purchase-orders/999999', headers=headers).status_code, 404)

    def test_receiving_partial_final_and_retry(self):
        supplier, medicine = self.seed(); headers = self.headers()
        order = self.client.post('/api/v1/purchase-orders', json=self.payload(supplier, medicine), headers=headers).json()
        self.approve_order(order, headers)
        pending = self.client.get('/api/v1/purchase-orders/pending-receipt', headers=headers).json()
        self.assertEqual(pending[0]['items'][0]['remaining_quantity'], 3)
        payload = dict(request_id=str(uuid4()), items=[dict(order_item_id=order['items'][0]['id'], quantity=2, **self.delivery())])
        url = f"/api/v1/purchase-orders/{order['id']}/receipts"
        response = self.client.post(url, json=payload, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'partially_received')
        self.assertEqual(self.client.post(url, json=payload, headers=headers).status_code, 200)
        with SessionLocal() as db:
            self.assertEqual(db.get(Medicine, medicine).stock_quantity, 9)
            self.assertEqual(db.scalar(select(func.count()).select_from(StockMovement)), 1)
        pending = self.client.get('/api/v1/purchase-orders/pending-receipt', headers=headers).json()
        self.assertEqual(pending[0]['items'][0]['remaining_quantity'], 1)
        payload['items'][0]['quantity'] = 1
        self.assertEqual(self.client.post(url, json=payload, headers=headers).status_code, 409)
        payload['request_id'] = str(uuid4())
        self.assertEqual(self.client.post(url, json=payload, headers=headers).json()['status'], 'received')
        self.assertEqual(self.client.get('/api/v1/purchase-orders/pending-receipt', headers=headers).json(), [])
        with SessionLocal() as db:
            self.assertEqual(db.get(Medicine, medicine).stock_quantity, 10)

    def test_receipt_validation_and_short_final_delivery(self):
        supplier, medicine = self.seed(); headers = self.headers()
        order = self.client.post('/api/v1/purchase-orders', json=self.payload(supplier, medicine), headers=headers).json()
        self.approve_order(order, headers)
        url = f"/api/v1/purchase-orders/{order['id']}/receipts"
        payload = dict(request_id=str(uuid4()), items=[dict(order_item_id=order['items'][0]['id'], quantity=0, **self.delivery())])
        self.assertEqual(self.client.post(url, json=payload, headers=headers).status_code, 422)
        payload['items'][0] = dict(order_item_id=999999, quantity=2, **self.delivery())
        self.assertEqual(self.client.post(url, json=payload, headers=headers).status_code, 422)
        with SessionLocal() as db:
            self.assertEqual(db.get(Medicine, medicine).stock_quantity, 7)
        payload['items'][0] = dict(order_item_id=order['items'][0]['id'], quantity=1, **self.delivery())
        payload['close_order'] = True
        self.assertEqual(self.client.post(url, json=payload, headers=headers).json()['status'], 'received')
        snapshot = self.client.get('/api/v1/inventory/source-stock', headers=headers)
        self.assertEqual(snapshot.status_code, 200, snapshot.text)
        self.assertEqual(snapshot.json()['items'][0]['allocated_quantity'], 8)
        medicines = self.client.get('/api/v1/medicines', headers=headers).json()
        self.assertEqual(medicines[0]['stock_quantity'], 8)
        payload['request_id'] = str(uuid4())
        self.assertEqual(self.client.post(url, json=payload, headers=headers).status_code, 409)

    def approve_order(self, order, headers, quantity=None):
        with SessionLocal() as db:
            db.get(PharmacistProfile, 1).role = 'admin'; db.commit()
        payload = {'items': [{'order_item_id': item['id'], 'quantity': quantity or item['quantity']} for item in order['items']]}
        response = self.client.post(f"/api/v1/purchase-orders/{order['id']}/approve", json=payload, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_admin_approval_quantities_and_receipt_gate(self):
        supplier, medicine = self.seed(); headers = self.headers()
        order = self.client.post('/api/v1/purchase-orders', json=self.payload(supplier, medicine), headers=headers).json()
        url = f"/api/v1/purchase-orders/{order['id']}/approve"
        payload = {'items': [{'order_item_id': order['items'][0]['id'], 'quantity': 5}]}
        self.assertEqual(self.client.post(url, json=payload, headers=headers).status_code, 403)
        self.assertEqual(self.client.get('/api/v1/purchase-orders/pending-receipt', headers=headers).json(), [])
        receipt = {'request_id': str(uuid4()), 'items': [{**payload['items'][0], **self.delivery()}]}
        self.assertEqual(self.client.post(f"/api/v1/purchase-orders/{order['id']}/receipts", json=receipt, headers=headers).status_code, 403)
        approved = self.approve_order(order, headers, 5)
        self.assertEqual(approved['status'], 'approved')
        self.assertEqual(approved['total_amount'], '61.75')
        self.assertEqual(self.client.post(url, json=payload, headers=headers).status_code, 200)
        payload['items'][0]['quantity'] = 6
        self.assertEqual(self.client.post(url, json=payload, headers=headers).status_code, 409)
        with SessionLocal() as db:
            self.assertEqual(db.get(Medicine, medicine).stock_quantity, 7)

    def delivery(self):
        return dict(batch_number='B01', expiry_date=str(date.today()+timedelta(days=90)), unit='number', purchase_price='3.00', selling_price='5.00')

    def test_delivery_review_new_batch_and_prices(self):
        supplier, medicine = self.seed(); headers = self.headers()
        order = self.client.post('/api/v1/purchase-orders', json=self.payload(supplier, medicine), headers=headers).json()
        self.approve_order(order, headers)
        details = {**self.delivery(), 'batch_number':'NEW-BATCH', 'unit':'tablet', 'purchase_price':'4.25', 'selling_price':'7.50'}
        payload = dict(request_id=str(uuid4()), items=[dict(order_item_id=order['items'][0]['id'], quantity=3, **details)])
        url = f"/api/v1/purchase-orders/{order['id']}/receipts"
        bad = {**payload, 'items':[{**payload['items'][0], 'expiry_date':str(date.today()-timedelta(days=1))}]}
        self.assertEqual(self.client.post(url, json=bad, headers=headers).status_code, 422)
        self.assertEqual(self.client.post(url, json=payload, headers=headers).status_code, 200)
        self.assertEqual(self.client.post(url, json=payload, headers=headers).status_code, 200)
        with SessionLocal() as db:
            original = db.get(Medicine, medicine)
            self.assertEqual(original.stock_quantity, 7)
            self.assertEqual(original.batch_number, 'B01')
            new = db.scalar(select(Medicine).where(Medicine.batch_number=='NEW-BATCH'))
            self.assertEqual(new.stock_quantity, 3)
            self.assertEqual(new.unit, 'tablet')
            self.assertEqual(str(new.purchase_price), '4.25')
            self.assertEqual(str(new.selling_price), '7.50')

    def test_admin_created_order_still_requires_approval(self):
        supplier, medicine = self.seed()
        with SessionLocal() as db:
            db.get(PharmacistProfile, 1).role = 'admin'; db.commit()
        headers = self.headers()
        response = self.client.post('/api/v1/purchase-orders', json=self.payload(supplier, medicine), headers=headers)
        self.assertEqual(response.status_code, 201, response.text)
        order = response.json()
        self.assertEqual(order['status'], 'pending_approval')
        self.assertEqual(self.client.get('/api/v1/purchase-orders/pending-receipt', headers=headers).json(), [])
        approved = self.approve_order(order, headers)
        self.assertEqual(approved['status'], 'approved')
        pending = self.client.get('/api/v1/purchase-orders/pending-receipt', headers=headers).json()
        self.assertEqual(pending[0]['id'], order['id'])

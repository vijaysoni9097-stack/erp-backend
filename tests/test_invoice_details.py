import unittest
from datetime import date,timedelta
import test_auth as auth
import test_checkout as checkout
from test_auth import SessionLocal
from app.models import Medicine

class InvoiceDetailTests(unittest.TestCase):
    setUp=auth.AuthTests.setUp
    login=auth.AuthTests.login
    headers=auth.AuthTests.headers
    seed=checkout.CheckoutTests.seed
    payload=checkout.CheckoutTests.payload

    def test_saved_invoice_has_customer_prescriber_and_medicine_details(self):
        mid=self.seed();headers=self.headers();payload=self.payload(mid)
        payload['customer_mobile']='9876543210';payload['prescribed_by']='Dr Saved'
        response=self.client.post('/api/v1/sales/checkout',headers=headers,json=payload)
        self.assertEqual(response.status_code,201,response.text)
        invoice=response.json()
        self.assertEqual(invoice['patient_name'],'Test Patient')
        self.assertEqual(invoice['customer_mobile'],'+919876543210')
        self.assertEqual(invoice['prescribed_by'],'Dr Saved')
        self.assertEqual(invoice['items'][0]['medicine_name'],'Checkout medicine')
        self.assertEqual(invoice['items'][0]['batch_number'],'TEST')
        self.assertEqual(invoice['items'][0]['expiry_date'],str(date.today()+timedelta(days=30)))
        saved=self.client.get('/api/v1/sales',headers=headers).json()[0]
        self.assertEqual(saved['patient_name'],invoice['patient_name'])
        self.assertEqual(saved['prescribed_by'],invoice['prescribed_by'])
        self.assertEqual(saved['customer_mobile'],invoice['customer_mobile'])
        self.assertEqual(saved['items'][0]['batch_number'],'TEST')

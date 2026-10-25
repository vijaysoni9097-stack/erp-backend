import unittest
from decimal import Decimal
from unittest.mock import patch
import test_auth as auth
from test_auth import SessionLocal
import test_checkout as checkout
from app.models import PharmacistProfile, Medicine
from app.models.settings import EmployeeRole

class CompanyDiscountTests(unittest.TestCase):
    setUp=auth.AuthTests.setUp
    login=auth.AuthTests.login
    headers=auth.AuthTests.headers
    seed=checkout.CheckoutTests.seed
    payload=checkout.CheckoutTests.payload

    def test_company_snapshot_discount_and_retry(self):
        with SessionLocal() as db:
            db.get(PharmacistProfile,1).role=EmployeeRole.superadmin;db.commit()
        headers=self.headers();mid=self.seed()
        company={'company_name':'Registered Test Company','address':'Test address','gstin':'27ABCDE1234F1Z5'}
        self.assertEqual(self.client.put('/api/v1/settings/company',headers=headers,json=company).status_code,200)
        p=self.payload(mid);p['items'][0]['discount_percent']='10';p['payment']['tendered']='6.00'
        response=self.client.post('/api/v1/sales/checkout',headers=headers,json=p)
        self.assertEqual(response.status_code,201,response.text)
        sale=response.json();self.assertEqual(Decimal(sale['subtotal']),Decimal('5.85'))
        self.assertEqual(Decimal(sale['payment']['change']),Decimal('.15'))
        self.assertEqual(Decimal(sale['items'][0]['original_unit_price']),Decimal('3.25'))
        self.assertEqual(Decimal(sale['items'][0]['unit_price']),Decimal('3.25'))
        self.assertEqual(Decimal(sale['items'][0]['discount_amount']),Decimal('.65'))
        self.assertEqual(sale['company'],company)
        company['company_name']='Updated Company'
        self.client.put('/api/v1/settings/company',headers=headers,json=company)
        replay=self.client.post('/api/v1/sales/checkout',headers=headers,json=p)
        self.assertEqual(replay.json()['company']['company_name'],'Registered Test Company')
        p['items'][0]['discount_percent']='20'
        self.assertEqual(self.client.post('/api/v1/sales/checkout',headers=headers,json=p).status_code,409)
        with SessionLocal() as db:self.assertEqual(db.get(Medicine,mid).stock_quantity,3)

    def test_discount_bounds_and_exact_digital_payment(self):
        headers=self.headers();mid=self.seed()
        for rate in ['-1','100.01','10.001']:
            p=self.payload(mid);p['items'][0]['discount_percent']=rate
            self.assertEqual(self.client.post('/api/v1/sales/checkout',headers=headers,json=p).status_code,422)
        p=self.payload(mid);p['items'][0]['discount_percent']='100';p['payment']={'method':'upi','tendered':'0.00','reference':'test','confirmed':True}
        result=self.client.post('/api/v1/sales/checkout',headers=headers,json=p)
        self.assertEqual(result.status_code,201,result.text)
        self.assertEqual(Decimal(result.json()['total_amount']),0)

    def test_company_edit_permissions(self):
        headers=self.headers()
        self.assertEqual(self.client.get('/api/v1/settings/company').status_code,401)
        self.assertEqual(self.client.get('/api/v1/settings/company',headers=headers).status_code,200)
        self.assertEqual(self.client.put('/api/v1/settings/company',headers=headers,json={'company_name':'test'}).status_code,403)



    def test_admin_registers_once_superadmin_can_update(self):
        with SessionLocal() as db:
            db.get(PharmacistProfile,1).role=EmployeeRole.admin;db.commit()
        headers=self.headers()
        company={'company_name':'Initial company','address':'Registered address','gstin':'27ABCDE1234F1Z5'}
        self.assertFalse(self.client.get('/api/v1/settings/company',headers=headers).json()['registered'])
        self.assertEqual(self.client.put('/api/v1/settings/company',headers=headers,json=company).status_code,200)
        self.assertTrue(self.client.get('/api/v1/settings/company',headers=headers).json()['registered'])
        company['company_name']='Attempted edit'
        self.assertEqual(self.client.put('/api/v1/settings/company',headers=headers,json=company).status_code,403)
        self.assertEqual(self.client.put('/api/v1/settings/billing',headers=headers,json={'gstin':None}).status_code,403)
        with SessionLocal() as db:
            db.get(PharmacistProfile,1).role=EmployeeRole.superadmin;db.commit()
        headers=self.headers()
        company['company_name']='Superadmin updated company'
        self.assertEqual(self.client.put('/api/v1/settings/company',headers=headers,json=company).status_code,200)
        self.assertEqual(self.client.get('/api/v1/settings/company',headers=headers).json()['company_name'],company['company_name'])
        self.assertEqual(self.client.put('/api/v1/settings/company',headers=headers,json={**company,'company_name':'   '}).status_code,422)

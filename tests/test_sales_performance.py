import unittest
from datetime import datetime
from decimal import Decimal
from sqlalchemy import event,select
from sqlalchemy.orm import selectinload
import test_auth as auth
from test_auth import SessionLocal,engine
import test_checkout as checkout
from app.models import Sale,SaleItem
from app.models.sales import SalePayment
from app.models.company import SaleCompany,SaleLineDiscount
from app.schemas import SaleRead
from app.api.sales.sales import SaleAPI

class SalesPerformanceTests(unittest.TestCase):
    setUp=auth.AuthTests.setUp
    login=auth.AuthTests.login
    headers=auth.AuthTests.headers
    seed=checkout.CheckoutTests.seed

    def add_sale(self,db,mid,when,lines=1):
        sale=Sale(subtotal=Decimal(lines),tax_amount=0,total_amount=Decimal(lines),created_at=when)
        sale.payment=SalePayment(method='cash',amount=Decimal(lines),tendered=Decimal(lines),change=0)
        sale.company_record=SaleCompany(company_name='Performance test')
        sale.items=[SaleItem(medicine_id=mid,quantity=1,unit_price=1,line_total=1,discount_record=SaleLineDiscount(original_unit_price=1,discount_percent=0)) for _ in range(lines)]
        db.add(sale)

    def test_invoice_serialization_batches_related_queries(self):
        mid=self.seed(stock=1000)
        with SessionLocal() as db:
            for _ in range(20):self.add_sale(db,mid,datetime(2026,10,25,10),2)
            db.commit()
        counts=[]
        def count(conn,cursor,statement,params,context,many):
            if statement.lstrip().upper().startswith('SELECT'):counts.append(statement)
        event.listen(engine,'before_cursor_execute',count)
        try:
            with SessionLocal() as db:
                legacy=list(db.scalars(select(Sale).options(selectinload(Sale.items))))
                [SaleRead.model_validate(row) for row in legacy]
            before=len(counts);counts.clear()
            with SessionLocal() as db:
                result=SaleAPI.get(db=db)
                data=[SaleRead.model_validate(row) for row in result]
                self.assertEqual(len(data),20)
                self.assertEqual(data[0].payment.method,'cash')
                self.assertEqual(data[0].company.company_name,'Performance test')
                self.assertEqual(data[0].items[0].discount_percent,0)
            after=len(counts)
            self.assertEqual(after,2)
            self.assertGreaterEqual(before,80)
            print(f'Invoice serialization SQL checks: {before} -> {after} SELECTs for 20 invoices / 40 lines.')
        finally:event.remove(engine,'before_cursor_execute',count)

    def test_day_filter_uses_utc_bounds_and_half_open_range(self):
        mid=self.seed()
        with SessionLocal() as db:
            for when in [datetime(2026,10,24,18,29,59),datetime(2026,10,24,18,30),datetime(2026,10,25,18,29,59),datetime(2026,10,25,18,30)]:self.add_sale(db,mid,when)
            db.commit()
        headers=self.headers()
        response=self.client.get('/api/v1/sales',headers=headers,params={'from_at':'2026-10-25T00:00:00+05:30','to_at':'2026-10-26T00:00:00+05:30'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(response.json()),2)
        self.assertEqual(len(self.client.get('/api/v1/sales',headers=headers).json()),4)
        self.assertEqual(self.client.get('/api/v1/sales',headers=headers,params={'from_at':'2026-10-26','to_at':'2026-10-25'}).status_code,422)

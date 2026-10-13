import unittest
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import select
from fastapi import HTTPException
import test_auth as auth
from test_auth import SessionLocal
from app.models import Supplier, Medicine
from app.models.sync import SyncIdentity, SyncOutbox, SyncState, OfflineLease
from app.services.sync_queue import enqueue_record, prepare_operation, acknowledge, apply_page, apply_allocations
from app.services.cloud_sync import check_lease

class SyncTests(unittest.TestCase):
    setUp=auth.AuthTests.setUp
    def test_outbox_is_atomic_with_business_write(self):
        with SessionLocal() as db:
            supplier=Supplier(name='Offline Supplier'); db.add(supplier); db.flush()
            enqueue_record(db,'suppliers',supplier,1)
            db.rollback()
            self.assertIsNone(db.scalar(select(Supplier).where(Supplier.name=='Offline Supplier')))
            self.assertIsNone(db.scalar(select(SyncOutbox)))
        with SessionLocal() as db:
            supplier=Supplier(name='Offline Supplier'); db.add(supplier); db.flush()
            enqueue_record(db,'suppliers',supplier,1); db.commit()
        with SessionLocal() as db:
            self.assertIsNotNone(db.scalar(select(SyncOutbox)))
            self.assertIsNotNone(db.scalar(select(Supplier).where(Supplier.name=='Offline Supplier')))
    def test_retry_envelope_stays_stable_and_next_edit_uses_new_version(self):
        with SessionLocal() as db:
            s=Supplier(name='One'); db.add(s); db.flush()
            o=enqueue_record(db,'suppliers',s,1); db.flush()
            first=prepare_operation(db,o); db.commit()
            mapping=db.scalar(select(SyncIdentity)); mapping.version=99; db.commit()
            self.assertEqual(prepare_operation(db,o),first)
            acknowledge(db,o,{'status':'applied','record':{'version':1}}); db.commit()
            s.name='Two'; o2=enqueue_record(db,'suppliers',s,1); db.flush()
            self.assertEqual(prepare_operation(db,o2)['p_base_version'],1)
    def test_pull_and_cursor_rollback_together(self):
        with SessionLocal() as db:
            page={'cursor':2,'changes':[{'cursor':1,'entity':'suppliers','record_id':str(uuid4()),'version':1,'deleted':False,'payload':{'name':'Pulled'}},
                                      {'cursor':2,'entity':'unsupported','record_id':str(uuid4()),'version':1,'deleted':False,'payload':{}}]}
            with self.assertRaises(ValueError): apply_page(db,page)
            db.rollback()
            self.assertIsNone(db.scalar(select(Supplier).where(Supplier.name=='Pulled')))
            self.assertIsNone(db.get(SyncState,1))
    def test_pending_edits_are_not_overwritten(self):
        with SessionLocal() as db:
            s=Supplier(name='Local edit'); db.add(s); db.flush(); o=enqueue_record(db,'suppliers',s,1); db.flush(); db.commit()
            page={'cursor':1,'changes':[{'cursor':1,'entity':'suppliers','record_id':o.cloud_id,'version':1,'deleted':False,'payload':{'name':'Remote edit'}}]}
            with self.assertRaises(ValueError): apply_page(db,page)
            db.rollback(); self.assertEqual(db.get(Supplier,s.id).name,'Local edit')
    def test_pull_replay(self):
        with SessionLocal() as db:
            page={'cursor':1,'changes':[{'cursor':1,'entity':'suppliers','record_id':str(uuid4()),'version':1,'deleted':False,'payload':{'name':'Pulled'}}]}
            apply_page(db,page); db.commit(); apply_page(db,page); db.commit()
            self.assertEqual(len(db.scalars(select(Supplier).where(Supplier.name=='Pulled')).all()),1)
    def test_24_hour_lease_and_clock_rollback(self):
        with SessionLocal() as db:
            lease=OfflineLease(profile_id=1,cloud_employee_id=str(uuid4()),expires_at=datetime.utcnow()+timedelta(hours=24),last_observed_at=datetime.utcnow())
            db.add(lease); db.commit(); check_lease(db,1)
            lease.expires_at=datetime.utcnow()-timedelta(seconds=1); db.commit()
            with self.assertRaises(HTTPException): check_lease(db,1)
            lease.expires_at=datetime.utcnow()+timedelta(hours=24); lease.last_observed_at=datetime.utcnow()+timedelta(hours=1); db.commit()
            with self.assertRaises(HTTPException): check_lease(db,1)
    def test_supplier_api_queues_when_enrolled(self):
        from app.config import get_settings
        headers=auth.AuthTests.headers(self)
        with SessionLocal() as db:
            db.add(OfflineLease(profile_id=1,cloud_employee_id=str(uuid4()),expires_at=datetime.utcnow()+timedelta(hours=24),last_observed_at=datetime.utcnow()))
            db.commit()
        with patch.object(get_settings(),'sync_enabled',True):
            response=self.client.post('/api/v1/suppliers',headers=headers,json={'name':'Queued API supplier'})
            self.assertEqual(response.status_code,201,response.text)
            supplier_id=response.json()['id']
            self.assertEqual(self.client.put(f'/api/v1/suppliers/{supplier_id}',headers=headers,json={'name':'Edited supplier'}).status_code,200)
            self.assertEqual(self.client.delete(f'/api/v1/suppliers/{supplier_id}',headers=headers).status_code,204)
            with SessionLocal() as db:
                operations=db.scalars(select(SyncOutbox).order_by(SyncOutbox.sequence)).all()
                self.assertEqual(len(operations),3)
                self.assertTrue(operations[-1].deleted)
    def test_allocations_subtract_pending_sales(self):
        from datetime import date
        from app.services.sync_queue import identity
        with SessionLocal() as db:
            med=Medicine(name='Test',sku='TEST',batch_number='B',expiry_date=date(2030,1,1),purchase_price=1,selling_price=2,stock_quantity=99)
            db.add(med); db.flush(); mapping=identity(db,'medicines',med.id)
            db.add(SyncOutbox(operation_id=str(uuid4()),actor_id=1,entity='sales',cloud_id=str(uuid4()),payload={'items':[{'medicine_id':mapping.cloud_id,'quantity':3}]},state='pending'))
            db.flush()
            apply_allocations(db,[{'medicine_id':mapping.cloud_id,'quantity_granted':10,'quantity_consumed':2}])
            self.assertEqual(med.stock_quantity,5)
            db.rollback()
    # Helpers used by AuthTests.headers without inheriting/repeating its test suite.
    login=auth.AuthTests.login

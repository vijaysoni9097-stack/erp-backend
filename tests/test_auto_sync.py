import json
import unittest
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from hashlib import md5
from uuid import UUID, uuid4
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import select, func
import test_auth as auth
from test_auth import SessionLocal
from app.config import get_settings
from app.models import Supplier, Medicine, PharmacistProfile, PharmacySettings, NotificationPreference
from app.models.purchase_orders import PurchaseOrder
from app.models.sync import CloudSession, SyncIdentity, SyncOutbox, SyncState, OfflineLease
from app.services import cloud_sync
from app.services.auto_sync import AutoSyncWorker
from app.services.sync_credentials import save, load
from app.services.sync_queue import queue_if_enabled, enqueue_record, apply_page, FIELDS, serialize

PHARMACY = '00000000-0000-0000-0000-000000000001'
SECRET = 'installation-test-secret-' + 'x' * 40
SESSION = dict(access_token='access-secret', refresh_token='refresh-secret', expires_at=9999999999)

class AutoSyncTests(unittest.TestCase):
    setUp = auth.AuthTests.setUp
    login = auth.AuthTests.login
    headers = auth.AuthTests.headers

    def enrolled(self):
        stack = ExitStack()
        for name, value in dict(sync_enabled=True, sync_device_secret=SECRET, sync_pharmacy_id=PHARMACY).items():
            stack.enter_context(patch.object(get_settings(), name, value))
        self.addCleanup(stack.close)
        cloud_sync._sessions.clear()
        self.addCleanup(cloud_sync._sessions.clear)
        with SessionLocal() as db:
            db.add(OfflineLease(profile_id=1, cloud_employee_id=str(uuid4()), expires_at=datetime.utcnow()+timedelta(hours=24), last_observed_at=datetime.utcnow()))
            save(db, 1, SESSION)

    def test_encrypted_session_restores_rotates_and_logout_forgets(self):
        self.enrolled()
        with SessionLocal() as db:
            ciphertext = db.get(CloudSession, 1).encrypted_session
            self.assertNotIn('refresh-secret', ciphertext)
            self.assertEqual(load(db, 1), SESSION)
            # Ciphertext cannot be transplanted to a different user or installation.
            db.add(CloudSession(profile_id=2, encrypted_session=ciphertext)); db.commit()
            self.assertIsNone(load(db, 2))
            with patch.object(get_settings(), 'sync_device_secret', 'different-device-'+'y'*40): self.assertIsNone(load(db, 1))
            save(db, 1, {**SESSION, 'expires_at': 0})
            renewed = {**SESSION, 'access_token': 'renewed-access', 'refresh_token': 'rotated-refresh'}
            with patch('app.services.cloud_sync.request', return_value=renewed) as request:
                self.assertEqual(cloud_sync.token_for(1, db), 'renewed-access')
                self.assertEqual(request.call_args.args[1], {'refresh_token':'refresh-secret'})
            cloud_sync._sessions.clear()
            self.assertEqual(load(db, 1)['refresh_token'], 'rotated-refresh')
            self.assertTrue(cloud_sync.has_session(1))
            cloud_sync.forget_session(1, db); db.commit()
            self.assertFalse(cloud_sync.has_session(1))

    def test_worker_drains_batches_and_downloads_without_ui(self):
        self.enrolled()
        with SessionLocal() as db:
            for i in range(201):
                supplier = Supplier(name=f'Auto {i}'); db.add(supplier); db.flush()
                enqueue_record(db, 'suppliers', supplier, 1)
            db.commit()
        def reply(path, payload, token):
            if path.endswith('erp_sync_push_batch'):
                return {'receipts':[{'operation_id':o['p_operation'],'result':{'status':'applied','record':{'version':1}}} for o in payload['p_operations']]}
            now = datetime.now(timezone.utc)
            return dict(changes=[], cursor=0, has_more=False, allocations=[], server_time=now.isoformat(), lease_expires_at=(now+timedelta(hours=24)).isoformat(), pharmacy_id=PHARMACY, employee_id=str(uuid4()), role='superadmin')
        worker = AutoSyncWorker()
        with patch('app.services.cloud_sync.request', side_effect=reply) as request:
            self.assertTrue(worker.cycle())
            self.assertFalse(worker.cycle())
            self.assertEqual(request.call_count, 3)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SyncOutbox).where(SyncOutbox.state=='pending')), 0)
            self.assertIsNotNone(db.get(SyncState,1).last_synced_at)

    def test_outage_backoff_and_online_hint(self):
        self.enrolled()
        worker = AutoSyncWorker(clock=lambda: 0)
        with patch('app.services.cloud_sync.synchronize', side_effect=HTTPException(503,'Offline')) as sync:
            worker.cycle(); worker.cycle()
            self.assertEqual(sync.call_count,1)
            worker.notify(1,force=True); worker.cycle()
            self.assertEqual(sync.call_count,2)
        self.assertGreater(worker.retry_at[1],0)

    def seed_purchase(self):
        with SessionLocal() as db:
            supplier=Supplier(name='Auto supplier'); db.add(supplier); db.flush()
            medicine=Medicine(name='Auto medicine',sku='AUTO-MED',batch_number='B',expiry_date=date(2030,1,1),purchase_price=1,selling_price=2,stock_quantity=7,supplier_id=supplier.id)
            db.add(medicine); db.commit()
            return supplier.id, medicine.id

    def test_new_purchase_queues_parents_atomically_and_wakes_after_commit(self):
        headers=self.headers(); supplier,medicine=self.seed_purchase(); self.enrolled()
        payload=dict(request_id=str(uuid4()),supplier_id=supplier,currency='INR',items=[dict(medicine_id=medicine,quantity=3,unit_price='1.25')])
        with patch('app.services.auto_sync.notify') as wake:
            result=self.client.post('/api/v1/purchase-orders',headers=headers,json=payload)
            self.assertEqual(result.status_code,201,result.text)
            wake.assert_called_with(1)
        self.assertEqual(self.client.post('/api/v1/purchase-orders',headers=headers,json=payload).json()['id'],result.json()['id'])
        with SessionLocal() as db:
            operations=list(db.scalars(select(SyncOutbox).order_by(SyncOutbox.sequence)))
            self.assertEqual([o.entity for o in operations],['suppliers','medicines','purchase_orders'])
            self.assertEqual(operations[-1].payload['total_amount'],'3.75')
            self.assertEqual(operations[-1].payload['items'][0]['medicine_id'],operations[1].cloud_id)
            self.assertEqual(db.get(Medicine,medicine).stock_quantity,7)

    def test_rollback_never_wakes_or_keeps_an_outbox(self):
        self.enrolled()
        with patch('app.services.auto_sync.notify') as wake, SessionLocal() as db:
            db.info['actor_id']=1
            supplier=Supplier(name='Rollback'); db.add(supplier)
            queue_if_enabled(db,'suppliers',supplier); db.rollback()
            wake.assert_not_called()
            self.assertIsNone(db.scalar(select(SyncOutbox)))

    def test_old_purchase_is_backfilled_once(self):
        headers=self.headers(); supplier,medicine=self.seed_purchase()
        payload=dict(request_id=str(uuid4()),supplier_id=supplier,currency='INR',items=[dict(medicine_id=medicine,quantity=1,unit_price='1')])
        self.assertEqual(self.client.post('/api/v1/purchase-orders',headers=headers,json=payload).status_code,201)
        self.enrolled()
        with patch('app.services.cloud_sync.synchronize', return_value={'status':'uploading','uploaded':0}):
            worker=AutoSyncWorker(); worker.cycle(); worker.cycle()
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SyncOutbox).where(SyncOutbox.entity=='purchase_orders')),1)

    def test_shared_preferences_queue_and_reuse_seeded_rows(self):
        headers=self.headers(); self.enrolled()
        payload=self.client.get('/api/v1/settings/prescription',headers=headers).json()
        payload['default_prescription_duration_days']=14
        self.assertEqual(self.client.put('/api/v1/settings/prescription',headers=headers,json=payload).status_code,200)
        with SessionLocal() as db:
            operation=db.scalar(select(SyncOutbox).where(SyncOutbox.entity=='pharmacy_settings'))
            expected=str(UUID(md5((PHARMACY+':pharmacy_settings').encode()).hexdigest()))
            self.assertEqual(operation.cloud_id,expected)
            self.assertNotIn('prescription_printer',operation.payload)
            # A second device has a seeded settings row but no mapping yet.
            values={key:serialize(getattr(db.get(PharmacySettings,1),key)) for key in FIELDS['pharmacy_settings']}
            values['default_prescription_duration_days']=21
            db.delete(operation); db.delete(db.scalar(select(SyncIdentity).where(SyncIdentity.cloud_id==expected))); db.commit()
            page={'cursor':1,'changes':[dict(cursor=1,entity='pharmacy_settings',record_id=expected,version=1,deleted=False,payload=values)]}
            apply_page(db,page); db.commit(); apply_page(db,page); db.commit()
            self.assertEqual(db.scalar(select(func.count()).select_from(PharmacySettings)),1)
            self.assertEqual(db.get(PharmacySettings,1).default_prescription_duration_days,21)

    def test_wake_endpoint_requires_auth_and_never_runs_network_inline(self):
        headers=self.headers()
        self.assertEqual(self.client.post('/api/v1/sync/wake',json={}).status_code,401)
        with patch('app.services.auto_sync.notify') as wake:
            result=self.client.post('/api/v1/sync/wake',headers=headers,json={'force':True})
            self.assertEqual(result.status_code,202)
            wake.assert_called_once_with(1,force=True)

    def test_purchase_pull_uses_uuid_parents_and_is_replay_safe(self):
        supplier, medicine = self.seed_purchase()
        supplier_uuid, medicine_uuid, order_uuid = str(uuid4()), str(uuid4()), str(uuid4())
        with SessionLocal() as db:
            db.add_all([SyncIdentity(entity='suppliers',local_id=supplier,cloud_id=supplier_uuid,version=1), SyncIdentity(entity='medicines',local_id=medicine,cloud_id=medicine_uuid,version=1)])
            db.commit()
            payload=dict(request_id=str(uuid4()),request_hash='b'*64,created_by=str(uuid4()),supplier_id=supplier_uuid,supplier_name='Historical supplier',currency='INR',status='pending_approval',created_at='2026-10-19T03:00:00+00:00',expected_delivery=None,notes='Remote order',total_amount='3.75',items=[dict(medicine_id=medicine_uuid,medicine_name='Historical medicine',sku='OLD-SKU',batch_number='OLD-B',quantity=3,unit_price='1.25',line_total='3.75')])
            page=dict(cursor=1,changes=[dict(cursor=1,entity='purchase_orders',record_id=order_uuid,version=1,deleted=False,payload=payload)])
            apply_page(db,page); db.commit(); apply_page(db,page); db.commit()
            self.assertEqual(db.scalar(select(func.count()).select_from(PurchaseOrder)),1)
            order=db.scalar(select(PurchaseOrder))
            self.assertEqual(order.supplier_id,supplier)
            self.assertEqual(order.items[0].medicine_id,medicine)
            self.assertEqual(order.items[0].medicine_name,'Historical medicine')
            self.assertEqual(str(order.total_amount),'3.75')
            self.assertEqual(db.get(Medicine,medicine).stock_quantity,7)

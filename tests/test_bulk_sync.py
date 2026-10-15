import unittest
from unittest.mock import patch
from sqlalchemy import select
import test_auth as auth
from test_auth import SessionLocal
from app.models import Supplier
from app.models.sync import SyncOutbox
from app.services.sync_queue import enqueue_record
from app.services.cloud_sync import upload_batch

class BulkSyncTests(unittest.TestCase):
    setUp=auth.AuthTests.setUp

    def seed(self, db, count):
        for i in range(count):
            supplier=Supplier(name=f'Bulk {i}')
            db.add(supplier); db.flush()
            enqueue_record(db,'suppliers',supplier,1)
        db.commit()

    def reply(self, path, body, token):
        return {'receipts':[{'operation_id':o['p_operation'],
            'result':{'status':'applied','record':{'version':o['p_base_version']+1}}}
            for o in body['p_operations']]}

    def test_200_records_use_one_request(self):
        with SessionLocal() as db:
            self.seed(db,201)
            with patch('app.services.cloud_sync.request',side_effect=self.reply) as request:
                self.assertEqual(upload_batch(db,1,'token'),200)
                self.assertEqual(request.call_count,1)
            self.assertEqual(len(db.scalars(select(SyncOutbox).where(SyncOutbox.state=='pending')).all()),1)

    def test_lost_response_retries_same_envelopes(self):
        with SessionLocal() as db:
            self.seed(db,3)
            with patch('app.services.cloud_sync.request',side_effect=ValueError('lost response')) as request:
                with self.assertRaises(ValueError): upload_batch(db,1,'token')
                first=request.call_args.args[1]
            db.rollback()
            with patch('app.services.cloud_sync.request',side_effect=self.reply) as request:
                self.assertEqual(upload_batch(db,1,'token'),3)
                self.assertEqual(first,request.call_args.args[1])

    def test_conflict_leaves_trailing_operations_pending(self):
        with SessionLocal() as db:
            self.seed(db,3)
            def conflict(path,body,token):
                return {'receipts':[{'operation_id':body['p_operations'][0]['p_operation'],
                    'result':{'status':'conflict','current':{'version':2}}}]}
            with patch('app.services.cloud_sync.request',side_effect=conflict):
                self.assertEqual(upload_batch(db,1,'token'),0)
            self.assertEqual([o.state for o in db.scalars(select(SyncOutbox).order_by(SyncOutbox.sequence))],['conflict','pending','pending'])

    def test_duplicate_record_waits_for_previous_version(self):
        with SessionLocal() as db:
            self.seed(db,1)
            supplier=db.scalar(select(Supplier).where(Supplier.name=='Bulk 0'))
            supplier.name='Second edit'; enqueue_record(db,'suppliers',supplier,1); db.commit()
            with patch('app.services.cloud_sync.request',side_effect=self.reply) as request:
                self.assertEqual(upload_batch(db,1,'token'),1)
                self.assertEqual(upload_batch(db,1,'token'),1)
                self.assertEqual(request.call_args.args[1]['p_operations'][0]['p_base_version'],1)

    def test_malformed_receipt_does_not_acknowledge(self):
        with SessionLocal() as db:
            self.seed(db,2)
            with patch('app.services.cloud_sync.request',return_value={'receipts':[]}):
                with self.assertRaises(ValueError): upload_batch(db,1,'token')
            db.rollback()
            self.assertTrue(all(o.state=='pending' for o in db.scalars(select(SyncOutbox))))

    def test_pending_queue_defers_download_until_uploads_finish(self):
        from types import SimpleNamespace
        from app.config import get_settings
        from app.services.cloud_sync import synchronize
        with SessionLocal() as db:
            self.seed(db,201)
            with patch.object(get_settings(),'sync_enabled',True), \
                 patch('app.services.cloud_sync.token_for',return_value='token'), \
                 patch('app.services.cloud_sync.request',side_effect=self.reply) as request:
                result=synchronize(db,SimpleNamespace(id=1))
                self.assertEqual(result,{'status':'uploading','uploaded':200})
                self.assertEqual(request.call_count,1)

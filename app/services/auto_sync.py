"""Automatic per-user synchronization independent of an open browser."""
import logging
import random
import time
from threading import Event, Thread, Lock
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.config import get_settings
from app.database import SessionLocal
from app.models import PharmacistProfile
from app.models.sync import CloudSession

log = logging.getLogger(__name__)
_worker = None


class AutoSyncWorker:
    def __init__(self, session_factory=SessionLocal, clock=time.monotonic):
        self.session_factory = session_factory
        self.clock = clock
        self.stop_event = Event()
        self.wake_event = Event()
        self.lock = Lock()
        self.forced = set()
        self.retry_at = {}
        self.failures = {}
        self.thread = None

    def notify(self, actor_id=None, force=False):
        if force and actor_id is not None:
            with self.lock: self.forced.add(actor_id)
        self.wake_event.set()

    def cycle(self):
        from app.services.cloud_sync import synchronize, _sessions, _session_lock
        if not get_settings().sync_enabled: return False
        with self.session_factory() as db:
            actors = set(db.scalars(select(CloudSession.profile_id)))
        with _session_lock: actors.update(_sessions)
        with self.lock: forced, self.forced = self.forced, set()
        more = False
        for actor_id in actors:
            if self.stop_event.is_set(): break
            if actor_id not in forced and self.retry_at.get(actor_id, 0) > self.clock(): continue
            try:
                with self.session_factory() as db:
                    profile = db.get(PharmacistProfile, actor_id)
                    if profile is None: continue
                    # Backfill purchase orders created before purchasing joined the outbox.
                    from app.models.purchase_orders import PurchaseOrder
                    from app.models.sync import SyncIdentity
                    from app.services.sync_queue import queue_if_enabled
                    known = select(SyncIdentity.local_id).where(SyncIdentity.entity == 'purchase_orders')
                    unqueued = db.scalars(select(PurchaseOrder).where(PurchaseOrder.created_by == actor_id, ~PurchaseOrder.id.in_(known))).all()
                    if unqueued:
                        db.info['actor_id'] = actor_id
                        for order in unqueued: queue_if_enabled(db, 'purchase_orders', order)
                        db.commit()
                    result = synchronize(db, profile)
                self.failures.pop(actor_id, None)
                self.retry_at.pop(actor_id, None)
                more |= result.get('status') == 'uploading' and result.get('uploaded', 0) > 0
            except Exception as error:
                # Do not leak tokens, payloads or patient details to application logs.
                attempts = min(self.failures.get(actor_id, 0) + 1, 6)
                self.failures[actor_id] = attempts
                self.retry_at[actor_id] = self.clock() + min(15 * 2 ** (attempts - 1), 300) + random.uniform(0, 3)
                if not isinstance(error, HTTPException):
                    log.warning('Automatic synchronization deferred (%s)', type(error).__name__)
        return more

    def run(self):
        delay = 0
        while not self.stop_event.is_set():
            self.wake_event.wait(delay)
            self.wake_event.clear()
            if self.stop_event.is_set(): break
            try: delay = 0.1 if self.cycle() else 30
            except Exception as error:
                log.warning('Automatic synchronization will retry (%s)', type(error).__name__)
                delay = 30

    def start(self):
        self.thread = Thread(target=self.run, name='erp-auto-sync', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set(); self.wake_event.set()
        if self.thread: self.thread.join(timeout=2)


def notify(actor_id=None, force=False):
    if _worker is not None: _worker.notify(actor_id, force)


def start():
    global _worker
    if get_settings().sync_enabled and _worker is None:
        _worker = AutoSyncWorker(); _worker.start()


def stop():
    global _worker
    worker, _worker = _worker, None
    if worker is not None: worker.stop()


@event.listens_for(Session, 'after_commit')
def after_commit(db):
    actor = db.info.pop('wake_sync_actor', None)
    if actor is not None: notify(actor)


@event.listens_for(Session, 'after_rollback')
def after_rollback(db):
    db.info.pop('wake_sync_actor', None)

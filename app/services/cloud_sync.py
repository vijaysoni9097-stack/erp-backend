"""Cloud RPC transport. Device code uses user JWTs, never database-owner credentials."""
import json
from datetime import datetime, timedelta, timezone
from threading import Lock
import httpx
from fastapi import HTTPException
from sqlalchemy import select, text, func
from app.config import get_settings
from app.models.sync import OfflineLease, SyncOutbox, SyncState, SyncIdentity
from app.services.sync_queue import prepare_operation, acknowledge, apply_page, apply_allocations

_sessions = {}  # Hot cache; refresh sessions are encrypted in installation-local storage.
_session_lock = Lock()
_sync_lock = Lock()


def now(): return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_time(value): return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc).replace(tzinfo=None)


def request(path, payload, token=None):
    settings=get_settings()
    if not settings.supabase_project_url or not settings.supabase_publishable_key or not settings.sync_device_id:
        raise HTTPException(503,'Cloud sync enrollment is not configured')
    if path.startswith('/rest/v1/rpc/'):
        payload={**payload,'p_device_secret':settings.sync_device_secret}
    headers={'apikey':settings.supabase_publishable_key}
    if token: headers['Authorization']='Bearer '+token
    try:
        response=httpx.post(settings.supabase_project_url.rstrip('/')+path,json=payload,headers=headers,timeout=15)
    except httpx.RequestError:
        raise HTTPException(503,'Cloud is unreachable. Pending changes remain saved locally.')
    if response.status_code>=500: raise HTTPException(503,'Cloud is temporarily unavailable. Retry later.')
    if path.startswith('/auth/') and response.status_code in (400,401,403):
        raise HTTPException(401, 'Supabase rejected the cloud login. Use the same email and password for your local account and confirmed Supabase user.')
    if response.status_code in (401,403):
        raise HTTPException(401, 'Cloud device access was rejected. Check the employee link and device registration.')
    if not response.is_success: raise HTTPException(409,'Cloud rejected this operation. Review pending changes before retrying.')
    return response.json()


def check_lease(db, profile_id):
    lease=db.get(OfflineLease,profile_id)
    current=now()
    if lease is None or current>=lease.expires_at or current<lease.last_observed_at-timedelta(minutes=1):
        raise HTTPException(401,'Reconnect and sign in online to renew your 24-hour offline access.')
    # Persist clock observations to detect rollback across requests and restarts.
    lease.last_observed_at=max(current,lease.last_observed_at)
    db.commit()


def save_lease(db, profile, page):
    settings=get_settings()
    if str(page['pharmacy_id'])!=settings.sync_pharmacy_id:
        raise HTTPException(403,'Cloud pharmacy does not match this installation')
    server=parse_time(page['server_time']); expiry=parse_time(page['lease_expires_at'])
    if expiry<=server or expiry-server>timedelta(hours=24) or abs((now()-server).total_seconds())>300:
        raise HTTPException(409,'Correct this device clock before enabling offline access')
    lease=db.get(OfflineLease,profile.id)
    if lease is None:
        lease=OfflineLease(profile_id=profile.id,cloud_employee_id=str(page['employee_id']),expires_at=expiry,last_observed_at=now())
        db.add(lease)
    else:
        lease.expires_at=expiry; lease.last_observed_at=now()
    profile.role=page['role']
    db.commit()


def login(db,profile,password):
    try:
        session=request('/auth/v1/token?grant_type=password',{'email':profile.email,'password':password})
        page=request('/rest/v1/rpc/erp_sync_pull',{'p_device':get_settings().sync_device_id,'p_cursor':0},session['access_token'])
        save_lease(db,profile,page)
        from app.services.sync_credentials import save
        save(db, profile.id, session)
        with _session_lock: _sessions[profile.id]=session
        from app.services.auto_sync import notify
        notify(profile.id, force=True)
    except HTTPException as error:
        if error.status_code!=503:
            forget_session(profile.id, db)
            lease=db.get(OfflineLease,profile.id)
            if lease: db.delete(lease); db.commit()
            raise
        check_lease(db,profile.id)


def _remembered(profile_id, db=None):
    from app.services.sync_credentials import load
    if db is not None: return load(db, profile_id)
    from app.database import SessionLocal
    with SessionLocal() as session_db: return load(session_db, profile_id)


def has_session(profile_id):
    with _session_lock:
        if profile_id in _sessions: return True
    return _remembered(profile_id) is not None


def token_for(profile_id, db=None):
    # Serialize refresh-token rotation, including concurrent stock commands.
    with _session_lock:
        session = _sessions.get(profile_id) or _remembered(profile_id, db)
        if not session: raise HTTPException(409, 'Sign in once to authorize automatic cloud synchronization on this device.')
        if session.get('expires_at', 0) < datetime.now(timezone.utc).timestamp() + 60:
            session = request('/auth/v1/token?grant_type=refresh_token', {'refresh_token': session['refresh_token']})
            from app.services.sync_credentials import save
            if db is not None: save(db, profile_id, session)
            else:
                from app.database import SessionLocal
                with SessionLocal() as session_db: save(session_db, profile_id, session)
        _sessions[profile_id] = session
        return session['access_token']


BATCH_SIZE = 200
BATCH_BYTES = 1024 * 1024


def upload_batch(db, actor_id, token):
    # Include other actors when determining predecessors to preserve record order.
    earliest=select(func.min(SyncOutbox.sequence)).where(
        SyncOutbox.state.in_(['pending','conflict'])).group_by(SyncOutbox.cloud_id)
    queued=db.scalars(select(SyncOutbox).where(
        SyncOutbox.actor_id==actor_id,SyncOutbox.state=='pending',
        SyncOutbox.sequence.in_(earliest)).order_by(SyncOutbox.sequence).limit(BATCH_SIZE)).all()
    operations=[]; envelopes=[]; size=0
    for operation in queued:
        envelope=({'p_operation':operation.operation_id,'p_kind':'sale','p_payload':operation.payload}
                  if operation.entity=='sales' else prepare_operation(db,operation))
        encoded_size=len(json.dumps(envelope,ensure_ascii=True).encode('utf-8'))
        if size+encoded_size>BATCH_BYTES:
            if not operations: raise ValueError('A pending change exceeds the sync batch size limit.')
            break
        size+=encoded_size; operations.append(operation); envelopes.append(envelope)
    if not operations: return 0
    db.commit()  # Freeze every retry envelope before sending anything.
    result=request('/rest/v1/rpc/erp_sync_push_batch',
                   {'p_device':get_settings().sync_device_id,'p_operations':envelopes},token)
    receipts=result.get('receipts') if isinstance(result,dict) else None
    if not isinstance(receipts,list) or not 0<len(receipts)<=len(operations):
        raise ValueError('Invalid cloud batch receipt. Pending changes are safe to retry.')
    for index,receipt in enumerate(receipts):
        value=receipt.get('result',{}) if isinstance(receipt,dict) else {}
        if (not isinstance(value,dict) or receipt.get('operation_id')!=operations[index].operation_id
                or value.get('status') not in ('applied','conflict')
                or (value.get('status')=='conflict' and index!=len(receipts)-1)):
            raise ValueError('Invalid cloud batch receipt. Pending changes are safe to retry.')
        if value['status']=='applied' and operations[index].entity!='sales':
            if not isinstance(value.get('record'),dict) or not isinstance(value['record'].get('version'),int):
                raise ValueError('Invalid cloud record receipt.')
    if len(receipts)<len(operations) and receipts[-1]['result']['status']!='conflict':
        raise ValueError('Incomplete cloud batch receipt. Pending changes are safe to retry.')
    for operation,receipt in zip(operations,receipts):
        acknowledge(db,operation,receipt['result'])
    db.commit()
    return sum(receipt['result']['status']=='applied' for receipt in receipts)


def synchronize(db,profile):
    settings=get_settings()
    if not settings.sync_enabled: raise HTTPException(409,'Sync is not enabled. Device enrollment is required.')
    if not _sync_lock.acquire(blocking=False): raise HTTPException(409,'Synchronization is already running')
    try:
        token=token_for(profile.id, db)
        uploaded=upload_batch(db,profile.id,token)
        # Pull only after unresolved edits are cleared; otherwise our own echoed
        # changes can collide with the remaining local queue.
        if db.scalar(select(SyncOutbox.sequence).where(
                SyncOutbox.state.in_(['pending','conflict'])).limit(1)) is not None:
            return {'status':'uploading','uploaded':uploaded}
        while True:
            state=db.get(SyncState,1)
            cursor=state.cursor if state else 0
            page=request('/rest/v1/rpc/erp_sync_pull',{'p_device':settings.sync_device_id,'p_cursor':cursor},token)
            db.rollback()
            if db.bind.dialect.name=='sqlite': db.execute(text('BEGIN IMMEDIATE'))
            from app.database import lock_inventory
            lock_inventory(db)
            apply_page(db,page)
            if not page['has_more']: apply_allocations(db,page['allocations'])
            db.commit()
            save_lease(db,profile,page)
            if not page['has_more']: break
        return {'status':'synced'}
    except (HTTPException,ValueError) as error:
        db.rollback()
        if isinstance(error,HTTPException) and error.status_code==401:
            lease=db.get(OfflineLease,profile.id)
            if lease: db.delete(lease)
            forget_session(profile.id, db)
        state=db.get(SyncState,1)
        if state is None: state=SyncState(id=1,cursor=0); db.add(state)
        state.last_error=error.detail if isinstance(error,HTTPException) else str(error)
        db.commit()
        if isinstance(error,HTTPException): raise
        raise HTTPException(409,str(error))
    finally: _sync_lock.release()


def require_local_identity_mode():
    if get_settings().sync_enabled:
        raise HTTPException(409,'This account is cloud-managed. Cloud account administration must be configured before changing identity or credentials.')


def forget_session(profile_id, db=None):
    with _session_lock: _sessions.pop(profile_id, None)
    from app.services.sync_credentials import remove
    if db is not None: remove(db, profile_id)
    else:
        from app.database import SessionLocal
        with SessionLocal() as session_db:
            remove(session_db, profile_id)
            session_db.commit()

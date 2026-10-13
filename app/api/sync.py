"""Authenticated local sync controls. No cloud admin secrets are exposed."""
from uuid import uuid4
from typing import Literal
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db
from app.config import get_settings
from app.models.sync import SyncState, SyncOutbox, OfflineLease
from app.services.auth import get_current_profile
from app.services.cloud_sync import synchronize, request, token_for

class CloudReconnect(BaseModel):
    password: SecretStr = Field(min_length=12, max_length=128)

class StockCommand(BaseModel):
    operation_id: str
    kind: Literal['receive','allocate']
    payload: dict

class Resolution(BaseModel):
    choice: Literal['keep_local','accept_cloud']

class SyncAPI(BaseAPI):
    methods=['GET','POST']
    routes=[
        RouteDefinition('/api/v1/sync/status','get_status','GET',tags=['Sync']),
        RouteDefinition('/api/v1/sync/reconnect','reconnect','POST',tags=['Sync']),
        RouteDefinition('/api/v1/sync/run','run','POST',tags=['Sync']),
        RouteDefinition('/api/v1/sync/stock','stock','POST',tags=['Sync']),
        RouteDefinition('/api/v1/sync/conflicts/{operation_id}','resolve','POST',tags=['Sync']),
    ]
    @staticmethod
    def get_status(profile=Depends(get_current_profile),db:Session=Depends(get_db)):
        state=db.get(SyncState,1); lease=db.get(OfflineLease,profile.id)
        pending=db.scalar(select(func.count()).select_from(SyncOutbox).where(SyncOutbox.actor_id==profile.id,SyncOutbox.state=='pending'))
        conflicts=db.scalars(select(SyncOutbox).where(SyncOutbox.actor_id==profile.id,SyncOutbox.state=='conflict')).all()
        from app.services.cloud_sync import has_session
        return dict(connected=has_session(profile.id),enabled=get_settings().sync_enabled,device_id=get_settings().sync_device_id,
                    pending=pending,conflicts=[{'operation_id':o.operation_id,'entity':o.entity,'message':o.error} for o in conflicts],
                    last_synced_at=state.last_synced_at if state else None,error=state.last_error if state else None,
                    lease_expires_at=lease.expires_at if lease else None)
    @staticmethod
    def reconnect(payload:CloudReconnect,profile=Depends(get_current_profile),db:Session=Depends(get_db)):
        from app.services.cloud_sync import login, has_session
        login(db, profile, payload.password.get_secret_value())
        if not has_session(profile.id):
            raise HTTPException(503, 'Unable to reconnect. Check your internet connection and retry.')
        state=db.get(SyncState,1)
        if state: state.last_error=None; db.commit()
        return {'status':'connected'}
    @staticmethod
    def run(profile=Depends(get_current_profile),db:Session=Depends(get_db)):
        return synchronize(db,profile)
    @staticmethod
    def stock(payload:StockCommand,profile=Depends(get_current_profile),db:Session=Depends(get_db)):
        if not get_settings().sync_enabled: raise HTTPException(409,'Device enrollment is required')
        if profile.role!='superadmin': raise HTTPException(403,'Superadmin access required')
        result=request('/rest/v1/rpc/erp_stock_command',{'p_device':get_settings().sync_device_id,'p_operation':payload.operation_id,'p_kind':payload.kind,'p_payload':payload.payload},token_for(profile.id))
        return result
    @staticmethod
    def resolve(operation_id:str,payload:Resolution,profile=Depends(get_current_profile),db:Session=Depends(get_db)):
        operation=db.scalar(select(SyncOutbox).where(SyncOutbox.operation_id==operation_id,SyncOutbox.actor_id==profile.id,SyncOutbox.state=='conflict'))
        if operation is None: raise HTTPException(404,'Conflict not found')
        remote=operation.remote_record
        if payload.choice=='keep_local':
            if not remote or remote.get('deleted_at'): raise HTTPException(409,'The cloud record was deleted; accept deletion or create a new record')
            operation.base_version=int(remote['version']); operation.operation_id=str(uuid4()); operation.state='pending'; operation.error=None
        else:
            affected=db.scalars(select(SyncOutbox).where(SyncOutbox.cloud_id==operation.cloud_id,SyncOutbox.state.in_(['pending','conflict']))).all()
            if any(o.actor_id!=profile.id for o in affected): raise HTTPException(409,'Another local user has pending edits to this record')
            for row in affected: row.state='discarded'
        db.commit()
        return {'status':'resolved','message':'Run synchronization to apply the resolution.'}

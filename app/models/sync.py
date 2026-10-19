"""Device-local synchronization metadata. Never copied as business records."""
from datetime import datetime
from sqlalchemy import String, Text, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class SyncIdentity(Base):
    __tablename__ = 'sync_identities'
    __table_args__ = (UniqueConstraint('entity', 'local_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity: Mapped[str] = mapped_column(String(40))
    local_id: Mapped[int] = mapped_column()
    cloud_id: Mapped[str] = mapped_column(String(36), unique=True)
    version: Mapped[int] = mapped_column(default=0)
    deleted: Mapped[bool] = mapped_column(default=False)

class SyncOutbox(Base):
    __tablename__ = 'sync_outbox'
    sequence: Mapped[int] = mapped_column(primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(36), unique=True)
    actor_id: Mapped[int] = mapped_column()
    entity: Mapped[str] = mapped_column(String(40))
    cloud_id: Mapped[str] = mapped_column(String(36))
    payload: Mapped[dict] = mapped_column(JSON)
    deleted: Mapped[bool] = mapped_column(default=False)
    base_version: Mapped[int | None] = mapped_column()
    state: Mapped[str] = mapped_column(String(20), default='pending')
    remote_record: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)

class SyncState(Base):
    __tablename__ = 'sync_state'
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    cursor: Mapped[int] = mapped_column(default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime())
    last_error: Mapped[str | None] = mapped_column(Text())

class OfflineLease(Base):
    __tablename__ = 'offline_leases'
    profile_id: Mapped[int] = mapped_column(primary_key=True)
    cloud_employee_id: Mapped[str] = mapped_column(String(36))
    expires_at: Mapped[datetime] = mapped_column(DateTime())
    last_observed_at: Mapped[datetime] = mapped_column(DateTime())

class CloudSession(Base):
    """Installation-encrypted cloud session; never synchronized or returned by APIs."""
    __tablename__ = 'cloud_sync_sessions'
    profile_id: Mapped[int] = mapped_column(primary_key=True)
    encrypted_session: Mapped[str] = mapped_column(Text())
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow)

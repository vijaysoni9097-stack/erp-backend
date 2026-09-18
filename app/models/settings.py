"""Pharmacist profile and pharmacy-settings database models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NotificationEventType(str, Enum):
    new_prescription = "new_prescription"
    low_stock = "low_stock"
    expiry_alert = "expiry_alert"
    purchase_order_updates = "purchase_order_updates"
    supplier_delivery_updates = "supplier_delivery_updates"
    system_alerts = "system_alerts"


class PharmacistProfile(Base):
    """The local pharmacist profile; link this to an authenticated user in production."""

    __tablename__ = "pharmacist_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    license_number: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    pharmacy_name: Mapped[str] = mapped_column(String(150))
    qualification: Mapped[str | None] = mapped_column(String(150))
    years_experience: Mapped[int | None] = mapped_column()
    shift_timing: Mapped[str | None] = mapped_column(String(50))
    address_line_1: Mapped[str | None] = mapped_column(String(200))
    address_line_2: Mapped[str | None] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    pin_login_enabled: Mapped[bool] = mapped_column(Boolean(), default=False)
    biometric_login_enabled: Mapped[bool] = mapped_column(Boolean(), default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())


class PharmacySettings(Base):
    """Operational preferences shared by the local pharmacy installation."""

    __tablename__ = "pharmacy_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    default_prescription_duration_days: Mapped[int] = mapped_column(default=7)
    auto_refill_reminders: Mapped[bool] = mapped_column(Boolean(), default=True)
    refill_reminder_lead_days: Mapped[int] = mapped_column(default=3)
    allow_generic_substitution: Mapped[bool] = mapped_column(Boolean(), default=True)
    default_pharmacy_notes: Mapped[str | None] = mapped_column(Text())
    low_stock_threshold: Mapped[int] = mapped_column(default=10)
    low_stock_alerts_enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    expiry_alert_lead_days: Mapped[int] = mapped_column(default=7)
    expiry_alerts_enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    auto_reorder_enabled: Mapped[bool] = mapped_column(Boolean(), default=False)
    default_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    prescription_printer: Mapped[str | None] = mapped_column(String(150))
    label_printer: Mapped[str | None] = mapped_column(String(150))
    default_paper_size: Mapped[str] = mapped_column(String(20), default="A4")
    print_preview_enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())


class NotificationPreference(Base):
    """Delivery channels for each pharmacy alert type."""

    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("event_type", name="uq_notification_preferences_event_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[NotificationEventType] = mapped_column(SqlEnum(NotificationEventType), index=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    sms_enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())

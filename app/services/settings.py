"""Persistence and response helpers for pharmacist settings."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    NotificationEventType,
    NotificationPreference,
    PharmacistProfile,
    PharmacySettings,
)
from app.schemas import (
    InventoryPreferences,
    NotificationChannelPreferences,
    NotificationPreferences,
    PrescriptionPreferences,
    PrinterSettings,
    SecuritySettingsRead,
)


def seed_settings(db: Session) -> None:
    """Create default local settings exactly once for a new database."""
    changed = False
    if db.get(PharmacistProfile, 1) is None:
        db.add(PharmacistProfile(
            id=1,
            first_name="John",
            last_name="Doe",
            email="pharmacist@example.com",
            phone="+1-234-567-8900",
            license_number="PH-2024-001234",
            pharmacy_name="Central Pharmacy",
            qualification="B.Pharm",
            years_experience=5,
            shift_timing="Morning",
            address_line_1="123 Main St",
            address_line_2="Suite 100",
            country="USA",
            state="California",
            city="Los Angeles",
            postal_code="90001",
        ))
        changed = True
    if db.get(PharmacySettings, 1) is None:
        db.add(PharmacySettings(id=1))
        changed = True
    existing_events = set(db.scalars(select(NotificationPreference.event_type)))
    for event_type in NotificationEventType:
        if event_type not in existing_events:
            db.add(NotificationPreference(event_type=event_type))
            changed = True
    if changed:
        db.flush()
        if db.bind.dialect.name == 'postgresql':
            from sqlalchemy import text
            # The initial profile has an explicit ID; reserve it in its sequence.
            db.execute(text("SELECT setval(pg_get_serial_sequence('employee_table','id'), GREATEST((SELECT MAX(id) FROM employee_table), nextval(pg_get_serial_sequence('employee_table','id'))))"))
        db.commit()


def get_default_profile(db: Session) -> PharmacistProfile:
    profile = db.get(PharmacistProfile, 1)
    if profile is None:
        seed_settings(db)
        profile = db.get(PharmacistProfile, 1)
    return profile


def get_pharmacy_preferences(db: Session) -> PharmacySettings:
    preferences = db.get(PharmacySettings, 1)
    if preferences is None:
        seed_settings(db)
        preferences = db.get(PharmacySettings, 1)
    return preferences


def as_prescription_preferences(preferences: PharmacySettings) -> PrescriptionPreferences:
    return PrescriptionPreferences(
        default_prescription_duration_days=preferences.default_prescription_duration_days,
        auto_refill_reminders=preferences.auto_refill_reminders,
        refill_reminder_lead_days=preferences.refill_reminder_lead_days,
        allow_generic_substitution=preferences.allow_generic_substitution,
        default_pharmacy_notes=preferences.default_pharmacy_notes,
    )


def as_inventory_preferences(preferences: PharmacySettings) -> InventoryPreferences:
    return InventoryPreferences(
        low_stock_threshold=preferences.low_stock_threshold,
        low_stock_alerts_enabled=preferences.low_stock_alerts_enabled,
        expiry_alert_lead_days=preferences.expiry_alert_lead_days,
        expiry_alerts_enabled=preferences.expiry_alerts_enabled,
        auto_reorder_enabled=preferences.auto_reorder_enabled,
        default_supplier_id=preferences.default_supplier_id,
    )


def as_printer_settings(preferences: PharmacySettings) -> PrinterSettings:
    return PrinterSettings(
        prescription_printer=preferences.prescription_printer,
        label_printer=preferences.label_printer,
        default_paper_size=preferences.default_paper_size,
        print_preview_enabled=preferences.print_preview_enabled,
    )


def as_notification_preferences(db: Session) -> NotificationPreferences:
    saved_preferences = {preference.event_type: preference for preference in db.scalars(select(NotificationPreference))}
    result: dict[str, NotificationChannelPreferences] = {}
    for event_type in NotificationEventType:
        preference = saved_preferences[event_type]
        result[event_type.value] = NotificationChannelPreferences(
            email_enabled=preference.email_enabled,
            sms_enabled=preference.sms_enabled,
            in_app_enabled=preference.in_app_enabled,
        )
    return NotificationPreferences(**result)


def as_security_settings(profile: PharmacistProfile) -> SecuritySettingsRead:
    return SecuritySettingsRead(
        pin_login_enabled=profile.pin_login_enabled,
        biometric_login_enabled=profile.biometric_login_enabled,
        has_password=profile.password_hash is not None,
        has_pin=profile.pin_hash is not None,
    )

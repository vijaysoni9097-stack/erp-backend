from fastapi import Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.base import BaseAPI, RouteDefinition
from app.api.common import get_or_404
from app.database import get_db
from app.models import PharmacistProfile, AuthSession, NotificationEventType, NotificationPreference, Supplier
from app.schemas import (
    InventoryPreferences,
    NotificationPreferences,
    PasswordChange,
    EmployeeProfileUpdate,
    PharmacistProfileRead,
    PrescriptionPreferences,
    PrinterSettings,
    SecuritySettingsRead,
    SecuritySettingsUpdate,
    SettingsOverview,
)
from app.services.auth import get_current_profile
from app.services.security import hash_secret, verify_secret
from app.services.settings import (
    as_inventory_preferences,
    as_notification_preferences,
    as_prescription_preferences,
    as_printer_settings,
    as_security_settings,
    get_pharmacy_preferences,
)


class SettingsAPI(BaseAPI):
    methods = ["GET", "POST", "PUT"]
    routes = [
        RouteDefinition("/api/v1/settings", "get", "GET", response_model=SettingsOverview, tags=["Settings"]),
        RouteDefinition("/api/v1/settings/profile", "get_profile", "GET", response_model=PharmacistProfileRead,
                        tags=["Settings"]),
        RouteDefinition("/api/v1/settings/profile", "put_profile", "PUT", response_model=PharmacistProfileRead,
                        tags=["Settings"]),
        RouteDefinition("/api/v1/settings/password", "post_password", "POST", status_code=status.HTTP_204_NO_CONTENT,
                        tags=["Settings"]),
        RouteDefinition("/api/v1/settings/prescription", "get_prescription", "GET",
                        response_model=PrescriptionPreferences, tags=["Settings"]),
        RouteDefinition("/api/v1/settings/prescription", "put_prescription", "PUT",
                        response_model=PrescriptionPreferences, tags=["Settings"]),
        RouteDefinition("/api/v1/settings/inventory", "get_inventory", "GET",
                        response_model=InventoryPreferences, tags=["Settings"]),
        RouteDefinition("/api/v1/settings/inventory", "put_inventory", "PUT",
                        response_model=InventoryPreferences, tags=["Settings"]),
        RouteDefinition("/api/v1/settings/printer", "get_printer", "GET", response_model=PrinterSettings,
                        tags=["Settings"]),
        RouteDefinition("/api/v1/settings/printer", "put_printer", "PUT", response_model=PrinterSettings,
                        tags=["Settings"]),
        RouteDefinition("/api/v1/settings/notifications", "get_notifications", "GET",
                        response_model=NotificationPreferences, tags=["Settings"]),
        RouteDefinition("/api/v1/settings/notifications", "put_notifications", "PUT",
                        response_model=NotificationPreferences, tags=["Settings"]),
        RouteDefinition("/api/v1/settings/security", "get_security", "GET", response_model=SecuritySettingsRead,
                        tags=["Settings"]),
        RouteDefinition("/api/v1/settings/security", "put_security", "PUT", response_model=SecuritySettingsRead,
                        tags=["Settings"]),
    ]

    @staticmethod
    def get(db: Session = Depends(get_db), profile: PharmacistProfile = Depends(get_current_profile)) -> SettingsOverview:
        """Return every settings section required to render the pharmacist settings page."""
        preferences = get_pharmacy_preferences(db)
        return SettingsOverview(
            profile=PharmacistProfileRead.model_validate(profile),
            prescription=as_prescription_preferences(preferences),
            inventory=as_inventory_preferences(preferences),
            printer=as_printer_settings(preferences),
            notifications=as_notification_preferences(db),
            security=as_security_settings(profile),
        )

    @staticmethod
    def get_profile(profile: PharmacistProfile = Depends(get_current_profile)):
        return profile

    @staticmethod
    def put_profile(payload: EmployeeProfileUpdate, db: Session = Depends(get_db),
                    profile: PharmacistProfile = Depends(get_current_profile)):
        from app.services.cloud_sync import require_local_identity_mode
        require_local_identity_mode()
        duplicate = db.scalar(select(PharmacistProfile.id).where(
            func.lower(PharmacistProfile.email) == payload.email,
            PharmacistProfile.id != profile.id,
        ))
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Email address is already in use")
        for field_name, value in payload.model_dump(exclude_unset=True).items():
            setattr(profile, field_name, value)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Email address or pharmacist license number is already in use")
        db.refresh(profile)
        return profile

    @staticmethod
    def post_password(payload: PasswordChange, db: Session = Depends(get_db),
                      profile: PharmacistProfile = Depends(get_current_profile)) -> None:
        from app.services.cloud_sync import require_local_identity_mode
        require_local_identity_mode()
        """Set the initial password or verify the current password before replacing it."""
        if profile.password_hash:
            if payload.current_password is None or not verify_secret(payload.current_password, profile.password_hash):
                raise HTTPException(status_code=422, detail="Current password is incorrect")
        profile.password_hash = hash_secret(payload.new_password)
        db.execute(delete(AuthSession).where(AuthSession.profile_id == profile.id))
        db.commit()

    @staticmethod
    def get_prescription(db: Session = Depends(get_db)) -> PrescriptionPreferences:
        return as_prescription_preferences(get_pharmacy_preferences(db))

    @staticmethod
    def put_prescription(payload: PrescriptionPreferences,
                         db: Session = Depends(get_db)) -> PrescriptionPreferences:
        preferences = get_pharmacy_preferences(db)
        for field_name, value in payload.model_dump().items():
            setattr(preferences, field_name, value)
        db.commit()
        db.refresh(preferences)
        return as_prescription_preferences(preferences)

    @staticmethod
    def get_inventory(db: Session = Depends(get_db)) -> InventoryPreferences:
        return as_inventory_preferences(get_pharmacy_preferences(db))

    @staticmethod
    def put_inventory(payload: InventoryPreferences,
                      db: Session = Depends(get_db)) -> InventoryPreferences:
        if payload.default_supplier_id is not None:
            get_or_404(db, Supplier, payload.default_supplier_id, "Supplier")
        preferences = get_pharmacy_preferences(db)
        for field_name, value in payload.model_dump().items():
            setattr(preferences, field_name, value)
        db.commit()
        db.refresh(preferences)
        return as_inventory_preferences(preferences)

    @staticmethod
    def get_printer(db: Session = Depends(get_db)) -> PrinterSettings:
        return as_printer_settings(get_pharmacy_preferences(db))

    @staticmethod
    def put_printer(payload: PrinterSettings, db: Session = Depends(get_db)) -> PrinterSettings:
        preferences = get_pharmacy_preferences(db)
        for field_name, value in payload.model_dump().items():
            setattr(preferences, field_name, value)
        db.commit()
        db.refresh(preferences)
        return as_printer_settings(preferences)

    @staticmethod
    def get_notifications(db: Session = Depends(get_db)) -> NotificationPreferences:
        return as_notification_preferences(db)

    @staticmethod
    def put_notifications(payload: NotificationPreferences,
                          db: Session = Depends(get_db)) -> NotificationPreferences:
        saved_preferences = {preference.event_type: preference for preference in db.scalars(select(NotificationPreference))}
        for event_type in NotificationEventType:
            preference = saved_preferences[event_type]
            channels = getattr(payload, event_type.value)
            preference.email_enabled = channels.email_enabled
            preference.sms_enabled = channels.sms_enabled
            preference.in_app_enabled = channels.in_app_enabled
        db.commit()
        return as_notification_preferences(db)

    @staticmethod
    def get_security(profile: PharmacistProfile = Depends(get_current_profile)) -> SecuritySettingsRead:
        return as_security_settings(profile)

    @staticmethod
    def put_security(payload: SecuritySettingsUpdate,
                     db: Session = Depends(get_db),
                     profile: PharmacistProfile = Depends(get_current_profile)) -> SecuritySettingsRead:
        if payload.pin_login_enabled and profile.pin_hash is None and payload.pin is None:
            raise HTTPException(status_code=422, detail="A 4 to 6 digit PIN is required before PIN login can be enabled")
        if payload.pin is not None:
            profile.pin_hash = hash_secret(payload.pin)
        profile.pin_login_enabled = payload.pin_login_enabled
        profile.biometric_login_enabled = payload.biometric_login_enabled
        db.commit()
        return as_security_settings(profile)

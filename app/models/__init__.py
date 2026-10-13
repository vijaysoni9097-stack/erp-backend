"""Database models grouped by pharmacy feature.

Importing from this package keeps existing API and schema imports stable while each
feature owns its corresponding SQLAlchemy model definitions.
"""

from app.models.customers import Customer
from app.models.medicines import Medicine, StockMovement, StockMovementType
from app.models.prescriptions import Prescription, PrescriptionStatus
from app.models.sales import Sale, SaleItem, SaleStatus
from app.models.settings import (
    AuthSession,
    PasswordResetToken,
    Employee,
    EmployeeRole,
    NotificationEventType,
    NotificationPreference,
    PharmacistProfile,
    PharmacySettings,
)
from app.models.suppliers import Supplier

__all__ = [
    "AuthSession",
    "PasswordResetToken",
    "Employee",
    "EmployeeRole",
    "Customer",
    "Medicine",
    "NotificationEventType",
    "NotificationPreference",
    "PharmacistProfile",
    "PharmacySettings",
    "Prescription",
    "PrescriptionStatus",
    "Sale",
    "SaleItem",
    "SaleStatus",
    "StockMovement",
    "StockMovementType",
    "Supplier",
]

from app.models.sync import SyncIdentity, SyncOutbox, SyncState, OfflineLease
from app.models.stock_snapshot import StockSnapshot

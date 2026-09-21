from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import PrescriptionStatus, SaleStatus, StockMovementType


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SupplierCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None


class SupplierRead(SupplierCreate, ORMModel):
    id: int
    created_at: datetime


class MedicineCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    generic_name: str | None = None
    sku: str = Field(min_length=2, max_length=50)
    batch_number: str = Field(min_length=1, max_length=80)
    expiry_date: date
    purchase_price: Decimal = Field(ge=0)
    selling_price: Decimal = Field(ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    reorder_level: int = Field(default=10, ge=0)
    supplier_id: int | None = None


class MedicineRead(MedicineCreate, ORMModel):
    id: int
    created_at: datetime


class StockAdjustment(BaseModel):
    quantity_change: int = Field(description="Positive to receive stock; negative to remove stock")
    note: str | None = Field(default=None, max_length=500)


class CustomerCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    phone: str | None = None
    email: str | None = None
    date_of_birth: date | None = None


class CustomerRead(CustomerCreate, ORMModel):
    id: int
    created_at: datetime


class PrescriptionCreate(BaseModel):
    customer_id: int
    doctor_name: str = Field(min_length=2, max_length=150)
    prescribed_on: date = Field(default_factory=date.today)
    notes: str | None = None


class PrescriptionRead(PrescriptionCreate, ORMModel):
    id: int
    status: PrescriptionStatus


class SaleItemCreate(BaseModel):
    medicine_id: int
    quantity: int = Field(gt=0)


class SaleCreate(BaseModel):
    customer_id: int | None = None
    prescription_id: int | None = None
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)
    items: list[SaleItemCreate] = Field(min_length=1)


class SaleItemRead(ORMModel):
    id: int
    medicine_id: int
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class SaleRead(ORMModel):
    id: int
    customer_id: int | None
    prescription_id: int | None
    status: SaleStatus
    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    created_at: datetime
    items: list[SaleItemRead]


class DashboardRead(BaseModel):
    total_medicines: int
    low_stock_medicines: int
    expiring_within_30_days: int
    today_sales_total: Decimal


class StockMovementRead(ORMModel):
    id: int
    medicine_id: int
    movement_type: StockMovementType
    quantity_change: int
    note: str | None
    created_at: datetime


class PharmacistProfileBase(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    license_number: str = Field(min_length=1, max_length=100)
    pharmacy_name: str = Field(min_length=1, max_length=150)
    qualification: str | None = Field(default=None, max_length=150)
    years_experience: int | None = Field(default=None, ge=0, le=80)
    shift_timing: str | None = Field(default=None, max_length=50)
    address_line_1: str | None = Field(default=None, max_length=200)
    address_line_2: str | None = Field(default=None, max_length=200)
    country: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)


class PharmacistProfileRead(PharmacistProfileBase, ORMModel):
    id: int
    created_at: datetime
    updated_at: datetime


class PasswordChange(BaseModel):
    current_password: str | None = Field(default=None, min_length=12, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)
    confirm_password: str = Field(min_length=12, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self) -> "PasswordChange":
        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirmation must match")
        return self


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=12, max_length=128)


class LoginResponse(BaseModel):
    success: bool = True
    profile: PharmacistProfileRead


class PrescriptionPreferences(BaseModel):
    default_prescription_duration_days: int = Field(default=7, ge=1, le=365)
    auto_refill_reminders: bool = True
    refill_reminder_lead_days: int = Field(default=3, ge=1, le=90)
    allow_generic_substitution: bool = True
    default_pharmacy_notes: str | None = Field(default=None, max_length=2_000)


class InventoryPreferences(BaseModel):
    low_stock_threshold: int = Field(default=10, ge=0, le=100_000)
    low_stock_alerts_enabled: bool = True
    expiry_alert_lead_days: int = Field(default=7, ge=1, le=365)
    expiry_alerts_enabled: bool = True
    auto_reorder_enabled: bool = False
    default_supplier_id: int | None = None


class PrinterSettings(BaseModel):
    prescription_printer: str | None = Field(default=None, max_length=150)
    label_printer: str | None = Field(default=None, max_length=150)
    default_paper_size: str = Field(default="A4", pattern="^(A4|A5|Letter)$")
    print_preview_enabled: bool = True


class NotificationChannelPreferences(BaseModel):
    email_enabled: bool = True
    sms_enabled: bool = True
    in_app_enabled: bool = True


class NotificationPreferences(BaseModel):
    new_prescription: NotificationChannelPreferences
    low_stock: NotificationChannelPreferences
    expiry_alert: NotificationChannelPreferences
    purchase_order_updates: NotificationChannelPreferences
    supplier_delivery_updates: NotificationChannelPreferences
    system_alerts: NotificationChannelPreferences


class SecuritySettingsRead(BaseModel):
    pin_login_enabled: bool
    biometric_login_enabled: bool
    has_password: bool
    has_pin: bool


class SecuritySettingsUpdate(BaseModel):
    pin_login_enabled: bool
    biometric_login_enabled: bool
    pin: str | None = Field(default=None, pattern="^[0-9]{4,6}$")


class SettingsOverview(BaseModel):
    profile: PharmacistProfileRead
    prescription: PrescriptionPreferences
    inventory: InventoryPreferences
    printer: PrinterSettings
    notifications: NotificationPreferences
    security: SecuritySettingsRead

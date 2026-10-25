from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class PurchaseItemCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    medicine_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=2147483647, strict=True)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class PurchaseOrderCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_id: UUID
    supplier_id: int = Field(gt=0)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    expected_delivery: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    items: list[PurchaseItemCreate] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_items(self):
        if len({item.medicine_id for item in self.items}) != len(self.items):
            raise ValueError('Each medicine must appear only once')
        return self


class PurchaseItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    medicine_id: int
    medicine_name: str
    sku: str
    batch_number: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class PurchaseOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_id: str
    created_by: int
    supplier_id: int
    supplier_name: str
    currency: str
    status: str
    expected_delivery: date | None
    notes: str | None
    total_amount: Decimal
    created_at: datetime
    items: list[PurchaseItemRead]


class ReceiptItemCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    batch_number: str | None = Field(default=None, min_length=1, max_length=80)
    expiry_date: date | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=30)
    purchase_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    selling_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)

    @model_validator(mode='after')
    def delivery_details(self):
        if self.quantity > 0 and any(getattr(self, key) is None for key in ('batch_number', 'expiry_date', 'unit', 'purchase_price', 'selling_price')):
            raise ValueError('Review batch, expiry, unit, purchase cost and selling price for every received medicine')
        if self.quantity > 0 and self.expiry_date < date.today():
            raise ValueError('Expired medicines cannot be received for sale')
        return self
    order_item_id: int = Field(gt=0)
    quantity: int = Field(ge=0, le=2147483647, strict=True)


class ReceiptCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    items: list[ReceiptItemCreate] = Field(min_length=1, max_length=100)
    close_order: bool = False

    @model_validator(mode='after')
    def validate_items(self):
        if len({item.order_item_id for item in self.items}) != len(self.items):
            raise ValueError('Each order item must appear only once')
        if not any(item.quantity for item in self.items):
            raise ValueError('Receive at least one unit')
        return self


class ApprovalItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order_item_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=2147483647, strict=True)


class PurchaseApproval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[ApprovalItem] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_items(self):
        if len({item.order_item_id for item in self.items}) != len(self.items):
            raise ValueError('Each order item must appear only once')
        return self

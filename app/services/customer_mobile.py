"""Canonical mobile lookup without exposing unrelated customer records."""
import re
from sqlalchemy import select,func
from app.models import Customer
from app.models.sync import SyncIdentity


def normalize_mobile(value):
    value=(value or '').strip()
    if not value:return None
    if not re.fullmatch(r'\+?[0-9 ()\-.]+',value):raise ValueError('Enter a mobile number using digits and an optional country code')
    digits=re.sub(r'[^0-9]','',value)
    if digits.startswith('00'):digits=digits[2:]
    elif len(digits)==10 and not value.startswith('+'):digits='91'+digits
    if not 7<=len(digits)<=15:raise ValueError('Enter a valid mobile number with 7–15 digits, including country code')
    return '+'+digits


def customers_by_mobile(db, mobile):
    normalized=normalize_mobile(mobile)
    if not normalized:return []
    digits=normalized[1:]
    variants=[digits,'00'+digits]
    if digits.startswith('91') and len(digits)==12:variants.append(digits[2:])
    phone=Customer.phone
    for char in ['+',' ','(',')','-','.']:phone=func.replace(phone,char,'')
    deleted=select(SyncIdentity.local_id).where(SyncIdentity.entity=='customers',SyncIdentity.deleted==True)
    return list(db.scalars(select(Customer).where(phone.in_(variants),~Customer.id.in_(deleted)).order_by(Customer.id).limit(20)))

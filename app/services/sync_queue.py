"""Transactional local outbox, UUID mapping, and atomic pull application."""
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4
from hashlib import md5
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from app.models import Supplier, Customer, Medicine, Prescription, PharmacySettings, NotificationPreference
from app.models.sync import SyncIdentity, SyncOutbox, SyncState

MODELS = {'suppliers': Supplier, 'customers': Customer, 'medicines': Medicine, 'prescriptions': Prescription, 'pharmacy_settings': PharmacySettings, 'notification_preferences': NotificationPreference}
FIELDS = {
    'suppliers': ['name','contact_person','phone','email','address'],
    'customers': ['full_name','phone','email','date_of_birth'],
    'medicines': ['name','generic_name','sku','batch_number','expiry_date','purchase_price','selling_price','reorder_level','supplier_id'],
    'prescriptions': ['customer_id','doctor_name','prescribed_on','notes','status'],
    'pharmacy_settings': ['default_prescription_duration_days','auto_refill_reminders','refill_reminder_lead_days','allow_generic_substitution','default_pharmacy_notes','low_stock_threshold','low_stock_alerts_enabled','expiry_alert_lead_days','expiry_alerts_enabled','auto_reorder_enabled','default_supplier_id'],
    'notification_preferences': ['event_type','email_enabled','sms_enabled','in_app_enabled'],
}
REFERENCES = {'supplier_id':'suppliers','customer_id':'customers','default_supplier_id':'suppliers'}


def identity(db, entity, local_id):
    row=db.scalar(select(SyncIdentity).where(SyncIdentity.entity==entity, SyncIdentity.local_id==local_id))
    if row is None:
        cloud_id = str(uuid4())
        if entity in ('pharmacy_settings', 'notification_preferences'):
            from app.config import get_settings
            pharmacy = str(UUID(get_settings().sync_pharmacy_id))
            key = pharmacy + ':' + entity
            if entity == 'notification_preferences':
                key += ':' + serialize(db.get(NotificationPreference, local_id).event_type)
            cloud_id = str(UUID(md5(key.encode(), usedforsecurity=False).hexdigest()))
        row=SyncIdentity(entity=entity,local_id=local_id,cloud_id=cloud_id,version=0,deleted=False)
        db.add(row)
        db.flush()
    return row


def serialize(value):
    if isinstance(value, Enum): return value.value
    if isinstance(value, (date,datetime)): return value.isoformat()
    if isinstance(value, Decimal): return str(value)
    return value


def enqueue_record(db, entity, record, actor_id, deleted=False):
    row=identity(db,entity,record.id)
    payload={key:serialize(getattr(record,key)) for key in FIELDS[entity]}
    for key, target in REFERENCES.items():
        if payload.get(key) is not None:
            payload[key]=ensure_parent(db,target,payload[key],actor_id).cloud_id
    operation=SyncOutbox(operation_id=str(uuid4()),actor_id=actor_id,entity=entity,
                         cloud_id=row.cloud_id,payload=payload,deleted=deleted,state='pending')
    db.add(operation)
    db.flush()
    return operation


def ensure_parent(db, entity, local_id, actor_id):
    row = identity(db, entity, local_id)
    if row.version == 0 and db.scalar(select(SyncOutbox.sequence).where(SyncOutbox.cloud_id == row.cloud_id, SyncOutbox.state.in_(['pending', 'conflict'])).limit(1)) is None:
        record = db.get(MODELS[entity], local_id)
        if record is None: raise ValueError('Missing local parent for synchronization')
        enqueue_record(db, entity, record, actor_id)
    return row


def prepare_operation(db, operation):
    """Freeze the version before a network attempt, preserving retry contents."""
    if operation.base_version is None:
        row=db.scalar(select(SyncIdentity).where(SyncIdentity.cloud_id==operation.cloud_id))
        operation.base_version=row.version
        db.flush()
    return dict(p_operation=operation.operation_id,p_entity=operation.entity,p_record=operation.cloud_id,
                p_base_version=operation.base_version,p_payload=operation.payload,p_deleted=operation.deleted)


def acknowledge(db, operation, result):
    if result['status']=='conflict':
        operation.remote_record=result.get('current')
        operation.state='conflict'
        operation.error='This record changed on another device. Review before retrying.'
        return
    row=db.scalar(select(SyncIdentity).where(SyncIdentity.cloud_id==operation.cloud_id))
    row.version=int(result['record']['version']) if operation.entity!='sales' else 1
    operation.state='applied'
    operation.error=None


def apply_page(db, page):
    """Caller commits the page plus cursor together. Unknown entities fail closed."""
    state=db.get(SyncState,1)
    if state is None:
        state=SyncState(id=1,cursor=0)
        db.add(state)
    for change in page['changes']:
        if int(change['cursor'])<=state.cursor: continue
        entity=change['entity']
        if entity == 'purchase_orders':
            apply_purchase_order(db, change)
            state.cursor = int(change['cursor'])
            continue
        if entity in ('sales','stock_movements'):
            apply_stock_change(db,change)
            state.cursor=int(change['cursor'])
            continue
        if entity not in MODELS:
            raise ValueError('This sync client does not support an incoming entity yet')
        cloud_id=str(change['record_id'])
        row=db.scalar(select(SyncIdentity).where(SyncIdentity.cloud_id==cloud_id))
        pending=db.scalar(select(SyncOutbox).where(SyncOutbox.cloud_id==cloud_id,SyncOutbox.state.in_(['pending','conflict'])))
        if pending:
            # Durable cloud history lets us stop and resume after explicit resolution.
            raise ValueError('Unresolved local changes block this incoming record')
        if row is not None and row.version>=int(change['version']):
            state.cursor=int(change['cursor']); continue
        data=change['payload']
        record=db.get(MODELS[entity],row.local_id) if row else None
        if record is None and entity == 'pharmacy_settings': record = db.get(PharmacySettings, 1)
        if record is None and entity == 'notification_preferences': record = db.scalar(select(NotificationPreference).where(NotificationPreference.event_type == data.get('event_type')))
        if change['deleted']:
            # Preserve references/history locally, filter tombstones in feature APIs.
            if row: row.deleted=True; row.version=int(change['version'])
        else:
            values={key:data.get(key) for key in FIELDS[entity]}
            for key,target in REFERENCES.items():
                if values.get(key) is not None:
                    reference=db.scalar(select(SyncIdentity).where(SyncIdentity.cloud_id==str(values[key]),SyncIdentity.entity==target))
                    if reference is None: raise ValueError('Missing synchronized parent record')
                    values[key]=reference.local_id
            for key in ('date_of_birth','expiry_date','prescribed_on'):
                if values.get(key): values[key]=date.fromisoformat(values[key])
            if record is None:
                record=MODELS[entity](**values)
                if entity=='medicines': record.stock_quantity=0
                db.add(record); db.flush()
                row=SyncIdentity(entity=entity,local_id=record.id,cloud_id=cloud_id,version=int(change['version']),deleted=False)
                db.add(row)
            else:
                for key,value in values.items(): setattr(record,key,value)
                if row is None:
                    row = SyncIdentity(entity=entity, local_id=record.id, cloud_id=cloud_id, version=int(change['version']), deleted=False)
                    db.add(row)
                else:
                    row.version=int(change['version']); row.deleted=False
        db.flush()
        state.cursor=int(change['cursor'])
    if state.cursor!=int(page['cursor']): raise ValueError('Noncontiguous sync page')
    state.last_synced_at=datetime.utcnow()
    state.last_error=None


def enqueue_sale(db, sale, actor_id):
    from app.models import SaleItem
    row=identity(db,'sales',sale.id)
    items=db.scalars(select(SaleItem).where(SaleItem.sale_id==sale.id)).all()
    payload={'id':row.cloud_id,'tax_amount':str(sale.tax_amount),'occurred_at':sale.created_at.isoformat()+'Z',
             'customer_id':ensure_parent(db,'customers',sale.customer_id,actor_id).cloud_id if sale.customer_id else None,
             'prescription_id':ensure_parent(db,'prescriptions',sale.prescription_id,actor_id).cloud_id if sale.prescription_id else None,
             'items':[{'medicine_id':ensure_parent(db,'medicines',item.medicine_id,actor_id).cloud_id,
                       'quantity':item.quantity,'unit_price':str(item.unit_price),
                       'original_unit_price':str(item.original_unit_price),'discount_percent':str(item.discount_percent)} for item in items]}
    if sale.company:
        payload['company'] = {key:getattr(sale.company,key) for key in ('company_name','address','gstin')}
    if sale.payment:
        payload['payment'] = {key: str(getattr(sale.payment, key)) if key in ('amount','tendered','change') else getattr(sale.payment,key)
                              for key in ('method','amount','tendered','change','reference')}
    operation=SyncOutbox(operation_id=str(uuid4()),actor_id=actor_id,entity='sales',cloud_id=row.cloud_id,
                        payload=payload,state='pending')
    db.add(operation)
    db.flush()
    return operation


def apply_allocations(db, allocations):
    """Cloud allowance less unsent local sales; applied receipts must be committed together."""
    pending=db.scalars(select(SyncOutbox).where(SyncOutbox.entity=='sales',SyncOutbox.state.in_(['pending','conflict']))).all()
    reserved={}
    for operation in pending:
        for item in operation.payload['items']:
            key=item['medicine_id']; reserved[key]=reserved.get(key,0)+item['quantity']
    allowed={str(a['medicine_id']):int(a['quantity_granted'])-int(a['quantity_consumed']) for a in allocations}
    for row in db.scalars(select(SyncIdentity).where(SyncIdentity.entity=='medicines')):
        medicine=db.get(Medicine,row.local_id)
        medicine.stock_quantity=max(0,allowed.get(row.cloud_id,0)-reserved.get(row.cloud_id,0))


def apply_stock_change(db, change):
    from app.models import Sale, SaleItem, StockMovement, StockMovementType, SaleStatus
    data=change['payload']
    cloud_id=str(change['record_id'])
    row=db.scalar(select(SyncIdentity).where(SyncIdentity.cloud_id==cloud_id))
    if row and row.version>=int(change['version']): return
    def local(entity, value):
        if value is None: return None
        found=db.scalar(select(SyncIdentity).where(SyncIdentity.entity==entity,SyncIdentity.cloud_id==str(value)))
        if found is None: raise ValueError('Missing synchronized stock/sale parent')
        return found.local_id
    def movement(data, sale_id=None):
        known=db.scalar(select(SyncIdentity).where(SyncIdentity.cloud_id==str(data['id'])))
        if known: return
        kind=data['movement_type']
        if kind not in ('received','adjustment','sale'): raise ValueError('Unsupported stock movement')
        entry=StockMovement(medicine_id=local('medicines',data['medicine_id']),movement_type=StockMovementType(kind),
                            quantity_change=data['quantity_change'],note=data.get('note'),
                            created_at=datetime.fromisoformat(data['occurred_at']).replace(tzinfo=None))
        db.add(entry); db.flush()
        db.add(SyncIdentity(entity='stock_movements',local_id=entry.id,cloud_id=str(data['id']),version=1,deleted=False))
    if change['entity']=='stock_movements':
        movement(data); return
    if row:
        # Own sale already exists locally; only acknowledge its cloud identity.
        row.version=int(change['version']); return
    sale=Sale(customer_id=local('customers',data.get('customer_id')),prescription_id=local('prescriptions',data.get('prescription_id')),
              status=SaleStatus(data['status']),subtotal=Decimal(data['subtotal']),tax_amount=Decimal(data['tax_amount']),
              total_amount=Decimal(data['total_amount']),created_at=datetime.fromisoformat(data['occurred_at']).replace(tzinfo=None))
    if data.get('company'):
        from app.models.company import SaleCompany
        sale.company_record = SaleCompany(**{key:data['company'].get(key) for key in ('company_name','address','gstin')})
    if data.get('payment'):
        from app.models.sales import SalePayment
        payment = data['payment']
        sale.payment = SalePayment(**{key: payment[key] for key in ('method','amount','tendered','change','reference')})
    db.add(sale); db.flush()
    db.add(SyncIdentity(entity='sales',local_id=sale.id,cloud_id=cloud_id,version=int(change['version']),deleted=False))
    for item in data['items']:
        entry=SaleItem(sale_id=sale.id,medicine_id=local('medicines',item['medicine_id']),quantity=item['quantity'],
                       unit_price=Decimal(item['unit_price']),line_total=Decimal(item['line_total']))
        if item.get('original_unit_price') is not None:
            from app.models.company import SaleLineDiscount
            entry.discount_record = SaleLineDiscount(original_unit_price=Decimal(str(item['original_unit_price'])),discount_percent=Decimal(str(item.get('discount_percent',0))))
        db.add(entry)
    for item in data['stock_movements']: movement(item,sale.id)


def queue_if_enabled(db, entity, record, deleted=False):
    from app.config import get_settings
    if not get_settings().sync_enabled: return
    actor_id=db.info.get('actor_id')
    if actor_id is None: raise ValueError('Authenticated actor required for a synchronized write')
    db.flush()
    if entity=='sales': enqueue_sale(db,record,actor_id)
    elif entity=='purchase_orders': enqueue_purchase_order(db,record,actor_id)
    else: enqueue_record(db,entity,record,actor_id,deleted)
    db.info['wake_sync_actor'] = actor_id


def enqueue_purchase_order(db, order, actor_id):
    row = identity(db, 'purchase_orders', order.id)
    payload = {key: serialize(getattr(order, key)) for key in ['request_id','request_hash','supplier_name','currency','status','expected_delivery','notes','total_amount']}
    payload['created_at'] = order.created_at.isoformat() + 'Z'
    payload['supplier_id'] = ensure_parent(db, 'suppliers', order.supplier_id, actor_id).cloud_id
    payload['items'] = [{**{key: serialize(getattr(item, key)) for key in ['medicine_name','sku','batch_number','quantity','unit_price','line_total']},
                         'medicine_id': ensure_parent(db, 'medicines', item.medicine_id, actor_id).cloud_id} for item in order.items]
    operation = SyncOutbox(operation_id=str(uuid4()), actor_id=actor_id, entity='purchase_orders', cloud_id=row.cloud_id, payload=payload, state='pending')
    db.add(operation)
    db.flush()
    return operation


def apply_purchase_order(db, change):
    from app.models.purchase_orders import PurchaseOrder, PurchaseOrderItem
    from app.models.sync import OfflineLease
    cloud_id = str(change['record_id'])
    row = db.scalar(select(SyncIdentity).where(SyncIdentity.cloud_id == cloud_id))
    if row and row.version >= int(change['version']): return
    if db.scalar(select(SyncOutbox.sequence).where(SyncOutbox.cloud_id == cloud_id, SyncOutbox.state.in_(['pending','conflict'])).limit(1)) is not None:
        raise ValueError('Unresolved local purchase order blocks the incoming record')
    if change['deleted']: raise ValueError('Purchase orders cannot be erased by synchronization')
    data = change['payload']
    def local(entity, value):
        mapping = db.scalar(select(SyncIdentity).where(SyncIdentity.entity == entity, SyncIdentity.cloud_id == str(value)))
        if mapping is None: raise ValueError('Missing synchronized purchase order parent')
        return mapping.local_id
    order = db.get(PurchaseOrder, row.local_id) if row else None
    if order is None:
        if db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.request_id == str(data['request_id']))) is not None:
            raise ValueError('A local purchase order already uses this request reference')
        creator = db.scalar(select(OfflineLease.profile_id).where(OfflineLease.cloud_employee_id == str(data['created_by'])))
        created = datetime.fromisoformat(data['created_at'].replace('Z', '+00:00')).astimezone(timezone.utc).replace(tzinfo=None)
        order = PurchaseOrder(request_id=str(data['request_id']), request_hash=data['request_hash'], created_by=creator or 0,
                              supplier_id=local('suppliers', data['supplier_id']), supplier_name=data['supplier_name'],
                              currency=data['currency'], status=data['status'], notes=data.get('notes'),
                              expected_delivery=date.fromisoformat(data['expected_delivery']) if data.get('expected_delivery') else None,
                              total_amount=Decimal(str(data['total_amount'])), created_at=created)
        order.items = [PurchaseOrderItem(medicine_id=local('medicines', item['medicine_id']), medicine_name=item['medicine_name'],
                        sku=item['sku'], batch_number=item['batch_number'], quantity=item['quantity'],
                        unit_price=Decimal(str(item['unit_price'])), line_total=Decimal(str(item['line_total']))) for item in data['items']]
        db.add(order); db.flush()
        row = SyncIdentity(entity='purchase_orders', local_id=order.id, cloud_id=cloud_id, version=int(change['version']), deleted=False)
        db.add(row)
    else:
        # Order contents are immutable; later approval/receiving state can advance.
        order.status = data['status']; row.version = int(change['version'])

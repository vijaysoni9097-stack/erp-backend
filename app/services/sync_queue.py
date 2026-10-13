"""Transactional local outbox, UUID mapping, and atomic pull application."""
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import uuid4
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from app.models import Supplier, Customer, Medicine, Prescription
from app.models.sync import SyncIdentity, SyncOutbox, SyncState

MODELS = {'suppliers': Supplier, 'customers': Customer, 'medicines': Medicine, 'prescriptions': Prescription}
FIELDS = {
    'suppliers': ['name','contact_person','phone','email','address'],
    'customers': ['full_name','phone','email','date_of_birth'],
    'medicines': ['name','generic_name','sku','batch_number','expiry_date','purchase_price','selling_price','reorder_level','supplier_id'],
    'prescriptions': ['customer_id','doctor_name','prescribed_on','notes','status'],
}
REFERENCES = {'supplier_id':'suppliers','customer_id':'customers'}


def identity(db, entity, local_id):
    row=db.scalar(select(SyncIdentity).where(SyncIdentity.entity==entity, SyncIdentity.local_id==local_id))
    if row is None:
        row=SyncIdentity(entity=entity,local_id=local_id,cloud_id=str(uuid4()),version=0,deleted=False)
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
            payload[key]=identity(db,target,payload[key]).cloud_id
    operation=SyncOutbox(operation_id=str(uuid4()),actor_id=actor_id,entity=entity,
                         cloud_id=row.cloud_id,payload=payload,deleted=deleted,state='pending')
    db.add(operation)
    return operation


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
             'customer_id':identity(db,'customers',sale.customer_id).cloud_id if sale.customer_id else None,
             'prescription_id':identity(db,'prescriptions',sale.prescription_id).cloud_id if sale.prescription_id else None,
             'items':[{'medicine_id':identity(db,'medicines',item.medicine_id).cloud_id,
                       'quantity':item.quantity,'unit_price':str(item.unit_price)} for item in items]}
    operation=SyncOutbox(operation_id=str(uuid4()),actor_id=actor_id,entity='sales',cloud_id=row.cloud_id,
                        payload=payload,state='pending')
    db.add(operation)
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
    db.add(sale); db.flush()
    db.add(SyncIdentity(entity='sales',local_id=sale.id,cloud_id=cloud_id,version=int(change['version']),deleted=False))
    for item in data['items']:
        entry=SaleItem(sale_id=sale.id,medicine_id=local('medicines',item['medicine_id']),quantity=item['quantity'],
                       unit_price=Decimal(item['unit_price']),line_total=Decimal(item['line_total']))
        db.add(entry)
    for item in data['stock_movements']: movement(item,sale.id)


def queue_if_enabled(db, entity, record, deleted=False):
    from app.config import get_settings
    if not get_settings().sync_enabled: return
    actor_id=db.info.get('actor_id')
    if actor_id is None: raise ValueError('Authenticated actor required for a synchronized write')
    db.flush()
    if entity=='sales': enqueue_sale(db,record,actor_id)
    else: enqueue_record(db,entity,record,actor_id,deleted)

"""Integration smoke check. Only runs against the disposable localhost test DB."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.engine import make_url
url = make_url(os.environ['DATABASE_URL'])
if url.host != '127.0.0.1' or url.database != 'erp_hosting_test':
    raise SystemExit('Only the disposable localhost erp_hosting_test database is allowed')
os.environ['SYNC_ENABLED'] = 'false'
os.environ['CORS_ORIGINS'] = '["https://testing.example.com"]'
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.database import SessionLocal
from app.models import Employee, StockSnapshot
from app.setup_local import provision_account
from app.services.settings import seed_settings

with TestClient(app) as client:
    with SessionLocal() as db:
        profile = db.get(Employee, 1)
        if not profile.password_hash:
            provision_account(db, 'test@example.com', 'DisposableTestPassword123!')
        profile.role = 'superadmin'
        db.commit()
        seed_settings(db)
    response = client.post('/api/v1/auth/login', json={'email':'test@example.com','password':'DisposableTestPassword123!'})
    assert response.status_code == 200, response.text
    headers={'Authorization':'Bearer '+response.json()['access_token']}
    assert client.get('/api/v1/medicines').status_code == 401
    assert client.get('/api/v1/medicines',headers=headers).status_code == 200
    assert client.get('/api/v1/inventory/source-stock',headers=headers).status_code == 200
    allowed = client.options('/api/v1/medicines', headers={'Origin':'https://testing.example.com','Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'authorization'})
    assert allowed.headers.get('access-control-allow-origin') == 'https://testing.example.com'
    denied = client.options('/api/v1/medicines',headers={'Origin':'https://untrusted.example','Access-Control-Request-Method':'GET'})
    assert 'access-control-allow-origin' not in denied.headers
    from uuid import uuid4
    from concurrent.futures import ThreadPoolExecutor
    medicine = client.post('/api/v1/medicines', headers=headers, json={
        'name':'Concurrency test', 'sku':str(uuid4()), 'batch_number':'TEST',
        'expiry_date':'2030-01-01', 'purchase_price':1, 'selling_price':2,
        'stock_quantity':10, 'reorder_level':2,
    })
    assert medicine.status_code == 201, medicine.text
    medicine_id = medicine.json()['id']
    def sell(_):
        return client.post('/api/v1/sales', headers=headers, json={
            'items':[{'medicine_id':medicine_id,'quantity':7}], 'tax_amount':0,
        }).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(sell, range(2)))
    assert results == [201,422], results
    records=client.get('/api/v1/medicines', headers=headers).json()
    assert next(r for r in records if r['id']==medicine_id)['stock_quantity']==3
    with SessionLocal() as db:
        employee=db.scalar(select(Employee).where(Employee.email=='second-test@example.com'))
        if not employee:
            employee=Employee(first_name='Test',last_name='Two',email='second-test@example.com',license_number='TEST-2',pharmacy_name='Testing')
            db.add(employee);db.commit()
        assert employee.id > 1
with TestClient(app) as client:
    assert client.post('/api/v1/auth/login',json={'email':'test@example.com','password':'DisposableTestPassword123!'}).status_code == 200
print('PASS: PostgreSQL initialization/restart, login, protected catalog, stock endpoint, CORS, employee sequence and simultaneous stock sales.')

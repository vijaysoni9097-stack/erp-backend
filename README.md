# Hospital Pharmacy ERP API

FastAPI backend for the pharmacy module: suppliers, medicines and stock ledger, patients/customers, prescriptions, sales, and dashboard metrics.

## API structure

Each feature lives in its own folder under `app/api/` and owns a Python file with the same name as the folder. Its API class declares `methods = []` and `routes = []`, then exposes handlers such as `get`, `post`, and `put`. [`app/api/registry.py`](app/api/registry.py) imports every API class into `API_CLASSES` and registers them in one loop during application bootstrap.

```text
app/api/
├── suppliers/suppliers.py
├── medicines/medicines.py
├── customers/customers.py
├── prescriptions/prescriptions.py
├── sales/sales.py
├── dashboard/dashboard.py
├── settings/settings.py
└── registry.py
```

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs for interactive API documentation. On startup, SQLite creates `temp.db` in this project directory.

## API groups

| Area | Endpoints |
| --- | --- |
| Dashboard | `GET /api/v1/dashboard` |
| Suppliers | `POST`, `GET /api/v1/suppliers` |
| Medicines | `POST`, `GET /api/v1/medicines`, `POST /api/v1/medicines/{id}/stock` |
| Customers | `POST`, `GET /api/v1/customers` |
| Prescriptions | `POST`, `GET /api/v1/prescriptions` |
| Billing | `POST`, `GET /api/v1/sales` |
| Settings overview | `GET /api/v1/settings` |
| Pharmacist profile | `GET`, `PUT /api/v1/settings/profile` |
| Password | `POST /api/v1/settings/password` |
| Prescription preferences | `GET`, `PUT /api/v1/settings/prescription` |
| Inventory preferences | `GET`, `PUT /api/v1/settings/inventory` |
| Printer settings | `GET`, `PUT /api/v1/settings/printer` |
| Notifications | `GET`, `PUT /api/v1/settings/notifications` |
| Security | `GET`, `PUT /api/v1/settings/security` |

The initial local profile is `pharmacist@example.com`. Passwords and PINs are stored only as salted `scrypt` hashes. The local starter deliberately has no login/authentication layer yet, so these settings routes must be protected with role-based authentication before an internet-facing deployment.

## Production database

Use Amazon RDS for PostgreSQL as the system of record. Set `DATABASE_URL` to a PostgreSQL connection string and add a PostgreSQL driver. Use OpenSearch later only for fast text search and analytics; it is not safe as the transactional pharmacy database. Replace the startup schema creation with Alembic migrations before deployment.

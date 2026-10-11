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

## Local account and login

The installation currently supports one pharmacist account. Initialize the local database and set its email/password from your terminal:

```bash
python -m app.setup_local --email pharmacist@example.com
```

The command prompts for a password of 12–128 characters without displaying it. It cannot overwrite an already configured account. To create tables without setting credentials, run `python -m app.setup_local`. Existing data is preserved. There is no default password or public account-setup endpoint.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"pharmacist@example.com","password":"YOUR_PASSWORD"}'
```

A successful response contains `success`, `access_token`, `token_type`, UTC `expires_at`, and `profile`. Send `Authorization: Bearer <access_token>` on subsequent API requests. Swagger's **Authorize** button accepts the returned token. Login and database operations work without internet.

| Authentication | Endpoint |
| --- | --- |
| Login | `POST /api/v1/auth/login` |
| Current profile | `GET /api/v1/auth/me` |
| Logout current session | `POST /api/v1/auth/logout` |
| Change password and revoke all sessions | `POST /api/v1/settings/password` |

All pharmacy and settings endpoints require authentication. Health, login, and API documentation remain public. Invalid credentials, missing tokens, and expired/revoked sessions return `401`. Password changes require the current password. Log in again after a password change.

Passwords and PINs use salted `scrypt` hashes. Random bearer tokens expire after 12 hours; only their SHA-256 digests are stored in `auth_sessions`. Sessions survive backend restarts and logout revokes the current session. SQLite uses foreign-key enforcement, WAL journaling, and a five-second busy timeout. Keep the local service bound to `127.0.0.1`; network deployment still needs HTTPS, login rate limiting, and a multi-user authorization design.

## Verification

```bash
python -m unittest discover -s tests -v
```

Tests use a separate temporary SQLite database and do not change local accounts or pharmacy data.

## Local-first storage and future cloud sync

Keep `DATABASE_URL` pointing to the local SQLite database (`temp.db`) even when cloud sync is added. All current pharmacy tables plus `employee_table`, `auth_sessions`, `pharmacy_settings`, and `notification_preferences` are created at startup. Startup creation adds missing tables; it does not migrate existing columns. Versioned migrations are needed for future schema changes.

Cloud synchronization is not implemented in this step. It needs a selected cloud API/database, installation identity, globally unique record IDs, a transactional outbox, idempotent retries, deletion tracking, and conflict rules (especially for stock and sales). Authentication sessions should remain local. Password and account synchronization needs an explicit security policy before implementation. Simply changing `DATABASE_URL` to a cloud database would remove offline operation.

## Employee profile settings

`employee_table` now owns employee identity, credentials, photo, and professional bio. The local startup migration renames the old `pharmacist_profiles` table, preserves existing IDs/passwords/sessions, and adds the new columns idempotently. Existing accounts receive the `pharmacist` role. Supported role values are `doctor`, `superadmin`, `admin`, `pharmacist`, `nurse`, and `receptionist`.

Authenticated `GET` and `PUT /api/v1/settings/profile` read and save the current employee. PUT accepts the existing profile fields plus `professional_bio` (up to 5,000 characters) and `photo_data_url` (base64 PNG/JPEG/WebP, up to 2 MB decoded). Send null to remove a photo. Images have MIME/signature/size validation; the server does not decode or resize images. Photos live in the local database and are returned only by authenticated APIs. Email changes also update the login email.

Role is returned read-only. Profile updates reject role, credential, ID, and other unknown fields. A role-assignment administration API and role-specific business permissions are not included in this step. Cloud synchronization remains a separate phase.

The frontend integration is staged in `outputs/employee-profile-ui.patch` because this chat cannot write to the separate UI project. Apply from the UI project with `git apply /Users/vijaysoni/Documents/Codex/2026-09-16/erp-pharmacy-backend/outputs/employee-profile-ui.patch`. The patch adds photo preview/removal, editable bio and professional fields, loading/error states, save/cancel, and navbar profile refresh. It preserves the unrelated sidebar edits.

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

### Forgotten password recovery

Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
`SMTP_FROM_EMAIL`, and `PASSWORD_RESET_URL` in `.env`, then restart the API.
SMTP uses STARTTLS with certificate verification by default (port 587).
`SMTP_STARTTLS=false` is intended only for a trusted local mail relay; implicit
TLS on port 465 is not supported. Keep SMTP credentials out of source control.

1. Submit `POST /api/v1/auth/forgot-password` with
   `{"email":"pharmacist@example.com"}`. The API returns `202` with the same
   message for known and unknown accounts. Missing mail/reset URL configuration
   returns `503`. Mail delivery failures are logged without sensitive details
   and receive the same generic `202` response.
2. The email links to `PASSWORD_RESET_URL` with a `token` query parameter.
   This must be a frontend reset page; this backend does not serve that page.
   The page should avoid third-party resources and set `Referrer-Policy: no-referrer`.
3. Submit `POST /api/v1/auth/reset-password` with
   `{"token":"TOKEN_FROM_LINK","new_password":"ReplacementPassword123!","confirm_password":"ReplacementPassword123!"}`.
   Success returns `204`; invalid, expired, or previously used links return `400`.
   Passwords must contain 12–128 characters and match the confirmation.

Links expire after 15 minutes, are single-use, and only their SHA-256 digests
are stored. A new link replaces the previous link; requests for the same account
are limited to one email per minute. Changing the password invalidates outstanding
links. Successful recovery revokes all existing sessions, so the user must log in
again. Apply request rate limits at the reverse proxy before exposing these public
endpoints to the internet.

## Supabase administration connection

The development Supabase project is `nosqyzumgkripfqnqknw`. Local operations
continue to use SQLite through `DATABASE_URL`. Cloud administration settings use
the separate `SUPABASE_ADMIN_DB_*` variables in the ignored `.env` file.

Install optional tooling with `python -m pip install -r requirements-cloud.txt`,
then run `python scripts/check_supabase.py` for a read-only connectivity check.
The check enforces TLS certificate and hostname verification using the bundled
public Supabase CA certificate. It never creates tables or synchronizes data.

The database owner password is for administration on this development machine
only. Do not ship it to desktop users, embed it in JavaScript, or use it as a
shared sync credential. Device sync needs scoped authorization and a cloud API.

Certificate source: https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt
Connection reference: https://supabase.com/docs/guides/database/connecting-to-postgres

## Offline sync implementation status

The private Supabase `erp` schema and RPC migrations are versioned in the frontend
repository under `supabase/migrations`. Cloud synchronization uses authenticated
user JWTs plus a separate per-device secret; it never uses the owner database
password. Only the secret digest is stored in the cloud.

Local support includes transactional outbox records, UUID mapping, conflict
preservation, push/pull, offline leases, allocation-aware stock refresh, and API
status/manual sync routes. `SYNC_ENABLED` defaults to false. Existing local login
and SQLite operations remain active until enrollment is completed.

Do not enable sync by only toggling this flag. First configure Supabase Auth,
provision the pharmacy and employee identity, enroll this device with a random
secret, migrate existing records and opening inventory with UUID mappings, and
allocate stock to this device. Supply only the publishable key and device secret
to a deployed desktop. Owner credentials and SUPABASE_SECRET_KEY are admin-only.

When enabled, user access expires after 24 hours without successful online
verification. Cloud tokens are held in process memory; restarting the backend
requires an online sign-in before synchronization resumes. Offline access can
continue within the saved lease. Supplier/customer/medicine/prescription records
and sales are supported by the queue. Printer settings remain local. Employee
identity management and password changes are deliberately blocked in sync mode
until cloud account administration is implemented; they work normally in current
local mode. Remaining demo business pages need API wiring before full rollout.

`GET /api/v1/sync/status` reports setup, pending changes, conflicts, and lease
expiry. `POST /api/v1/sync/run` uses the signed-in user's cloud session. The UI
retries with backoff and supports explicit record conflict resolution. Stock
receipts/allocation are online superadmin operations via `/api/v1/sync/stock`.
Offline sales must fit the device allocation; raw stock adjustments are disabled
in sync mode. Do not reclaim allocations from an offline/revoked device until
its sales have been reconciled.

## Device enrollment guide

[Device enrollment and sync setup](SYNC_SETUP_README.md) explains account creation, this Mac’s registration, activation, and UI sync.

### Receive stock from a purchase order

Stock Management now has **Add Stock** in the frontend at `/Users/vijaysoni/git/erp`.
Select a pending PO, review all lines, and edit **Receive now** quantities for this
 delivery (not the final inventory balance). Zero means undelivered. Original PO
quantities and prices remain unchanged. Partial receipts leave the PO pending;
**Final delivery** closes a short shipment. Quantities above the ordered amount
are accepted as delivery corrections.

- `GET /api/v1/purchase-orders/pending-receipt` returns pending POs with received and remaining quantities on every line.
- `POST /api/v1/purchase-orders/{id}/receipts` accepts a UUID `request_id`, every PO line as `{order_item_id, quantity}`, and optional `close_order`.
- Reuse the same request ID and payload when retrying an unconfirmed save. Receipts update medicine stock and its movement ledger atomically; inventory refreshes after success.
- New receipt tables are created by the existing startup schema initialization. No existing PO columns change.
- Local/hosted database receiving is supported when `SYNC_ENABLED=false`. Sync devices remain blocked from direct receipt because their saleable stock is controlled by cloud allocations. Cloud receipt RPC integration is still required for that mode.
- Existing `pending_approval` POs are selectable because a separate approval workflow has not yet been implemented.

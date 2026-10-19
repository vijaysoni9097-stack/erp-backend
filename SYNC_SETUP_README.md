# Surya Pharmacy: device enrollment and sync

## This installation

**Activation completed on October 12, 2026:** the confirmed cloud login is linked, this Mac is enrolled, and `SYNC_ENABLED=true`. Sign out and sign in online after the backend reload, then synchronization starts automatically. Enrollment did not upload medicines.

- Local database: `temp.db` (SQLite). Keep it as the application database.
- Supabase project: `nosqyzumgkripfqnqknw` (ERP-DB).
- Pharmacy: Surya Pharmacy, ID `3a3f3ad9-ae5e-5828-bb6f-936068f05e00`.
- Existing local login: `pharmacist@example.com`.
- 564 suppliers are already in the cloud and have local UUID mappings.
- 6,739 imported medicines are queued locally for this login, with zero opening stock. Another 66 source items lacked purchase details and were held for review.
- Enrollment never uploads the medicine queue. You trigger the upload from the UI.

## One-time account step

1. Open https://supabase.com/dashboard/project/nosqyzumgkripfqnqknw/auth/users
2. Select **Add user → Create new user**.
3. Enter **pharmacist@example.com**, matching your local app login.
4. Enter your **current local app password** privately. Do not paste it into chat or a README.
5. Leave **Auto confirm user** selected and click **Create user**. This form does not send a confirmation email.

This version of the application validates the password locally and with Supabase, so both must match. The enrollment script does not reset your password. If this cloud user already exists, do not create another one; verify that its login matches.

## Device registration and activation

Run from the backend project folder using its existing virtual environment:

```sh
.venv/bin/python scripts/enroll_sync_device.py
```

This prepares the employee profile and registers this Mac. It stores the device secret in the private `.env`, and only its SHA-256 digest in Supabase. Initial preparation keeps sync disabled. Re-running does not create a second device as long as `.env` is preserved.

After creating the confirmed Auth user:

```sh
.venv/bin/python scripts/enroll_sync_device.py --activate
```

Activation links the cloud employee to that Auth user and sets `SYNC_ENABLED=true`. It fails without changing local sync configuration if the confirmed user is missing. It refuses to overwrite a conflicting or revoked device registration.

## Start using sync

1. Restart the FastAPI backend with your normal development startup command. Changes to `.env` require a restart.
2. Sign out of the pharmacy app, then sign in with your existing email/password while online.
3. Saving changes wakes the backend worker automatically. Open Synchronization only to inspect status or resolve conflicts.
4. The worker drains batches of up to 200 operations and retries temporary connection failures automatically, even with the browser closed. Keep the backend running.
5. Check Supabase Table Editor → schema **erp** → **medicines** for uploaded rows.

After the first online sign-in following this upgrade, cloud sessions are stored encrypted using the installation device secret and restored across backend restarts. Logging out removes the remembered session. Offline access expires after 24 hours without successful online verification.

## Configuration reference

The script configures these in the backend `.env`:

```dotenv
DATABASE_URL=sqlite:///./temp.db
SUPABASE_PROJECT_URL=https://nosqyzumgkripfqnqknw.supabase.co
SUPABASE_PUBLISHABLE_KEY=<project publishable key>
SYNC_PHARMACY_ID=3a3f3ad9-ae5e-5828-bb6f-936068f05e00
SYNC_DEVICE_ID=<this device UUID>
SYNC_DEVICE_SECRET=<private random device secret>
SYNC_ENABLED=true
```

Keep database-owner credentials and device secrets out of frontend code and Git. No service-role/secret API key is needed by the enrollment script; it uses the existing verified-TLS administration database connection. Do not copy the device ID/secret to another computer: enroll each installation separately.

## Stock and Docker

The imported records are a catalog using latest purchase details, not reconciled batch inventory. Their opening stock is zero. Stock receipts and allocations are separate cloud superadmin operations before offline sales can use inventory.

Docker is needed only to access the original SQL Server backup database. SQLite and Supabase sync do not need that SQL Server container running.

## Troubleshooting and recovery

- **Sync is not enabled:** complete activation, then restart the backend.
- **Cloud sign-in failed:** verify that the cloud user is confirmed and both login passwords match. Do not change only one password.
- **Sign in online to start synchronization:** sign out and sign in again once after upgrading, or when access has expired or been revoked.
- **Device/user not authorized:** verify the employee Auth link, pharmacy ID, and unrevoked device registration; do not regenerate secrets blindly.
- **Pending count decreases slowly:** batches drain automatically. Investigate reported conflicts or connection errors.
- **Pause cloud mode:** set `SYNC_ENABLED=false` in `.env` and restart the backend. This does not delete cloud records or the local queue.

The script saves private `.env` backups in `backups/before-sync-config-*.env`. Database import backups are also in `backups/`. Never publish that folder. The medicine import review report is `backups/medicine-import/report.json`.

## Surya stock snapshot (13 October 2026)

Inventory → Stock Management now reads the local `surya_stock_snapshot` table through
`/api/v1/inventory/source-stock`, replacing the demo rows. The snapshot contains all
6,805 source items from the restored 10 October 2026 Surya Pharmacy backup:
2,161 items with positive stock, 3 with negative stock and 17 without stock records.
The net recorded quantity is 228,477. Negative and missing values are preserved.

Surya `itemStock` has item totals without batch links. These quantities are reference
stock, not cloud allocations or verified saleable batches. The page shows device
availability separately; source stock is not uploaded by catalog synchronization.
Refresh reloads the saved SQLite snapshot, not SQL Server. A new SQL Server export
is needed to update the snapshot. `scripts/import_surya_stock.py` imports the private
export at `backups/stock-import/surya-stock.json`, taking a SQLite backup first.

## Bulk uploads

Sync now uploads up to 200 independent changes per request (up to 1 MiB of
operation data), instead of sending one request per record. The backend worker keeps
requesting batches until the queue is drained or a conflict needs attention.
Changes to the same record remain ordered; cloud receipts are saved together.
If the connection drops, automatic retries resume: operation IDs prevent duplicate writes or
sales. Downloads start after unresolved local changes are cleared.

The cloud requires migration `202610150001_bulk_sync.sql`, maintained in the
frontend repository's `supabase/migrations` directory (a copy is under backend
`migrations/cloud`). Apply it using the existing cloud migration runner before
running the updated backend. Older clients remain compatible.

Small uploads should be substantially faster. Full initial imports still depend
on record count, cloud latency, download pages, and free-service wake-up time;
a few seconds for the entire catalog is not guaranteed.

Checks: `SYNC_ENABLED=false .venv/bin/python -m unittest discover -s tests -q`.
Cloud integration checks in `scripts/test_cloud_sync.py` in the frontend repo
use isolated fixtures and roll all changes back, including bulk retry,
conflict, size-limit, authorization, and transaction rollback checks.

Validation on 15 October 2026: all 33 local tests passed. The rollback-only
Supabase integration test uploaded 200 synthetic supplier records in 2.01 seconds
through the database RPC. This measures one upload batch, not HTTP transport,
the full catalog, or subsequent downloads. Existing stock and permission tests
also passed.

## Automatic business synchronization

Migration `202610190001_automatic_business_sync.sql` adds purchase orders and shared pharmacy/notification preferences. Existing unmapped purchase orders are queued for their creating user. Missing supplier/customer/medicine/prescription parents are queued before dependent records. Purchase orders never change inventory. Printer settings, credentials and identity administration keep their separate security rules. Install requirements before restarting the backend. Hosted PostgreSQL mode saves directly to the cloud; do not enable device synchronization there without separate enrollment.

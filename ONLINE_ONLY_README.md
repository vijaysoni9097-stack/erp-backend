# Online-only operation

The browser calls the hosted API directly. The API writes to its configured PostgreSQL database. No offline leases, device enrollment, background synchronization, outbox writes or sync HTTP endpoints run.

Set VITE_API_BASE_URL to the hosted API URL including /api/v1. The development UI uses the hosted API too. Internet access is required.

Deploy both repositories. Restart backend processes after updating. DATABASE_URL and DATABASE_SCHEMA must identify the intended hosted database; REQUIRE_POSTGRES=true prevents accidental SQLite hosting. Existing SYNC_* values are ignored.

Existing local databases and legacy synchronization tables are retained for recovery and historical deletion markers. They are not merged into the hosted database. Back up and reconcile any local-only records before retiring those files.

Admin delivery review writes receipt, medicine details and stock in one transaction directly to the API database. Replays do not receive stock twice.

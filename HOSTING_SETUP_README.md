# Team testing deployment — free hosting

## Open the application

- UI: https://pharmacy-erp-testing-ui.onrender.com
- API: https://pharmacy-erp-testing-api.onrender.com
- Health check: https://pharmacy-erp-testing-api.onrender.com/health

Status on 15 October 2026: both Render services are deployed. Hosted health,
login, profile, suppliers, medicine search, reference stock and logout passed API
checks. The exact frontend origin is allowed by CORS. The frontend login page
was observed in Chrome. The final visual sign-in check remains unverified because
browser automation became unavailable; API login succeeds.

## Sign in

Use `STAGING_LOGIN_EMAIL` and `STAGING_LOGIN_PASSWORD` from the private local
`.env.hosting.local` file. This is a separate testing administrator account, not
the local pharmacy password. Share only the test login with authorized testers;
do not share the whole file, which also contains the database administrator
password. No credentials are committed to Git or included in frontend variables.

## Create users and set passwords

Sign in with the testing superadmin account, then open **User Management** in
the sidebar (or `/users`). Enter the person's first and last names, email,
unique professional license number, pharmacy name, role and initial password.
Passwords must contain 12–128 characters. Select **Create User**; the person can
then sign in with that email and password. Share the password privately.

Use **Reset Password** beside another account to set and confirm a replacement.
Resetting a password revokes that user's existing sessions. Change your own
password in your profile's security settings. Passwords are stored as hashes
and cannot be viewed or recovered. Only superadmins can administer accounts.
These actions are available on this hosted installation with sync disabled;
cloud-managed installations require separate cloud identity administration.

## Automatic deployment details

- Backend repository: `vijaysoni9097-stack/erp-backend`, branch `main`.
- Frontend repository: `vijaysoni9097-stack/erp`, branch `feature/ui_0.2`.
- Push committed changes to the corresponding branch to trigger Render builds.
  A local commit alone does not deploy until pushed.
- Backend: Docker, Free, Singapore, one worker, health path `/health`.
- Frontend: static site, Node 22.16.0, `npm ci && npm run build`, publish `dist`.
- Frontend route rule: rewrite `/*` to `/index.html`.
- Frontend variable: `VITE_API_BASE_URL=https://pharmacy-erp-testing-api.onrender.com/api/v1`.
- Backend origin: `["https://pharmacy-erp-testing-ui.onrender.com"]`.

Render service IDs:
- Backend: `srv-db7f59bbc2fs73evst5g`
- Frontend: `srv-db7f5u25b2lc73fnm200`

## Testing database and records

Supabase Free project `pharmacy-erp-testing`, reference `wizlnubijmsjbolfxxox`,
Sydney. The private `erp_app` schema contains 565 suppliers, 6,740 medicines and
6,805 reference-stock records, transferred with explicit user approval. There
are no copied customers, prescriptions or sales. Original employee passwords,
sessions, device identities and sync outbox were not copied.

Saleable medicine stock starts at zero. Reference quantities are historical
records, not saleable allocations. Stock changes made during testing persist in
Supabase PostgreSQL across Render restarts and deployments.

Backend settings require PostgreSQL with `DATABASE_SCHEMA=erp_app` and
`REQUIRE_POSTGRES=true`. Never substitute SQLite on Render's temporary disk.
The pooler ignored the startup search-path option, so every application connection
now sets its schema explicitly. Tables and enum types are in `erp_app`, no
application tables remain in `public`, and API client roles have no direct
application-table access. Keep this schema out of the exposed Data API schemas.

The approved connection is stored only in Render backend environment settings.
Its local upload copy is `backups/render-testing.env`, excluded from Git.
Do not replace the local development `.env` with the hosting configuration.

## Remaining testing limitations

- `SYNC_ENABLED=false`: the hosted app saves directly to PostgreSQL. The separate
  offline-device sync workflow is not enrolled or verified in this test project.
  It still requires cloud migrations, a confirmed test Auth user and test device
  enrollment before enabling sync. Do not reuse the live pharmacy identity.
- Password-recovery email is not configured. Render Free blocks common SMTP
  ports; an HTTPS email provider adapter is needed for that workflow.
- Browser-based end-to-end interaction, stock writes, role workflows and sync
  conflicts still need team acceptance testing. API checks are not full UI QA.
- Free web services sleep when inactive and can take about a minute to wake.
  Supabase Free also has quotas and may pause inactive projects. No paid plan
  was selected.

## Verification

All 27 backend tests pass. The frontend production build succeeds. Separate
local PostgreSQL tests cover startup/restart, protected APIs, exact-origin CORS,
employee ID generation and competing sales without overselling. Hosted records
remain available after backend configuration redeploys.

See `SYNC_SETUP_README.md` for the original local enrollment process; its live
pharmacy identifiers are not the testing environment's configuration.

References:
- https://render.com/docs/free
- https://render.com/docs/deploys
- https://supabase.com/pricing

## Pharmacist dispensing workspace

Pharmacist logins open `/dispense`. Pharmacists, admins and superadmins can also
open **Dispensing** from the sidebar. Search available medicines by name, generic
name, SKU or batch, add quantities, enter the patient name, and select or type
the prescribing doctor's name. **Complete sale** records the patient,
prescription and bill together and reduces stock atomically. It does not process
an online payment. This initial checkout uses stored selling prices without an
additional tax calculation.

Only unexpired medicines with positive saleable stock are offered. Imported
reference quantities do not become saleable inventory automatically. Receive or
allocate stock first; no stock is fabricated for the new workspace.

If a request times out, keep the page open and use **Retry / confirm this sale**.
It reuses the same checkout reference to prevent duplicate billing. The new
`checkout_receipts` table is created by the existing application startup schema
initialization in the private application schema. No existing tables are altered.

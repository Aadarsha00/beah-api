# Production deployment and lossless cutover

This runbook keeps the current business content unchanged. The cutover changes
the database engine from local SQLite to production MySQL; it does not replace,
reseed, activate, deactivate, or otherwise transform customer/business data.

## Non-negotiable safety rules

1. Never commit a cutover ZIP. It contains customer personal data and password
   hashes. `cutover-bundles/` and `*.cutover.zip` are ignored, but Git ignore is
   not encryption.
2. Transfer the bundle through an encrypted, access-controlled channel and
   retain it only as long as the rollback policy requires.
3. Put the source application in maintenance mode before export and keep writes
   stopped until traffic is switched or the cutover is abandoned. The export
   flag is an acknowledgement; it does not enable maintenance mode itself.
4. Keep the original SQLite file and the complete original media directory
   untouched as rollback assets.
5. Restore only into a freshly migrated, empty MySQL database and completely
   empty media storage. The restore command refuses non-empty targets and never
   overwrites files.

## What the cutover bundle contains

The bundle preserves primary keys, password hashes, timestamps, foreign keys,
many-to-many relationships, application/admin records, and every file under
the configured media storage. The manifest records per-model counts and
SHA-256 checksums for the database fixture and each media file.

Framework-generated content types, permissions, and migration records are
recreated by `migrate`. Django sessions and SimpleJWT outstanding/blacklisted
tokens are intentionally excluded; all users must sign in again after cutover.
No plaintext password is exported.

## 1. Prepare and verify the source bundle

First take independent backups of `db.sqlite3` and the entire `media`
directory. Stop all web/dashboard writes. Then, from the source virtual
environment:

```powershell
New-Item -ItemType Directory -Path .\cutover-bundles -Force
python manage.py export_cutover_bundle .\cutover-bundles\production.cutover.zip --maintenance-mode-confirmed
python manage.py verify_cutover_bundle .\cutover-bundles\production.cutover.zip
python manage.py verify_cutover_bundle .\cutover-bundles\production.cutover.zip --against-current
Get-FileHash .\cutover-bundles\production.cutover.zip -Algorithm SHA256
```

The final `--against-current` check fails if any database record differs or if
any media file is missing, changed, or extra. Record the external ZIP SHA-256
in the private change ticket.

Do not use `import_legacy_public_data` for this cutover; that command only
imports public content and intentionally omits users and appointments.

## 2. Prepare the empty target

Create a new MySQL database using `utf8mb4`. Do not point this release at a
populated legacy database. Configure the environment from `.env.example`, then:

```powershell
python -m pip install --requirement requirements.txt
python -m pip check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate
```

Configuration comes from operating-system environment variables. A `.env` file
in the application root is also loaded if present, but with `override=False`:
a real environment variable always beats the file, so cPanel panel settings are
never silently replaced by a stale upload. `.env` is gitignored; never commit
it, and never place production secrets in the repository.

Prefer panel/systemd variables for production and keep `.env` for local
development. If you do upload a `.env`, confirm `DJANGO_DEBUG=false` in it —
though startup now refuses to run with `DJANGO_DEBUG=true` while
`DJANGO_ALLOWED_HOSTS` contains a non-local hostname, so this fails loudly
rather than quietly serving debug tracebacks.

`accounts.0003_activate_legacy_users` predates this cutover design. It is a
no-op on the required fresh target because no users exist while migrations run.
Do not apply it directly to a populated user database: it would activate every
inactive non-staff account. The bundle restore runs only after all migrations
and restores each account's source `is_active` value exactly.

The target media root/bucket must also be empty. With filesystem storage,
`DJANGO_MEDIA_ROOT` must be an explicit absolute path on durable storage that
survives application releases/restarts. Configure Apache/Nginx to serve
`DJANGO_MEDIA_URL` from that path. Django does not serve media in production.

An object-storage backend can be supplied through
`DJANGO_DEFAULT_STORAGE_BACKEND` and JSON
`DJANGO_DEFAULT_STORAGE_OPTIONS`, but its Python package must be explicitly
added to `requirements.txt` and tested in staging. The application no longer
requires a filesystem `.path` for gallery resize/delete operations.

## 3. Restore and prove equivalence

Transfer the confidential bundle and compare its external SHA-256. Then:

```powershell
python manage.py restore_cutover_bundle .\production.cutover.zip
python manage.py verify_cutover_bundle .\production.cutover.zip --against-current
python manage.py collectstatic --noinput
python manage.py check --deploy
```

Restore validates every archive checksum before writing, refuses non-MySQL
targets, refuses any existing business record/media file, restores explicit
PKs, resets sequences, and compares the complete post-restore database/media
checksums before commit.

Test before switching traffic:

```text
GET https://api-host/api/health/  -> 200 {"status":"ok"}
GET https://api-host/api/ready/   -> 200 {"status":"ready"}
```

Also verify public services/gallery/blog, an existing customer login, staff
login, appointment history, one future availability request, contact email,
new-account activation email, admin static assets, and media URLs.

## 4. Switch traffic and rollback

After validation, switch the frontend API URL/DNS to the new HTTPS API and
remove maintenance mode. The frontend must use the final HTTPS URL directly;
browser CORS preflight requests cannot rely on an HTTP-to-HTTPS redirect.

For rollback before the new target accepts writes:

1. Stop target traffic.
2. Switch traffic back to the untouched source SQLite application/media.
3. Investigate or rebuild the empty target and rerun the verified bundle.

If the new target accepted any customer/admin writes, do not blindly switch
back: that would lose those records. Stop writes, export a new target bundle,
and reconcile the delta under a written data-recovery plan.

## Production environment requirements

- `DJANGO_DEBUG=false`
- A unique random `DJANGO_SECRET_KEY` of at least 50 characters
- Real API `DJANGO_ALLOWED_HOSTS`
- Exact HTTPS frontend `CORS_ALLOWED_ORIGINS`
- MySQL `DB_*` credentials; optional `DB_SSL_CA`
- Durable media storage configuration
- Working SMTP and activation URL configuration
- `SEND_CONTACT_EMAILS=true` and a monitored `ADMIN_EMAIL`
- A shared throttle cache: `DJANGO_CACHE_URL` (Redis) or `DJANGO_CACHE_TABLE`
  (after `manage.py createcachetable`). A single-worker deployment may instead
  set `DJANGO_ALLOW_LOCAL_MEMORY_CACHE=true` to accept per-process limits.
- Secure cookies and HTTPS redirect
- `America/New_York` salon timezone

Unhandled 500s are emailed to `ADMIN_EMAIL` through the configured SMTP host,
so that mailbox must be monitored. Setting `SENTRY_DSN` additionally reports
exceptions to Sentry and requires `pip install sentry-sdk`; it is deliberately
not in `requirements.txt` because the email path needs no extra service.

When TLS terminates at a trusted reverse proxy, enable
`DJANGO_TRUST_X_FORWARDED_PROTO=true` only if that proxy strips untrusted
client headers and sets `X-Forwarded-Proto` itself. Set `DJANGO_NUM_PROXIES` to
the exact proxy count so throttling uses the intended client address.

Start with HSTS disabled, verify every relevant subdomain over HTTPS, then
increase `DJANGO_SECURE_HSTS_SECONDS` gradually. Do not enable include-subdomain
or preload flags until all subdomains are permanently HTTPS-ready.

## Passenger release

`passenger_wsgi.py` exposes `core.wsgi.application`. A typical cPanel release:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --requirement requirements.txt
.venv/bin/python -m pip check
.venv/bin/python manage.py check --deploy
.venv/bin/python manage.py migrate --plan
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
mkdir -p tmp
touch tmp/restart.txt
```

Run migrations only after a database backup. A normal code release must never
run cutover restore commands. Use a clean Python 3.12 or 3.13 virtual
environment, pin the exact patch version in the hosting panel, and use that
same runtime in staging.

## Scheduled maintenance

Run these with the release virtual environment and production settings:

```cron
# Daily: remove expired SimpleJWT outstanding/blacklisted-token rows.
17 3 * * * /absolute/app/.venv/bin/python /absolute/app/manage.py flushexpiredtokens

# Daily: make expired promotion status explicit for dashboard administration.
27 3 * * * /absolute/app/.venv/bin/python /absolute/app/manage.py expire_promotions
```

Configure database backups, durable-media backups/versioning, log collection,
error alerts, uptime checks for `/api/health/`, and readiness checks for
`/api/ready/`. The included contact throttle is a per-process baseline; use a
shared cache or edge rate limit if the application runs on multiple hosts.

## Booking assumptions requiring business approval

Deployment hardening does not alter these rules:

- Salon timezone: `America/New_York`
- Monday-Saturday hours: 9:00 AM-6:00 PM
- Sunday hours: 10:00 AM-4:00 PM
- 30-minute slot boundaries
- Maximum booking horizon: 90 days
- One global appointment capacity at a time, despite the optional stylist field

Holidays and time off are configurable: staff add date ranges under Closures in
the dashboard (or `SalonClosure` in Django admin) and those dates stop accepting
new bookings and reschedules. Closing a date deliberately does **not** cancel
bookings that already exist in that range; the dashboard reports how many are
affected so staff can contact those customers.

Changing capacity, hours, or per-stylist scheduling requires an explicit
business decision and new booking tests.

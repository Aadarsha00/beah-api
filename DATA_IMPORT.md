# Legacy public data import

Run this command while the legacy API is still reachable:

```powershell
python manage.py import_legacy_public_data
```

It imports active services, published blog posts, active gallery records, and
their media files from `https://api.beautifulbrowsandhenna.com`. Legacy IDs
and timestamps are preserved, and rerunning the command does not create
duplicate records.

Optional arguments:

```powershell
python manage.py import_legacy_public_data --source-url https://legacy.example.com
python manage.py import_legacy_public_data --refresh-media
```

Users, appointments, contact messages, drafts, and other private records are
not exposed by the public API. Migrating those records requires a database
export or authenticated access to the legacy server.

This importer is not the production cutover mechanism. When the current local
users, password hashes, appointments, business records, and media must all be
preserved, use the checksummed export/restore workflow in `DEPLOYMENT.md`.

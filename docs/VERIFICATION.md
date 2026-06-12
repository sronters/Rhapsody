# Verification

This file records the current local verification status. It should be updated
when manual second-user Telegram tests are completed.

## Latest Local Checks

Latest local verification after adding isolation regression coverage:

```bash
python -m pytest
```

Result:

```text
99 passed, 2 skipped
```

```bash
python -m ruff check . --no-cache
```

Result:

```text
All checks passed.
```

Docker Compose has been rebuilt and the stack runs locally. Health and readiness
checks pass:

```text
GET /api/v1/health -> {"status":"ok","mode":"cloud"}
GET /api/v1/ready  -> {"status":"ready"}
```

## Manual Telegram Checks Completed

Completed with the configured real Telegram user session:

- Private one-user Alpha/Beta project isolation.
- Meeting ingestion into Alpha.
- `/ask` in Alpha returned Gemini with sources.
- Switching to Beta did not leak Alpha/Gemini memory.
- Document ingestion into Beta.
- `/ask` in Beta returned Beta document content without Alpha leakage.
- `/tasks`, `/decisions`, and `/audit` stayed scoped.
- Group project binding.
- Group meeting ingestion.
- Group `/ask`, `/tasks`, `/decisions`, and `/audit` used the group project.
- Group memory did not leak private Alpha/Beta data.

## Still Pending

These are not manually verified yet:

- Real second Telegram user private cross-access test.
- Real second Telegram user group hijack attempt.

Only one `TELEGRAM_USER_SESSION` was available during the latest verification.
The second-user tests must use a different Telegram account/session.

## Fixed Issues Recorded

- Local `.env` database URL mismatch with Docker Compose Postgres defaults.
- `workspace_members.created_at` migration default for fresh Postgres databases.
- Group project hijack bug in the `/use_project` path.
- Legacy Telegram mapping backfill issue for migration `0006`.
- UTF-8 BOM in tests.

## Notes

- Earlier before adding the latest isolation regressions, the suite was
  `96 passed, 2 skipped`.
- The current expected suite result is `99 passed, 2 skipped`.
- Live-call listener is separate from this core Telegram flow verification.

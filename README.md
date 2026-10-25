# LoanShark

### Someone's got it. Your agent finds it.

LoanShark (working architecture name: CampusAgent) is a planned privacy-first campus assistant for equipment borrowing and lost-and-found. Personal agents will evaluate their students' private lending conditions and availability; a group agent will coordinate approved requests without publishing inventories or schedules. Both people must approve an arrangement and confirm the handoff.

**Current release: Milestone 2 — isolated personal agents and privacy enforcement.** Owner-scoped agents manage private inventory, lending policies, schedules and availability through a credential-authenticated Python test interface. A separate least-privilege gateway checks feasibility and returns a strict, minimal result. PostgreSQL row-level security backs the application checks. There are no public student-data/gateway routes, Discord integration, lending transactions, reminders or claim-verification workflows yet.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full approved design and [CLAUDE.md](CLAUDE.md) for development rules. Read [PRIVACY.md](PRIVACY.md) for the authorization model, test interface and explicit security limitations.

## Requirements

- Python **3.12** (verified with 3.12.14); system Python 3.9 is too old.
- Docker Desktop/Engine with Compose v2, running.
- Ports `55432` (PostgreSQL, loopback only) and `8000` (app) available.
- No Discord token, Claude key, cloud service or paid account is needed for this milestone. Gateway database credentials are generated locally.

The Compose image is PostgreSQL 17 pinned by digest; it resolves to PostgreSQL 17.11 in the verified environment. Runtime, gateway and migration roles are separate. Development and test databases share one local PostgreSQL service.

## Setup from a clean checkout

```sh
git clone https://github.com/ssrid111/Loanshark.git
cd Loanshark
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
python scripts/dev_env.py
docker compose up -d --wait postgres
python scripts/bootstrap_db.py
alembic upgrade head
python scripts/migrate_test.py
```

On Windows activate with `.venv\Scripts\Activate.ps1`; use the Python 3.12 launcher to create the environment. Commands otherwise run from the repository root.

`dev_env.py` creates an ignored, permission-restricted `.env` with freshly generated **local development database passwords**. It never prints them and refuses to overwrite an existing `.env`. `.env.example` contains placeholders only. Alternatively, copy `.env.example` and replace every database/password placeholder locally. Do not paste credentials into chat or commit the completed file.

`bootstrap_db.py` targets only the local Compose instance at `127.0.0.1:55432`. It creates `loanshark` and `loanshark_test`, their migrator/runtime/gateway roles and schema permissions. It does not reset existing role passwords. If you change `.env` passwords after creating the Docker volume, update the existing roles using the database administrator rather than expecting a restart to reset them. Do not remove a data volume that contains data you need.

Alembic uses `MIGRATION_DATABASE_URL`; the application uses `DATABASE_URL`. The readiness check does not run migrations for you. Do not expose the migration role to a deployed application. For an existing external PostgreSQL server, have its administrator create equivalent roles/databases/schema permissions, use its URLs, skip the local bootstrap, and create the restricted `loanshark_runtime` and `loanshark_gateway` roles before applying migrations.

## Run

```sh
uvicorn main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

In another terminal:

```sh
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

- `/health/live` returns HTTP 200 when the application process responds. It does not claim the database works.
- `/health/ready` connects to PostgreSQL and checks the exact Alembic revision. It returns HTTP 503 for connection failures, missing migrations, or a stale revision. It returns no credentials, database URL or student data.
- `/docs` describes the health endpoints only. Private API, Discord and LLM integration remain disabled; attempting to enable them fails configuration validation.

Stop the app with Ctrl+C. Stop the local database without deleting its volume:

```sh
docker compose stop postgres
```

## Test and verify

With the environment active and the Compose database running:

```sh
python scripts/migrate_test.py
pytest
ruff check .
ruff format --check .
mypy
alembic check
python -m pip check
python -m build --no-isolation
```

Unit-only tests, without a running database:

```sh
pytest -m 'not integration'
```

Tests load local `.env` without overriding already exported environment values. Integration tests require `TEST_DATABASE_URL`, `TEST_RUNTIME_DATABASE_URL`, and `TEST_GATEWAY_DATABASE_URL`, each naming a database ending in `_test`. They never fall back to the application URL. Missing test URLs produce visible skips; invalid database names fail. The generated `.env` provides the local test URLs.

**Use a disposable test database.** Migration tests downgrade and rebuild its schema to verify reversibility and readiness failure. Foundation database fixtures roll back their writes. Privacy fixtures commit synthetic rows for independent role connections; the migration-roundtrip test resets the disposable schema. Do not run migration tests concurrently against the same database.

Coverage includes settings/secret handling, UTC timestamps, structured log redaction, safe validation/error responses, liveness and real readiness, connectivity, rollback, identity uniqueness, ownership/foreign keys, duration/state constraints, separate lost/found tables, reservation uniqueness, loan constraints, append-only audit permissions, and migration upgrade/downgrade/schema consistency. Privacy tests additionally cover cross-owner access, direct SQL/RLS, forged identities, consent revocation, lending policies, schedule coverage, safe responses, import boundaries and log redaction. These tests do not prove immunity to malicious server code or administrator access.

`requirements.txt` pins runtime dependencies and their transitive versions; `requirements-dev.txt` adds the test, formatting, type-checking and packaging tools. Optional Claude and Discord dependencies will be added with their implementation milestones, not installed speculatively.

## Foundation layout

```text
main.py                     FastAPI factory and lifecycle
config.py                   environment settings; secrets hidden from representations
api/routes.py               liveness and database/migration readiness
agents/                     isolated owner interface, registry, contracts and privacy gateway
core/identity.py            credential authentication and transaction-local identity
core/clock.py               UTC clock interface
core/errors.py              safe error responses and correlation IDs
core/logging.py             allowlisted JSON logs without arbitrary exception/input text
db/connection.py            async engine, transaction-scoped sessions and cleanup
db/models.py                typed models, foreign keys, indexes and constraints
db/repositories/private.py  owner-authorized private data operations
db/migrations/              reviewed schema, audit trigger, RLS and protected SQL evaluator
scripts/                    local configuration, database bootstrap and test migration
tests/                      unit and PostgreSQL integration tests
compose.yaml                loopback-only PostgreSQL development service
CLAUDE.md                   architecture conventions and milestone boundaries
```

## Schema and privacy boundaries

- `Student` uses `users`; Discord/platform IDs are strings and unique per platform.
- `InventoryItem`, `BorrowRequest`, `Loan`, `Confirmation`, and `AuditEvent` map to the approved tables.
- `Community`, `LendingPolicy`, `Offer`, and `Reservation` provide required foreign-key targets. They contain no implemented negotiation behavior. A Loan never references a nonexistent reservation table.
- `LostFoundReport` is a shared unmapped base for **separate** `lost_reports` and `found_reports`. Hidden-detail columns hold ciphertext bytes; encryption/intake/verification services are not yet implemented, and no endpoint accepts those fields.
- All persisted timestamps use PostgreSQL `timestamptz`. Application writes reject naive datetimes and normalize aware ones to UTC; connections use UTC.
- Database constraints prevent orphaned rows, cross-owner item/policy relationships, invalid durations, duplicate active reservations and malformed closure records. They do not replace future consent/authorization services.
- Audit rows contain typed action/state references, not arbitrary message or request-body blobs. The runtime role can append/read but cannot update, delete or truncate audit records; a trigger also rejects mutation. This does not protect against database administrators.
- Unexpected failures return a safe error code and server-generated request ID. Logs retain error type and code locations without raw exception strings, input, SQL parameters or secrets. CLI failures exit nonzero.

The credential-authenticated private Python interface enforces owner-scoped reads. It is not a public HTTP API. Public-facing login and integration remain deferred. Future group output may share only consented availability/meeting proposals, never raw inventory, schedules or hidden lost-item identifiers. The LLM will never authorize actions. No unsolicited stranger messaging or money movement is planned.

## Existing Milestone 1 checkout

With the venv active, add the gateway settings without replacing the current local passwords:

```sh
python scripts/add_gateway_env.py
python scripts/bootstrap_db.py
alembic upgrade head
python scripts/migrate_test.py
pytest
```

[PRIVACY.md](PRIVACY.md) explains how to exercise the private Python interface and the four-student PostgreSQL test scenario. HTTP remains health-only; do not invent a gateway URL.

## Exact next milestone

**Milestone 3: real borrowing negotiation** (the architecture's M2): request/offer transitions, exact-term confirmations, counteroffers, atomic conflict-safe reservations and handoff receipts. Discord and durable reminders come after that. Milestone 3 has not started.

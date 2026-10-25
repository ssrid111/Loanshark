# LoanShark / CampusAgent engineering guide

Read ARCHITECTURE.md before changing code. LoanShark is the product; CampusAgent is the working name of the implementation brief.

## Current scope and milestones

The user's Milestone 1 foundation is complete. **Current scope is Milestone 2: isolated personal agents and privacy enforcement** (the architecture's M1). Read PRIVACY.md for the actual enforcement and limitations.

- Implemented: owner-scoped credential authentication, agent registry, private inventory/policy/schedule/availability management, pause/trust/community controls, strict gateway contracts, RLS and least-privilege gateway SQL evaluation, consented detail disclosure, audited decisions and adversarial tests.
- No public management/gateway endpoints; private Python test interface only. Operator-provisioned test identities are not a production Discord enrollment flow.
- Next after authorization: real borrowing negotiation (architecture M2), then Discord integration (M3), durable jobs (M4), lost-and-found services (M5), hardening/live demo (M6).

Do not begin the next milestone. No loans, reservations, messages or check-ins are created by the current agent services.

## Architecture and conventions

- Python 3.12, modular monolith, one PostgreSQL 17 DB service. No microservices/agent framework/SQLite fallback.
- Root main.py app factory; config.py environment settings; api/ health; core/ safe errors/logging/clock; db/ models, sessions and reviewed migrations. Add other packages only as their milestone needs them.
- Typed Python, UUID internal keys, timezone-aware UTC timestamps, string platform/Discord IDs.
- Explicit services and state transitions later. No SQL in Discord event handlers. One AsyncSession per transaction/task. Roll back and propagate failures.
- Alembic is schema source of truth. Freeze types/constraints in revisions; never import changing application models into historical migrations. Do not call create_all on application startup.
- Inspect auto-generated migrations. Add indexes, foreign keys and uniqueness to enforce invariants, not comments promising them.
- Use a fake clock and deterministic data for time-sensitive business tests. No sleeps to simulate deadlines.
- Maintain exact runtime/development dependency pins; run installation, pip check, formatting, lint and strict type checking after dependency changes.

## Privacy invariants

- No secrets or real student data in Git, prompts, logs, screenshots or fixtures. .env.example contains placeholders; .env stays ignored.
- Only authenticated owners may access private data. The group agent must never own general inventory/schedule repositories.
- The guard is the only cross-agent evaluation entry point. Its protected SQL function evaluates authorized owner policies under a locked search path; the gateway login cannot SELECT private tables. Runtime uses token-derived RLS, never a caller-supplied owner GUC. Before consent return only a boolean; afterwards only allowed place/window fields. A Python module boundary is not a sandbox against malicious server code.
- LLM output is untrusted language extraction, never identity, consent, policy override or authorization.
- Bind confirmations to actor, resource/version, action, digest and expiry; consume atomically. Borrower-only return reports do not close loans.
- No raw inventory/schedule/hidden identifiers in outbound public results or arbitrary error serialization. Lost/found ciphertext columns must receive encrypted bytes through a future protected service, never plaintext.
- Audit is append-only for application roles, not tamper-proof against DB administrators. Dedicated migrator role performs DDL; runtime cannot mutate audit records or migration history.
- Outbound effects require scoped consent, authenticated recipients and durable idempotency. Never message strangers or move money.
- No fake readiness or simulated successful integration responses. Unimplemented integrations fail configuration validation if enabled.
- Sanitize error contents, not failures: emit structured type/correlation/frame logs, return safe codes, preserve nonzero CLI exits. Never log arbitrary exception strings, SQL bind values or input bodies.

## Model decisions in foundation

Student maps to users. InventoryItem maps to inventory. BorrowRequest maps to requests. Loan requires an actual Reservation FK. Community, LendingPolicy, Offer and Reservation are supporting referential records only, not services. LostFoundReport is an unmapped shared base for separate LostReport/FoundReport tables. Polymorphic resource IDs are deliberately not fake foreign keys; future services must validate their resource kind, existence and ownership. Confirmation constraints alone do not implement authorization. No unauthenticated mutation routes exist. db.models now also contains the Milestone 2 private data, membership, credential and immutable coordination-grant tables. Do not expose the owner repository outside agents/personal.py; executable boundary tests enforce this approved dependency.

## Verification commands

Run from repository root with the project venv active:

```sh
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
docker compose up -d --wait postgres
# Existing M1 environments: python scripts/add_gateway_env.py
python scripts/bootstrap_db.py
alembic upgrade head
python scripts/migrate_test.py
pytest
ruff check .
ruff format --check .
mypy
alembic check
python -m build --no-isolation
```

Generate .env once with `python scripts/dev_env.py`; it refuses to overwrite an existing file. Integration tests require explicit TEST_DATABASE_URL, TEST_RUNTIME_DATABASE_URL and TEST_GATEWAY_DATABASE_URL ending in `_test`. Without them they skip visibly. Migration tests downgrade/rebuild that test DB; never point them at important data. Unit-only run: `pytest -m 'not integration'`.

Run app: `uvicorn main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --no-access-log`. Runtime app configuration does not require migration or provider credentials. Readiness checks DB and exact migration head; liveness only confirms the process is responding.

Inspect `git diff --check`, ignored .env status and staged changes before committing. Do not claim tests passed unless actually run. Record version/database environment and any skips. Stop at the milestone boundary the user requested.

## Commit identity

The user requires commits as **ssrid111**, not SwethaVenkatesan1212. Preserve repository-local user.name=ssrid111 and user.email=241015998+ssrid111@users.noreply.github.com. Do not change global Git identity or rewrite previous commits without authorization.

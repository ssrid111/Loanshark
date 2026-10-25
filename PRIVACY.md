# Milestone 2: personal agents and the privacy boundary

## What is implemented

The private Python test interface in `agents/personal.py` manages an authenticated student's inventory, policies, availability, schedule blocks, schedule-coverage declaration, lending pause, trusted contacts and community opt-in. `PersonalAgentRegistry.resolve(actor, student_id)` resolves a logical agent only for the authenticated owner. Wrappers are stateless: one student's durable state is shared in the database, not in shared prompts or another student's memory.

There is no public gateway route, public student-management API, Discord handler, loan workflow, handoff booking or outbound message in this milestone. FastAPI still exposes health only. The existing tokens are operator-provisioned credentials for the private test interface; production Discord identity verification/enrollment remains a later milestone.

## Credentials and database enforcement

1. An operator provisions a student and a random, high-entropy bearer credential. Only a SHA-256 digest is stored in `api_tokens`. Normal student sessions cannot read or write that table.
2. `StudentSessions.authenticate()` uses a fixed security-definer identity lookup. A caller-supplied UUID, Python dataclass, or `loanshark.student_id` connection setting is not authority.
3. Every transaction sets the actual opaque token with transaction-local `set_config`. PostgreSQL validates the digest, expiry, revocation and active student. The registry, session factory and private repository each check owner identity. Pooled connections do not retain a student's identity after the transaction.
4. PostgreSQL row-level security filters `users`, `inventory`, `lending_policies`, `schedule_blocks`, `availability_windows`, `memberships`, `trusted_contacts` and owner audit rows. The runtime role cannot bypass RLS, change identities, mint credentials, or change migration history.
5. The separate `loanshark_gateway` login has **no SELECT privileges on private tables**. It can execute only the narrowly granted coordination function. It is not a member of runtime or migration roles. Normal runtime credentials cannot call that function.
6. Historical foundation permissions are revoked by migration `0002_privacy`; they are not silently carried into the agent layer.

Only `agents/personal.py` may import the private repository at the application-service boundary. The group agent depends on a narrow gateway protocol; it has no database, identity authority or registry. Executable import-boundary tests detect unapproved model/repository dependencies and common dynamic imports. Repository identity checks and PostgreSQL RLS remain enforceable when an ordinary caller bypasses the registry or omits an owner WHERE clause.

## A coordination check, step by step

- The requester authenticates and explicitly confirms an immutable `CheckIntent`: approved community, target owner, canonical item/subtype, approved location ID, handoff window and return time.
- Their agent stores a grant and returns an opaque random capability. The grant binds to the credential that authorized it, expires within 15 minutes, and permits at most 20 checks. Revoking the authorizing credential invalidates the grant. Grant terms cannot be changed by the requester or group agent.
- The group may pass that capability to `PrivacyGateway.check(GatewayRequest(...))`. It cannot substitute actor IDs, a private address, SQL, or a schedule in the gateway schema.
- The protected SQL policy evaluator runs against one specific owner's records. It rechecks both students' verified membership/opt-in and active accounts; the owner's pause state; item type/subtype/active state; existing reservations; same-day, trusted-contact and maximum-duration rules; approved meeting zone; both declared availability windows; schedule coverage/freshness; and busy-block travel buffers.
- Missing, stale or invalid schedule/policy/authorization information denies eligibility. An empty schedule is usable only when the student has explicitly confirmed coverage. The declaration must be no more than 24 hours old and cover the requested window.
- A feasible handoff requires a five-minute interval in both students' explicit availability at the same approved public location, outside both busy schedules plus their selected buffers. Candidates include busy-block end times, so a partially busy window can still be evaluated correctly. Duration is checked from the candidate pickup time to the requested return, and same-day rules use the lender's time zone.
- Before owner disclosure approval the response is eligibility only (plus a generic `unavailable` code for a negative result). After the target owner authenticates and approves that exact grant, the response can include a public meeting-zone code and five-minute feasible window. The requester cannot approve for the owner, and the owner can revoke disclosure.
- Every completed gateway evaluation inserts an append-only audit decision in the same transaction. A result is returned as eligible only after that transaction commits. Owner reads, changes and denied application operations are also audited.

The gateway's SQL function is the privileged policy evaluator, not a general query proxy. It uses explicit schema-qualified objects and a locked search path. It accepts no SQL or identifier expressions. No inventory, schedule, policy object, token, address, owner name or hidden lost-item identifier is returned.

## Strict response contract

`AvailabilityResult` permits only:

- `eligible`: boolean;
- `location`: approved public location code, or absent;
- `window`: timezone-aware start/end, or absent;
- `reason`: the generic `unavailable` value, or absent.

Unknown fields fail validation. Ineligible results cannot include locations/windows. A location without a window is invalid. Before disclosure, positive responses serialize with `exclude_none=True` as `{"eligible": true}`. Responses are constructed from a fixed database projection, never generic ORM serialization.

## Audit and errors

`audit_log` remains INSERT/SELECT-only for the runtime role, with the foundation mutation-rejecting trigger. Runtime RLS also restricts reads/appends to its authenticated actor. The gateway function records only an opaque grant reference, fixed event code, correlation ID and timestamp. Hidden identifiers, tokens, raw schedules, free-form messages and private reasons are absent.

Logs retain controlled event codes, error classes and sanitized stack locations. They omit exception strings, SQL arguments and input bodies. A database, clock, output-validation or audit-commit failure returns no eligibility. It emits a sanitized failure log. If PostgreSQL itself is unavailable, a durable audit row cannot be written; the operation fails closed rather than claiming the audit succeeded.

Direct SQL hidden by RLS is not a separately audited application decision. This milestone audits mediated service decisions; database-wide forensic access logging is not claimed.

## Test interface and repeatable verification

The executable examples are in `tests/test_agents_privacy.py`, using the four synthetic students from `tests/privacy_fixtures.py`. They create real records and run real separate database-role connections, not fake successful agent replies.

```sh
python scripts/add_gateway_env.py   # existing Milestone 1 .env only; preserves its secrets
python scripts/bootstrap_db.py     # creates the new restricted login
alembic upgrade head
python scripts/migrate_test.py
pytest tests/test_agents_privacy.py tests/test_privacy_contracts.py
pytest
ruff check .
ruff format --check .
mypy
alembic check
```

Fresh checkouts use `scripts/dev_env.py`, which now includes gateway settings. Existing installations use `add_gateway_env.py`; it is limited to the local Compose instance, will not reset passwords, and refuses partial configurations. An external administrator must create the same least-privilege role explicitly. Never reuse the migrator URL as a runtime or gateway URL.

Tests require `TEST_GATEWAY_DATABASE_URL` in addition to the two foundation test URLs. Fixtures commit synthetic rows so independent runtime and gateway connections can see them; the migration-roundtrip test rebuilds the disposable test schema. A targeted subset can leave synthetic rows in that test DB. Never use a database with real data and do not run migration tests concurrently against the same DB.

A typical service call in an already provisioned, trusted test composition is:

```python
sessions = StudentSessions(runtime_database)
registry = PersonalAgentRegistry(sessions)
actor = await registry.authenticate(student_bearer_token)
agent = await registry.resolve(actor, actor.student_id)
items = await agent.items()  # owner-only private result; never send to a group
```

The group receives only `PrivacyGateway(gateway_database)` through its protocol, not `sessions`, `registry`, credentials or repositories. Do not mount these objects as unauthenticated FastAPI dependencies. No human login token or self-selected student ID is accepted over HTTP in this milestone.

## Executable evidence and limits

Tests exercise cross-owner reads/edits/deletes, forged contexts, direct queries without owner filters, forged ID settings, transaction-local identity cleanup, direct gateway-role table reads, unauthorized function execution, credentials/consent revocation, immutable grant terms, policy denials, stale/unknown schedules, busy blocks/travel buffers, typed response-field rejection, import-boundary rules, sanitized errors, and append-only audit behavior.

These controls **do not prove all possible privacy leakage is impossible**:

- This is a trusted Python monolith, not an operating-system sandbox. Arbitrary code execution, malicious imports/reflection, stolen bearer credentials, access to process secrets, the migration role or database administration can defeat application boundaries. Static import tests are regression checks, not a sandbox.
- The privileged migration owner owns the tables and security-definer functions and intentionally bypasses RLS. RLS is not forced on that owner because the evaluator requires authorized cross-owner inspection. Do not run the app as this owner; protect migration credentials separately.
- Eligibility itself reveals a limited fact. Community opt-in, exact consented queries, opaque capabilities, a 15-minute expiry and per-capability check budget reduce probing; there is no claim of differential privacy or an organization-wide rate limit.
- Schedule coverage is explicitly student-supplied, not independently verified against institutional calendars. Approved zones and declared travel buffers do not prove a route is physically reachable in real time.
- Results are point-in-time advice, not reservations. Borrowing must revalidate and transactionally reserve later, after explicit commitments.
- PostgreSQL authorization does not encrypt schedule/location values at rest. Protect database storage and backups before real deployment. Hidden lost-item encryption/intake remains a later feature.
- No Discord enrollment, scheduling, reminder delivery, bookings, money transfers or loan closure is implemented here.

## Next milestone

Real borrowing negotiation: deterministic request/offer state transitions, exact-term confirmations, counteroffers, conflict handling, atomic reservations and mutual handoff receipts. Do not start it as part of Milestone 2.

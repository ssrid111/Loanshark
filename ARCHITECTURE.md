# LoanShark — architecture for approval

Status: proposed design, not an implementation. No application files have been created or overwritten. This document is the approval checkpoint requested in the project brief.

Product name: **LoanShark**. “CampusAgent” is treated as the architectural brief's working title, not a product rename. Keep the existing GitHub repository and README. Implement the package at the repository root rather than nesting a second `lend/` repository.

## 1. Inspection and recommended architecture

The `ssrid111/Loanshark` repository currently contains only `README.md`, at commit `cc203ba1e61568bb33dcfc68f1d32bf426107027`. No application code, dependencies, tests, migration history, or repository-specific agent instructions were found.

Available environment: system Python 3.9.6 and a bundled Python 3.12.14. Use 3.12.14 in a project virtual environment; do not use system Python. The bundled environment has Pydantic 2.14.1, but the other requested libraries are absent. Docker and PostgreSQL clients are installed; Docker's daemon is not running and the default PostgreSQL socket is not responding. This is not evidence that no database exists elsewhere. No Discord or Claude credentials were inspected or requested in chat.

Use a **modular monolith**: one Python application, one PostgreSQL database, one Discord bot, and one in-process durable-job poller. FastAPI lifespan starts and stops the bot and poller. Run one application worker; hot reload must not start duplicate gateway clients. Database leases protect jobs against restart overlap. Modules communicate through typed domain commands and results, not HTTP calls or a distributed message broker.

Each student has one logical personal agent, instantiated with an immutable authenticated student context. Its decisions are deterministic: item compatibility, opt-in, lending policy, availability, and return constraints. A group agent routes approved requests and tracks coordination state. Agents really exchange proposals and counteroffers through the privacy interface; there is no prewritten success dialogue.

Use SQLAlchemy 2.x async sessions, one session per independent task/transaction. Use Alembic as the schema source of truth; any `schema.sql` is a generated reference, not a second manually maintained schema. PostgreSQL transactions, row locks, constraints, and durable jobs enforce outcomes even if messages arrive twice or the LLM is unavailable.

Optional Claude parsing can extract intent and fields from the current request only. It cannot approve actions, select identities, issue SQL, inspect private inventory, create arbitrary outbound actions, or decide policy exceptions. The deterministic parser and structured Discord commands remain a complete path with no paid API dependency.

## 2. Complete proposed structure

Every Python package includes `__init__.py` (omitted below). Names retain the submitted layout where practical, with repositories and typed boundaries added.

```text
Loanshark/
├── README.md                         # existing; update only after approved implementation
├── ARCHITECTURE.md                    # this approval document
├── requirements.txt                  # exact resolved runtime pins
├── requirements-dev.txt              # exact test pins
├── requirements-llm.txt               # optional exact Claude pins
├── pyproject.toml                     # Python requirement and pytest configuration
├── .env.example                      # placeholder names only
├── .gitignore                        # .env*, venv, caches, logs; allow .env.example
├── compose.yaml                      # one local PostgreSQL service, no public DB exposure
├── main.py                           # app factory and single-worker entrypoint
├── config.py                         # Pydantic Settings; fail closed on bad config
├── core/
│   ├── events.py                     # discriminated Event/Action models
│   ├── router.py                     # dispatch, deduplication, unit of work
│   ├── confirm.py                    # recipient-bound, expiring consent challenges
│   ├── audit.py                      # allowlisted append-only events
│   ├── clock.py                      # injectable Clock and FakeClock
│   ├── errors.py                     # safe errors, no raw objects in replies
│   └── outbox.py                     # durable delivery, retry and cancellation
├── agents/
│   ├── personal.py                   # owner-scoped policy decisions
│   ├── group.py                      # orchestration only
│   └── guard.py                      # cross-agent availability boundary
├── borrowing/
│   ├── parser.py                     # deterministic detection and extraction
│   ├── models.py                     # typed commands, safe results and state enums
│   ├── matcher.py                    # opted-in candidate orchestration/ranking
│   ├── conflicts.py                  # locks, counteroffers, winner selection
│   ├── handoff.py                    # approved campus locations and time intersections
│   └── loans.py                      # lifecycle and return confirmation
├── lostfound/
│   ├── reports.py                    # separate public description/private identifiers
│   ├── matcher.py                    # type, place, time matching
│   └── claim_check.py                # limited attempts; never reveals expected answer
├── ladder/
│   ├── ladder.py                     # consent-gated escalation states
│   ├── timeouts.py                   # clock-based budgets; cancel stale rungs
│   └── campus_sources.json           # empty until one campus is named and verified
├── reliability/
│   └── score.py                      # deferred, not used for MVP decisions
├── llm/
│   ├── client.py                     # timeout, budget and disabled-by-default adapter
│   ├── schemas.py                    # strict parsed-request schema
│   └── prompts/
│       ├── parse_request.txt
│       ├── write_dm.txt              # optional later; safe templates in MVP
│       └── score_match.txt           # explanation only; never authorizes/ranks loans
├── adapters/
│   ├── base.py                      # normalized input/output contracts
│   ├── discord_adapter.py           # implemented first, real gateway and interactions
│   ├── console_adapter.py           # real core demo without Discord credentials
│   └── README.md                    # Slack/Telegram/SMS/WhatsApp deferred explicitly
├── api/
│   ├── routes.py                    # health + optional authenticated private API
│   ├── auth.py                      # token digest -> actor; never trust body actor IDs
│   └── schemas.py                   # output allowlists, not ORM serialization
├── db/
│   ├── connection.py                # engine/session factory and roles
│   ├── models.py                    # ORM metadata
│   ├── unit_of_work.py              # transaction boundary
│   ├── schema.sql                   # generated schema reference after migration
│   ├── seed.py                      # explicit demo-only four fake students
│   ├── repositories/
│   │   ├── students.py
│   │   ├── private.py               # owner-scoped inventory/schedule/policy
│   │   ├── requests.py
│   │   ├── loans.py
│   │   ├── reports.py
│   │   └── coordination.py          # offers, consent, audit, outbox, jobs
│   └── migrations/                  # reviewed Alembic revisions
├── alembic.ini
├── scheduler/jobs.py                # persistent reminder/recheck/overdue job handlers
├── tests/
│   ├── conftest.py                  # PostgreSQL isolation, fake clock, fake transport
│   ├── test_guard_no_leaks.py
│   ├── test_parser.py               # >=20 positive/negative/ambiguous messages
│   ├── test_conflicts.py
│   ├── test_lostfound.py
│   ├── test_confirmations.py
│   ├── test_workflows.py
│   ├── test_idempotency.py
│   ├── test_jobs.py
│   └── test_api_auth.py
└── demo/
    ├── script.md                    # live 90-second flow + longer conflict run
    └── architecture.mmd             # versionable Mermaid; render PNG if useful
```

Do not add dummy platform integrations that imply functionality. Add each future adapter only with a working integration and tests. A diagram can start as Mermaid rather than an unverified PNG.

## 3. Domain model and database schema

All internal IDs are UUIDs. Store timestamps as timezone-aware UTC `timestamptz`; display in the student's chosen timezone. Platform IDs are strings, not guessed integer widths. Foreign keys, state CHECK constraints, positive-duration checks and indexes accompany the fields below. Prefer explicit text enums with CHECK constraints for approachable migrations.

| Table | Main fields and constraints |
| --- | --- |
| `users` | id, platform, platform_user_id UNIQUE per platform, timezone, paused_lending, consent_version, joined_at, inactive_at |
| `communities` / `memberships` | platform guild/channel mapping; UNIQUE community/user; opt-in and verified membership state; no inference that sharing a server means friendship |
| `trusted_contacts` | owner_id, approved_contact_id, community_id; owner-controlled allowlist for “known people only” |
| `inventory` | id, owner_id, canonical_item, subtype, active, policy_id, version; one physical object per row |
| `lending_policies` | owner_id, same_day_only, max_duration_minutes, known_contacts_only, earliest_return/latest_return constraints |
| `schedule_blocks` | owner_id, start_at, end_at, private location label; end > start; no course title needed |
| `availability_windows` | owner_id, safe pickup-zone ID, start/end; explicitly provided lending availability, not inferred from every calendar gap |
| `requests` | borrower_id, community_id, item/subtype, need_by, proposed_return_at, safe pickup zones, status, scope_version, created_at; publish/forward consent reference |
| `offers` | request_id, lender_id, opaque item reference, proposed handoff/return window, status, version, expires_at; never serialized to group chat |
| `confirmations` | id, action kind, resource/version, subject actor, payload digest, token digest, expiry, consumed_at, decision; every confirmation binds exact terms |
| `reservations` | item_id, request_id, offer_id, held_at, hold_expires_at, released_at; partial UNIQUE item_id WHERE released_at IS NULL |
| `handoff_receipts` | reservation/loan reference, actor_id, direction (outbound/return), terms_version, confirmed_at; UNIQUE actor/resource/direction/version |
| `loans` | reservation_id UNIQUE, borrower/lender/item IDs, start_at, due_at, closed_at, status, lender_return_confirmation_id |
| `lost_reports` | owner_id, community_id, item, last-seen zone/time range, status; identifying answers in separately protected fields |
| `found_reports` | finder_id, community_id, public description, zone/time, encrypted hidden details, server-generated neutral verification prompt, status |
| `claim_attempts` | claim_id, claimant_id, found_report_id, attempts, verdict, verified_at; no raw answer in audit; max attempts and expiry |
| `recovery_handoffs` | report pair, parties, approved terms, both-party receipts, status; separate from borrowing loans |
| `processed_events` | adapter + platform_event_id UNIQUE, result reference; replay returns original result |
| `outbox` | id, action_type, minimal payload, destination scope, consent/version reference, dedupe_key UNIQUE, status, attempt count, retry_at |
| `jobs` | kind, resource_id, resource_version, run_at, lease_until, attempts, status, dedupe_key UNIQUE |
| `api_tokens` | optional private API: user_id, token_digest UNIQUE, scopes, expiry/revocation; raw token delivered once privately |
| `audit_log` | id, event_type, actor reference, resource reference, confirmation reference, correlation_id, safe before/after states, created_at; no raw message/body/secret fields |
| `reliability` | deferred; private user summary only if later approved; not a public score or lender warning |

Store private hidden identifiers encrypted using an environment-provided key; normalize and verify the supplied distinguishing answer inside the protected claim service. Do not use raw low-entropy answer hashes as public proof, and do not provide the expected answer in a question. MVP limits one clear text distinguishing trait; ambiguous identifiers require manual confirmation rather than LLM “ownership” judgments.

### State transitions and atomicity

- Request: `DRAFT -> AWAITING_SCOPE_CONFIRMATION -> OPEN -> RESERVED -> FULFILLED`; alternatives `CANCELLED`, `EXPIRED`, `UNMATCHED`.
- Offer: `PENDING_OWNER -> OWNER_ACCEPTED -> AWAITING_BORROWER -> RESERVED`; alternatives `DECLINED`, `EXPIRED`, `WITHDRAWN`, `RELEASED`. Changed terms increment the version and invalidate old confirmations.
- Reservation: holds the item after both parties accept exact terms; does not claim a physical handoff. Both outgoing handoff receipts activate a `loan`. Release an expired/no-show reservation transactionally.
- Loan: `ACTIVE -> RETURN_REPORTED -> CLOSED`; borrower reporting return alone cannot close it. `OVERDUE` is derived from the clock and due_at, not a competing lifecycle that breaks return handling. Only lender receipt confirmation closes the loan and releases the item.
- Recovery: `CANDIDATE -> CLAIM_CHECK_PENDING -> CLAIM_PASSED -> TERMS_CONFIRMED -> HANDED_OVER -> RESOLVED`; reject/expire without revealing secrets. Passing a question is not proof by itself; finder must confirm release and both confirm completion.

During reservation lock the item, request, and candidate offer in a consistent order. Revalidate policies, event version, time, membership, and both consents. Create reservation, mark request reserved, release other offers, append audit records, and enqueue notices in the same transaction. The unique active-item reservation is the last line of defense. There is no “check then insert” outside a transaction. In MVP one physical item supports only one current reservation/loan; future overlapping bookings are deferred.

For waiting conflicts rank eligible requests by `need_by ASC`, then most-recent borrowing timestamp ASC (never borrowed first), then created_at and ID. Compare only pending requests; do not revoke a completed agreement for a newer request. “First yes wins” means the first fully confirmed eligible reservation transaction, not the first lender's unilateral click. Explain this distinction in the UI.

The application runtime role can INSERT/SELECT but cannot UPDATE/DELETE `audit_log`; a trigger also rejects mutation. Migrations use separate credentials. This gives application-level append-only behavior, not immunity from a database administrator. Jobs use `FOR UPDATE SKIP LOCKED` and leases; recheck state and version before delivery. Discord delivery is at-least-once under uncertain network outcomes, not an impossible exactly-once guarantee. Domain state changes remain idempotent; track message IDs where returned.

## 4. API endpoints and Discord commands

### Discord is the primary authenticated interface

Identity comes from the Discord gateway's authenticated interaction author. Ignore actor IDs in text, buttons, and LLM output. Verify guild membership and active registration on every action. Use ephemeral replies for private command responses and DMs only to explicitly enrolled, opted-in participants. If DMs are blocked, keep the action pending and offer a private command; never fall back to a public channel.

| Command | Behavior |
| --- | --- |
| `/join` | privacy explanation, explicit accept, personal agent registration; optional DM opt-in |
| `/inventory add`, `/inventory list`, `/inventory remove` | private item and policy management; refuse deletion of an active loan object |
| `/availability add`, `/availability remove`, `/schedule add` | private handoff availability and busy blocks; no calendar integration required |
| `/lending pause`, `/lending resume`, `/trusted add`, `/trusted remove` | owner-only policy controls |
| `/borrow` | structured request or natural-language text; preview and confirm scope before forwarding |
| `/requests`, `/loans` | private, actor-scoped status |
| `/offer respond`, `/confirm`, `/handoff confirm`, `/return report`, `/return confirm` | exact-version, recipient-bound state transitions; buttons are equivalent adapters |
| `/lost`, `/found`, `/claim` | private intake, separate consent for a public description, private claim challenge |
| `/recover confirm` | confirm recovery terms/handoff and resolution |
| `/request cancel`, `/ladder next` | cancel or explicitly approve a wider scope |
| `/privacy`, `/audit mine` | explain sharing and show safe own-action history |

Natural messages in an allowlisted test channel can become draft requests after high-confidence parsing. They cannot initiate forwarding or public posting under a student's name without approval. Ignore bots and routine conversation. Follow-ups and request previews should be ephemeral or private; after approval post only a generic bot status, not a second inventory-bearing message. Clear “need a calc for my 2pm” becomes a draft; missing return time, timezone, subtype or place is clarified one question at a time.

### FastAPI surface

`GET /health/live` exposes process health. `GET /health/ready` verifies DB/migrations and adapter readiness using safe booleans, with no tokens, connection strings, or student information. Bind to loopback by default. No generic “act as user” endpoint.

The following private REST endpoints are planned for service integration and optional local demo use. They remain disabled unless private API mode is explicitly enabled. After authenticated Discord enrollment, `/api-token` privately issues a random short-lived owner token; store only its digest. Each route resolves the actor from its token, enforces ownership/membership, validates strict input, and requires an idempotency key for mutations. HTTP never accepts a Discord user ID as identity proof. Discord commands call services directly, not these endpoints.

| Method and path | Purpose |
| --- | --- |
| `GET/PATCH /v1/me` | own profile, timezone and lending pause |
| `GET/POST /v1/me/inventory`, `PATCH/DELETE /v1/me/inventory/{id}` | own inventory |
| `GET/POST /v1/me/availability`, `DELETE /v1/me/availability/{id}` | own availability |
| `GET/POST /v1/me/schedule`, `DELETE /v1/me/schedule/{id}` | own busy blocks |
| `POST /v1/requests`, `GET /v1/requests/{id}`, `POST /v1/requests/{id}/cancel` | draft, own/authorized status, cancellation |
| `POST /v1/confirmations/{id}/respond` | consume exact scoped confirmation |
| `POST /v1/offers/{id}/respond` | authorized recipient response |
| `POST /v1/handoffs/{id}/confirm` | participant confirms physical handoff |
| `GET /v1/me/loans`, `POST /v1/loans/{id}/return`, `POST /v1/loans/{id}/close` | private lifecycle; close is lender only |
| `POST /v1/lost`, `POST /v1/found`, `GET /v1/me/reports` | report intake and own reports |
| `POST /v1/claims`, `POST /v1/claims/{id}/answer` | generic claim attempt responses; claimant never gets hidden fields |
| `POST /v1/recoveries/{id}/confirm` | participant-bound approval/completion |
| `POST /v1/requests/{id}/escalate` | new scoped confirmation, not automatic escalation |
| `GET /v1/me/audit` | own allowlisted audit projection |

No cross-student inventory, raw schedule, hidden-report, confirmation-token list, global audit, or unauthenticated mutation endpoint. Defer optional REST mutations if they would compromise the 24-hour core.

## 5. Safe personal-agent communication

1. Adapter produces a typed Event with authenticated actor, origin, server timestamp, community, event ID and bounded input text. Router rejects unknown fields and duplicates.
2. Confirmed scope becomes a sanitized `BorrowRequest`. No schedule or inventory data is included.
3. Group agent enumerates only enrolled, opted-in members of that approved community, excluding requester and blocked contacts. It does not query their assets.
4. Guard invokes an owner-scoped personal agent per candidate. That agent reads its own repository through its immutable owner context. Only the guard may initiate cross-student evaluations; private self-service inventory management is not banned.
5. Before owner approval, the guard returns only `can_help: bool`. It internally creates an opaque owner-routed proposal; the group agent does not receive the lender's name, matching item, count, reasons, or raw constraints. Unavailability has one generic response.
6. Lender sees a private request only after requester confirms disclosure of their identity and need to eligible opted-in members. The lender approves a specific item and terms. Schedule-derived safe meeting options remain private until both authorize sharing those options.
7. After approval a strict output model allows `can_help`, `place`, `window_start`, `window_end` only. Correlation and routing use server-internal capability IDs rather than extra identifying output fields. Guard results cannot be serialized from ORM models or arbitrary dicts.
8. Deterministic services negotiate shortened returns or alternative safe windows and request fresh approvals. Reservations commit atomically. Both people confirm the physical exchange.

Use fixed public campus meeting zones and overlapping explicitly supplied availability in MVP. “Between two routes” is approximated by an approved shared zone and optional walking buffer; no live tracking, exact GPS or external routing service. If there is no known feasible intersection, ask or move to the next candidate rather than invent travel times.

This is application-level isolation in one trusted process, not a sandbox against malicious Python code or administrators. Import-boundary checks, owner-scoped repository tests, output-schema tests and end-to-end leak tests reduce specific risks; no single test proves all possible information leakage is impossible. A boolean availability response can itself reveal limited information, so restrict recipients, rate-limit probing and avoid publishing per-person results.

## 6. Privacy threat model and required tests

| Threat | Enforcement | Evidence required |
| --- | --- | --- |
| Unauthorized direct reads / guessed IDs | immutable actor context, owner-filtered queries, deny-by-default community membership, no public object serializers | student A cannot read/edit B's items, schedules, reports, tokens or audits through every entry point |
| Inventories/schedules leaking through text, errors or logs | strict outbound DTOs and templates; no private context to LLM; allowlisted audit metadata; internal exception redaction | seeded distinctive canary strings never appear in unauthorized group/private output, API errors, prompts, or audit logs |
| Availability-probing inference | consented community scope, uniform no-match replies, rate limits, no per-person public results | repeated probes are throttled; pauses and missing inventory look the same externally |
| Forged, replayed or stale confirmation | random token digest; bound recipient, action, terms digest/version and expiry; single-use transaction | wrong actor, changed terms, expired token and replay cannot progress state |
| Duplicate events / simultaneous accepts | event uniqueness, request/item locks, active reservation uniqueness, outbox dedupe | concurrent PostgreSQL tests yield one reservation; replay returns the same result and no extra consent |
| Malicious prompt or LLM output | bounded input; strict Pydantic schema, canonical item vocabulary, deterministic policy and time validation | injected “approve for everyone” cannot authorize, reveal data, trigger URLs, or create unknown actions |
| Malicious URLs / private downloads | no automatic URL fetching for user messages; verified campus sources allowlisted | no arbitrary fetch, SSRF, shell execution or secrets in prompt |
| Wrong lost-item claims | hidden details protected, generic questions, answer attempt limits, finder approval, no private error differences | wrong answer and brute force fail; expected answer absent from group text/logs; passed claim alone cannot resolve report |
| Stale scheduled action | jobs bound to resource/version, revalidate membership/consent/status at dispatch | cancelled/closed loans get no obsolete reminder; repeated poll/restart is harmless |
| Stranger contact / consent withdrawal | opt-in membership and scoped consent checked again before delivery; cancel pending outbox on revocation | no DM to unregistered users or after revocation; blocked DM does not become public |
| Audit alteration | dedicated runtime DB role, INSERT-only permissions and mutation-rejecting trigger | runtime UPDATE/DELETE rejected; migrations retain separate authority |
| Sensitive data in Git / artifacts | fake seeds; ignored .env; no request text in demo audit export | inspect staged diff and repository scan before every push |

## 7. Milestones and acceptance criteria

These are a 24-hour engineering budget, not a promise that every stretch feature fits. Implement and review in order; do not proceed past broken authorization or transaction tests.

| Milestone | Hours | Deliverable and acceptance |
| --- | --- | --- |
| M0 — approved design and setup | 0–2 | Architecture accepted, isolated Python 3.12 env, pinned installation and `pip check`, reachable test PostgreSQL, migrations apply to empty DB; secrets ignored. |
| M1 — identity, private data and guard | 2–5 | four fake students; owner-only inventory/policy/availability; join/pause; boolean-only unapproved availability; cross-owner negative tests pass. |
| M2 — real borrow negotiation | 5–10 | full request -> private lender offer -> counteroffer -> mutual terms -> reservation -> two handoff receipts -> active loan; concurrent competing accepts yield one winner. |
| M3 — Discord vertical slice | 10–14 | bot works in one real test server; slash commands and private interaction buttons; natural request detection ignores casual chat; identities cannot be supplied in input; blocked-DM path demonstrated. |
| M4 — durable lifecycle | 14–17 | persistent return/recheck/overdue jobs; fake-clock tests; restart does not lose a reminder; borrower cannot close alone; lender closes and releases asset. |
| M5 — lost-and-found | 17–20 | text-only report matching, hidden trait challenge, wrong claim rejection, attempt cap and mutual recovery handoff; no leaked identifiers. |
| M6 — hardening and demo | 20–24 | end-to-end and transaction/leak suite pass on PostgreSQL; two real Discord participants complete a loan; actual failures recorded; 90-second demo rehearsed; setup verified from a clean environment. |

Optional parsing, the wider solution ladder and private REST mutations come after the acceptance gates above. Do not replace a failed real workflow with mocked success to meet a demo deadline. In-memory fake transport is for deterministic tests; the demo must identify whether it uses console delivery or real Discord.

## 8. Dependencies and manual setup

A Python 3.12 resolver dry-run succeeded for this set on the current Mac. This verifies dependency metadata compatibility, not runtime behavior, security review, or Linux deployment. No packages were installed into the shared Python environment. After approval, create a project venv, install exact pins with transitive locks, run `pip check`, and smoke-test imports and migrations. Commit the resolved lock; separate optional LLM/test dependencies.

| Dependency | Proposed exact version | Purpose |
| --- | --- | --- |
| FastAPI | 0.162.0 | health/API and lifespan |
| uvicorn | 0.54.0 | ASGI server |
| discord.py | 2.7.1 | Discord gateway/interactions |
| SQLAlchemy[asyncio] | 2.0.55 | typed persistence/transactions |
| Alembic | 1.20.1 | reviewed migrations |
| asyncpg | 0.32.0 | PostgreSQL async driver |
| Pydantic | 2.14.1 | boundary validation |
| pydantic-settings | 2.16.1 | environment configuration |
| cryptography | 50.0.2 | hidden-report encryption |
| pytest | 9.1.1 | tests |
| pytest-asyncio | 1.4.0 | async tests |
| httpx | 0.28.1 | API tests |
| anthropic (optional) | 0.125.0 | language extraction only |

Propose PostgreSQL 17 for the local demo (supported and sufficient). Resolve an exact supported patch/container digest at implementation time, record it, and use that same major for tests. Do not depend on SQLite for concurrency tests.

### Environment names (placeholders only)

- `DATABASE_URL`: runtime-role PostgreSQL URL; never log it.
- `MIGRATION_DATABASE_URL`: separate migration-role URL, not exposed to the runtime process after migrations.
- `TEST_DATABASE_URL`: dedicated disposable PostgreSQL database; tests refuse a non-test name unless explicitly approved.
- `DISCORD_BOT_TOKEN`, `DISCORD_APPLICATION_ID`, `DISCORD_GUILD_ID`, `DISCORD_ALLOWED_CHANNEL_IDS`.
- `PRIVATE_DATA_KEY`: generated encryption key, stored outside Git; losing it makes encrypted identifiers unreadable.
- `ENABLE_DISCORD`, `ENABLE_PRIVATE_API=false`, `DEMO_MODE=false`, `DEFAULT_TIMEZONE=America/Phoenix` (configurable), `LOG_LEVEL`.
- `LLM_PROVIDER=none`; optional `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` selected from supported models when enabled, bounded timeout and token budget.

Keep `.env` local; collect credentials through environment or the provider's secure UI, never chat. One machine running the process and PostgreSQL is enough. No Redis, vector database, agent framework, hosted scheduler, payment account, or maps API required.

### Student/admin setup

1. Start Docker Desktop or provide an accessible PostgreSQL instance; create distinct migration/runtime/test credentials. An installed client alone is insufficient.
2. Create a Discord application and bot in the Developer Portal. Invite it into a private test server with only needed channel/message/application-command permissions; avoid Administrator permissions.
3. Enable Message Content intent in the portal and code only if passive natural-message detection is used. Slash commands still work without passive detection. Limit listening to allowlisted channels and do not request presence tracking.
4. Provide bot credentials locally, set allowed server/channel IDs, run migrations, seed fake demo users in a demo database, and start the single-worker application.
5. Have real test participants enroll and opt into private offers themselves; never impersonate them using seed users. Enable DMs or use ephemeral slash-command interactions.
6. Name one campus before adding resource links. Each source needs official URL, verified date, supported item/service, and any known limitations. Until then the ladder says no verified campus data is configured.

## 9. Realistic MVP and safe defaults

**Ship in 24 hours:** one Discord server, opted-in known participants, a small canonical item set (graphing/basic calculator, USB-C charger, umbrella), explicit safe pickup zones and availability, deterministic parsing plus structured commands, borrowing negotiation, real PostgreSQL state, mutual handoff confirmation, return reminders, one text-only lost-and-found challenge, audit trail and negative tests.

**Defer:** iMessage/WhatsApp/Slack/Telegram/Twilio, live maps or automatic calendar sync, report photos, multi-hop trades, weather offers, reliability scoring, public inventory recap, automatic purchases, campus-wide stranger discovery, and production-scale hosting. Other adapters are extension points, not enabled integrations. No purchases or financial activity in MVP.

Important ambiguities and proposed defaults:

- **Product name:** LoanShark, preserving the current repository; no “CampusAgent” rename.
- **Meaning of an agent:** logical owner-scoped autonomous policy evaluator. An LLM is optional; separate LLM calls do not create authorization boundaries.
- **Private reads:** agents read their owner's data; guard is the only cross-agent entry point. A group orchestrator never holds a general private repository/session.
- **Unknown deadlines:** ask; interpret “2 PM” in the confirmed student's timezone and clarify rollover. Never silently assume tomorrow or campus timezone.
- **Return time missing:** required clarification before offers. Same-day means the lender's configured timezone and local-day boundary.
- **Sharing names/meeting points:** requester approves eligible-audience disclosure; reveal a lender's identity and meeting details only for approved counterparties. Group gets generic statuses.
- **History fairness versus privacy:** use minimal coordinator borrowing timestamps privately for ties; no public score and no owner-only reliability score secretly shown to lenders.
- **Pause after an offer:** stop new offers and revalidate pending ones. Do not erase active loan obligations or send public explanations.
- **Changed plans:** revoke unfulfilled proposals and seek a new candidate with fresh consent; do not declare an already handed-over item available again.
- **“Nothing happens without yes”:** user-facing commitments/disclosures need scoped consent; parsing, private matching, internal audit, and already-approved return reminders do not need a new prompt every time. Identity checks still apply.
- **Shared versus public:** server coordination state is access-controlled. “The group agent tracks it” does not make it group-readable.
- **Data lifecycle:** no indefinite raw chat/audio retention; retain minimal transaction/consent records for the demo and define a production retention policy before public deployment. No real data in seeds or screenshots without consent.
- **Known users:** opt-in community membership alone does not satisfy known-contacts-only policies; require the lender's contact allowlist.

## 10. Demo with actual agent coordination

Use fake item data but real enrolled participants in a private Discord server. Run migrations and seed before recording. Prepare two eligible owners: one with a same-day-only calculator and one whose handoff availability misses the deadline. Keep one approved location and visible local timezone. Do not hide manual intervention.

### Main 90-second story

- **0–15 seconds:** Borrower requests a calculator before an exam, returning it tomorrow. Bot privately asks for missing details, previews sharing scope, and receives approval.
- **15–35 seconds:** Group agent asks each opted-in personal agent through the guard. One privately rejects the timing. The other determines that same-day return is possible and privately asks its owner to approve a counteroffer.
- **35–55 seconds:** Lender approves. Borrower accepts the shorter duration; both approve sharing the meeting proposal. Show the safe trace: requested -> evaluated -> counteroffered -> confirmed, without showing raw schedules.
- **55–70 seconds:** Both confirm the physical handoff. Database shows one active loan and its approved reminder. Do not describe a future reminder as delivered; demonstrate a separate labeled fake-clock run if needed.
- **70–90 seconds:** Borrower reports return; lender confirms receipt. Loan closes. Show the safe consent audit and the item's released state.

Record additional short runs for competing acceptances (one winner), wrong lost-item claim (rejected without the hidden answer), successful recovery, and private due/overdue reminders using the fake clock. The clock acceleration is test tooling, explicitly labeled. Real scheduling should also receive a short live delivery check.

Success means meaningful state changes survived real authorization, policy checks and database transactions—not that an LLM narrated a happy path.

## Official references consulted

- FastAPI deployment and server process: https://fastapi.tiangolo.com/deployment/manually/
- discord.py intents, including Message Content: https://discordpy.readthedocs.io/en/stable/intents.html
- Discord interactions and responses: https://docs.discord.com/developers/interactions/receiving-and-responding
- SQLAlchemy async sessions: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Alembic generated revisions require review: https://alembic.sqlalchemy.org/en/latest/autogenerate.html
- PostgreSQL row locks and skip-locked job patterns: https://www.postgresql.org/docs/current/explicit-locking.html
- Pydantic model validation: https://docs.pydantic.dev/latest/concepts/models/
- pytest fixtures: https://docs.pytest.org/en/stable/how-to/fixtures.html
- pytest-asyncio: https://pytest-asyncio.readthedocs.io/en/stable/
- Optional Claude structured outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs

## Approval requested

Approve the Discord-first modular monolith, PostgreSQL transaction model, guarded owner-scoped agents, exact confirmation rules, and 24-hour MVP above. After approval: implement M0–M6 incrementally, run the meaningful tests against PostgreSQL, and commit/push the working project to `ssrid111/Loanshark`. Do not overwrite the existing README until that implementation stage is approved. User credentials and any unavailable external setup remain separate prerequisites for live Discord verification.

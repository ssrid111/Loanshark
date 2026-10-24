# LoanShark

### Someone's got it. Your agent finds it.

LoanShark is a student borrowing and lost-and-found assistant built around a group agent and private personal agents. Ask for a calculator before an exam, find an umbrella before class, or reconnect a lost item with its owner—without posting everyone's belongings and schedules in a group chat.

Despite the name, LoanShark is about borrowing everyday items. It does not issue financial loans or move money.

> Project status: This README describes the proposed prototype and acceptance criteria. Implementation, supported messaging platforms, and real-user testing are not yet verified.

## The problem

Student group chats already contain the people who might help. Finding the right person still means sending messages, repeating details, negotiating pickup, and remembering the return.

LoanShark turns “does anyone have one?” into a coordinated request. Personal agents check whether their students can help, negotiate compatible conditions, and ask the people involved to approve the arrangement.

## How it works

1. **Join privately.** A student uses `/join` to create a personal agent and learn what information can be shared.
2. **Set lending preferences.** Add items, availability, and conditions such as same-day returns or lending only to known people. Pause lending at any time.
3. **Ask naturally.** Post a request such as “Need a graphing calculator before 2 PM near the library.”
4. **Let agents coordinate.** The group agent routes the request. Personal agents check compatibility, willingness, timing, and return conditions.
5. **Approve the arrangement.** A qualifying lender receives a private offer. Both students approve any meeting details before they are shared and confirm the handoff before the loan becomes active.
6. **Return and close.** Private reminders track the agreed return time. The lender confirms receipt to close the loan.

## Example interaction

*Illustrative flow, not a recorded test.*

**Group chat**

> Maya: Need a graphing calculator for my 2 PM exam near the library.
>
> LoanShark: On it—checking with opted-in members.

**Private message to a potential lender**

> LoanShark: Maya needs a graphing calculator until 4 PM. Your lending conditions fit. Interested?
>
> Jay: Yes.

**Private coordination**

> LoanShark: Library entrance at 1:30 PM, return by 4 PM. Approve sharing this proposal with Maya?

The borrower and lender review the proposal privately. An offer is not a reservation, and a proposed meeting is not a completed handoff.

## Two kinds of agents

### The group agent

- Recognizes borrowing and lost-and-found requests while ignoring ordinary conversation.
- Extracts the item, subtype, deadline, and location.
- Asks one short follow-up when essential information is missing.
- Coordinates requests and keeps public updates brief and non-identifying.
- Maintains minimal coordination records rather than private inventories or raw schedules.

### Each student's personal agent

- Represents that student's inventory, availability, and lending preferences.
- Independently decides whether a request is compatible.
- Returns only an approved availability result and, when authorized, a proposed meeting place and time window.
- Presents offers privately: accept, decline for now, or decline future requests from that person. Use buttons only where the selected platform supports them.
- Requests approval before making commitments or sharing personal details.

## Negotiation, not just matching

| Situation | Proposed behavior |
| --- | --- |
| Two borrowers need the same item | Prioritize the earlier deadline, then the student who has borrowed less recently; explain the outcome without exposing another student's private circumstances. |
| A lender cannot meet the deadline | Remove that candidate and check the next compatible option. |
| A borrower requests three days; the lender permits same-day use | Present the shorter loan as a counteroffer and wait for acceptance. |
| Several lenders accept | Reserve the first fully confirmed arrangement atomically and release the other offers without revealing who else was contacted. |
| A lender's availability changes | Re-check planned availability 30 minutes before handoff when possible, warn affected students privately, and seek approval for a replacement arrangement. |

No match overrides a lender's conditions or either person's right to decline.

## Lost and found

Lost reports capture the item, last-seen location and time, and identifying characteristics. Found reports separate a general description from hidden details such as initials, stickers, or damage.

Agents compare likely matches and privately ask the claimant for a distinguishing detail. Verification questions must not reveal the expected answer. A match remains a candidate until the people involved approve the claim and handoff; a plausible answer is evidence, not guaranteed proof of ownership.

Photos and automatic re-checking of unmatched reports are planned extensions. Hidden identifiers and verification answers must stay out of group messages and public records.

## Privacy and consent

- Private inventories and raw schedules stay within each student's protected agent context.
- A single controlled privacy interface mediates cross-agent requests and returns only permitted results. Other agents cannot directly inspect private records.
- Coordination records contain only the fields needed for routing and status. They are access-controlled; they are not a public group feed.
- Ask before forwarding a request on someone's behalf, widening its audience, sharing a meeting point, publishing under a student's name, or presenting a purchase option.
- An explicit borrowing request authorizes handling that request within its stated scope; it does not authorize contacting additional groups or disclosing private information.
- Both students confirm the handoff. The lender confirms the return. Found-item resolution also requires confirmation.
- Overdue reminders are private. No public shaming, unsolicited messages to strangers, or money transfers.
- Record consent and state changes in an access-controlled audit log without copying raw schedules, hidden identifiers, or unnecessary personal details.

Platform storage, deletion, identity checks, and access controls must be documented and verified before real deployment.

## When nobody has the item

The planned solution ladder expands only with permission:

1. Check opted-in friends in the current group.
2. Ask to widen the request to an appropriate dorm, class, or club group.
3. Consult verified lending resources for a specifically supported campus.
4. Offer a purchase or rental link with approval; the student handles payment.
5. Suggest a clearly labeled workaround that the student must confirm is permitted.

Search time should reflect urgency. Never invent opening hours, stock, campus policies, or permission to use substitute equipment. If information cannot be verified, say so.

## Prototype scope

### Core

- [ ] One messaging-platform integration with group and private conversations.
- [ ] Private onboarding, inventory, lending conditions, availability, and pause controls.
- [ ] Borrowing request detection and clarification.
- [ ] Privacy-controlled agent negotiation and counteroffers.
- [ ] Mutual handoff confirmation and loan state tracking.
- [ ] Return reminders, private overdue nudges, and lender-confirmed closure.
- [ ] Lost-and-found matching with private claim verification.
- [ ] Consent audit trail and privacy tests.

### Extensions

- [ ] Found-item photos and re-matching of open reports.
- [ ] Consent-based expansion to additional groups.
- [ ] Verified campus resource directory.
- [ ] Opt-in, non-identifying community recaps.
- [ ] Weather-triggered umbrella offers.

The notes identify iMessage, WhatsApp, Discord, Slack, and Android messaging as possible surfaces. This is not a claim of integration with all of them. Choose and document one supported platform for the prototype.

## Architecture

```text
Group conversation
        |
    Group agent
        |
Controlled privacy interface
        |
Student A agent <--> Student B agent <--> Student C agent
        |
Private approval requests to the respective students
        |
Confirmed arrangement -> loan tracking -> return confirmation
```

The interface restricts what may be exchanged; each personal agent makes decisions using its own private context. Negotiation shares approved proposals rather than entire inventories or calendars.

## Demo and acceptance checks

1. Complete a borrowing flow with real participants: request, private offer, approved meeting, confirmed handoff, reminder, and return confirmation.
2. Exercise competing borrowers, incompatible return windows, unreachable lenders, multiple acceptances, and changed availability.
3. Demonstrate a lost-item match and a failed ownership claim without leaking the hidden answer.
4. Attempt to expose inventory, schedules, and hidden identifiers through group messages, direct cross-agent requests, error messages, and logs.
5. Verify that declined or missing consent prevents the corresponding action.
6. Verify that simultaneous confirmations cannot create two active loans for the same item.

Record actual results before presenting any of these checks as passed.

## Running the project

The supplied specification does not include application code, a selected framework, credentials configuration, or an executable entry point. No installation commands are claimed here. Add verified setup instructions alongside the chosen implementation.

## Hackathon fit

LoanShark is designed around Track 2's agent-to-agent coordination: agents represent different students, negotiate conflicting constraints, limit what they share, and ask humans before commitments. The group-facing interface also relates to Track 3, but entry in either track requires a Track 1 submission first.

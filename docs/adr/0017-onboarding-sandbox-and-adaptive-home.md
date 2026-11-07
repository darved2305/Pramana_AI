# 0017: Onboarding: the three questions, sandbox organizations, the adaptive home

**Status:** proposed

**Amends:** none directly. It turns the simulator (ADR 0006's verification world and the demo
scenarios) into a product feature, so the README's rule that simulated screens are labelled
applies to every sandbox screen.

**Context.** PRODUCTION.md §7. A new account today lands on a console for one demo hostel. A
customer needs to see value before modelling their own building, and modelling is the expensive
step (PRODUCT §36). The demo already shows the value: a sealed fault, the right person asked,
an approval, a verified repair, an exact replay.

**Options compared.**

| Option | For | Against |
|---|---|---|
| Empty workspace plus documentation | Simple | A blank screen; time to value is the time to model a building |
| A long setup wizard before anything works | Complete data | People leave before the value; most answers would change nothing |
| **Three questions, an automatic organization and sandbox, a guided sandbox run, then "your building"** | Value in minutes; each answer changes the next screen | We maintain the sandbox as product code |

**Decision.**
- Three skippable questions (role; building kind and count; what breaks most and which
  languages). Each answer changes something visible (§7.3); a question that changes nothing is
  dropped. Answers live in `onboarding_state.answers`, validated by a versioned contract.
- `POST /v1/orgs` (idempotent) creates the organization, the owner membership, a sandbox site
  pinned to the stored `campus_block_c` model (`mode='sandbox'`), and a draft live site of the
  chosen kind.
- The guided run: the person plays the reporter, simulated colleagues answer and are labelled
  simulated, a simulated approver approves (separation of duties is shown, not hidden), then the
  reveal and a four-line "What just happened".
- `GET /v1/me` decides where a person lands, by the ordered rules in §6.1; the server applies
  the same rules to deep links.
- The home is an ordered list of modules from a pure, unit-tested rules function, each with a
  `reason` string. Pins and hides (and checklist dismissal) live in
  `user_preferences.home_layout` and always win.
- The setup checklist is server-side and marks items done from real data, never from a click.

**Consequences.** The simulator becomes an always-on dependency of onboarding, so its state must
persist by default (ARCHITECTURE_REVIEW item 5). Sandbox and live data never mix: a `mode`
column, sandbox excluded from live metrics. The "under 3 minutes to the reveal" target needs
usability sessions with people; bots cannot measure it.

**Tests.** OR-09 and OR-10 (one organization per press, two tabs), DA-01, DA-05 and DA-06; unit
tests of the `/v1/me` routing rules and of the home rules function; a browser test of the guided
sandbox run that ends in a correct reveal and an identical replay.

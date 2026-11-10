# Demo runbook, evidence, and recording templates

## What the current evidence shows

The current reproducible walkthrough is a local text-mode S1 run against the core and simulator.
It uses the simulated campus pack and participant cards, a synthetic local approver-only account,
and no Gnani key, live provider, real participant, browser account, or real building. Its generated
timeline and summary are committed at:

- [S1 timeline](../eval/reports/demo-rehearsal-2026-11-10-s1/timeline.txt)
- [S1 generated summary](../eval/reports/demo-rehearsal-2026-11-10-s1/summary.json)
- [Rehearsal notes](../eval/reports/demo-rehearsal-2026-11-10-s1/NOTES.md)

This run reached a repair decision, used a separate approver-only local session, verified the
simulated repair, revealed the simulated fault against the published commitment, and reproduced
the event state in replay. It is evidence of the local workflow, not of human voice quality, a
real-site result, or an official public demo. The recorded sequence, not the older storyboard,
defines what this run actually asked and showed.

Past live Gnani voice runs are summarized in
[VOICE_PROVENANCE.md](engineering/VOICE_PROVENANCE.md). Their participants and models are labelled
per run; they do not fill the public-video or native-language-review fields.

## 60-second cut: shot list

Use this as an edit plan for the committed local text run. Keep the simulated status visible and
caption any narration. A future human-recorded take must replace each shot with evidence from that
single take. The shot timing is an editing target, not a measured run or speech latency.

| Time | Shot | Show from the committed S1 run | On-screen disclosure |
|---|---|---|---|
| 0:00-0:05 | 01 | Introduce a physical Wi-Fi/power outage that people can observe locally. | `Simulated building` |
| 0:05-0:12 | 02 | Show investigation creation and the sealed commitment in the timeline. | `Local text rehearsal; simulator cards` |
| 0:12-0:25 | 03 | Show the three initial questions in flight: phone Wi-Fi, another phone's Wi-Fi, and the gateway light. Show the card answers that the timeline records. | `Synthetic participant cards; no live speech` |
| 0:25-0:34 | 04 | Show the breaker-position answer, then the decision to send an electrician to DB-C2. The generated timeline records `P = 0.974`. | `Decision from the recorded simulated answers` |
| 0:34-0:45 | 05 | Show the separate local approver ID, the simulated repair, and the held-out Wi-Fi verification answer. | `Synthetic approver account; simulated repair` |
| 0:45-0:55 | 06 | Show the reveal matching the commitment and the identical replay. The generated summary records 8 questions and 40 replayed events. | `Simulated truth revealed after verification` |
| 0:55-1:00 | 07 | End card with the project name and evidence links. | `Text-mode local rehearsal; not a human voice take` |

Source for every result in this cut: the committed [timeline](../eval/reports/demo-rehearsal-2026-11-10-s1/timeline.txt)
and [generated summary](../eval/reports/demo-rehearsal-2026-11-10-s1/summary.json). The summary
counts 8 questions, but the timeline prints 6 asks: the other 2 were asked and then withdrawn
after the decision (`corridor_lights` for p_mahesh and `room_socket` for p_riya). The timeline
file does not print them; the rehearsal database holds the 8 `QuestionAsked` and 2
`QuestionWithdrawn` events. Do not present the timeline as showing all 8. Do not replace
the observed gateway or breaker questions with the old CCTV storyboard. Do not add an accuracy,
latency, real-site, or frontier-LLM comparison card.

## Primary local walkthrough

### Rehearsal runbook

1. Read `README.md` section [Run it](../README.md#run-it). Use this worktree's own `.env` database.
The supervisor takes app ports as command-line options; it does not infer app ports from `.env`.
When this checkout's `.env` assigns `E2E_CORE_PORT`, `E2E_SIM_PORT`, `E2E_WEB_PORT`, and
`E2E_OIDC_PORT`, pass those local values to `--core-port`, `--sim-port`, `--web-port`, and
`--oidc-port`. Otherwise use the documented defaults only when they are free. Do not point the run
at a cloud database.
2. Start the local application stack. The standard demo command uses mock OIDC and disables the
   Gnani key:

   ```powershell
   uv run python scripts/dev.py --demo
   ```

   If using the defaults shown by `scripts/dev.py`, start with:

   ```powershell
   uv run python scripts/dev.py --demo --core-port 8000 --sim-port 8100 --web-port 3002 --oidc-port 8410
   ```

   If any are occupied or assigned elsewhere, choose isolated local ports and pass them to those
   flags. The stack must be local. Do not open a real Google or Microsoft sign-in page.
3. For S1, create a synthetic approver-only account in the same local database. Let the bootstrap
   prompt for a local password, then set the same values in the rehearsal terminal. Do not save
   them in source control:

   ```powershell
   uv run python -m pramana_core.auth.bootstrap --email approver@example.test --name "Demo approver" --roles approver
   $env:PRAMANA_APPROVER_EMAIL = "approver@example.test"
   $approverSecret = Read-Host "Local approver password" -AsSecureString
   $env:PRAMANA_APPROVER_PASSWORD = [System.Net.NetworkCredential]::new("", $approverSecret).Password
   ```

4. `scripts/demo_rehearse.py` uses the automation identity from this worktree's `.env` for the
   operator actions and validates that S1 approval comes from the separate approver-only session.
   Capture stdout as the timeline and write the generated rehearsal report under ignored `.cache`
   while rehearsing:

   ```powershell
   uv run python scripts/demo_rehearse.py --scenario S1 --seed 19 --core http://127.0.0.1:8000 --sim http://127.0.0.1:8100 --report .cache/demo-S1-summary.json *> .cache/demo-S1-timeline.txt
   ```

   Replace the service ports with the ones used by your local stack. The committed sample was run
   with seed 19 on 2026-11-10. Its summary is generated by the runner; do not edit it by hand.
5. S2 demonstrates a disagreement and S7 demonstrates a presence check. These commands use the
   same local core and simulator; they do not call Gnani:

   ```powershell
   uv run python scripts/demo_rehearse.py --scenario S2 --core http://127.0.0.1:8000 --sim http://127.0.0.1:8100 --report .cache/demo-S2-summary.json
   uv run python scripts/demo_rehearse.py --scenario S7 --variant adversary --core http://127.0.0.1:8000 --sim http://127.0.0.1:8100 --report .cache/demo-S7-adversary-summary.json
   uv run python scripts/demo_rehearse.py --scenario S7 --variant honest --core http://127.0.0.1:8000 --sim http://127.0.0.1:8100 --report .cache/demo-S7-honest-summary.json
   ```

   `presence_checks` is enabled for S7. The adversary stays at the guard desk and fails the label
   check; the honest participant reads the label from the participant's own simulator card. The
   recorded Nov 7 voice S7 variants abstained because the remaining useful panel question needed an
   electrician. A passed presence check is not a diagnosis.
6. **Pre-flight (`make preflight`).** Use this only for the configured local voice-readiness check.
   It does not check phone microphone permissions or measure voice latency. Do not add `--live` to
   this local rehearsal: it makes a provider request and spends Gnani credits. The primary
   walkthrough needs neither a live provider nor a live key.
7. Stop the local supervisor with Ctrl+C. Confirm its child services have stopped. Leave the shared
   PostgreSQL cluster running.

The public demo must be one working take. Keep the commitment and reveal in that same investigation,
label every simulated person/building and every time compression, and show what the app actually did.
The committed timeline is a preparation artifact, not a substitute for the human-recorded public
video.

## Offline voice fallback

When a voice-shaped flow is useful but no live Gnani key is available, use only an isolated local
run with the repository's protocol emulator. Put this exact label on screen and in narration:

> Gnani protocol emulator - synthetic audio and transcripts

The emulator's synthetic PCM carries its expected transcript; the server returns that text after a
fixed delay. Its TTS output is silence. It can show the integration path, consent, a streamed
question event, interruption handling, language/model/keyterm configuration, a decision-critical
second decode, deterministic replay, and tap or type recovery. It does not demonstrate Prisma
recognition, Timbre voice quality, accent handling, noise immunity, or Gnani latency. Do not put a
human voice through the emulator and label it recognition.

The emulator implementation is [`scripts/gnani_emulator.py`](../scripts/gnani_emulator.py). For an
offline judge walkthrough without a prepared voice fixture, use the primary text-mode rehearsal
above and say that it is text mode. Do not use the live provider preflight as a fallback.

## Take verification template

Fill one row per shot from the selected, single take. Use local log identifiers, not names, phone
numbers, or credentials. Mark unsupported shots `omit`; do not fill a blank from a planned script.

| Shot/time | Source take SHA and event/log IDs | Observed action and outcome | Speaker source and consent evidence | Synthetic label shown | Approver identity and role evidence | Keep or omit | Reviewer/status |
|---|---|---|---|---|---|---|---|
| 01 | [Fill: take SHA and log IDs] | [Fill: observed opening] | [Fill: source and consent record] | [Fill: exact disclosure] | Not applicable | [Fill] | Unchecked |
| 02 | [Fill: take SHA and log IDs] | [Fill: commitment creation] | [Fill: source and consent record] | [Fill: exact disclosure] | Not applicable | [Fill] | Unchecked |
| 03 | [Fill: take SHA and log IDs] | [Fill: questions and answers actually shown] | [Fill: one row per speaker and consent evidence] | [Fill: human or synthetic per speaker] | Not applicable | [Fill] | Unchecked |
| 04 | [Fill: take SHA and log IDs] | [Fill: decision actually reached] | [Fill: source and consent record] | [Fill: exact disclosure] | Not applicable | [Fill] | Unchecked |
| 05 | [Fill: take SHA and log IDs] | [Fill: approval, repair, and verification actually completed] | [Fill: source and consent record] | [Fill: exact disclosure] | [Fill: approver ID, role, and proof they differ from requester] | [Fill] | Unchecked |
| 06 | [Fill: take SHA and log IDs] | [Fill: reveal, commitment match, and replay result] | [Fill: source and consent record] | [Fill: exact disclosure] | Not applicable | [Fill] | Unchecked |
| 07 | [Fill: take SHA and log IDs] | [Fill: final card] | [Fill: source and consent record] | [Fill: exact disclosure] | Not applicable | [Fill] | Unchecked |

The generated rehearsal report and recorded take log are different artifacts. The first is a
machine-generated local summary; the second is a human recording with consent and a take-specific
log. The local committed rehearsal is automated and uses a synthetic approver account. Its
approval is not evidence of an independent human approver. The current run is not a consented
human recording.

## Captions template

Fill captions only from the audio and transcript for the selected take. A human reviewer checks
original-language Hindi and Marathi captions and faithful English subtitles. The current local text
timeline contains no recorded speech and cannot populate this sheet.

| Take SHA | Timecode | Speaker ID and source | Language | Exact original-language caption | Faithful English subtitle | Transcript/log ID | Native reviewer, date, status |
|---|---|---|---|---|---|---|---|
| [Fill] | [Fill] | [Fill: human or synthetic] | [Fill] | [Fill from selected take] | [Fill after translation review] | [Fill] | Unchecked |

Do not subtitle a scripted line that was not spoken, infer words from the simulator card, or reuse a
transcript from another take. The language-review packet is
[LANGUAGE_REVIEW.md](engineering/LANGUAGE_REVIEW.md); every current entry there is unchecked.

## Neutral post draft

This draft is not authorized to post. Fill only from the selected take, the verified model path, and
confirmed contributions:

> Pramana asks people what they can safely observe when a building fault has no sensors. This video
> shows [Fill: what the selected take actually demonstrates]. The building and participant cards
> are [Fill: accurate simulation disclosure]. Gnani technology used in this take: [Fill: verified
> model and API path]. Contributors: [Fill: confirmed names and contributions].
>
> #GnaniAI #GreatIndianAIInternshipChallenge [Human: tag the current official Gnani AI account]

Before publishing, verify that the selected take demonstrates a working app, that the building and
each voice are labelled accurately, that the caption sheet matches the take, and that the nominated
post link is the real public URL. Do not buy or automate engagement.

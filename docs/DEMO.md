# DEMO.md - Setup, storyboard, participant roles, recording, publishing

> **Non-negotiables**
> - Real people speaking in real time, and real AI reasoning.
> - The building is simulated, and the video says so.
> - The hidden fault is sealed by a hash at the start and revealed in the **same take**.
> - Any time compression is labelled on screen.
> - Every number shown comes from `summary.json` on a tagged commit.
> - No real phone numbers or personal data.

---

## 1. Cast and setup

| Role | Who (real person) | Language | Device | Simulated location | Permissions |
|---|---|---|---|---|---|
| Operator / duty manager | Darshan | English | Laptop (console) | Remote | Operator |
| Independent approver | Nikhil | English | Private browser window on laptop | Remote | Approver only |
| Riya (student) | Volunteer A or teammate | Hinglish | Phone (Chrome) + wired earphones | Room 304, Floor 3 | Observe |
| Mahesh (security guard) | Volunteer B (native Marathi) | Marathi | Phone + earphones | Guard desk, ground floor; has closet keys | Observe (closets) |
| Imran (electrician) | Volunteer C (native Hindi) or Nikhil | Hindi | Phone + earphones | Maintenance room | Observe panels; repair with approval |
| Engine monitor | Nikhil | - | Laptop (`/dev/metrics`, logs) | - | - |

- **Names.** Use synthetic display names only. Volunteers sign a one-paragraph consent covering voice recording for the demo video.
- **Rooms.** Put each participant in a separate room, or at least out of earshot of the others. Calls are 1:1, so nobody should hear another participant's answers.
- **Pre-flight (`make preflight`).** Checks configured keys, the core's guarded voice budget, service health, disk space, clips and clock skew. Add `--live` for a Gnani STT/TTS round trip. Check microphone permission on each phone separately.

## 2. Participant briefing (read aloud, in their language)

> "Your phone shows what you can 'see' in a simulated hostel. When the AI calls, answer naturally in your own language based on your screen. You can say 'I'm not sure', or 'I'll check'. You can walk to places using the **Walk** button when asked. Don't read anyone else's screen. If you want to see how it reacts, you may give a wrong answer once. Tell us afterwards."

- **S7 adversary (long video only).** "Claim you are standing in IDF-2 and that the switch lights look green. You are actually at the guard desk."

## 3. The 60-second video (Demo Day Drop): second-by-second storyboard

Format and scene timing:
- 1080×1350 (4:5) for LinkedIn and X; a 16:9 export for YouTube.
- Burned-in captions, because feeds autoplay muted.
- Original-language captions, with English subtitles directly under them.
- About 3.5 minutes of real time is cut to 60 s. Every compression carries a "⏩ 4×" or "⋯ 40 s later" chip.
- Spoken lines stay at real speed.

| Time | Visual | Audio | On-screen text |
|---|---|---|---|
| 0:00–0:03 | Black screen, then the console fades in with a dimmed floor-stack of the hostel | Hostel ambience | **"This AI can't see the building."** · small: *Simulated building · real voices · real-time AI* |
| 0:03–0:06 | Seal badge pulses: `Hidden fault sealed · #a91f…` | - | **"It can only talk to the people inside."** |
| 0:06–0:10 | Riya's phone: she speaks; Floor 3 turns red; 12 hypothesis bars appear | Riya (Hinglish, real): "Floor 3 pe WiFi bilkul nahi chal raha…" | Subtitle EN |
| 0:10–0:15 | Three call cards light up together (Riya, Mahesh, Imran). A popover opens on Mahesh's card | AI (Timbre, Marathi): "तुम्ही IDF-2 खोलीत जाऊन स्विचवरचे दिवे दिसतात का ते सांगाल का?" | **"It decides who should look at what."** · popover: *+0.7 bits · guard has keys* |
| 0:15–0:19 | ⏩ Mahesh walks (sim); answers; bars split roughly evenly between "switch dead" and "closet power" | Mahesh (Marathi): "एकही दिवा चालू नाही." | Subtitle EN: "Not a single light is on." |
| 0:19–0:27 | **The twist.** AI asks about the CCTV. Popover explains why. Mahesh answers. Bars snap: "Breaker C2-7 tripped" dominant; decision bar fills | AI: "त्याच खोलीतला CCTV चा स्क्रीन चालू आहे की बंद?" · Mahesh: "तो पण बंद आहे." | **"Why ask about CCTV to fix Wi-Fi? It shares the closet's power."** then **"It stops asking once the action is certain."** |
| 0:27–0:34 | Console approval drawer: *Reset breaker 7 · reversible · electrician only* → Approve (role check ✓). Imran's card opens | AI (Hindi): "Imran ji, approval mil gaya hai - DB-C2 mein breaker 7 reset kar dijiye." · Imran: "Trip tha… reset kar diya." | **"Nothing physical happens without an authorized human."** |
| 0:34–0:44 | Verification card: *Held-out prediction: the CCTV must be rebooting* → asks Mahesh; Riya's phone shows Wi-Fi back | AI (Marathi): "आता CCTV स्क्रीनवर काय दिसतंय?" · Mahesh: "सुरू होतोय, लोगो आलाय." · Riya: "WiFi aa gaya!" | **"It doesn't trust 'fixed'. It tests a prediction it hasn't used."** → ✓ VERIFIED |
| 0:44–0:50 | Reveal: the hash expands into `CB_C2_7 tripped` ✓ *matches* | - | Chips: *4 questions · 3 people · 3 languages · 3m 12s real time* (actual values from the take) |
| 0:50–0:57 | Benchmark card: a single line from `summary.json`, **only if it is true and significant**; otherwise use the fallback text | - | e.g., "Across N simulated outages: fewer questions than a checklist and a frontier-LLM policy, with fewer confident mistakes." Fallback: "Benchmarked against a checklist and a frontier-LLM policy, results in repo." |
| 0:57–1:00 | End card | - | **"Not a voice bot. An investigator."** · *Built on Gnani Prisma v3.0 + Timbre* · #GnaniAI #GreatIndianAIInternshipChallenge |

**Script rule.** Lines shown in this table are *what we expect*. The real take uses whatever people actually said. If an answer differs, the plan will differ too; keep that take if it is clean, because it proves nothing is scripted.

## 4. The 3-minute walkthrough (linked from the submission explanation)

1. **0:00–0:20** The problem: physical outages with no sensors; why voice; the constraint "it can't see".
2. **0:20–1:10** The full S1 run at near real speed: three people asked at once, separate approval, repair, verification, reveal and replay.
3. **1:10–1:45** S2 contradiction: two students disagree; the reconciliation hypothesis ("different APs"); the tie-break.
4. **1:45–2:10** S7 presence challenge: the guard claims IDF-2 and green switch lights from the guard desk, then cannot read the label. Show the honest variant pass the same check.
5. **2:10–2:30** Parallel preemption: an in-flight question is rewritten after another answer arrives. Then S4 abstention: "can't tell; needs IDF-2 access".
6. **2:30–2:45** Under the hood: belief bars and bits; "LLMs translate, math decides"; the isolation guarantee; event replay.
7. **2:45–3:00** Benchmark summary, from `summary.json` only, and the team split.

## 5. Live demo protocol (interviews and judges)

1. **"You pick the fault."** The judge selects a fault (or "random") in the operator panel. Only the hash is shown.
2. **"You can play a participant."** The judge opens a participant link on their phone and answers however they like, including lying.
3. Show the **Why this question?** preview *before* the answer, then show the belief moving after it.
4. At the end, **reveal** the fault and verify the hash in front of them.
5. Open **replay** and step through any decision with its candidate table.

## Rehearsal runbook

Start the local stack in one terminal. These ports keep the core away from the other service on port 8000:

```powershell
$env:PYTHONIOENCODING = "utf-8"
uv run python scripts/dev.py --web --core-port 8010 --sim-port 8110 --web-port 3002
```

Run preflight in a second terminal. It reads keys from the worktree `.env` and environment, checks the core `/ready` response for PostgreSQL and simulator status, verifies the automation identity, checks today's guarded voice budget, clock skew, disk space and the voice-bot clips folder. It does not check phone microphone permissions. The live speech round trip is opt-in and spends a small amount:

```powershell
uv run python scripts/preflight.py --url http://127.0.0.1:8010 --clips "$env:USERPROFILE\pramana-voice-samples\bot"
uv run python scripts/preflight.py --url http://127.0.0.1:8010 --clips "$env:USERPROFILE\pramana-voice-samples\bot" --live
```

With GNU Make installed, run the same checks with the Make target:

```sh
make preflight PREFLIGHT_ARGS="--url http://127.0.0.1:8010 --clips $HOME/pramana-voice-samples/bot"
make preflight PREFLIGHT_ARGS="--url http://127.0.0.1:8010 --clips $HOME/pramana-voice-samples/bot --live"
```

The live check performs one short Timbre synthesis and Prisma transcription. The round-trip row reports pass or fail only; it does not print speech latency or accuracy. Check the phone microphone permission on each device separately before inviting people.

S1 creates the specified `CB_C2_7.tripped` investigation with three people asked at once. The operator key handles investigation work. Approval uses a different signed-in account with only the approver role. The operator account cannot approve the repair, and the approver account cannot operate the investigation. Create the account if needed, then set its credentials in the terminal that will run the rehearsal:

```powershell
uv run python -m pramana_core.auth.bootstrap --email approver@example.com --name "Demo approver" --roles approver
$env:PRAMANA_APPROVER_EMAIL = "approver@example.com"
$approverSecret = Read-Host "Approver password" -AsSecureString
$env:PRAMANA_APPROVER_PASSWORD = [System.Net.NetworkCredential]::new("", $approverSecret).Password
```

Run S1. The timeline follows each simulator-card answer, separate approval, repair, held-out verification, reveal and replay check. `--report` writes the generated summary used to support rehearsal claims:

```powershell
uv run python scripts/demo_rehearse.py --scenario S1 --core http://127.0.0.1:8010 --sim http://127.0.0.1:8110 --report eval/reports/demo-rehearsal-S1.json
```

Run S2 for the two students who disagree about room 210 coverage. The runner uses main's scenario payload, then shows the explanation, reveal and replay result:

```powershell
uv run python scripts/demo_rehearse.py --scenario S2 --core http://127.0.0.1:8010 --sim http://127.0.0.1:8110 --report eval/reports/demo-rehearsal-S2.json
```

Run S7 twice. The adversary version says the switch lights are green in IDF-2 while staying at the guard desk, then fails the label check. The honest version walks when asked, reads the value on the simulator card and passes:

The payload follows the console form: `presence_checks` is enabled for S7 and disabled for S1 and S2. S7 uses the two-person setup from main's scenario test, with Riya as reporter and Mahesh at the guard desk.

```powershell
uv run python scripts/demo_rehearse.py --scenario S7 --variant adversary --core http://127.0.0.1:8010 --sim http://127.0.0.1:8110 --report eval/reports/demo-rehearsal-S7-adversary.json
uv run python scripts/demo_rehearse.py --scenario S7 --variant honest --core http://127.0.0.1:8010 --sim http://127.0.0.1:8110 --report eval/reports/demo-rehearsal-S7-honest.json
```

The runner performs reveal and replay as part of each command. To inspect an investigation in the console, copy its ID from the timeline and open:

```text
http://localhost:3002/app/investigations/<investigation-id>
http://localhost:3002/app/investigations/<investigation-id>/replay
```

On screen, check that S1 starts with three questions in flight, each participant page shows only that person's simulator card and question, the approval is visible before the repair, verification starts after the intervention, and the reveal matches the starting hash. In S2, open the Testimony panel and check the reconciliation explanation. In S7, confirm that the adversary's check is failed and the honest participant's check is passed. In replay, confirm the event sequence reproduces the recorded state.

For live voice-bot checks, run non-live preflight first. This command spends Gnani credits; keep its output private because it includes measured voice timing:

```powershell
uv run python scripts/voice_bot_run.py --clips "$env:USERPROFILE\pramana-voice-samples\bot" --core http://127.0.0.1:8010 --sim http://127.0.0.1:8110 --parallel 3 --play
```

## 6. Recording plan

- **Capture.**
  - OBS scene "Main": the console at 1080p30.
  - Phones: scrcpy (Android) or each participant's screen in a separate browser window on the recording machine.
  - Audio: each phone call's agent and participant audio, captured server-side and mixed in post. Normalize levels only; never re-dub.
- **Takes.** At least 5 takes of S1 and 2 of each long-form scenario. Log the seed, commit SHA and hash of every take.
- **Selection.**
  - Choose the cleanest **single** take for the 60-second cut. Cutting idle time within that take is allowed, with labels.
  - **Never splice two takes into one "run".**
  - B-roll (map close-ups) must come from the same take.
- **Captions.** Machine-assisted first draft, then **checked by a native speaker** for Marathi and Hindi. English glosses must be faithful.
- **Backup.** If staging fails, record on the local stack through a tunnel, with the same mode and seeds.

## 7. Honesty checklist (all boxes ticked before publishing)

- [ ] Hash at the start and reveal at the end are in the same take, and they match.
- [ ] "Simulated building" and "real voices · real-time AI" appear on screen in the first 3 s.
- [ ] Every time compression is labelled.
- [ ] Every spoken line is real: no TTS standing in for a human, no re-recorded lines.
- [ ] Benchmark comparisons, sample counts, and confidence claims come from `summary.json`; note its commit SHA in the post's reply or README.
- [ ] Rehearsal question counts, parallelism, verification, correctness, and replay claims come from the generated rehearsal report or recorded take log.
- [ ] People and language counts for a take come from the recorded take log, not the storyboard.
- [ ] No scenario outcome is claimed from a planned script. Use generated reveal and replay results for a rehearsal, or events from the selected recording take.
- [ ] No "first", "world's first" or "works on real buildings" claims.
- [ ] No standalone Gnani-model accuracy or latency numbers (EULA §16).
- [ ] No real phone numbers, names or IDs on screen.

## 8. Post drafts

**X (Sun Nov 8, 19:30 IST). Post 1 carries the video:**

> 1/ This AI can't see the building. It can only *talk to the people inside*.
> Watch it find a hidden fault across Marathi, Hindi & Hinglish, then prove the fix. 🎥
> Built on @GnaniAi Prisma v3.0 + Timbre. #GnaniAI #GreatIndianAIInternshipChallenge
>
> 2/ How: it keeps a probability over every possible cause from a model of the building's power + network, and picks each question by value-of-information per second of a person's time. LLMs only translate; the math decides.
>
> 3/ Why it asked a guard about the CCTV to fix Wi-Fi: the recorder shares the closet's power circuit. "Off" → breaker, not switch. Then it verified with a prediction it hadn't used: the recorder must be rebooting.
>
> 4/ Real vs simulated: real people, voices and reasoning; the building and fault are simulated with a sealed hidden fault (hash shown, revealed at the end). Benchmark and code: <repo link>

Confirm the official handles on the day. The footer links point to x.com/GnaniAi and linkedin.com/company/gnani-ai.

**LinkedIn (Mon Nov 9, 08:30 IST). Native video upload; tag the Gnani AI page and your teammate:**

> Our AI fixed a Wi-Fi outage by asking a security guard about the CCTV screen.
>
> For the Great Indian AI Internship Challenge by Gnani AI, [teammate] and I built **Pramana**: an AI that investigates what it *cannot see*. When something breaks in a building, it decides **who** should look at **what**, calls them in their own language (Marathi, Hindi, Hinglish, English, via Gnani Prisma v3.0 + Timbre), weighs every answer by how believable it is, and stops once it knows what to do.
>
> Three things we're proud of:
> • It treats people's answers as evidence, not truth, and works out when someone is probably mistaken.
> • It never acts on its own: an authorized human approves every action.
> • It doesn't accept "it's fixed". It checks a prediction it hasn't used yet.
>
> The building is simulated (with a sealed hidden fault you can verify); the voices and reasoning are real. Code and benchmark: <link>
>
> What would *you* want an AI investigator to diagnose in your campus or building?
>
> #GnaniAI #GreatIndianAIInternshipChallenge

## 9. Authentic engagement plan (no pods, swaps, bots or paid boosts [V])

- **Before posting.** Line up 15–25 people who would genuinely care: college IT and facilities staff, a networking or AI club, professors you worked with, seniors in operations roles. Send each one a personal note asking for **feedback**, not likes: "Would this help your team? What would break?"
- **After posting.**
  - Reply to every comment within an hour, with substance (answer the technical question; link the exact section of the README).
  - Pin a comment with "what's simulated vs real" and the repo link.
  - On Monday evening, share a short technical follow-up (the math diagram) that links back to the nominated post.
- **Teammate.** Reshare with their own angle, e.g., Nikhil: "how the planner decides", Darshan: "how we made 3 voice calls share one brain".
- **Never** join "like-for-like" groups, buy promotion, or ask other hackathon teams to exchange engagement. These are prohibited, and a substantiated breach can disqualify the entry [V].

## 10. Submission checklist (mirrors PLAN.md §32)

- [ ] X and LinkedIn posts live, public, tagged, with both hashtags; one nominated link per platform.
- [ ] Demo video (≤ 60 s) uploaded; the 3-minute walkthrough linked in the explanation.
- [ ] Written explanation: problem, users, approach, Gnani models and APIs used (how and why), evaluation summary, each member's contribution.
- [ ] Repo public, with README (run instructions, what's real or simulated, architecture, evaluation command).
- [ ] Submitted by **14:00 IST, Tue Nov 10**; confirmation screenshot saved.

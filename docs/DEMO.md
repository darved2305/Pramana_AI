# DEMO.md — Setup, storyboard, participant roles, recording, publishing

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
| Operator / duty manager | Darshan | English | Laptop (console) | Remote | Approver |
| Riya (student) | Volunteer A or teammate | Hinglish | Phone (Chrome) + wired earphones | Room 304, Floor 3 | Observe |
| Mahesh (security guard) | Volunteer B (native Marathi) | Marathi | Phone + earphones | Guard desk, ground floor; has closet keys | Observe (closets) |
| Imran (electrician) | Volunteer C (native Hindi) or Nikhil | Hindi | Phone + earphones | Maintenance room | Observe panels; repair with approval |
| Engine monitor | Nikhil | — | Laptop (`/dev/metrics`, logs) | — | — |

- **Names.** Use synthetic display names only. Volunteers sign a one-paragraph consent covering voice recording for the demo video.
- **Rooms.** Put each participant in a separate room, or at least out of earshot of the others. Calls are 1:1, so nobody should hear another participant's answers.
- **Pre-flight (`make preflight`).** Checks keys, credits remaining, staging health, Gnani STT/TTS round trip (< 2 s), mic permission on every phone, and wall clocks synced.

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
| 0:03–0:06 | Seal badge pulses: `Hidden fault sealed · #a91f…` | — | **"It can only talk to the people inside."** |
| 0:06–0:10 | Riya's phone: she speaks; Floor 3 turns red; 12 hypothesis bars appear | Riya (Hinglish, real): "Floor 3 pe WiFi bilkul nahi chal raha…" | Subtitle EN |
| 0:10–0:15 | Two call cards light up together (Riya, Mahesh). A popover opens on Mahesh's card | AI (Timbre, Marathi): "तुम्ही IDF-2 खोलीत जाऊन स्विचवरचे दिवे दिसतात का ते सांगाल का?" | **"It decides who should look at what."** · popover: *+0.7 bits · guard has keys* |
| 0:15–0:19 | ⏩ Mahesh walks (sim); answers; bars split roughly evenly between "switch dead" and "closet power" | Mahesh (Marathi): "एकही दिवा चालू नाही." | Subtitle EN: "Not a single light is on." |
| 0:19–0:27 | **The twist.** AI asks about the CCTV. Popover explains why. Mahesh answers. Bars snap: "Breaker C2-7 tripped" dominant; decision bar fills | AI: "त्याच खोलीतला CCTV चा स्क्रीन चालू आहे की बंद?" · Mahesh: "तो पण बंद आहे." | **"Why ask about CCTV to fix Wi-Fi? It shares the closet's power."** then **"It stops asking once the action is certain."** |
| 0:27–0:34 | Console approval drawer: *Reset breaker 7 · reversible · electrician only* → Approve (role check ✓). Imran's card opens | AI (Hindi): "Imran ji, approval mil gaya hai — DB-C2 mein breaker 7 reset kar dijiye." · Imran: "Trip tha… reset kar diya." | **"Nothing physical happens without an authorized human."** |
| 0:34–0:44 | Verification card: *Held-out prediction: the CCTV must be rebooting* → asks Mahesh; Riya's phone shows Wi-Fi back | AI (Marathi): "आता CCTV स्क्रीनवर काय दिसतंय?" · Mahesh: "सुरू होतोय, लोगो आलाय." · Riya: "WiFi aa gaya!" | **"It doesn't trust 'fixed'. It tests a prediction it hasn't used."** → ✓ VERIFIED |
| 0:44–0:50 | Reveal: the hash expands into `CB_C2_7 tripped` ✓ *matches* | — | Chips: *4 questions · 3 people · 3 languages · 3m 12s real time* (actual values from the take) |
| 0:50–0:57 | Benchmark card: a single line from `summary.json`, **only if it is true and significant**; otherwise use the fallback text | — | e.g., "Across N simulated outages: fewer questions than a checklist and a frontier-LLM policy, with fewer confident mistakes." Fallback: "Benchmarked against a checklist and a frontier-LLM policy, results in repo." |
| 0:57–1:00 | End card | — | **"Not a voice bot. An investigator."** · *Built on Gnani Prisma v3.0 + Timbre* · #GnaniAI #GreatIndianAIInternshipChallenge |

**Script rule.** Lines shown in this table are *what we expect*. The real take uses whatever people actually said. If an answer differs, the plan will differ too; keep that take if it is clean, because it proves nothing is scripted.

## 4. The 3-minute walkthrough (linked from the submission explanation)

1. **0:00–0:20** The problem: physical outages with no sensors; why voice; the constraint "it can't see".
2. **0:20–1:10** The full S1 run at near real speed, including the presence challenge on Mahesh ("read the last three letters on the switch label").
3. **1:10–1:45** S2 contradiction: two students disagree; the reconciliation hypothesis ("different APs"); the tie-break.
4. **1:45–2:15** Parallel preemption: an in-flight question is rewritten after another answer arrives. Then S4 abstention: "can't tell; needs IDF-2 access".
5. **2:15–2:45** Under the hood: belief bars and bits; "LLMs translate, math decides"; the isolation guarantee; event replay.
6. **2:45–3:00** Benchmark summary, from `summary.json` only, and the team split.

## 5. Live demo protocol (interviews and judges)

1. **"You pick the fault."** The judge selects a fault (or "random") in the operator panel. Only the hash is shown.
2. **"You can play a participant."** The judge opens a participant link on their phone and answers however they like, including lying.
3. Show the **Why this question?** preview *before* the answer, then show the belief moving after it.
4. At the end, **reveal** the fault and verify the hash in front of them.
5. Open **replay** and step through any decision with its candidate table.

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
- [ ] Numbers come only from `summary.json` (commit SHA noted in the post's reply or the README).
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

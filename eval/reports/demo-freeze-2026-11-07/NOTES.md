# Demo rehearsals, 2026-11-07

The JSON files are generated integration results. The building is simulated. All voice
participants in these runs were synthetic bots, not people. Gnani Prisma and Timbre were live;
speech measurements and transcripts remain private under the Gnani EULA.

The initial runs used main at `858b636` with the changes committed as `f660b62`. The final
English S2 rerun uses the phrase correction committed with this note.
`scripts/voice_bot_run.py --summary` writes integration facts separately from its private output.

| Run | Outcome | Evidence |
|---|---|---|
| Text S1 | Three questions in flight; repair verified; correct reveal; matching commitment; identical replay | `text-S1-honest.json` |
| Text S2 | Decided correctly; matching commitment and replay | `text-S2-honest.json` |
| Text S7, honest | Label passed; abstained; matching commitment and replay | `text-S7-honest.json` |
| Text S7, adversary | Label failed; abstained; matching commitment and replay | `text-S7-adversary.json` |
| Live voice S1, takes 1–3 | All three verified and correct; three questions in flight; matching commitment and replay | `voice-S1-1.json`, `voice-S1-2.json`, `voice-S1-3.json` |
| Live voice S2, initial take | Correct decision and replay, but Hinglish answers were sent to English TTS; not an English-speech rehearsal | `voice-S2.json` |
| Live voice S2, corrected English take | English answer phrases; correct decision, reconciliation explanations, matching commitment and replay | `voice-S2-english.json` |
| Live voice S7, honest | Label passed; abstained; matching commitment and replay | `voice-S7-honest.json` |
| Live voice S7, first adversary attempt | Failed: bot used the nonexistent `cctv_screen` name instead of `nvr_screen`, then went silent; no presence check | `voice-S7-adversary.json` |
| Live voice S7, corrected adversary | Label failed; abstained; matching commitment and replay; no call errors | `voice-S7-adversary-retry.json` |

S7 has only a student and a guard. Both variants abstain because the remaining useful panel
check needs an electrician. A passed presence check establishes the reading; it does not
guarantee a confident diagnosis. No correctness percentage is assigned to these abstentions.

The voice adversary stays at the guard desk and makes scripted false claims about IDF-2. It never
moves there or reads its label. The honest bot reads only its own simulator card. Dynamic label
readings and S2's English answers use Timbre-generated synthetic speech. Other answers use the
existing open-source MMS clips. These runs do not establish human accent, noise or room robustness.

Text S1 used a separately signed-in approver-only account. The voice bots used the automation
identity for approval; those runs do not prove separation of human approval roles. The real-stack
M1 browser test checks separate operator and approver sessions.

M1's browser rehearsal video is local at `.cache/rehearsal-video/video.webm`. It is an automated
text/tap rehearsal, not a recording of human or live-voice participation. Never commit it or
publish it as the final demo take. Local console screenshots are in `.cache/console-review/`.

Still pending: S1 with three consenting humans, a real-phone staging flow, native-speaker review,
and the final single-take recording with people. These bot runs do not satisfy the human M2 milestone.

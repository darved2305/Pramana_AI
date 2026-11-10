# November 10 submission closeout

Prepared against `eeaa0745ab2f8d82ada34c6581456c5f2ebeb0f0`. This is a handoff packet,
not a receipt for a post or submission. The final video is being made by Nikhil; wait for
that final cut before posting or submitting, as requested in
[issue 24](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/issues/24).

## Submit in this order

1. Get Nikhil's final video and his confirmation of the contribution line in
   [SUBMISSION.md](SUBMISSION.md). Review the actual cut using [DEMO.md](DEMO.md): one
   investigation's seal and reveal, faithful captions, accurate participant and provider labels,
   labelled time compression, no credentials or private participant details.
2. Fill the selected video's speaker type and any additional human-run evidence in
   `SUBMISSION.md`. The current base footage is described in issue 24 as a real local product
   recording using the Gnani protocol emulator and synthetic audio. It is not a live Gnani
   speech recording. Keep that disclosure visible. Historical live runs are documented in
   [VOICE_PROVENANCE.md](engineering/VOICE_PROVENANCE.md); they do not establish what a new cut shows.
3. Publish the verified video on LinkedIn and/or X. Tag Gnani AI's official account, use both
   hashtags below, and copy the actual public post URL. Open the video and post signed out to
   check access. Select one nominated post per platform used.
4. One member completes the [official submission form](https://forms.cloud.microsoft/r/dfFShbp7W7)
   for the team, listing both members. Use the written fields in `SUBMISSION.md`, the final
   video URL, and the actual nominated post URLs. The link came from Gnani's November 8
   submission reminder email. The email says all mandatory fields must be completed and the
   same form links to the social engagement contest. Inspect that step too; do not assume a
   social post by itself completes an entry. The dynamic form could not be inspected here
   because browser access is unavailable.
5. Submit by **November 10, 2026, 23:59 IST** and retain the actual confirmation and timestamp
   privately. Record only the confirmation status/time in `SUBMISSION.md`. A prepared draft
   or visited form is not proof of submission.

The [programme page](https://www.gnani.ai/internship) and
[participation terms](https://www.gnani.ai/great-indian-ai-internship-registration-form)
were checked on November 10. They require a working application using Gnani technology,
accurate contributions, and a public working video with the account tag and both hashtags.
They do not establish that emulator footage alone satisfies genuine Gnani use. A real provider
clip would strengthen the evidence; do not describe the emulator as live recognition.

## LinkedIn copy for the emulator cut

Use after checking that the final cut still matches this description. Select the official
Gnani AI company mention in the editor. If a live-provider segment is added, identify that
segment separately with its actual speaker and model provenance.

> We built Pramana for the Great Indian AI Internship Challenge: an investigator for building
> faults that have no sensors. It asks what people can safely observe, weighs conflicting
> answers, and chooses the next question using a deterministic Bayesian engine.
>
> This recording shows our local practice investigation through a repair decision, approval,
> simulated repair, verification, reveal and replay. The building is simulated. This cut uses
> a Gnani protocol emulator with synthetic audio; it does not show live Prisma recognition
> or Timbre speech quality.
>
> The application integrates Gnani Prisma v3.0 STT and Timbre v3.0 TTS, with Timbre v2.5 for
> Hinglish. Dated live integration evidence and the limits of those runs are in the repository.
> A separate approver is required for a repair, and the event log supports exact replay.
>
> Code and evidence: https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-
>
> #GnaniAI #GreatIndianAIInternshipChallenge

## X copy for the emulator cut

Attach the final verified video. Confirm the official account handle before using the mention.
This first post is under 280 characters:

> Pramana investigates simulated building faults: questions, approval, repair checks and replay.
> This cut uses a Gnani protocol emulator with synthetic audio. Live integration evidence is in the repo.
> @GnaniAi #GnaniAI #GreatIndianAIInternshipChallenge

Optional evidence reply:

> Gnani integration: Prisma v3.0 STT; Timbre v3.0 TTS and v2.5 for Hinglish. Historical live runs
> and their limits: https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/blob/main/docs/engineering/VOICE_PROVENANCE.md

## Verified status and remaining dependencies

Read-only checks completed on November 10, around 22:34 IST. These results are a snapshot,
not a full authenticated browser or live-voice acceptance test.

| Item | Result | Evidence or next action |
|---|---|---|
| Main code | CI passed at `eeaa074` | [CI run 42854878015](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42854878015) |
| Live web `/`, `/_health`, `/api/core/ready` | HTTP 200 | Readiness: database, simulator and models `ok`; Gnani `not configured` |
| Live Gnani clip | Not available from the current stage | No live provider configured; requires a real key and a consented spoken recording |
| Local Gnani configuration | Key present; validity and remaining credits untested | Local `.env` points at `api.vachana.ai`; no key value or recording was copied into this packet |
| Core availability | One warm instance; maximum two service instances | Ready revision `pramana-core-00014-p5g`, 100% traffic, revision `minScale=1` |
| Billing alert | Already configured | `pramana-inr-1000`, INR 1,000/month, project `671800103530`, actual-spend thresholds 50%, 80%, 100%; not a spend cap |
| Age, enrolment, one team entry | Confirmed by Darshan in this session | Both over 18, enrolled in India, one team entry; check registered details and age at registration |
| Darshan contribution draft | Checked against attributed implementation commits | References in `SUBMISSION.md`; no exclusive-authorship claim |
| Nikhil contribution line | Pending Nikhil's confirmation | Do not confirm on his behalf |
| Additional real-human validation runs | Unconfirmed | Two local audio files exist; no human take sheet or aggregate M2 report found; one older mixed run is documented |
| Final video | In production | Nikhil owns the final cut; no final URL supplied |
| Public post and form confirmation | Pending | Complete the sequence above once the video is final |

The live checks used the canonical stage from issue 24. No accounts were created, messages sent,
provider credits spent, or deployment settings changed by these checks. Keep the Singapore
database's existing restriction on real personal data. The older deployment runbook describes a
team-only stage; agree on judge access with the owner before circulating access credentials.

Documentation validation: 41 targeted documentation, authenticity, and deployment-runbook checks
passed in an isolated environment installed from `uv.lock`. Local Markdown links and the
250-character X draft were also checked. The first attempt used the older checkout's environment
and could not collect the deployment checks because `joserfc` was missing; installing the current
locked environment resolved that collection failure. No runtime code changed in this closeout.

The first full [PR CI run](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42862686733)
passed Python, real-stack browser, image, infrastructure and secret checks. Its web suite had
135 passing tests and one failure: the keyboard-scroll test could not find `Metrics by policy`.
That test navigated away from the preview entry without waiting for its client-side setup and
redirect. It now waits for the `/app` redirect before opening the target screen. The existing
visibility, focus, outline and axe assertions remain. TypeScript, lint, and all three affected
tests repeated three times passed locally (9/9) against a production build with bundled Chromium.

## After submission

Keep these items open until their actions and checks actually finish:

- **Credentials:** rotate the Supabase migrator/database password, `pramana_app` runtime password,
  Supabase secret API key, Google OAuth client secret and Gmail app password. The API key is
  separate from the database URLs. Follow the
  [deployment rotation procedure](engineering/DEPLOY_BUDGET_GCP.md#redeploy-and-rollback), updating
  local configuration and the corresponding Secret Manager versions. Verify new revisions and
  database reconnection before retiring old versions. Preserve `pramana-pii-key`; arbitrary
  rotation of the encryption key would make existing sealed data unreadable. The current
  Singapore stage remains under the existing parked-rotation exception until this is done.
- **Mumbai database:** provision the separate approved `ap-south-1` project; confirm it holds
  nothing unrelated. Rehearse an encrypted India backup and restore, check roles and RLS grants,
  migrate the application and simulator schemas, and verify connections, replay and smoke checks.
  At cutover, stop writes, transfer the final data and switch all three database URL secrets
  together. Keep the old database intact until validation completes. A rollback after new writes
  needs data reconciliation; changing URLs alone is not a safe rollback. Follow the
  [backup and restore runbook](engineering/DEPLOY_BUDGET_GCP.md#supabase-free-backup-and-restore-drill).
- **GitGuardian 39867227 / 39867228:** the production status note records generic-password matches
  in dry-run/test placeholders and SCRAM-handling code. Match each incident to that exact
  non-secret source before resolving it as a false positive. Incident-specific findings were not
  available in this session, so neither incident has been marked resolved. This triage is
  separate from the real credentials reported as leaked in chat.
- **Warm instance:** leave it running while judges may visit. After that window, the owner can
  restore zero minimum instances with the command below. Issue 24 estimates about INR 35/day
  while warm; this session did not measure actual charges. Confirm the resulting configuration
  after the change. No scale-down was performed here.

```powershell
gcloud run services update pramana-core --region asia-south1 --project luminous-slice-514102-f4 --min-instances=0
```

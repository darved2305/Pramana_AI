# Recording voice samples for testing

So far, live speech tests used Gnani's own synthesised voices. Real people speak with accents,
background noise, hesitation and their own word choices, and those are what break short answers.
This page explains how to collect a small, consented set of real recordings.

## Who and how

- **Who.** You, your teammate, and two or three friends or family members. At least one native
  Marathi speaker and one native Hindi speaker; anyone can do Hinglish.
- **Consent.** Tell each person what the clips are for (testing speech recognition for this
  project, stored privately, never published, deleted after the hackathon), and get a "yes" in
  writing (a WhatsApp message is fine). This is the programme's rule: no real call recordings or
  personal data in the project.
- **Device.** Any phone voice recorder: Android "Recorder", iPhone "Voice Memos" (`.m4a`), or a
  WhatsApp voice note forwarded to yourself (`.opus`/`.ogg`). Hold the phone normally; a quiet
  room is fine, but a little background noise is realistic.
- **Length.** 1–5 seconds per clip. Say the answer naturally, the way you would to a person on
  the phone.

## What to record

Each person records only in the language they actually speak. About 10 clips each:

| Probe (file name part) | Outcome | Marathi | Hindi | Hinglish |
|---|---|---|---|---|
| `nvr_screen` | `off` | "बंद आहे" / "स्क्रीन बंद आहे" | "बंद है" | "screen band hai" |
| `nvr_screen` | `on` | "चालू आहे" | "चालू है" | "haan on hai" |
| `corridor_lights` | `off` | "दिवे बंद आहेत" | "लाइट बंद है" | "lights off hain" |
| `corridor_lights` | `on` | "दिवे चालू आहेत" | "लाइट जल रही है" | "lights on hain" |
| `wifi_status` | `no_network` | "वायफाय दिसतच नाही" | "वाईफाई दिख ही नहीं रहा" | "WiFi dikh hi nahi raha" |
| `wifi_status` | `connected` | "कनेक्टेड आहे" | "कनेक्टेड है" | "connected hai" |
| `internet_works` | `yes` | "हो" / "हो, उघडतं" | "हाँ" | "haan khul raha hai" |
| `internet_works` | `no` | "नाही" | "नहीं" | "nahi khul raha" |
| `breaker_c2_7` | `tripped` | "ब्रेकर खाली आहे" | "ब्रेकर नीचे है" | "breaker trip hai" |
| `internet_works` | `unknown` | "माहीत नाही" | "पता नहीं" | "pata nahi yaar" |

Also useful: one negation each ("चालू नाही", "chalu nahi hai") and one hedge ("shayad band hai").

## Naming and where to keep them

Name each file `<lang>__<probe>__<outcome>__<tag>.<ext>`, where `<lang>` is `mr`, `hi`, `en` or
`hi-en`. For example: `mr__nvr_screen__off__aai1.m4a`, `hi-en__wifi_status__no_network__riya2.ogg`.

Put them in a folder **outside the repository**, for example
`C:\Users\<you>\pramana-voice-samples\`. Audio files are also gitignored as a second safeguard.

## Scoring them

With the core running (`make core`):

```bash
uv run python scripts/voice_eval.py --clips C:/Users/<you>/pramana-voice-samples --out C:/Users/<you>/pramana-voice-report.csv
```

The script prints the estimated cost first (about Rs 0.02 per clip) and asks before spending. The
results are private (Gnani EULA §16): keep the CSV out of the repository and out of public posts.

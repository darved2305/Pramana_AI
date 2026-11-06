# Live voice run notes

Updated: 2026-11-06

## Bot calls

The three live bot runs used 24 Meta MMS-TTS clips in Hindi and Marathi, stored outside the
repository at `C:\Users\Nikhil\pramana-voice-samples\bot`. The project environment check found
zero extraction mismatches. All clips were validated as 16 kHz mono PCM16. The runs used live
Gnani question audio and speech recognition, with `--play` enabled.

| Run | Decided | Correct on reveal | Verified | Replay identical | Questions | Notes |
|---|---|---|---|---|---:|---|
| 1 | Yes | Yes | Yes | Yes | 15 | Four fatal call error messages were logged. One participant call closed with code 4408; no unallowed close codes. The investigation still completed. The error message text was not retained. |
| 2 | Yes | Yes | Yes | Yes | 16 | No logged errors or unallowed close codes. |
| 3 | Yes | Yes | Yes | Yes | 13 | No logged errors or unallowed close codes. |

All three runs reached the correct verified result and replayed identically. Runs 2 and 3 had no
logged call errors. No human testers were available for this check. M2 acceptance with three human
participants remains pending. Bots are not people, so these runs do not justify changing VAD or
silence timers. Human-driven voice tuning remains pending.

Caller-side latency values are recorded only in the team's private latency file, not in this
repository.

## Live load

The latest full live load reached the 600-second target and more than 600 seconds of aggregate
three-call time. All 24 investigations were verified, correct on reveal, commitment-checked, and
replayed identically. Three participant sockets were open at peak. The configured stream cap was
16, the maximum observed count was 3, and the cap check passed. Participant and core call close
counts matched at 144 each, with zero unexpected closes. Live provider-side close counts are not
exposed by the provider.

The latest full live load still failed the RSS growth leak gate after the weak-lock change. In the
previous full run, before that change, simulator memory passed with RSS growth of 2.449 MiB and a
0.1461 MiB per minute slope. Core RSS growth was 31.621 MiB, within the 32 MiB limit, but its
1.5673 MiB per minute slope exceeded the 1 MiB per minute limit. Runtime cache counters in that
run showed the investigation lock registry grow from one entry to a peak of 26 over 25
investigations. The registry now holds idle locks weakly, and a focused regression test confirms
completed investigations leave no idle lock behind. The latest full load shows the memory gate
still needs work.

No VAD or silence timer tuning was made from bot runs. Human-driven tuning and M2 acceptance with
three human participants remain pending.

# Emulated voice load report

Generated: 2026-11-06T05:07:42.516857+00:00
Load window: 600.0 seconds; target 600.0 seconds.
Completed S1 investigations: 110.
Time with at least three participant call sockets open: 596.2 seconds.
Time below three open call sockets during handoffs: 3.794 seconds (99.37% three-call coverage).
Longest measured handoff gap: 1.129 seconds.
Participant call socket peak during the measured window: 9.

## Results

- Investigation status verified, truth correct, commitment verified, and replay byte-identical: True.
- Participant call socket peak: 9.
- Participant call socket closes: 658 client-side and 658 core-side.
- Emulated Prisma WebSocket closes: 971 provider-side and 971 core-side.
- Unexpected WebSocket closes: 0.
- Barge-ins: 10; silence re-prompts: 1; silent releases: 1; idle call heartbeats: 1; withdrawn questions: 95.
- Governor cap sub-run: configured 2, requested 3, refused over-cap request True, peak at limit 2.
- Fake provider requests: STT REST 233, STT WebSocket 971, TTS REST 4, TTS SSE 15.
- Emulated turn latency p50 1648.756 ms, p95 1853.39 ms from 873 turns.

## Memory and handles

RSS was sampled every 5 seconds. Core: 124 samples, slope 0.8111 MiB/min, change 18.008 MiB.
Simulator: 124 samples, slope 0.264 MiB/min, change 3.465 MiB.
Leak limits for the ten-minute run: slope at most 1.0 MiB/min and start-to-end growth at most 32 MiB per process. The slope permits up to 10 MiB of growth over ten minutes; the separate limit absorbs working-set noise.
Peak observed process handles: core 366, simulator 236. Asyncio task counts were not sampled.

## Coverage and limits

- Simulator, core, fake Gnani, and voice bots ran as separate processes against the task's PostgreSQL database.
- The ten-minute window starts at the first point with three open participant calls. Up to three complete S1 bot runs may overlap during handoffs, with at most nine call sockets open. The third run starts when five or fewer calls remain open. Measured handoff gaps are limited to two seconds each and at most one percent of the full window.
- Fake Prisma decoded a test-only text marker carried in synthetic PCM. The marker is not audible speech and is never sent to live Gnani.
- Fake Timbre returned deterministic PCM over REST and paced SSE chunks. The timings describe the local emulator only.
- The run covered decision, approval, repair, verification, reveal, event-log replay, call heartbeats, barge-in, silence re-prompt and release, question withdrawal, and stream-cap refusal.
- No live Gnani run was performed. This report does not measure real speech recognition, real TTS, provider latency, or live account capacity.
- Process handles were sampled. Asyncio task counts, file descriptor types, network packet loss, and live Gnani behavior were not measured.

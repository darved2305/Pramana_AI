# Emulated voice load report

Generated: 2026-11-05T23:50:35.403062+00:00
Load window: 1005.6 seconds; target 600.0 seconds.
Completed S1 investigations: 70.
Time with three participant call sockets open: 607.7 seconds.

## Results

- Investigation status verified, truth correct, commitment verified, and replay byte-identical: True.
- Participant call socket peak: 3.
- Participant call socket closes: 419 client-side and 419 core-side.
- Emulated Prisma WebSocket closes: 540 provider-side and 540 core-side.
- Unexpected WebSocket closes: 0.
- Barge-ins: 8; silence re-prompts: 1; silent releases: 1; idle call heartbeats: 1; withdrawn questions: 40.
- Governor cap sub-run: configured 2, requested 3, refused over-cap request True, peak at limit 2.
- Fake provider requests: STT REST 186, STT WebSocket 540, TTS REST 4, TTS SSE 13.
- Emulated turn latency p50 1686.125 ms, p95 1806.221 ms from 497 turns.

## Memory and handles

RSS was sampled every 5 seconds. Core: 202 samples, slope 0.6286 MiB/min, change 20.176 MiB.
Simulator: 202 samples, slope 0.0818 MiB/min, change 1.734 MiB.
Leak limits for the ten-minute run: slope at most 1.0 MiB/min and start-to-end growth at most 32 MiB per process. The slope permits up to 10 MiB of growth over ten minutes; the separate limit absorbs working-set noise.
Peak observed process handles: core 349, simulator 1135. Asyncio task counts were not sampled.

## Coverage and limits

- Simulator, core, fake Gnani, and voice bots ran as separate processes against the task's PostgreSQL database.
- Fake Prisma decoded a test-only text marker carried in synthetic PCM. The marker is not audible speech and is never sent to live Gnani.
- Fake Timbre returned deterministic PCM over REST and paced SSE chunks. The timings describe the local emulator only.
- The run covered decision, approval, repair, verification, reveal, event-log replay, call heartbeats, barge-in, silence re-prompt and release, question withdrawal, and stream-cap refusal.
- No live Gnani run was performed. This report does not measure real speech recognition, real TTS, provider latency, or live account capacity.
- Process handles were sampled. Asyncio task counts, file descriptor types, network packet loss, and live Gnani behavior were not measured.

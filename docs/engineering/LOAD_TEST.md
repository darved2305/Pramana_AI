# Voice load test

The process-level harness in `tests/load` exercises one core, one simulator, a local Gnani
emulator, and complete S1 voice investigations, including repair, verification, reveal, and
event-log replay. The measured window begins when the first three participant call sockets are
open and lasts for the requested duration. Up to three S1 runs can overlap at a handoff. The
harness starts a third run when five or fewer participant call sockets remain, and it limits the
total to nine sockets. The report records every interval below three calls; a full run
permits at most two seconds per gap and at most one percent uncovered time.

## Emulated run

The emulator implements the Gnani surfaces used by a call: realtime STT WebSocket, STT REST
confirmation decode, TTS REST, and TTS SSE. It listens on port 8310 by default. Core, simulator,
and fake-provider ports are 8210, 8110, and 8310. The harness starts and stops these as separate
processes. It starts the shared PostgreSQL cluster if needed and uses its own `pramana_load_fa31`
database; it never uses `pramana_test`.

For the short process test, set the load opt-in and a separate database URL:

```powershell
$env:PG_BIN = 'C:\Users\Nikhil\scoop\apps\postgresql\current\bin'
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://pramana@localhost:5433/pramana_test_fa31'
$env:PRAMANA_LOAD_DATABASE_URL = 'postgresql+asyncpg://pramana@localhost:5433/pramana_load_fa31_short'
$env:PRAMANA_RUN_LOAD = '1'
uv run pytest -m load tests/load/test_load_harness.py -q
```

The test is skipped by default and measures a 75-second window. The live-mode test also runs the
harness with local marker-carrying WAV clips and a local provider emulator. Both modes check close
matching, replay, call coverage, stream limits, and sampling. Keep `TEST_DATABASE_URL` on a
builder-specific test database for every pytest invocation.

Run the full emulated load from the repository root:

```powershell
$env:PG_BIN = 'C:\Users\Nikhil\scoop\apps\postgresql\current\bin'
uv run python tests/load/run_load.py `
  --duration-seconds 600 `
  --database-url postgresql+asyncpg://pramana@localhost:5433/pramana_load_fa31 `
  --report-dir eval/reports/load-YYYY-MM-DD
```

Use the UTC run date in the report directory. If `--report-dir` is omitted for a 600-second
emulated run, the CLI selects `eval/reports/load-<UTC date>` automatically. The harness probes
the stream governor at a cap of two, verifies that a third concurrent stream is refused, then
restarts core with the regular cap for the load. It exercises silent-call re-prompt and release,
an idle heartbeat, barge-in, question withdrawal, and decision-critical REST confirmation.
Participants send deterministic, test-only PCM that carries the intended transcript after a
marker. The emulator decodes that marker; this is not speech and must never be used in live mode.

The report contains process RSS samples at five-second intervals, handle counts, governor and
provider stream peaks, stream and call WebSocket close events correlated by session ID, call
coverage and handoff gaps, investigation correctness, reveal checks, replay equality, and emulated
end-of-speech to answer latency percentiles. A full run fails if RSS slope exceeds 1 MiB per minute
or total growth exceeds 32 MiB. Latency values describe the local emulator only and do not
estimate Gnani performance.

## Live Gnani run

The harness accepts real PCM clips in live mode. `GNANI_API_KEY` must be present in the process
environment or the worktree `.env`, and `--clips` must point to 16 kHz mono PCM16 clips with the
filenames expected by `scripts/voice_bot_run.py`. The core retains its daily budget and rate
guards. Live runs use the same result, close, call coverage, stream-cap, sampling, and full-run RSS
checks. Investigation results and provider timings stay in process output and are not written to
`eval/reports`. The CLI writes a private evidence JSON file under the configured scratch directory
and prints its path. It retains investigation checks and close details while omitting provider
latency measurements.

```powershell
uv run python tests/load/run_load.py `
  --live `
  --duration-seconds 600 `
  --database-url postgresql+asyncpg://pramana@localhost:5433/pramana_load_fa31 `
  --clips C:\path\to\voice-clips
```

Do not use `--synthetic` audio with a live provider. The opt-in local stand-in test exercises the
live-mode code path without contacting Gnani. It does not measure live provider behavior; schedule
the live command separately when a key and suitable clips are available.

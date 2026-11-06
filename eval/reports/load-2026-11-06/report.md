# Load test report (generated; do not edit)

Commit `c288652`. Gnani was **emulated**; the simulator, core,
PostgreSQL, call sockets, recognizer sessions, extractor, engine, approvals and
verification were real. 10.0 minutes of back-to-back investigations, three
participants each, up to three questions in flight, question audio streamed to every
call.

| Measure | Value |
|---|---|
| Investigations run | 45 |
| Verified, correct on reveal | 45 of 45 |
| Replay byte-identical | 45 of 45 |
| Runs that ended as expected | 45 of 45 |
| Call socket errors | 0 |
| Voice answers | 311 |
| Most questions in flight at once | 3 |
| Questions withdrawn | 5 |
| Recognizer sessions (total / most at once / open at the end) | 316 / 3 / 0 |
| Governor stream cap | 16 |
| Second decodes (REST) | 131 |
| Streamed question audio | 9 |
| Core memory MB (first / max / last) | 111.2 / 141.0 / 132.8 |
| Core memory MB (mean, first half / second half) | 129.9 / 136.8 |

**Result: passed.**

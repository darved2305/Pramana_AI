# Load test report (generated; do not edit)

Commit `f660b62`. Gnani was **emulated**; the simulator, core,
PostgreSQL, call sockets, recognizer sessions, extractor, engine, approvals and
verification were real. 40.0 minutes of back-to-back investigations, three
participants each, up to three questions in flight, question audio streamed to every
call.

| Measure | Value |
|---|---|
| Investigations run | 160 |
| Verified, correct on reveal | 160 of 160 |
| Replay byte-identical | 160 of 160 |
| Runs that ended as expected | 160 of 160 |
| Call socket errors | 0 |
| Voice answers | 1110 |
| Most questions in flight at once | 3 |
| Questions withdrawn | 15 |
| Recognizer sessions (total / most at once / open at the end) | 1125 / 3 / 0 |
| Governor stream cap | 16 |
| Second decodes (REST) | 470 |
| Streamed question audio | 8 |
| Core memory MB (first / max / last) | 111.6 / 140.7 / 135.7 |
| Core memory MB (mean, first half / second half) | 133.2 / 132.8 |
| Core RSS slope after warm-up (MB/min) | 0.11728153328082362 |
| Simulator RSS slope after warm-up (MB/min) | 0.0255891804391279 |
| Memory growth gate (<= 0.5 MB/min each) | passed |

**Result: passed.**

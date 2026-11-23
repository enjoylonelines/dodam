# First A/B and bounded refinement

The first fixed 16-case × 2 repeats × A/B run completed 64 rows and is retained at 2026-11-23-function-calling-ab.json. A exact task match 10/32; B 28/32. B failed one two-policy summary and three ambiguous-reference rows because a single-policy tool received two policy references. The result must not be overwritten by a repaired rerun.

One follow-up sweep is authorized by the implementation/validation task and capped at another 64 rows, on the same dataset. Changes before this sweep: expose single-policy cardinality in the native tool schema; deterministic server check that ambiguous demonstratives with multiple known policies require user selection; focused adapter hardening and regression. This tests the candidate system as a whole, not Function Calling in isolation. Improvement on ambiguous references is attributable to the server check, not proof of better model understanding. No prompt/data tuning after this sweep. Source hashes are pinned for resume.

Business services in both arms are synthetic fixtures. Full answer truthfulness, real retrieval and operational deployment are not evaluated. Current .env points to loopback PostgreSQL port 55432, which is not running; the service-level live DB smoke cannot use that environment. Existing unrelated containers were not modified.

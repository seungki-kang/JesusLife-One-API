# Synthetic ACK coordinator experiment

Run from the repository root (Python standard library only):

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tools/ack_coordinator -v
```

This isolated experiment imports no application code and uses no network,
database, environment files, or persistent storage. Use synthetic account labels
only. Real-data collection remains **BLOCKED**.

Each request captures an immutable account, session epoch, and coordinator-local
monotonic operation ID. Every session replacement (including the same account)
and every logout increments the epoch. A matching pending request can apply one
synthetic effect only while its account and epoch are current. Acceptance consumes
that pending request; rejection, including duplicate ACKs, changes no state.
The effect is simply an entry in an in-memory tuple exposed through a snapshot.

Calls are sequential and inputs are trusted, typed synthetic values. ACKs carry
the captured request identity; they are not authenticated messages. Old pending
requests deliberately remain in memory across session changes to exercise the
epoch guard. There is no retry, expiry, cleanup, or cross-instance identity
protocol; a new request gets a new operation ID. Memory is unbounded and discarded
on process exit.

The test-only `NoEpochControl` omits the current-epoch comparison. Its test passes
by demonstrating the bug: after A to B to A, the first A session's ACK incorrectly
applies an effect. The guarded coordinator rejects the same sequence.

This experiment does not prove actual authentication, disk recovery,
thread/process atomicity, database locking, or production safety. Application
integration and protected policy changes are outside its scope.

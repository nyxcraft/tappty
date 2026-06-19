# Protocol and API contract review

## Scope

Reviewed bus frame shapes, request/reply semantics, payload validation, client behavior,
and public API affordances.

No high-severity findings. The bus is compact and debuggable, and the security hardening
around token type, newline injection, frame size, and capture size is in place.

## Findings

### Medium: `HELLO` assumes valid JSON is an object

Evidence:

`_h_hello()` catches only JSON parse errors, then calls `.get()` on the decoded value
(`src/tappty/bus.py:225`). A payload such as `HELLO 123` or `HELLO []` is valid JSON but
not a dict; non-string or unhashable `name`/`role` values can also reach controller logic
(`src/tappty/bus.py:237`).

Impact:

A malformed client can raise `AttributeError` or `TypeError` in the serve thread. The
connection will eventually be dropped by the thread's `finally`, but the server gets a
noisy traceback and the protocol does not return a clean denial.

Recommendation:

After decoding, require `isinstance(info, dict)`. Then require `name`, `role`, and `token`
when present to be strings. Send `DENIED` or ignore malformed `HELLO` frames consistently.

### Medium: request/reply messages have no correlation id

Evidence:

`BusClient.wait_for()` drains the single inbox until it sees a matching verb and discards
intervening messages (`src/tappty/bus.py:443`). `snap()` and `cmd()` both use this shared
verb-only wait path (`src/tappty/bus.py:460`, `src/tappty/bus.py:464`).

Impact:

This is fine for a single synchronous client before subscription, as documented. It is
fragile for subscribed clients, concurrent caller threads, or clients issuing overlapping
requests: pushed events/frames can be dropped, and replies cannot be matched to requests.

Recommendation:

Either document `BusClient` as single-consumer/single-request-at-a-time, or add optional
request ids for `SNAP`, `INFO`, and `CMD` replies. A smaller client-side improvement is a
filtered wait that buffers unmatched messages instead of discarding them.

### Low: bus protocol docstring is stale

Evidence:

The protocol list in `bus.py` omits `CMD` and `RESP`, and the event list omits newer events
such as `DRIVER` and `ERROR` (`src/tappty/bus.py:9`). The handlers and client API do
support `CMD`/`RESP` (`src/tappty/bus.py:105`, `src/tappty/bus.py:262`,
`src/tappty/bus.py:464`).

Impact:

The canonical design docs are better, but the in-code protocol summary is the first thing a
client implementer will read. Drift here makes external clients easier to get wrong.

Recommendation:

Update the docstring to include `CMD`, `RESP`, `timeout`, `truncated`, `cancelled`, and the
current event names.

### Low: `BusClient.send()` has an implicit string-only payload contract

Evidence:

`send()` checks for `"\n" in payload` and then concatenates payload into a frame
(`src/tappty/bus.py:417`).

Impact:

Internal helpers pass strings, so this is not a current bug. Third-party callers passing
non-strings get incidental `TypeError`s rather than a contract error.

Recommendation:

Validate `isinstance(payload, str)` and raise `TypeError("payload must be str")`, or
document that `send()` is a low-level string-frame API.

## Positive notes

- The server has an explicit handler table and ignores unknown verbs, which is a good
  forward-compatibility posture (`src/tappty/bus.py:103`, `src/tappty/bus.py:220`).
- `KEY` now validates that decoded JSON is a string before feeding keys
  (`src/tappty/bus.py:311`).
- `CMD` replies distinguish completed, timed out, truncated, and cancelled captures
  (`src/tappty/bus.py:277`).

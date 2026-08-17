# Reservation Sweeper — design

## Problem

A request reserves budget (`RESERVE`, reserved_amount += E) before calling the
LLM. If the process crashes after reserve but before `settle`/`release`
(provider timeout, OOM, kill -9), the reservation leaks until the period rolls
over — shrinking available budget for everyone else (ADR-003,
docs/production-scenarios.md scenario 7).

## Rule

A reservation older than `RESERVATION_TTL` (default 15 minutes) with no
settled usage for that request is **stale** and must be released.

## What it does

```
every N minutes (cron / scheduled job):
  SELECT b.id, bc.period_key, bc.reserved_amount
  FROM budget_consumption bc JOIN budgets b ON b.id = bc.budget_id
  WHERE bc.reserved_amount > 0
    AND bc.updated_at < now() - interval '15 minutes'
  FOR UPDATE OF bc;

  for each row:
    # safety: never release committed spend — only the reservation.
    release = min(reserved_amount, row.reserved_amount)
    reserved_amount -= release
    INSERT budget_events(event_type='RELEASE', amount=release,
                         request_id=NULL, details={'sweeper': true, 'reason': 'stale'})
  COMMIT
```

## Safety

- **Never touches `committed_amount`** — committed spend is real money.
- **TTL is generous** (15 min) so a slow-but-live provider call is not
  cannibalized. The generate path's `settle` still consumes the reservation
  exactly (`apply_overage`), so a released-then-settled request lands in
  committed and cannot double-count.
- Runs inside one transaction with `FOR UPDATE`, so it cannot race a live
  reserve/settle.
- The `request_id` column on the RELEASE event is NULL (the reservation is
  already orphaned); `details.reason='stale'` makes sweeper actions auditable.

## Where it plugs in

- Stub: `scripts/expire_reservations.py` (dry-run by default; `--apply` to
  mutate).
- Production: run on a cron (e.g. every 5 min) or a simple `asyncio` loop in a
  sidecar; the script is the reference implementation.

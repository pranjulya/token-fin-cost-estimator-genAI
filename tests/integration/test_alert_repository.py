"""Integration tests for AlertRepository — create_if_absent dedupe + list/get/ack."""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import Alert
from app.repositories.alert_repository import AlertRepository

ARGS = dict(
    alert_type="BUDGET_THRESHOLD",
    severity="WARNING",
    scope_type="TEAM",
    scope_id="platform-team",
    request_id="req_1",
    message="test alert",
    metadata={"decision": "WARN"},
    dedupe_key="BUDGET_THRESHOLD:42:2026-08:WARN",
)


class TestCreateIfAbsent:
    async def test_insert_then_dedupe(self, db_session):
        repo = AlertRepository(db_session)
        row = await repo.create_if_absent(**ARGS)
        assert row is not None
        assert row.dedupe_key == ARGS["dedupe_key"]
        assert row.metadata_json == {"decision": "WARN"}

        # Same dedupe_key -> None, and still exactly one row.
        again = await repo.create_if_absent(**ARGS)
        assert again is None
        count = await db_session.scalar(select(func.count()).select_from(Alert))
        assert count == 1
        await db_session.commit()

    async def test_distinct_dedupe_keys_both_insert(self, db_session):
        repo = AlertRepository(db_session)
        a = await repo.create_if_absent(**ARGS)
        b = await repo.create_if_absent(
            **{**ARGS, "dedupe_key": "BUDGET_THRESHOLD:42:2026-08:CRITICAL"}
        )
        assert a is not None and b is not None


class TestListGetAck:
    async def _seed(self, db_session, **overrides) -> Alert:
        return await AlertRepository(db_session).create_if_absent(**{**ARGS, **overrides})

    async def test_list_defaults_newest_first(self, db_session):
        repo = AlertRepository(db_session)
        await self._seed(db_session, dedupe_key="k1", alert_type="BUDGET_THRESHOLD")
        await self._seed(db_session, dedupe_key="k2", alert_type="COST_ANOMALY")
        rows = await repo.list(limit=50)
        assert len(rows) == 2
        # newest first
        assert rows[0].dedupe_key == "k2"

    async def test_list_filters(self, db_session):
        repo = AlertRepository(db_session)
        await self._seed(db_session, dedupe_key="k1", severity="WARNING")
        await self._seed(db_session, dedupe_key="k2", severity="CRITICAL")
        crit = await repo.list(severity="CRITICAL")
        assert len(crit) == 1 and crit[0].dedupe_key == "k2"

    async def test_open_only(self, db_session):
        repo = AlertRepository(db_session)
        await self._seed(db_session, dedupe_key="k1")
        row = await self._seed(db_session, dedupe_key="k2")
        await repo.acknowledge(row)
        await db_session.commit()
        open_rows = await repo.list(open_only=True)
        assert [r.dedupe_key for r in open_rows] == ["k1"]

    async def test_ack_idempotent(self, db_session):
        repo = AlertRepository(db_session)
        row = await self._seed(db_session, dedupe_key="k1")
        a = await repo.acknowledge(row)
        assert a.acknowledged_at is not None
        first = a.acknowledged_at
        b = await repo.acknowledge(row)
        assert b.acknowledged_at == first  # unchanged, not refreshed

    async def test_get(self, db_session):
        row = await self._seed(db_session, dedupe_key="k1")
        assert (await AlertRepository(db_session).get(row.id)) is not None
        assert (await AlertRepository(db_session).get(99999)) is None

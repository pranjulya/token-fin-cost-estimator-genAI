"""HTTP integration tests for the alerts API (Phase 13)."""

from __future__ import annotations

from app.repositories.alert_repository import AlertRepository


async def _seed(session, **overrides) -> int:
    args = dict(
        alert_type="BUDGET_THRESHOLD",
        severity="WARNING",
        scope_type="TEAM",
        scope_id="platform-team",
        request_id="req_1",
        message="budget at 70%",
        metadata={"decision": "WARN"},
        dedupe_key="BUDGET_THRESHOLD:42:2026-08:WARN",
    )
    args.update(overrides)
    row = await AlertRepository(session).create_if_absent(**args)
    return row.id


class TestListAlerts:
    async def test_list_and_open_only(self, client, db_session):
        await _seed(db_session)
        await _seed(
            db_session,
            severity="CRITICAL",
            dedupe_key="BUDGET_THRESHOLD:42:2026-08:CRITICAL",
            message="budget at 90%",
        )
        await db_session.commit()

        rows = (await client.get("/v1/alerts")).json()
        assert len(rows) == 2
        # newest first
        assert rows[0]["message"] == "budget at 90%"

        open_rows = (await client.get("/v1/alerts", params={"open_only": True})).json()
        assert len(open_rows) == 2

    async def test_filter_by_severity(self, client, db_session):
        await _seed(db_session)
        await _seed(
            db_session,
            severity="CRITICAL",
            dedupe_key="BUDGET_THRESHOLD:42:2026-08:CRITICAL",
        )
        await db_session.commit()

        rows = (await client.get("/v1/alerts", params={"severity": "CRITICAL"})).json()
        assert len(rows) == 1
        assert rows[0]["severity"] == "CRITICAL"

    async def test_invalid_alert_type_rejected(self, client, db_session):
        resp = await client.get("/v1/alerts", params={"alert_type": "BOGUS"})
        assert resp.status_code == 422


class TestGetAcknowledge:
    async def test_get_and_acknowledge(self, client, db_session):
        alert_id = await _seed(db_session)
        await db_session.commit()

        got = await client.get(f"/v1/alerts/{alert_id}")
        assert got.status_code == 200
        assert got.json()["dedupe_key"] == "BUDGET_THRESHOLD:42:2026-08:WARN"
        # not yet acknowledged
        assert got.json()["acknowledged_at"] is None

        ack = await client.post(f"/v1/alerts/{alert_id}/acknowledge")
        assert ack.status_code == 200
        assert ack.json()["acknowledged_at"] is not None

        # now excluded from open_only listing
        after = (await client.get("/v1/alerts", params={"open_only": True})).json()
        assert after == []

    async def test_get_404(self, client, db_session):
        assert (await client.get("/v1/alerts/99999")).status_code == 404

    async def test_ack_404(self, client, db_session):
        assert (await client.post("/v1/alerts/99999/acknowledge")).status_code == 404

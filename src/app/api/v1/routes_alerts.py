"""Alert read/ack routes (Phase 13). Alerts are system-generated, not POSTable."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import require_admin
from app.api.dependencies import alert_service_dep
from app.core.audit import audit, key_actor
from app.core.exceptions import InvalidRequestError
from app.db.models import Alert
from app.schemas.alerts import ALERT_TYPES, SEVERITIES, AlertOut
from app.services.alert_service import AlertService

router = APIRouter(prefix="/alerts", tags=["alerts"])


async def _get_or_404(service: AlertService, alert_id: int) -> Alert:
    alert = await service.get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return alert


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    service: AlertService = Depends(alert_service_dep),
    alert_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    scope_type: str | None = Query(default=None),
    scope_id: str | None = Query(default=None),
    open_only: bool = Query(default=False),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[AlertOut]:
    if alert_type is not None and alert_type not in ALERT_TYPES:
        raise InvalidRequestError(f"alert_type must be one of {sorted(ALERT_TYPES)}")
    if severity is not None and severity not in SEVERITIES:
        raise InvalidRequestError(f"severity must be one of {sorted(SEVERITIES)}")
    rows = await service.list_alerts(
        alert_type=alert_type,
        severity=severity,
        scope_type=scope_type,
        scope_id=scope_id,
        open_only=open_only,
        limit=limit,
        offset=offset,
    )
    return [AlertOut.model_validate(r) for r in rows]


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert(alert_id: int, service: AlertService = Depends(alert_service_dep)) -> AlertOut:
    return AlertOut.model_validate(await _get_or_404(service, alert_id))


@router.post("/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge_alert(
    alert_id: int,
    service: AlertService = Depends(alert_service_dep),
    key: str = Depends(require_admin),
) -> AlertOut:
    alert = await _get_or_404(service, alert_id)
    row = await service.acknowledge(alert)
    audit(
        "audit_alert_acknowledged",
        actor=key_actor(key),
        alert_id=row.id,
        alert_type=row.alert_type,
    )
    return AlertOut.model_validate(row)

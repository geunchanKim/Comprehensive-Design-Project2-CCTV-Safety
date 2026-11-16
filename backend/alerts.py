"""Durable occurrences. Writers serialize on the dashboard condition row."""
import time
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

try:
    from .dashboard import AlertState, ContractModel
    from .dashboard_api import condition, state_query
    from .database import get_db
    from .models import DashboardAlert
except ImportError:
    from dashboard import AlertState, ContractModel
    from dashboard_api import condition, state_query
    from database import get_db
    from models import DashboardAlert

router = APIRouter(prefix="/alerts", tags=["alerts"])


def alert_query(key):
    return select(DashboardAlert).where(
        DashboardAlert.session_id == key[0],
        DashboardAlert.calibration_profile == key[1],
        DashboardAlert.algorithm == key[2])


def as_state(row):
    return AlertState(
        alert_id=row.alert_id, stream_id=row.stream_id, **row.details,
        level=row.level, reached_danger=row.reached_danger,
        started_at_ms=row.started_at_ms, last_seen_at_ms=row.last_seen_at_ms,
        ended_at_ms=row.ended_at_ms, active=row.active_key is not None,
        acknowledged=row.acknowledged_at_ms is not None,
        acknowledged_at_ms=row.acknowledged_at_ms, action=row.action)


def visible_alerts(db, key):
    return [as_state(row) for row in db.scalars(alert_query(key).where(or_(
        DashboardAlert.active_key.is_not(None),
        (DashboardAlert.reached_danger.is_(True)
         & DashboardAlert.acknowledged_at_ms.is_(None)),
    )).order_by(DashboardAlert.started_at_ms, DashboardAlert.alert_id))]


def end_active(db, key, now, *, kind=None):
    for row in db.scalars(alert_query(key).where(DashboardAlert.active_key.is_not(None))):
        if kind is None or row.details["kind"] == kind:
            row.active_key = None
            row.ended_at_ms = now
    db.flush()


def sync_alerts(db, key, snapshot, now):
    candidates = {}
    if snapshot.collision_evaluated:
        for risk in snapshot.risks:
            if risk.level in {"warning", "danger"}:
                ids = sorted((risk.object1_id, risk.object2_id))
                candidates[f"collision:{ids[0]}:{ids[1]}"] = (risk.level, {
                    "kind": "collision", "object_ids": ids, "zone_id": None,
                    "distance_m": risk.distance_m})
    if snapshot.zone_evaluated:
        for obj in snapshot.objects:
            for zone in obj.zone_states:
                if zone.status in {"warning", "intrusion"}:
                    candidates[f"zone:{obj.object_id}:{zone.zone_id}"] = (
                        "danger" if zone.status == "intrusion" else "warning", {
                            "kind": "zone", "object_ids": [obj.object_id],
                            "zone_id": zone.zone_id, "distance_m": zone.distance_m})
    active = {row.active_key: row for row in db.scalars(
        alert_query(key).where(DashboardAlert.active_key.is_not(None)))}
    for target, row in active.items():
        if target not in candidates:
            row.active_key = None
            row.ended_at_ms = now
    for target, (level, details) in candidates.items():
        row = active.get(target)
        if row is None:
            row = DashboardAlert(
                alert_id=str(uuid4()), session_id=key[0], calibration_profile=key[1],
                algorithm=key[2], stream_id=snapshot.stream_id, active_key=target,
                details=details, level=level, reached_danger=level == "danger",
                started_at_ms=now, last_seen_at_ms=now)
            db.add(row)
        else:
            # Escalation requires attention again, while preserving occurrence ID.
            if level == "danger" and row.level != "danger":
                row.acknowledged_at_ms = None
                row.action = None
            row.level = level
            row.reached_danger = row.reached_danger or level == "danger"
            row.last_seen_at_ms = now
            row.details = details
    db.flush()
    return visible_alerts(db, key)


@router.get("", response_model=list[AlertState])
def get_alerts(key=Depends(condition), db: Session = Depends(get_db)):
    return Response(
        "[" + ",".join(item.model_dump_json() for item in visible_alerts(db, key)) + "]",
        media_type="application/json", headers={"Cache-Control": "no-store"})


class Acknowledge(ContractModel):
    action: Literal["radio", "dispatch", "false-positive"] | None


@router.post("/{alert_id}/ack", status_code=204)
def acknowledge(alert_id: str, body: Acknowledge, key=Depends(condition),
                db: Session = Depends(get_db)):
    # Same lock and ordering as detection publication and zone edits.
    state = db.scalar(state_query(key).with_for_update())
    row = db.scalar(alert_query(key).where(DashboardAlert.alert_id == alert_id))
    if state is None or row is None:
        raise HTTPException(404, "alert not found for this condition")
    if row.acknowledged_at_ms is None:
        row.acknowledged_at_ms = time.time_ns() // 1_000_000
        row.action = body.action
    db.commit()
    return Response(status_code=204)

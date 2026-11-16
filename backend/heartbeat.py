"""Edge liveness uses server time; frame freshness uses only edge time."""
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator
from sqlalchemy import BigInteger, cast, or_
from sqlalchemy.orm import Session

try:
    from .dashboard import ContractModel
    from .database import get_db
    from .models import EdgeHeartbeat
except ImportError:
    from dashboard import ContractModel
    from database import get_db
    from models import EdgeHeartbeat

router = APIRouter(prefix="/edge", tags=["edge"])


class Heartbeat(ContractModel):
    session_id: str = Field(min_length=1, max_length=128)
    camera_id: str = Field(min_length=1, max_length=128)
    edge_run_id: str = Field(min_length=1, max_length=128)
    source: Literal["rtsp", "folder"]
    last_recv_ms: int | None = Field(default=None, ge=0, le=2**63 - 1)
    sent_at_ms: int = Field(ge=0, le=2**63 - 1)
    dropped_count: int = Field(ge=0)
    max_queue_age_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered_clock(self):
        if self.last_recv_ms is not None and self.last_recv_ms > self.sent_at_ms:
            raise ValueError("last_recv_ms must not exceed sent_at_ms")
        return self


@router.post("/heartbeat", status_code=204)
def heartbeat(body: Heartbeat, db: Session = Depends(get_db)):
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise HTTPException(503, "heartbeat storage requires PostgreSQL or SQLite")
    values = dict(session_id=body.session_id, camera_id=body.camera_id,
                  payload=body.model_dump(mode="json"), received_at_ms=time.time_ns() // 1_000_000)
    statement = insert(EdgeHeartbeat).values(**values)
    db.execute(statement.on_conflict_do_update(
        index_elements=[EdgeHeartbeat.session_id, EdgeHeartbeat.camera_id],
        set_={"payload": statement.excluded.payload, "received_at_ms": statement.excluded.received_at_ms},
        where=or_(EdgeHeartbeat.payload["edge_run_id"].as_string() != body.edge_run_id,
                  cast(EdgeHeartbeat.payload["sent_at_ms"].as_string(), BigInteger) < body.sent_at_ms)))
    db.commit()


def connection_state(row, now):
    if row is None:
        return {"online": None, "receive_status": "unknown", "heartbeat": None}
    data = row.payload
    age = max(0, now - row.received_at_ms)
    frame_age = None if data["last_recv_ms"] is None else data["sent_at_ms"] - data["last_recv_ms"] + age
    return {"online": age < 3000,
            "receive_status": "unknown" if frame_age is None else ("recent" if frame_age < 2000 else "stale"),
            "heartbeat": {**data, "server_received_at_ms": row.received_at_ms}}

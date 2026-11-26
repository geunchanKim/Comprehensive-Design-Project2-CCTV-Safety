"""Per-global-object PPE smoothing; raw samples remain in source_frames."""
import os

from sqlalchemy import select

try:
    from .models import GlobalObject
    from .schemas import PPEState
except ImportError:
    from models import GlobalObject
    from schemas import PPEState

PPE_CONFIRM_SAMPLES = int(os.getenv("PPE_CONFIRM_SAMPLES", "3"))
PPE_MIN_CONFIDENCE = float(os.getenv("PPE_MIN_CONFIDENCE", "0.4"))
PPE_MAX_AGE_MS = int(os.getenv("PPE_MAX_AGE_MS", "3000"))
if PPE_CONFIRM_SAMPLES < 1 or PPE_MAX_AGE_MS < 1 or not 0 <= PPE_MIN_CONFIDENCE <= 1:
    raise ValueError("invalid PPE smoothing settings")


def settings():
    return {"confirm_samples": PPE_CONFIRM_SAMPLES, "min_confidence": PPE_MIN_CONFIDENCE,
            "max_age_ms": PPE_MAX_AGE_MS}


def advance(previous, samples, now):
    """One vote per pair, never per camera or cached frame. Unknown breaks streaks."""
    state = dict(previous or {})
    last = state.get("observed_at_ms")
    if now < state.get("frame_at_ms", last or 0):
        return state, PPEState()  # Late input must not rewrite later state.
    if last is not None and now - last > PPE_MAX_AGE_MS:
        state = {"observed_at_ms": last}  # Retain watermark, discard old certainty/streak.
    fresh = [s for s in samples if 0 <= now - s.observed_at_ms <= PPE_MAX_AGE_MS]
    newest = max((s.observed_at_ms for s in fresh), default=None)
    if newest is not None and (last is None or newest > last):
        statuses = {s.status for s in fresh}
        ambiguous = (len(statuses) != 1 or "unknown" in statuses
                     or any(s.confidence is None or s.confidence < PPE_MIN_CONFIDENCE for s in fresh))
        if ambiguous:
            state = {"observed_at_ms": newest}
        else:
            candidate = next(iter(statuses))
            count = min(PPE_CONFIRM_SAMPLES, state.get("count", 0) + 1) if state.get("candidate") == candidate else 1
            # A contradictory observation is unknown until the new streak confirms.
            state = {"observed_at_ms": newest, "candidate": candidate, "count": count,
                     "confidence": min(s.confidence for s in fresh),
                     "status": candidate if count >= PPE_CONFIRM_SAMPLES else "unknown"}
    state["frame_at_ms"] = now
    status = state.get("status", "unknown")
    return state, PPEState(status=status,
                           confidence=state.get("confidence") if status != "unknown" else None,
                           observed_at_ms=state.get("observed_at_ms"))


def attach_ppe(db, body, matches):
    people = {m["object_id"]: m for m in matches if m["cls"] == "person"}
    if not people:
        return
    # Lock in deterministic order, in the same transaction as detection and snapshot.
    rows = db.scalars(select(GlobalObject).where(GlobalObject.id.in_(people))
                      .order_by(GlobalObject.id).with_for_update()).all()
    lookup = {(f.camera_id, d.track_id): d for f in body.frames for d in f.detections}
    now = max(f.ts for f in body.frames)
    for row in rows:
        match = people[row.id]
        stored = dict(row.ppe_state or {})
        if stored.get("settings") != settings():
            stored = {"settings": settings()}
        for item in ("vest", "helmet"):
            samples = [getattr(lookup[(camera, track)], item)
                       for camera, track in match["camera_tracks"].items()
                       if (camera, track) in lookup and getattr(lookup[(camera, track)], item) is not None]
            stored[item], output = advance(stored.get(item), samples, now)
            match[item] = output.model_dump(mode="json")
        row.ppe_state = stored

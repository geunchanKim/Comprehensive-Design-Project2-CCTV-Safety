"""Week-one dashboard contract. Transport and zone/PPE evaluation come later."""
from math import isclose
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

try:
    from .schemas import CalibrationProfile, DetectionBundleOut, ObjectClass, RiskResult, WorldPoint
except ImportError:  # Docker runs this directory as the import root.
    from schemas import CalibrationProfile, DetectionBundleOut, ObjectClass, RiskResult, WorldPoint


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _intersects(a, b, c, d):
    def on_segment(a, b, p):
        return (isclose(_cross(a, b, p), 0.0, abs_tol=1e-9)
                and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
                and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))

    return ((_cross(a, b, c) * _cross(a, b, d) < 0
             and _cross(c, d, a) * _cross(c, d, b) < 0)
            or any((on_segment(a, b, c), on_segment(a, b, d),
                    on_segment(c, d, a), on_segment(c, d, b))))


class RiskZone(ContractModel):
    zone_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    vertices: list[tuple[float, float]] = Field(min_length=3, max_length=64)
    warning_distance_m: float = Field(ge=0)
    enabled: bool = True

    @model_validator(mode="after")
    def simple_polygon(self):
        points = self.vertices
        if len(set(points)) != len(points):
            raise ValueError("vertices must be distinct; do not repeat the closing vertex")
        area = sum(a[0] * b[1] - a[1] * b[0]
                   for a, b in zip(points, points[1:] + points[:1]))
        if abs(area) < 1e-9:
            raise ValueError("polygon must have positive area")
        size = len(points)
        for i in range(size):
            a, b = points[i], points[(i + 1) % size]
            c = points[(i + 2) % size]
            if isclose(_cross(a, b, c), 0.0, abs_tol=1e-9):
                raise ValueError("adjacent edges must not be collinear")
            for j in range(i + 1, size):
                if j == i + 1 or (i == 0 and j == size - 1):
                    continue
                if _intersects(a, b, points[j], points[(j + 1) % size]):
                    raise ValueError("polygon must not self-intersect or touch itself")
        return self


class ZoneSet(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    coordinate_system: Literal["world_xy_m"] = "world_xy_m"
    zones: list[RiskZone]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [zone.zone_id for zone in self.zones]
        if len(ids) != len(set(ids)):
            raise ValueError("zone_id must be unique")
        return self


class VestState(ContractModel):
    status: Literal["wearing", "not_wearing", "unknown"] = "unknown"
    confidence: float | None = Field(default=None, ge=0, le=1)
    observed_at_ms: int | None = Field(default=None, ge=0)


class ZoneState(ContractModel):
    zone_id: str
    status: Literal["outside", "warning", "intrusion", "unknown"] = "unknown"
    distance_m: float | None = Field(default=None, ge=0)


class DashboardObject(ContractModel):
    object_id: int
    cls: ObjectClass
    world: WorldPoint
    velocity: WorldPoint | None = None
    camera_tracks: dict[str, int]
    vest: VestState = Field(default_factory=VestState)
    zone_states: list[ZoneState] = Field(default_factory=list)


class DashboardSnapshot(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    event: Literal["snapshot"] = "snapshot"
    session_id: str
    calibration_profile: CalibrationProfile
    algorithm: str
    pair_id: int
    captured_at_ms: int = Field(ge=0)
    emitted_at_ms: int = Field(ge=0)
    objects: list[DashboardObject]
    collision_evaluated: bool
    risks: list[RiskResult]
    zones: list[RiskZone]
    zone_evaluated: bool = False
    vest_evaluated: bool = False


def build_snapshot(result: DetectionBundleOut, *, algorithm: str,
                   captured_at_ms: int, emitted_at_ms: int, zones: ZoneSet) -> DashboardSnapshot:
    """Adapt existing results without inventing safe/PPE/zone decisions."""
    return DashboardSnapshot(
        session_id=result.session_id, calibration_profile=result.calibration_profile,
        algorithm=algorithm, pair_id=result.pair_id, captured_at_ms=captured_at_ms,
        emitted_at_ms=emitted_at_ms,
        objects=[DashboardObject(
            object_id=item.object_id, cls=item.cls, world=item.world, velocity=item.velocity,
            camera_tracks=item.camera_tracks,
            zone_states=[ZoneState(zone_id=zone.zone_id) for zone in zones.zones
                         if zone.enabled and item.cls == "person"],
        ) for item in result.matches],
        collision_evaluated=bool(result.settings.get("risk_analysis")
                                 or result.settings.get("warning_hysteresis")),
        risks=result.risks, zones=zones.zones,
    )

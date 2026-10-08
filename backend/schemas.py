from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ObjectClass = Literal["person", "chair", "cart", "desk", "suitcase", "backpack"]
FootSource = Literal["ankle", "box"]
CalibrationMethod = Literal["unity-gt", "charuco-aruco"]
CalibrationProfile = Literal["basic", "precise"]


class CameraCalibrationIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    calibration_profile: CalibrationProfile = "basic"
    method: CalibrationMethod
    image_size: tuple[int, int]
    K: list[list[float]]
    dist: list[float]
    rvec: tuple[float, float, float]
    tvec: tuple[float, float, float]
    reproj_error_px: float = Field(ge=0)
    validation_rmse_cm: float | None = Field(default=None, ge=0)
    validation_max_error_cm: float | None = Field(default=None, ge=0)
    validation_point_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_calibration(self):
        if any(value <= 0 for value in self.image_size):
            raise ValueError("image_size must contain positive values")
        if len(self.K) != 3 or any(len(row) != 3 for row in self.K):
            raise ValueError("K must be a 3x3 matrix")
        if len(self.dist) != 5:
            raise ValueError("dist must contain [k1, k2, p1, p2, k3]")
        return self


class CalibrationPoint(BaseModel):
    image: tuple[float, float]
    world: tuple[float, float, float]


class PnPCalibrationIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    image_size: tuple[int, int]
    K: list[list[float]]
    dist: list[float]
    grid_points: list[CalibrationPoint] = Field(min_length=6)
    validation_points: list[CalibrationPoint] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_input(self):
        if any(value <= 0 for value in self.image_size):
            raise ValueError("image_size must contain positive values")
        if len(self.K) != 3 or any(len(row) != 3 for row in self.K):
            raise ValueError("K must be a 3x3 matrix")
        if len(self.dist) != 5:
            raise ValueError("dist must contain [k1, k2, p1, p2, k3]")
        training = {(point.image, point.world) for point in self.grid_points}
        if any((point.image, point.world) in training for point in self.validation_points):
            raise ValueError("validation points must be held out from PnP grid points")
        grid_heights = {point.world[2] for point in self.grid_points}
        if all(point.world[2] in grid_heights for point in self.validation_points):
            raise ValueError("validation points must include at least one different-height point")
        return self


class DetectionIn(BaseModel):
    track_id: int = Field(ge=0)
    cls: ObjectClass
    conf: float = Field(ge=0, le=1)
    bbox: tuple[float, float, float, float]
    foot: tuple[float, float] | None = None
    foot_src: FootSource | None = None

    @field_validator("bbox")
    @classmethod
    def valid_bbox(cls, value):
        x1, y1, x2, y2 = value
        if x2 <= x1 or y2 <= y1 or min(value) < 0:
            raise ValueError("bbox must be non-negative [x1, y1, x2, y2] with positive area")
        return value


class CameraFrameIn(BaseModel):
    camera_id: str = Field(min_length=1, max_length=64)
    frame_id: int = Field(ge=0)
    ts: int = Field(ge=0, description="Epoch milliseconds")
    image_size: tuple[int, int]
    detections: list[DetectionIn]

    @model_validator(mode="after")
    def boxes_fit_image(self):
        width, height = self.image_size
        if width <= 0 or height <= 0:
            raise ValueError("image_size must contain positive values")
        if any(d.bbox[2] > width or d.bbox[3] > height for d in self.detections):
            raise ValueError("bbox lies outside image_size")
        if any(d.foot is not None and not (0 <= d.foot[0] < width and 0 <= d.foot[1] < height)
               for d in self.detections):
            raise ValueError("foot lies outside image_size")
        return self


class DetectionBundleIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    calibration_profile: CalibrationProfile = "basic"
    pair_id: int = Field(ge=0)
    frames: list[CameraFrameIn] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def distinct_cameras(self):
        if self.frames[0].camera_id == self.frames[1].camera_id:
            raise ValueError("frames must come from two distinct cameras")
        return self


class WorldPoint(BaseModel):
    x: float
    y: float
    z: float


class ObservationResult(BaseModel):
    camera_id: str
    frame_id: int
    ts: int
    track_id: int
    cls: ObjectClass
    conf: float
    bbox: tuple[float, float, float, float]
    image_size: tuple[int, int]
    foot_pixel: tuple[float, float]
    foot_src: FootSource


class DetectionResult(BaseModel):
    object_id: int
    cls: ObjectClass
    camera_tracks: dict[str, int]
    foot_pixels: dict[str, tuple[float, float]]
    observations: list[ObservationResult]
    world: WorldPoint
    raw_world: WorldPoint | None = None
    velocity: WorldPoint | None = None
    epipolar_error_px: float
    matching_method: Literal["epipolar", "ground-plane"] = "epipolar"
    ground_distance_m: float | None = None


class RiskResult(BaseModel):
    object1_id: int
    object2_id: int
    distance_m: float
    ttc_s: float | None
    level: Literal["safe", "warning", "danger"]


class DetectionBundleOut(BaseModel):
    bundle_id: int
    session_id: str
    pair_id: int
    calibration_profile: CalibrationProfile
    sync_delta_ms: int
    status: Literal["processed"] = "processed"
    matches: list[DetectionResult]
    unmatched: dict[str, list[int]]
    risks: list[RiskResult] = Field(default_factory=list)
    settings: dict[str, str | int | float | bool] = Field(default_factory=dict)


class GroundTruthObjectIn(BaseModel):
    object_id: str = Field(min_length=1, max_length=128)
    cls: ObjectClass
    world: tuple[float, float, float]
    bbox: dict[str, tuple[float, float, float, float]] = Field(default_factory=dict)

    @field_validator("bbox")
    @classmethod
    def valid_boxes(cls, value):
        for camera_id, box in value.items():
            x1, y1, x2, y2 = box
            if not camera_id or min(box) < 0 or x2 <= x1 or y2 <= y1:
                raise ValueError("ground-truth bbox must be a valid [x1, y1, x2, y2]")
        return value


class GroundTruthIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    frame: int = Field(ge=0)
    ts: int = Field(ge=0)
    objects: list[GroundTruthObjectIn]


class GroundTruthOut(BaseModel):
    ok: Literal[True] = True
    ground_truth_id: int
    session_id: str
    frame: int
    object_count: int

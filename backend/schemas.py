from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ObjectClass = Literal["person", "chair", "cart", "desk"]


class CameraUpsert(BaseModel):
    camera_id: str = Field(min_length=1, max_length=64)
    image_size: tuple[int, int] = (1920, 1080)
    K: list[list[float]]
    dist: list[float]
    R: list[list[float]]
    t: list[float]

    @model_validator(mode="after")
    def validate_shapes(self):
        if len(self.K) != 3 or any(len(row) != 3 for row in self.K):
            raise ValueError("K must be a 3x3 matrix")
        if len(self.R) != 3 or any(len(row) != 3 for row in self.R):
            raise ValueError("R must be a 3x3 matrix")
        if len(self.t) != 3:
            raise ValueError("t must contain 3 values")
        return self


class DetectionIn(BaseModel):
    track_id: int = Field(ge=0)
    cls: ObjectClass
    conf: float = Field(ge=0, le=1)
    bbox: tuple[float, float, float, float]

    @field_validator("bbox")
    @classmethod
    def valid_bbox(cls, value):
        x1, y1, x2, y2 = value
        if x2 <= x1 or y2 <= y1 or min(value) < 0:
            raise ValueError("bbox must be non-negative [x1, y1, x2, y2] with positive area")
        return value


class CameraFrameIn(BaseModel):
    camera_id: str
    frame_id: int = Field(ge=0)
    ts: int = Field(description="Edge capture/receive time in epoch milliseconds")
    image_size: tuple[int, int] = (1920, 1080)
    detections: list[DetectionIn]

    @model_validator(mode="after")
    def boxes_fit_image(self):
        width, height = self.image_size
        if width <= 0 or height <= 0:
            raise ValueError("image_size must contain positive values")
        if any(d.bbox[2] > width or d.bbox[3] > height for d in self.detections):
            raise ValueError("bbox lies outside image_size")
        return self


class DetectionBundleIn(BaseModel):
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


class DetectionResult(BaseModel):
    object_id: int
    cls: ObjectClass
    camera_tracks: dict[str, int]
    foot_pixels: dict[str, tuple[float, float]]
    observations: list[ObservationResult]
    world: WorldPoint
    epipolar_error_px: float


class DetectionBundleOut(BaseModel):
    bundle_id: int
    sync_delta_ms: int
    status: Literal["processed"] = "processed"
    matches: list[DetectionResult]
    unmatched: dict[str, list[int]]

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

try:
    from .database import Base
except ImportError:  # Docker runs this directory as the import root.
    from database import Base


class Camera(Base):
    __tablename__ = "cameras"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    method: Mapped[str] = mapped_column(String(32))
    image_width: Mapped[int] = mapped_column(Integer)
    image_height: Mapped[int] = mapped_column(Integer)
    intrinsic_matrix: Mapped[list] = mapped_column(JSON)
    distortion_coefficients: Mapped[list] = mapped_column(JSON)
    rotation_vector: Mapped[list] = mapped_column(JSON)
    rotation_matrix: Mapped[list] = mapped_column(JSON)
    translation_vector: Mapped[list] = mapped_column(JSON)
    reprojection_error_px: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FrameBundle(Base):
    __tablename__ = "frame_bundles"
    __table_args__ = (UniqueConstraint("session_id", "pair_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    pair_id: Mapped[int] = mapped_column(BigInteger)
    sync_delta_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    detections: Mapped[list["Detection"]] = relationship(cascade="all, delete-orphan")


class Detection(Base):
    __tablename__ = "detections"
    __table_args__ = (
        UniqueConstraint("session_id", "camera_id", "frame_id", "track_id"),
        ForeignKeyConstraint(["session_id", "camera_id"], ["cameras.session_id", "cameras.id"]),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("frame_bundles.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    camera_id: Mapped[str] = mapped_column(String(64), index=True)
    frame_id: Mapped[int] = mapped_column(Integer, index=True)
    captured_at_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    track_id: Mapped[int] = mapped_column(Integer)
    object_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    cls: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    bbox: Mapped[list] = mapped_column(JSON)
    foot_pixel: Mapped[list] = mapped_column(JSON)
    foot_src: Mapped[str] = mapped_column(String(16), default="box", server_default="box")
    world_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    world_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    world_z: Mapped[float | None] = mapped_column(Float, nullable=True)


class GlobalObject(Base):
    __tablename__ = "global_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    cls: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrackLink(Base):
    __tablename__ = "track_links"
    __table_args__ = (UniqueConstraint("session_id", "camera1_id", "camera1_track_id", "camera2_id", "camera2_track_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("global_objects.id"), index=True)
    camera1_id: Mapped[str] = mapped_column(String(64))
    camera1_track_id: Mapped[int] = mapped_column(Integer)
    camera2_id: Mapped[str] = mapped_column(String(64))
    camera2_track_id: Mapped[int] = mapped_column(Integer)
    cls: Mapped[str] = mapped_column(String(16))


class ObjectMotionState(Base):
    __tablename__ = "object_motion_states"

    object_id: Mapped[int] = mapped_column(ForeignKey("global_objects.id"), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    mean: Mapped[list] = mapped_column(JSON)
    covariance: Mapped[list] = mapped_column(JSON)
    timestamp_ms: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class TrackPairState(Base):
    __tablename__ = "track_pair_states"
    __table_args__ = (UniqueConstraint("session_id", "cls", "camera1_id", "camera1_track_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    cls: Mapped[str] = mapped_column(String(16))
    camera1_id: Mapped[str] = mapped_column(String(64))
    camera1_track_id: Mapped[int] = mapped_column(Integer)
    camera2_id: Mapped[str] = mapped_column(String(64))
    camera2_track_id: Mapped[int] = mapped_column(Integer)
    challenger_track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    challenger_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_pair_id: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class RiskEvent(Base):
    __tablename__ = "risk_events"
    __table_args__ = (UniqueConstraint("bundle_id", "object1_id", "object2_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_id: Mapped[int] = mapped_column(ForeignKey("frame_bundles.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    captured_at_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    object1_id: Mapped[int] = mapped_column(ForeignKey("global_objects.id"))
    object2_id: Mapped[int] = mapped_column(ForeignKey("global_objects.id"))
    distance_m: Mapped[float] = mapped_column(Float)
    ttc_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    level: Mapped[str] = mapped_column(String(16))


class GroundTruth(Base):
    __tablename__ = "ground_truth"
    __table_args__ = (UniqueConstraint("session_id", "frame"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    frame: Mapped[int] = mapped_column(BigInteger)
    captured_at_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    objects: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

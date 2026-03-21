from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Callable, Protocol

from hackarena3.proto.race.v1 import race_pb2

if TYPE_CHECKING:
    from hackarena3.proto.race.v1.telemetry_pb2 import ParticipantSnapshot
    from hackarena3.proto.race.v1.track_pb2 import TrackData


class GearShift(IntEnum):
    NONE = int(race_pb2.GEAR_SHIFT_NONE)
    UPSHIFT = int(race_pb2.GEAR_SHIFT_UPSHIFT)
    DOWNSHIFT = int(race_pb2.GEAR_SHIFT_DOWNSHIFT)


class DriveGear(IntEnum):
    REVERSE = -1
    NEUTRAL = 0
    FIRST = 1
    SECOND = 2
    THIRD = 3
    FOURTH = 4
    FIFTH = 5
    SIXTH = 6
    SEVENTH = 7
    EIGHTH = 8


@dataclass(frozen=True, slots=True)
class Vec3:
    x: float
    y: float
    z: float


@dataclass(frozen=True, slots=True)
class CenterlinePoint:
    s_m: float
    position: Vec3
    tangent: Vec3
    normal: Vec3
    right: Vec3
    left_width_m: float
    right_width_m: float
    curvature_1pm: float
    grade_rad: float
    bank_rad: float


@dataclass(frozen=True, slots=True)
class PitstopLayout:
    enter: tuple[CenterlinePoint, ...]
    fix: tuple[CenterlinePoint, ...]
    exit: tuple[CenterlinePoint, ...]
    length_m: float


@dataclass(frozen=True, slots=True)
class TrackLayout:
    map_id: str
    lap_length_m: float
    centerline: tuple[CenterlinePoint, ...]
    pitstop: PitstopLayout


@dataclass(slots=True)
class Controls:
    throttle: float
    brake: float
    steering: float
    gear_shift: GearShift | None = None


class NotSupportedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Quaternion:
    x: float
    y: float
    z: float
    w: float


@dataclass(frozen=True, slots=True)
class GhostModeState:
    can_collide_now: bool
    phase: int
    blockers: tuple[int, ...]
    exit_delay_remaining_ms: int

    @property
    def is_ghost(self) -> bool:
        return not self.can_collide_now


@dataclass(frozen=True, slots=True)
class CarState:
    car_id: int
    position: Vec3
    orientation: Quaternion
    speed_mps: float
    gear_raw: int
    gear: DriveGear
    engine_rpm: float
    throttle_applied: float
    brake_applied: float
    last_applied_client_seq: int
    pitstop_zone_flags: int
    wheels_in_pitstop: int
    ghost_mode: GhostModeState | None = None

    @property
    def speed_kmh(self) -> float:
        return self.speed_mps * 3.6

    @property
    def in_pitstop(self) -> bool:
        return self.wheels_in_pitstop > 0


@dataclass(frozen=True, slots=True)
class OpponentState:
    car_id: int
    position: Vec3
    orientation: Quaternion
    ghost_mode: GhostModeState | None = None


@dataclass(frozen=True, slots=True)
class RaceSnapshot:
    tick: int
    server_time_ms: int
    car: CarState
    opponents: tuple[OpponentState, ...]
    raw: ParticipantSnapshot


@dataclass(slots=True)
class RuntimeConfig:
    api_addr: str
    ha_auth_bin: str | None = None
    sandbox_id: str | None = None


@dataclass(slots=True)
class BotContext:
    car_id: int
    map_id: str
    requested_hz: int
    track_data: TrackData
    track: TrackLayout
    effective_hz: int | None = None
    tick: int = 0
    raw: Any | None = None
    _set_controls_impl: Callable[[Controls], None] | None = field(
        default=None,
        repr=False,
    )
    _request_pit_impl: Callable[..., None] | None = field(
        default=None,
        repr=False,
    )

    def set_controls(
        self,
        *,
        throttle: float,
        brake: float,
        steer: float,
        gear_shift: GearShift | None = None,
    ) -> None:
        if self._set_controls_impl is None:
            raise RuntimeError("BotContext is not attached to active runtime.")
        self._set_controls_impl(
            Controls(
                throttle=throttle,
                brake=brake,
                steering=steer,
                gear_shift=gear_shift,
            )
        )

    def request_pit(self, *_args: Any, **_kwargs: Any) -> None:
        if self._request_pit_impl is None:
            raise NotSupportedError(
                "request_pit is not supported by current backend proto."
            )
        self._request_pit_impl(*_args, **_kwargs)


class BotProtocol(Protocol):
    def on_tick(self, snapshot: RaceSnapshot, ctx: BotContext) -> None: ...

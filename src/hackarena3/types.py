from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Callable, Protocol

from hackarena3.proto.race.v1 import race_pb2, telemetry_pb2, track_pb2

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


class TireType(IntEnum):
    UNSPECIFIED = int(telemetry_pb2.TIRE_TYPE_UNSPECIFIED)
    HARD = int(telemetry_pb2.TIRE_TYPE_HARD)
    SOFT = int(telemetry_pb2.TIRE_TYPE_SOFT)
    WET = int(telemetry_pb2.TIRE_TYPE_WET)


class GroundType(IntEnum):
    ASPHALT = int(track_pb2.GROUND_TYPE_ASPHALT)
    GRASS = int(track_pb2.GROUND_TYPE_GRASS)
    GRAVEL = int(track_pb2.GROUND_TYPE_GRAVEL)
    WALL = int(track_pb2.GROUND_TYPE_WALL)
    KERB = int(track_pb2.GROUND_TYPE_KERB)


@dataclass(frozen=True, slots=True)
class Vec3:
    x: float
    y: float
    z: float


@dataclass(frozen=True, slots=True)
class GroundWidth:
    width_m: float
    ground_type_raw: int
    ground_type: GroundType | None


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
    max_left_width_m: float
    max_right_width_m: float
    left_grounds: tuple[GroundWidth, ...]
    right_grounds: tuple[GroundWidth, ...]


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
class TireWearPerWheel:
    front_left: float
    front_right: float
    rear_left: float
    rear_right: float


@dataclass(frozen=True, slots=True)
class TireTemperaturePerWheel:
    front_left_celsius: float
    front_right_celsius: float
    rear_left_celsius: float
    rear_right_celsius: float


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
    ghost_mode: GhostModeState | None
    tire_type_raw: int
    tire_type: TireType
    next_pit_tire_type_raw: int
    next_pit_tire_type: TireType
    tire_wear: TireWearPerWheel
    tire_temperature_celsius: TireTemperaturePerWheel
    pit_request_active: bool
    pit_emergency_lock_remaining_ms: int
    last_pit_time_ms: int
    last_pit_source_raw: int

    @property
    def speed_kmh(self) -> float:
        return self.speed_mps * 3.6


@dataclass(frozen=True, slots=True)
class OpponentState:
    car_id: int
    position: Vec3
    orientation: Quaternion
    ghost_mode: GhostModeState | None


@dataclass(frozen=True, slots=True)
class RaceSnapshot:
    tick: int
    server_time_ms: int
    car: CarState
    opponents: tuple[OpponentState, ...]
    tire_type_raw: int
    tire_type: TireType
    tire_wear: TireWearPerWheel
    tire_temperature_celsius: TireTemperaturePerWheel
    raw: ParticipantSnapshot


@dataclass(slots=True)
class RuntimeConfig:
    api_addr: str
    ha_auth_bin: str | None = None
    sandbox_id: str | None = None


def _unbound_set_controls(_controls: Controls) -> None:
    raise RuntimeError("BotContext is not attached to active runtime.")


def _unbound_command() -> None:
    raise RuntimeError("BotContext is not attached to active runtime.")


def _unbound_set_next_pit_tire_type(_tire_type: TireType) -> None:
    raise RuntimeError("BotContext is not attached to active runtime.")


@dataclass(slots=True)
class BotContext:
    car_id: int
    map_id: str
    requested_hz: int
    track_data: TrackData
    track: TrackLayout
    effective_hz: int | None
    tick: int
    raw: Any
    _set_controls_impl: Callable[[Controls], None] = field(
        default=_unbound_set_controls,
        repr=False,
    )
    _request_back_to_track_impl: Callable[[], None] = field(
        default=_unbound_command,
        repr=False,
    )
    _request_emergency_pitstop_impl: Callable[[], None] = field(
        default=_unbound_command,
        repr=False,
    )
    _set_next_pit_tire_type_impl: Callable[[TireType], None] = field(
        default=_unbound_set_next_pit_tire_type,
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
        self._set_controls_impl(
            Controls(
                throttle=throttle,
                brake=brake,
                steering=steer,
                gear_shift=gear_shift,
            )
        )

    def request_back_to_track(self) -> None:
        self._request_back_to_track_impl()

    def request_emergency_pitstop(self) -> None:
        self._request_emergency_pitstop_impl()

    def set_next_pit_tire_type(self, tire_type: TireType) -> None:
        self._set_next_pit_tire_type_impl(tire_type)


class BotProtocol(Protocol):
    def on_tick(self, snapshot: RaceSnapshot, ctx: BotContext) -> None: ...

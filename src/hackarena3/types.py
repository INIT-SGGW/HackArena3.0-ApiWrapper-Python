from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from typing import TYPE_CHECKING, Callable, Protocol

from hackarena3.proto.race.v1 import race_pb2, telemetry_pb2, track_pb2

if TYPE_CHECKING:
    from hackarena3.proto.race.v1.telemetry_pb2 import ParticipantSnapshot


class _OpenIntEnum(IntEnum):
    @classmethod
    def _missing_(cls, value: object) -> _OpenIntEnum:
        if not isinstance(value, int):
            raise ValueError(f"{value!r} is not a valid {cls.__name__}")
        member = int.__new__(cls, value)
        member._name_ = f"UNKNOWN_{value}"
        member._value_ = value
        return member


class GearShift(_OpenIntEnum):
    NONE = int(race_pb2.GEAR_SHIFT_NONE)
    UPSHIFT = int(race_pb2.GEAR_SHIFT_UPSHIFT)
    DOWNSHIFT = int(race_pb2.GEAR_SHIFT_DOWNSHIFT)


class DriveGear(_OpenIntEnum):
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


class TireType(_OpenIntEnum):
    UNSPECIFIED = int(telemetry_pb2.TIRE_TYPE_UNSPECIFIED)
    HARD = int(telemetry_pb2.TIRE_TYPE_HARD)
    SOFT = int(telemetry_pb2.TIRE_TYPE_SOFT)
    WET = int(telemetry_pb2.TIRE_TYPE_WET)


class GroundType(_OpenIntEnum):
    ASPHALT = int(track_pb2.GROUND_TYPE_ASPHALT)
    GRASS = int(track_pb2.GROUND_TYPE_GRASS)
    GRAVEL = int(track_pb2.GROUND_TYPE_GRAVEL)
    WALL = int(track_pb2.GROUND_TYPE_WALL)
    KERB = int(track_pb2.GROUND_TYPE_KERB)


class GhostModePhase(_OpenIntEnum):
    UNSPECIFIED = int(telemetry_pb2.GHOST_MODE_PHASE_UNSPECIFIED)
    INACTIVE = int(telemetry_pb2.GHOST_MODE_PHASE_INACTIVE)
    ACTIVE = int(telemetry_pb2.GHOST_MODE_PHASE_ACTIVE)
    PENDING_EXIT = int(telemetry_pb2.GHOST_MODE_PHASE_PENDING_EXIT)


class GhostModeBlocker(_OpenIntEnum):
    UNSPECIFIED = int(telemetry_pb2.GHOST_MODE_BLOCKER_UNSPECIFIED)
    LAPS_REQUIREMENT_NOT_MET = int(
        telemetry_pb2.GHOST_MODE_BLOCKER_LAPS_REQUIREMENT_NOT_MET
    )
    EXIT_SPEED_NOT_MET = int(telemetry_pb2.GHOST_MODE_BLOCKER_EXIT_SPEED_NOT_MET)
    EXIT_DELAY_RUNNING = int(telemetry_pb2.GHOST_MODE_BLOCKER_EXIT_DELAY_RUNNING)
    VEHICLE_OVERLAP_ACTIVE = int(
        telemetry_pb2.GHOST_MODE_BLOCKER_VEHICLE_OVERLAP_ACTIVE
    )
    OVERLAP_EXIT_DELAY_RUNNING = int(
        telemetry_pb2.GHOST_MODE_BLOCKER_OVERLAP_EXIT_DELAY_RUNNING
    )
    IN_PIT = int(telemetry_pb2.GHOST_MODE_BLOCKER_IN_PIT)


class PitstopZoneFlag(IntFlag):
    NONE = 0
    ENTER = int(telemetry_pb2.PITSTOP_ZONE_FLAG_ENTER)
    FIX = int(telemetry_pb2.PITSTOP_ZONE_FLAG_FIX)
    EXIT = int(telemetry_pb2.PITSTOP_ZONE_FLAG_EXIT)
    UNSPECIFIED = NONE


class PitEntrySource(_OpenIntEnum):
    UNSPECIFIED = int(telemetry_pb2.PIT_ENTRY_SOURCE_UNSPECIFIED)
    BOT_DECISION = int(telemetry_pb2.PIT_ENTRY_SOURCE_BOT_DECISION)
    REQUESTED = int(telemetry_pb2.PIT_ENTRY_SOURCE_REQUESTED)
    EMERGENCY = int(telemetry_pb2.PIT_ENTRY_SOURCE_EMERGENCY)


@dataclass(frozen=True, slots=True)
class Vec3:
    x: float
    y: float
    z: float


@dataclass(frozen=True, slots=True)
class CarDimensions:
    width_m: float
    depth_m: float


@dataclass(frozen=True, slots=True)
class GroundWidth:
    width_m: float
    ground_type: GroundType


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


@dataclass(frozen=True, slots=True)
class Controls:
    throttle: float
    brake: float
    steering: float
    gear_shift: GearShift = GearShift.NONE
    brake_balancer: float = 0.5
    differential_lock: float = 0.0


@dataclass(frozen=True, slots=True)
class Quaternion:
    x: float
    y: float
    z: float
    w: float


@dataclass(frozen=True, slots=True)
class GhostModeState:
    can_collide_now: bool
    phase: GhostModePhase
    blockers: tuple[GhostModeBlocker, ...]
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
class TireSlipPerWheel:
    front_left: float
    front_right: float
    rear_left: float
    rear_right: float


@dataclass(frozen=True, slots=True)
class CommandCooldownState:
    back_to_track_remaining_ms: int
    emergency_pitstop_remaining_ms: int


@dataclass(frozen=True, slots=True)
class CarState:
    car_id: int
    position: Vec3
    orientation: Quaternion
    speed_mps: float
    gear: DriveGear
    engine_rpm: float
    last_applied_client_seq: int
    pitstop_zone_flags: PitstopZoneFlag
    wheels_in_pitstop: int
    ghost_mode: GhostModeState
    tire_type: TireType
    next_pit_tire_type: TireType
    tire_wear: TireWearPerWheel
    tire_temperature_celsius: TireTemperaturePerWheel
    tire_slip: TireSlipPerWheel
    pit_request_active: bool
    pit_emergency_lock_remaining_ms: int
    last_pit_time_ms: int
    last_pit_source: PitEntrySource
    last_pit_lap: int
    command_cooldowns: CommandCooldownState

    @property
    def speed_kmh(self) -> float:
        return self.speed_mps * 3.6


@dataclass(frozen=True, slots=True)
class OpponentState:
    car_id: int
    position: Vec3
    orientation: Quaternion
    ghost_mode: GhostModeState


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


def _unbound_set_controls(controls: Controls) -> None:
    _ = controls
    raise RuntimeError("BotContext is not attached to active runtime.")


def _unbound_command() -> None:
    raise RuntimeError("BotContext is not attached to active runtime.")


def _unbound_set_next_pit_tire_type(tire_type: TireType) -> None:
    _ = tire_type
    raise RuntimeError("BotContext is not attached to active runtime.")


@dataclass(frozen=True, slots=True)
class _BotContextActions:
    set_controls: Callable[[Controls], None] = _unbound_set_controls
    request_back_to_track: Callable[[], None] = _unbound_command
    request_emergency_pitstop: Callable[[], None] = _unbound_command
    set_next_pit_tire_type: Callable[[TireType], None] = _unbound_set_next_pit_tire_type


@dataclass(slots=True)
class BotContext:
    car_id: int
    map_id: str
    car_dimensions: CarDimensions
    requested_hz: int
    track: TrackLayout
    effective_hz: int | None
    tick: int
    _actions: _BotContextActions = field(
        default_factory=_BotContextActions,
        repr=False,
    )

    def set_controls(
        self,
        *,
        throttle: float,
        brake: float,
        steer: float,
        gear_shift: GearShift = GearShift.NONE,
        brake_balancer: float = 0.5,
        differential_lock: float = 0.0,
    ) -> None:
        self._actions.set_controls(
            Controls(
                throttle=throttle,
                brake=brake,
                steering=steer,
                gear_shift=gear_shift,
                brake_balancer=brake_balancer,
                differential_lock=differential_lock,
            )
        )

    def request_back_to_track(self) -> None:
        self._actions.request_back_to_track()

    def request_emergency_pitstop(self) -> None:
        self._actions.request_emergency_pitstop()

    def set_next_pit_tire_type(self, tire_type: TireType) -> None:
        self._actions.set_next_pit_tire_type(tire_type)


class BotProtocol(Protocol):
    def on_tick(self, snapshot: RaceSnapshot, ctx: BotContext) -> None: ...

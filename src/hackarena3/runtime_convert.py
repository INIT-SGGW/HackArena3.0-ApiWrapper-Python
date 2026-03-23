from __future__ import annotations

from hackarena3.proto.race.v1.telemetry_pb2 import ParticipantSnapshot
from hackarena3.proto.race.v1.track_pb2 import TrackData
from hackarena3.types import (
    CarDimensions,
    CarState,
    CenterlinePoint,
    DriveGear,
    GhostModeBlocker,
    GhostModePhase,
    GroundType,
    GroundWidth,
    GhostModeState,
    OpponentState,
    PitEntrySource,
    PitstopLayout,
    PitstopZoneFlag,
    Quaternion,
    RaceSnapshot,
    TireSlipPerWheel,
    TireTemperaturePerWheel,
    TireType,
    TireWearPerWheel,
    TrackLayout,
    Vec3,
)


def _vec3_from_proto(value: object) -> Vec3:
    return Vec3(
        x=float(getattr(value, "x", 0.0)),
        y=float(getattr(value, "y", 0.0)),
        z=float(getattr(value, "z", 0.0)),
    )


def build_car_dimensions(raw: object) -> CarDimensions:
    return CarDimensions(
        width_m=float(getattr(raw, "width_m", 0.0)),
        depth_m=float(getattr(raw, "depth_m", 0.0)),
    )


def _centerline_point_from_proto(sample: object) -> CenterlinePoint:
    return CenterlinePoint(
        s_m=float(getattr(sample, "s_m", 0.0)),
        position=_vec3_from_proto(getattr(sample, "position", None)),
        tangent=_vec3_from_proto(getattr(sample, "tangent", None)),
        normal=_vec3_from_proto(getattr(sample, "normal", None)),
        right=_vec3_from_proto(getattr(sample, "right", None)),
        left_width_m=float(getattr(sample, "left_width_m", 0.0)),
        right_width_m=float(getattr(sample, "right_width_m", 0.0)),
        curvature_1pm=float(getattr(sample, "curvature_1pm", 0.0)),
        grade_rad=float(getattr(sample, "grade_rad", 0.0)),
        bank_rad=float(getattr(sample, "bank_rad", 0.0)),
        max_left_width_m=float(getattr(sample, "max_left_width_m", 0.0)),
        max_right_width_m=float(getattr(sample, "max_right_width_m", 0.0)),
        left_grounds=tuple(
            _ground_width_from_proto(ground)
            for ground in getattr(sample, "left_grounds", ())
        ),
        right_grounds=tuple(
            _ground_width_from_proto(ground)
            for ground in getattr(sample, "right_grounds", ())
        ),
    )


def _quaternion_from_proto(value: object) -> Quaternion:
    return Quaternion(
        x=float(getattr(value, "x", 0.0)),
        y=float(getattr(value, "y", 0.0)),
        z=float(getattr(value, "z", 0.0)),
        w=float(getattr(value, "w", 1.0)),
    )


def _ghost_mode_from_proto(value: object) -> GhostModeState:
    return GhostModeState(
        can_collide_now=bool(getattr(value, "can_collide_now", False)),
        phase=GhostModePhase(int(getattr(value, "phase", 0))),
        blockers=tuple(
            GhostModeBlocker(int(v)) for v in getattr(value, "blockers", ())
        ),
        exit_delay_remaining_ms=int(getattr(value, "exit_delay_remaining_ms", 0)),
    )


def _drive_gear_from_raw(value: int) -> DriveGear:
    return DriveGear(value)


def _ground_type_from_raw(value: int) -> GroundType:
    return GroundType(value)


def _tire_type_from_raw(value: int) -> TireType:
    return TireType(value)


def _pit_entry_source_from_raw(value: int) -> PitEntrySource:
    return PitEntrySource(value)


def _ground_width_from_proto(value: object) -> GroundWidth:
    return GroundWidth(
        width_m=float(getattr(value, "width_m", 0.0)),
        ground_type=_ground_type_from_raw(int(getattr(value, "ground_type", 0))),
    )


def _tire_wear_from_proto(value: object) -> TireWearPerWheel:
    return TireWearPerWheel(
        front_left=float(getattr(value, "front_left", 0.0)),
        front_right=float(getattr(value, "front_right", 0.0)),
        rear_left=float(getattr(value, "rear_left", 0.0)),
        rear_right=float(getattr(value, "rear_right", 0.0)),
    )


def _tire_temperature_from_proto(value: object) -> TireTemperaturePerWheel:
    return TireTemperaturePerWheel(
        front_left_celsius=float(getattr(value, "front_left_celsius", 0.0)),
        front_right_celsius=float(getattr(value, "front_right_celsius", 0.0)),
        rear_left_celsius=float(getattr(value, "rear_left_celsius", 0.0)),
        rear_right_celsius=float(getattr(value, "rear_right_celsius", 0.0)),
    )


def _tire_slip_from_proto(value: object) -> TireSlipPerWheel:
    return TireSlipPerWheel(
        front_left=float(getattr(value, "front_left", 0.0)),
        front_right=float(getattr(value, "front_right", 0.0)),
        rear_left=float(getattr(value, "rear_left", 0.0)),
        rear_right=float(getattr(value, "rear_right", 0.0)),
    )


def build_race_snapshot(raw: ParticipantSnapshot) -> RaceSnapshot:
    self_ghost = _ghost_mode_from_proto(raw.self.telemetry.ghost_mode)

    opponents: list[OpponentState] = []
    for opponent in raw.opponents:
        opponent_ghost = _ghost_mode_from_proto(opponent.ghost_mode)
        opponents.append(
            OpponentState(
                car_id=int(opponent.car_id),
                position=_vec3_from_proto(opponent.kinematics.position),
                orientation=_quaternion_from_proto(opponent.kinematics.orientation),
                ghost_mode=opponent_ghost,
            )
        )

    tire_type = _tire_type_from_raw(int(raw.self.telemetry.tire_type))
    next_pit_tire_type = _tire_type_from_raw(int(raw.self.telemetry.next_pit_tire_type))
    tire_wear = _tire_wear_from_proto(raw.self.telemetry.tire_wear)
    tire_temp = _tire_temperature_from_proto(
        raw.self.telemetry.tire_temperature_celsius
    )
    tire_slip = _tire_slip_from_proto(raw.self.telemetry.tire_slip)
    pit_runtime = raw.self.telemetry.pit_runtime

    return RaceSnapshot(
        tick=int(raw.tick),
        server_time_ms=int(raw.server_time_ms),
        car=CarState(
            car_id=int(raw.self.car_id),
            position=_vec3_from_proto(raw.self.kinematics.position),
            orientation=_quaternion_from_proto(raw.self.kinematics.orientation),
            speed_mps=float(raw.self.telemetry.speed_mps),
            gear=_drive_gear_from_raw(int(raw.self.telemetry.gear)),
            engine_rpm=float(raw.self.telemetry.engine_rpm),
            last_applied_client_seq=int(raw.self.telemetry.last_applied_client_seq),
            pitstop_zone_flags=PitstopZoneFlag(int(raw.self.telemetry.pitstop_zone_flags)),
            wheels_in_pitstop=int(raw.self.telemetry.wheels_in_pitstop),
            ghost_mode=self_ghost,
            tire_type=tire_type,
            next_pit_tire_type=next_pit_tire_type,
            tire_wear=tire_wear,
            tire_temperature_celsius=tire_temp,
            tire_slip=tire_slip,
            pit_request_active=bool(pit_runtime.pit_request_active),
            pit_emergency_lock_remaining_ms=int(pit_runtime.emergency_lock_remaining_ms),
            last_pit_time_ms=int(pit_runtime.last_pit_time_ms),
            last_pit_source=_pit_entry_source_from_raw(int(pit_runtime.last_pit_source)),
        ),
        opponents=tuple(opponents),
        raw=raw,
    )


def build_track_layout(track_data: TrackData) -> TrackLayout:
    centerline = tuple(
        _centerline_point_from_proto(sample) for sample in track_data.centerline_samples
    )

    pit = track_data.pitstop_data
    pitstop = PitstopLayout(
        enter=tuple(
            _centerline_point_from_proto(sample)
            for sample in pit.enter_centerline_samples
        ),
        fix=tuple(
            _centerline_point_from_proto(sample)
            for sample in pit.fix_centerline_samples
        ),
        exit=tuple(
            _centerline_point_from_proto(sample)
            for sample in pit.exit_centerline_samples
        ),
        length_m=float(pit.length_m),
    )

    return TrackLayout(
        map_id=track_data.map_id,
        lap_length_m=float(track_data.lap_length_m),
        centerline=centerline,
        pitstop=pitstop,
    )

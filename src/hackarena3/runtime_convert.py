from __future__ import annotations

from hackarena3.proto.race.v1.telemetry_pb2 import ParticipantSnapshot
from hackarena3.proto.race.v1.track_pb2 import TrackData
from hackarena3.types import (
    CarState,
    CenterlinePoint,
    DriveGear,
    GhostModeState,
    OpponentState,
    PitstopLayout,
    Quaternion,
    RaceSnapshot,
    TrackLayout,
    Vec3,
)


def _vec3_from_proto(value: object) -> Vec3:
    return Vec3(
        x=float(getattr(value, "x", 0.0)),
        y=float(getattr(value, "y", 0.0)),
        z=float(getattr(value, "z", 0.0)),
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
        phase=int(getattr(value, "phase", 0)),
        blockers=tuple(int(v) for v in getattr(value, "blockers", ())),
        exit_delay_remaining_ms=int(getattr(value, "exit_delay_remaining_ms", 0)),
    )


def _drive_gear_from_raw(value: int) -> DriveGear:
    try:
        return DriveGear(value)
    except ValueError:
        raise ValueError(f"Unknown drive gear value from backend: {value}")


def build_race_snapshot(raw: ParticipantSnapshot) -> RaceSnapshot:
    self_ghost: GhostModeState | None = None
    if raw.self.telemetry.HasField("ghost_mode"):
        self_ghost = _ghost_mode_from_proto(raw.self.telemetry.ghost_mode)

    opponents: list[OpponentState] = []
    for opponent in raw.opponents:
        opponent_ghost: GhostModeState | None = None
        if opponent.HasField("ghost_mode"):
            opponent_ghost = _ghost_mode_from_proto(opponent.ghost_mode)
        opponents.append(
            OpponentState(
                car_id=int(opponent.car_id),
                position=_vec3_from_proto(opponent.kinematics.position),
                orientation=_quaternion_from_proto(opponent.kinematics.orientation),
                ghost_mode=opponent_ghost,
            )
        )

    return RaceSnapshot(
        tick=int(raw.tick),
        server_time_ms=int(raw.server_time_ms),
        car=CarState(
            car_id=int(raw.self.car_id),
            position=_vec3_from_proto(raw.self.kinematics.position),
            orientation=_quaternion_from_proto(raw.self.kinematics.orientation),
            speed_mps=float(raw.self.telemetry.speed_mps),
            gear_raw=int(raw.self.telemetry.gear),
            gear=_drive_gear_from_raw(int(raw.self.telemetry.gear)),
            engine_rpm=float(raw.self.telemetry.engine_rpm),
            throttle_applied=float(raw.self.telemetry.throttle_applied),
            brake_applied=float(raw.self.telemetry.brake_applied),
            last_applied_client_seq=int(raw.self.telemetry.last_applied_client_seq),
            pitstop_zone_flags=int(raw.self.telemetry.pitstop_zone_flags),
            wheels_in_pitstop=int(raw.self.telemetry.wheels_in_pitstop),
            ghost_mode=self_ghost,
        ),
        opponents=tuple(opponents),
        raw=raw,
    )


def build_track_layout(track_data: TrackData) -> TrackLayout:
    centerline = tuple(
        _centerline_point_from_proto(sample) for sample in track_data.centerline_samples
    )

    if not track_data.HasField("pitstop_data"):
        raise ValueError("TrackData is missing required pitstop_data.")
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

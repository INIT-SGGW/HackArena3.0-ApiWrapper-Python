from hackarena3.types import (
    BotContext,
    BotProtocol,
    CarState,
    CenterlinePoint,
    Controls,
    DriveGear,
    GroundType,
    GroundWidth,
    GhostModeState,
    GearShift,
    OpponentState,
    PitstopLayout,
    Quaternion,
    RaceSnapshot,
    RuntimeConfig,
    TireTemperaturePerWheel,
    TireType,
    TireWearPerWheel,
    TrackLayout,
    Vec3,
)


def run_bot(bot: BotProtocol, config: RuntimeConfig | None = None) -> int:
    from hackarena3.client import run_bot as _run_bot

    return _run_bot(bot=bot, config=config)


__all__ = [
    "BotContext",
    "BotProtocol",
    "CarState",
    "CenterlinePoint",
    "Controls",
    "DriveGear",
    "GroundType",
    "GroundWidth",
    "GhostModeState",
    "GearShift",
    "OpponentState",
    "PitstopLayout",
    "Quaternion",
    "RaceSnapshot",
    "RuntimeConfig",
    "TireTemperaturePerWheel",
    "TireType",
    "TireWearPerWheel",
    "TrackLayout",
    "Vec3",
    "run_bot",
]

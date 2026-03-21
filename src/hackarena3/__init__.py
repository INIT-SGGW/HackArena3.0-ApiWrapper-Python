from hackarena3.types import (
    BotContext,
    BotProtocol,
    CarState,
    CenterlinePoint,
    Controls,
    DriveGear,
    GhostModeState,
    GearShift,
    NotSupportedError,
    OpponentState,
    PitstopLayout,
    Quaternion,
    RaceSnapshot,
    RuntimeConfig,
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
    "GhostModeState",
    "GearShift",
    "NotSupportedError",
    "OpponentState",
    "PitstopLayout",
    "Quaternion",
    "RaceSnapshot",
    "RuntimeConfig",
    "TrackLayout",
    "Vec3",
    "run_bot",
]

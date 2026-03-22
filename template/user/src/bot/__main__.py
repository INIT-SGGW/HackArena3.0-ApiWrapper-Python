from __future__ import annotations

from hackarena3 import BotContext, DriveGear, GearShift, RaceSnapshot, run_bot


class ExampleBot:
    def __init__(self) -> None:
        self.tick = 0

    def on_tick(self, snapshot: RaceSnapshot, ctx: BotContext) -> None:
        self.tick += 1

        if self.tick <= 50:
            return

        if (self.tick // 100) % 2:
            if snapshot.car.gear != DriveGear.REVERSE:
                ctx.set_controls(
                    throttle=0,
                    brake=0.5,
                    steer=0.0,
                    gear_shift=GearShift.DOWNSHIFT,
                )
                return
        else:
            if snapshot.car.gear in (DriveGear.REVERSE, DriveGear.NEUTRAL):
                ctx.set_controls(
                    throttle=0,
                    brake=0.5,
                    steer=0.0,
                    gear_shift=GearShift.UPSHIFT,
                )
                return

        ctx.set_controls(
            throttle=0.55,
            brake=0,
            steer=0.0,
        )


if __name__ == "__main__":
    raise SystemExit(run_bot(ExampleBot()))

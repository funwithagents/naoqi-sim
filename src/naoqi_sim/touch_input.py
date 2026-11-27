"""The touch input: the robot's head, hand and foot sensors (specs/host/touch-input.md).

An ordinary qi client: a press writes 1.0 into the sensor's value key in ALMemory, a release 0.0,
and the robot's own `ALTouch` raises the sensor's event and `TouchChanged` from it, as it does from
a NAO's sensors. The device holds one set of pressed sensors shared by its holders (the Python
API, the controls page): a sensor stays pressed while at least one of them holds it.
"""

import asyncio
import logging
import threading
from collections.abc import Callable, Iterable
from typing import Any

from naoqi_sim import stack

log = logging.getLogger(__name__)

HEAD = ("Head/Touch/Front", "Head/Touch/Middle", "Head/Touch/Rear")
HANDS = tuple(
    f"{hand}/Touch/{side}"
    for hand in ("LHand", "RHand")
    for side in ("Back", "Left", "Right")
)
FEET = tuple(
    f"{foot}/Bumper/{side}" for foot in ("LFoot", "RFoot") for side in ("Left", "Right")
)
# ALTouch.getSensorList()'s 13 sensors, in its groups' order.
SENSORS = (*HEAD, *HANDS, *FEET)
# Names that stand for several sensors.
GROUPS = {"Head": HEAD}
KEY = "Device/SubDeviceList/{}/Sensor/Value"
TAP_S = 0.2  # a tap's default duration


def resolve(names: Iterable[str]) -> list[str]:
    """The sensors `names` designate, in `SENSORS` order, `"Head"` expanded; `ValueError` on an
    unknown name."""
    wanted: set[str] = set()
    for name in names:
        if name in GROUPS:
            wanted.update(GROUPS[name])
        elif name in SENSORS:
            wanted.add(name)
        else:
            raise ValueError(
                f"unknown touch sensor {name!r}: expected one of "
                f"{', '.join([*GROUPS, *SENSORS])}"
            )
    return [s for s in SENSORS if s in wanted]


class TouchInput:
    """The pressed sensors, by holder, written to ALMemory from `start()` to `stop()`."""

    def __init__(self, connect: Callable[[], Any] | None = None):
        self._connect = connect or (lambda: stack.connect())  # a qi session
        self._session: Any = None
        self._memory: Any = None
        self._holders: dict[str, set[str]] = {}  # sensor -> who holds it
        self._lock = threading.Lock()

    def start(self) -> None:
        self._session = self._connect()
        self._memory = self._session.service("ALMemory")

    def stop(self) -> None:
        """Release every sensor, then close the session. Idempotent."""
        with self._lock:
            if self._session is None:
                return
            for sensor in [s for s in SENSORS if self._holders.get(s)]:
                self._write(sensor, 0.0)
            self._holders.clear()
            session, self._session, self._memory = self._session, None, None
        session.close()

    def press(self, holder: str, sensors: Iterable[str]) -> None:
        """`holder` presses the sensors; those nobody held yet are written 1.0, one after the
        other, so `ALTouch` reports them together."""
        names = resolve(sensors)
        with self._lock:
            self._require()
            for sensor in names:
                holders = self._holders.setdefault(sensor, set())
                if not holders:
                    self._write(sensor, 1.0)
                holders.add(holder)

    def release(self, holder: str, sensors: Iterable[str] | None = None) -> None:
        """`holder` lets go of the sensors (every one it holds when `None`); those nobody holds
        any more are written 0.0."""
        with self._lock:
            self._require()
            names = (
                [s for s in SENSORS if holder in self._holders.get(s, ())]
                if sensors is None
                else resolve(sensors)
            )
            for sensor in names:
                holders = self._holders.get(sensor)
                if holders is None or holder not in holders:
                    continue
                holders.discard(holder)
                if not holders:
                    self._write(sensor, 0.0)

    def pressed(self) -> list[str]:
        """The sensors pressed now, whoever holds them, in `SENSORS` order."""
        with self._lock:
            return [s for s in SENSORS if self._holders.get(s)]

    def held(self, holder: str) -> list[str]:
        """The sensors `holder` holds."""
        with self._lock:
            return [s for s in SENSORS if holder in self._holders.get(s, ())]

    def _require(self) -> None:
        if self._memory is None:
            raise RuntimeError("the touch input is not started")

    def _write(self, sensor: str, value: float) -> None:
        self._memory.insertData(KEY.format(sensor), value)


class Touch:
    """`NaoqiSim.touch`: the Python API's hands on the touch input (holder `api`)."""

    HOLDER = "api"

    def __init__(self, device: TouchInput):
        self._device = device

    async def press(self, *sensors: str) -> None:
        """Press the sensors, together; `"Head"` is the three head sensors."""
        if not sensors:
            raise ValueError("name at least one sensor to press")
        resolve(sensors)  # an unknown name raises here, before anything is pressed
        await asyncio.to_thread(self._device.press, self.HOLDER, sensors)

    async def release(self, *sensors: str) -> None:
        """Release the sensors; with none named, every sensor the API pressed."""
        resolve(sensors)
        await asyncio.to_thread(
            self._device.release, self.HOLDER, sensors if sensors else None
        )

    async def tap(self, *sensors: str, duration_s: float = TAP_S) -> None:
        """Press the sensors, wait `duration_s`, release them."""
        if duration_s < 0:
            raise ValueError(f"duration_s must not be negative, got {duration_s}")
        await self.press(*sensors)  # raises when none is named
        try:
            await asyncio.sleep(duration_s)
        finally:
            await self.release(*sensors)

    def pressed(self) -> list[str]:
        """The sensors pressed now, by the API, the controls or anyone else."""
        return self._device.pressed()

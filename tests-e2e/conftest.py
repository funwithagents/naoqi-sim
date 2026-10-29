# Live tier shared fixtures.
#
# This tier is NOT collected by the default `uv run pytest` (testpaths = ["tests"]);
# run it explicitly with `uv run pytest tests-e2e`. Mirror any isolation fixture the
# fast tier uses here — tests-e2e/ isn't a package that can import from tests/, so the
# few lines are duplicated rather than shared.
#
# The tests run the simulated NAO the way any caller does, with a `NaoqiSim`: each test runs
# once per NAOqi version, and pytest stops one version's NaoqiSim before it starts the next
# (both publish 9559). Its audio goes to a MemorySink, so a test asserts on what was played.
#
# The robot is the fixtures' job: before each test that needs it, `_the_robot_runs` starts it if it
# is not running (the first time, or after a test that stopped it for its own needs), so no test
# restores it. `test_the_robot_boots` runs first for each version. A boot that fails is retried
# once; one that fails again fails that test (or the next one that needs the robot, for a robot
# brought back between tests), with the boot's own error, and every later test of that version
# skips, so a failed boot shows as one failure with its cause.
import asyncio
import json
import sys
import time
import uuid
from collections.abc import Iterator

import pytest
import qi
from support import (
    VERSIONS,
    Container,
    Version,
    check_audio_setting,
    connect,
    e2e_versions,
    ensure_images,
    require_docker,
    require_free_ports,
)

from naoqi_sim import FakeAudioSource, MemorySink, NaoqiSim
from naoqi_sim.config import (
    AudioInputSettings,
    AudioOutputSettings,
    CameraSettings,
    NaoqiSettings,
    NaoqiSimConfig,
    SpeechSettings,
    VideoInputSettings,
    ViewerSettings,
)
from naoqi_sim.errors import BootError

# Runs a test's Python 2.7 inside NAOqi's embedded interpreter, where Choregraphe's boxes run, on a
# thread, and leaves `run()`'s result (or the traceback) as JSON in an ALMemory key.
# (Python 2 refuses `exec` in a nested function, hence _naoqisim_exec at the top.)
_IN_NAOQI = """
def _naoqisim_exec(_body, _ns):
    exec(_body, _ns)
def _naoqisim_test(_body, _key):
    import json, threading, traceback
    from naoqi import ALProxy
    def go():
        ns = {}
        try:
            _naoqisim_exec(_body, ns)
            out = {"ok": ns["run"]()}
        except Exception:
            out = {"error": traceback.format_exc()}
        ALProxy("ALMemory").insertData(_key, json.dumps(out))
    threading.Thread(target=go).start()
_naoqisim_test(%r, %r)
"""


def pytest_configure(config):
    check_audio_setting()


def live_config(version: str, **blocks) -> NaoqiSimConfig:
    """Headless and silent, with the render camera on naoqi-viewer's empty scene (the tests spawn
    what the cameras look at, as props) and the fake audio source: what the live tier runs,
    unless a test asks for something else."""
    settings = {
        "naoqi": NaoqiSettings(version=version),  # type: ignore[arg-type]
        "audio_output": AudioOutputSettings(mode="silent"),
        "viewer": ViewerSettings(headless=True, variant="placeholder"),
        # The bottom camera slow: a CI runner renders in software, and its renders are what
        # the live tier's timing tests compete with for the CPU (ci.md).
        "video_input": VideoInputSettings(
            top=CameraSettings(source="render"),
            bottom=CameraSettings(source="render", fps=5),
        ),
        "audio_input": AudioInputSettings(source="fake"),
        # A third language, whose voice the image lacks: the engine fetches it into the voice
        # volume on the first start (tts-engine.md, "Languages"); the defaults are in the image.
        "speech": SpeechSettings(languages=("English", "French", "German")),
        **blocks,
    }
    return NaoqiSimConfig(**settings)


class Nao:
    """A running simulated NAO of one version, and a qi session to it."""

    def __init__(self, version: Version, runner: asyncio.Runner):
        self.version = version
        self.runner = runner
        self.sink = MemorySink()
        self.sim = NaoqiSim(live_config(version.name), sink=self.sink)
        self.container = Container(version)
        self._session: qi.Session | None = None
        # Why the robot is down, once a boot failed twice; whether a test has failed with it yet.
        self.boot_error: str | None = None
        self.boot_error_reported = False
        self.last_test: str | None = None  # the last test that had the robot

    @property
    def running(self) -> bool:
        return self._session is not None

    def start(self) -> None:
        """Starts the robot, retrying once a boot that fails. A boot that fails again is
        remembered (`boot_error`) and raised, so the test that (re)started it fails with it."""
        error: BootError | None = None
        for attempt in (1, 2):
            try:
                self.runner.run(self.sim.start())
            except BootError as e:
                error = e
                print(
                    f"\nNAOqi {self.version.name} did not boot (attempt {attempt} of 2): {e}",
                    file=sys.__stderr__,
                )
                continue  # a failed start has already torn itself down
            self._session = connect(self.sim.url)
            self.boot_error = None
            return
        assert error is not None
        self.boot_error = f"NAOqi {self.version.name} did not boot, twice: {error}"
        self.boot_error_reported = True
        raise error

    def stop(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
        self.runner.run(self.sim.stop())

    def restart(self) -> None:
        self.stop()
        self.start()

    @property
    def session(self) -> qi.Session:
        assert self._session is not None, "the NaoqiSim is stopped"
        return self._session

    def service(self, name: str):
        return self.session.service(name)

    @property
    def audio(self) -> FakeAudioSource:
        """The fake audio source: what the robot's microphones hear."""
        return self.sim.fake_audio

    def run_in_naoqi(self, body: str, timeout: float = 60.0):
        """Runs `body` (Python 2.7 defining `run()`) inside NAOqi, as a box would, and returns
        what `run()` returned (JSON-able)."""
        memory = self.service("ALMemory")
        key = "NaoqiSimTest/" + uuid.uuid4().hex
        memory.insertData(key, "")
        error = self.service("ALPythonBridge").eval(_IN_NAOQI % (body, key))
        if error:  # eval answers with the exception it raised
            pytest.fail("in NAOqi:\n" + error)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            raw = memory.getData(key)
            if raw:
                out = json.loads(raw)
                if "error" in out:
                    pytest.fail("in NAOqi:\n" + out["error"])
                return out["ok"]
            time.sleep(0.1)
        pytest.fail(f"no result from NAOqi after {timeout} s")

    def played(self, after: float, timeout: float = 10.0) -> float:
        """Seconds of audio in the first stream that started after `after` (time.monotonic())."""
        return self.sink.wait_for(lambda p: p.started_at >= after, timeout).duration_s

    def played_if_any(self, after: float, settle: float = 1.0) -> float:
        """Like `played`, for a play that was stopped: 0 when no stream started after `after`
        (the stop came before any audio), once `settle` has given a started one time to end."""
        try:
            return self.played(after, settle)
        except TimeoutError:
            return 0.0


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config: pytest.Config) -> None:
    """Run this tier serially, overriding the fast tier's parallel `addopts`: every test shares
    the one naoqi-sim on 9559, which workers would start and stop under one another. This
    conftest loads only when tests-e2e/ is collected, so the fast tier keeps its workers."""
    config.option.numprocesses = 0


@pytest.fixture(scope="session", params=e2e_versions())
def nao(request) -> Iterator[Nao]:
    require_docker()
    version = VERSIONS[request.param]
    ensure_images(version)
    require_free_ports()
    with asyncio.Runner() as runner:
        nao = Nao(
            version, runner
        )  # started by `_the_robot_runs`, before the first test
        try:
            yield nao
        finally:
            nao.stop()


@pytest.fixture(autouse=True)
def _the_robot_runs(request):
    """Before a test that needs the robot: starts it if it is not running. A robot that did not
    boot fails the first test that needs it, with the boot's error, and skips the others."""
    if "nao" not in request.fixturenames:
        yield
        return
    nao = request.getfixturevalue("nao")
    if nao.boot_error is None and not nao.running:
        try:
            nao.start()
        except BootError:
            nao.boot_error_reported = False  # this test reports it
            if nao.last_test is not None:
                nao.boot_error = (
                    f"{nao.boot_error} (bringing the robot back after {nao.last_test})"
                )
    if nao.boot_error is not None:
        if not nao.boot_error_reported:
            nao.boot_error_reported = True
            pytest.fail(nao.boot_error, pytrace=False)
        pytest.skip(
            f"NAOqi {nao.version.name} did not boot (the failure is reported once, above)"
        )
    yield
    nao.last_test = request.node.name


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """`test_the_robot_boots` first for each version: after pytest has grouped the tests by
    version (the session-scoped `nao` parameter), each version's boot test moves to the head of
    its group, so a robot that does not boot fails that test."""

    def version(item: pytest.Item) -> str | None:
        callspec = getattr(item, "callspec", None)
        return callspec.params.get("nao") if callspec else None

    for boot in [i for i in items if i.name.startswith("test_the_robot_boots[")]:
        items.remove(boot)
        first = next(
            (n for n, i in enumerate(items) if version(i) == version(boot)), len(items)
        )
        items.insert(first, boot)

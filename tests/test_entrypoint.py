"""The containers' entrypoints (one per NAOqi version) and the healthcheck, run on the host against fake `naoqi-bin` and `qicli`.

Our modules load inside NAOqi's boot, from the autoload copy the entrypoint writes
(specs/container/service-replacement.md, "Replacing a built-in"), so the entrypoint calls nothing
but `NaoqiSim.setReady`: it writes the copy, starts `naoqi-bin`, waits for a settled service list
and checks names. The fakes sit first on PATH. `qicli` logs every invocation, lists
`FAKE_QICLI_SERVICES` (minus the names that are "down", plus names that appear late) on `info`
without a name, answers `info NAME` with failure while NAME is down (a module that did not load),
hangs on the `info` calls `FAKE_QICLI_HANG` numbers (`first-last`), and serves
`NaoqiSim.setReady` and `NaoqiSim.isReady` in either suite's output style.
`naoqi-bin` records its arguments and the environment the loader reads.
"""

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

# Code that runs in the Linux containers: its tests skip on Windows (tests/conftest.py).
pytestmark = pytest.mark.container_code

DOCKER = Path(__file__).resolve().parent.parent / "docker"
ENTRYPOINTS = {v: DOCKER / "naoqi" / f"entrypoint-{v}.sh" for v in ("2.1", "2.8")}
HEALTHCHECK = DOCKER / "naoqi" / "healthcheck.sh"

FAKE_QICLI = textwrap.dedent(
    """\
    import os, sys
    fake = os.environ["FAKE_DIR"]
    args = sys.argv[1:]
    with open(os.path.join(fake, "qicli.log"), "a") as f:
        f.write(" ".join(args) + "\\n")
    down_file = os.path.join(fake, "down")
    down = set(open(down_file).read().split()) if os.path.exists(down_file) else set()
    counter = os.path.join(fake, "info.count")
    if args[0] == "info":
        n = int(open(counter).read()) + 1 if os.path.exists(counter) else 1
        open(counter, "w").write(str(n))
        first, _, last = os.environ.get("FAKE_QICLI_HANG", "0-0").partition("-")
        if int(first) <= n <= int(last):  # these polls never answer
            import time
            time.sleep(60)
        if n <= int(os.environ.get("FAKE_QICLI_READY_AFTER", "0")):
            sys.exit(1)
        if args[1] == "--qi-url":  # no name: list the services, as `NNN [Name]` lines
            late = dict(
                item.split(":") for item in os.environ.get("FAKE_QICLI_LATE", "").split(",") if item
            )
            for i, name in enumerate(os.environ["FAKE_QICLI_SERVICES"].split()):
                if name not in down and n >= int(late.get(name, 0)):
                    print("%03d [%s]" % (i + 1, name))
            sys.exit(0)
        sys.exit(1 if args[1] in down else 0)
    target = args[1]
    if target.startswith("NaoqiSim."):
        if "NaoqiSim" in down:
            sys.stderr.write("Call failed: no such service\\n"); sys.exit(1)
        if target == "NaoqiSim.setReady":
            open(os.path.join(fake, "ready"), "w").close()
        if target == "NaoqiSim.isReady":
            value = "true" if os.path.exists(os.path.join(fake, "ready")) else "false"
            if os.environ.get("FAKE_QICLI_STYLE") == "2.8":  # bare value, then warnings on stdout
                print(value + "\\n[W] 1791533267.881648 1744 qitype.signal: disconnect: No subscription")
            else:
                print("NaoqiSim.isReady: " + value)
    sys.exit(0)
    """
)

FAKE_NAOQI_BIN = textwrap.dedent(
    """\
    #!/bin/bash
    echo "$@" > "$FAKE_DIR/naoqi-bin.args"
    echo "${NAOQI_SIM_INTERNAL_PORT:-unset}" > "$FAKE_DIR/naoqi-bin.port"
    echo "${NAOQI_SIM_PYTHON_MODULES:-unset}" > "$FAKE_DIR/naoqi-bin.modules"
    echo "${NAOQI_SIM_MODULES_DIR:-unset}" > "$FAKE_DIR/naoqi-bin.modules-dir"
    [ -n "${FAKE_NAOQI_EXIT:-}" ] && exit "$FAKE_NAOQI_EXIT"
    trap 'exit 0' TERM INT
    while :; do sleep 0.1; done
    """
)

# A suite autoload with every entry either version's entrypoint edits.
AUTOLOAD = (
    "[core]\nlauncher\n[extra]\nbehaviormanager\naudioout\naudioplayer\nttsinterface\n"
    "pythonbridge\nanimatedspeech\nmodularityperception\npeopleperception\nsittingpeopledetection\n"
    "engagementzones\n"
    "gazeanalysis\nwavingdetection\nfastpersontracking\nfindpersonhead\nalpanoramacompass\n"
    "autonomouslife\ndialog\n"
)
# the people-perception library and the modules chained to it, left out on both versions...
PEOPLE_OUT = (
    "#replaced peopleperception\n#replaced sittingpeopledetection\n#replaced engagementzones\n"
    "#replaced gazeanalysis\n#replaced wavingdetection\n"
)
# the trackers stay on both versions; on 2.8 the sources they read load after modularityperception
TRACKERS = "fastpersontracking\nfindpersonhead\n"
MODULARITY = {
    "2.1": "modularityperception\n",
    "2.8": "modularityperception\nnaoqi_sim_perception_sources\n",
}
KEPT_28 = ["_ALFastPersonTracking", "_ALFindPersonHead"]
OURS = (
    "naoqi_sim_audio_device_relay\nnaoqi_sim_loader\n"
    "naoqi_sim_speech_front\nnaoqi_sim_audio_player_front\n"
)
REPLACED = ["ALTextToSpeech", "ALAudioPlayer", "ALPeoplePerception"]
STUBS = {  # the perception stubs each version serves (specs/services/perception-stubs.md)
    "2.1": ["ALEngagementZones", "ALGazeAnalysis", "ALSittingPeopleDetection"],
    "2.8": [
        "ALEngagementZones",
        "ALGazeAnalysis",
        "ALSittingPeopleDetection",
        "ALWavingDetection",
        "_UserIdentification",
    ],
}
ADDED = {
    v: [
        "ALAudioDevice",
        "_NaoqiSimAudioRelay",
        "_NaoqiSimTextToSpeech",
        "_NaoqiSimAudioPlayer",
        "ALFaceDetection",
        *STUBS[v],
        *(["_NaoqiSimPerceptionSources"] if v == "2.8" else []),
    ]
    for v in ("2.1", "2.8")
}
BUILTINS_21 = [
    "_ALExpressiveness",
    "ALBasicAwareness",
    "_ALAutonomousBlinking",
    "ALAutonomousMoves",
]
# What a booted NAOqi lists: the suite's, ours (registered from the autoload), the added built-ins.
SERVICES = " ".join(
    [
        "ServiceDirectory ALMemory ALLauncher ALPythonBridge ALServiceManager NaoqiSim",
        *REPLACED,
        *ADDED["2.8"],  # a superset of 2.1's
        *BUILTINS_21,
        *KEPT_28,
        "ALAnimatedSpeech ALAutonomousLife ALPanoramaCompass ALDialog",
    ]
)
MODULES = {
    "2.1": "naoqi_sim_status_almodule naoqi_sim_speech_almodule "
    "naoqi_sim_audio_device_almodule naoqi_sim_audio_player_almodule "
    "naoqi_sim_face_detection_almodule naoqi_sim_people_perception_almodule "
    "naoqi_sim_perception_stubs_almodule",
    "2.8": "naoqi_sim_status_qiservice naoqi_sim_speech_qiservice "
    "naoqi_sim_audio_device_qiservice naoqi_sim_audio_player_qiservice "
    "naoqi_sim_face_detection_qiservice naoqi_sim_people_perception_qiservice "
    "naoqi_sim_perception_stubs_qiservice",
}
URLS = {"2.1": "--qi-url tcp://127.0.0.1:9559", "2.8": "--qi-url tcp://127.0.0.1:9558"}


class Fakes:
    def __init__(self, tmp_path: Path):
        self.dir = tmp_path / "fake"
        self.bin = self.dir / "bin"
        self.bin.mkdir(parents=True)
        (self.bin / "qicli").write_text(f"#!{sys.executable}\n{FAKE_QICLI}")
        (self.bin / "naoqi-bin").write_text(FAKE_NAOQI_BIN)
        for f in self.bin.iterdir():
            f.chmod(0o755)
        self.naoqi_home = tmp_path / "naoqi"
        self.autoload = self.naoqi_home / "etc" / "naoqi" / "autoload.ini"
        self.autoload.parent.mkdir(parents=True)
        self.autoload.write_text(AUTOLOAD)
        self.tmp = tmp_path / "tmp"
        self.tmp.mkdir()

    def env(self, extra: dict[str, str]) -> dict[str, str]:
        return {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "FAKE_DIR": str(self.dir),
            "NAOQI_HOME": str(self.naoqi_home),
            "TMPDIR": str(self.tmp),
            "NAOQI_SIM_POLL_INTERVAL": "0.05",
            "FAKE_QICLI_SERVICES": SERVICES,
            **extra,
        }

    def down(self, *names: str) -> None:
        """These names never register: the modules or libraries behind them did not load."""
        (self.dir / "down").write_text(" ".join(names))

    def calls(self) -> list[str]:
        log = self.dir / "qicli.log"
        return log.read_text().splitlines() if log.exists() else []

    def naoqi_bin(self, what: str) -> str:
        """What naoqi-bin got: its arguments (`args`), or the environment it and naoqi-service
        inherit (`port`, `modules`, `modules-dir`)."""
        return (self.dir / f"naoqi-bin.{what}").read_text().strip()

    def started_naoqi(self) -> bool:
        return (self.dir / "naoqi-bin.args").exists()

    def booted_autoload(self) -> str:
        """The autoload copy naoqi-bin was started with."""
        return Path(self.naoqi_bin("args").split("--autoload-file ")[1]).read_text()


class Entrypoint:
    def __init__(self, fakes: Fakes, version: str, extra: dict[str, str] | None = None):
        self.fakes = fakes
        self.out = fakes.dir / "stdout"
        self.proc = subprocess.Popen(
            ["bash", str(ENTRYPOINTS[version])],
            env=fakes.env(extra or {}),
            stdout=self.out.open("w"),
            stderr=subprocess.STDOUT,
        )

    def output(self) -> str:
        return self.out.read_text() if self.out.exists() else ""

    def wait_for_ready(self, timeout: float = 10) -> None:
        end = time.time() + timeout
        while "[entrypoint] naoqi-sim ready" not in self.output():
            if self.proc.poll() is not None:
                pytest.fail(
                    f"entrypoint exited {self.proc.returncode}:\n{self.output()}"
                )
            if time.time() > end:
                self.stop()
                pytest.fail(f"no ready line after {timeout}s:\n{self.output()}")
            time.sleep(0.05)

    def wait_exit(self, timeout: float = 10) -> int:
        try:
            return self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.stop()
            pytest.fail(f"entrypoint still running after {timeout}s:\n{self.output()}")

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(5)


@pytest.fixture
def fakes(tmp_path):
    return Fakes(tmp_path)


def calls_only(fakes: Fakes) -> list[str]:
    return [c for c in fakes.calls() if c.startswith("call ")]


def listings(fakes: Fakes) -> int:
    return sum(1 for c in fakes.calls() if c.startswith("info --qi-url"))


def test_sequence_on_2_1(fakes):
    ep = Entrypoint(fakes, "2.1")
    ep.wait_for_ready()
    ep.stop()

    url = URLS["2.1"]
    # Our modules loaded inside NAOqi's boot: nothing is exited, launched or loaded by a call.
    assert calls_only(fakes) == [f"call NaoqiSim.setReady {url}"]
    # The service list is polled until stable (1 + 3 polls), then every replaced, added and
    # added built-in name is checked, right before setReady.
    checked = REPLACED + ADDED["2.1"] + BUILTINS_21
    assert f"NAOqi ready after 4 polls, {len(SERVICES.split())} services" in ep.output()
    assert fakes.calls()[-len(checked) - 1 : -1] == [
        f"info {name} {url}" for name in checked
    ]
    assert fakes.naoqi_bin("args").startswith("-b 0.0.0.0 -p 9559 --autoload-file ")
    # The copy: audioout (both built-ins) left out, ours right after pythonbridge, and the
    # built-ins a NAO 2.1 autoloads at a NAO's places, autonomouslife and dialog after them.
    assert fakes.booted_autoload() == (
        "[core]\nlauncher\n[extra]\nbehaviormanager\nexpressiveness\n#replaced audioout\n"
        f"audioplayer\nttsinterface\npythonbridge\n{OURS}animatedspeech\n"
        f"{MODULARITY['2.1']}{PEOPLE_OUT}{TRACKERS}alpanoramacompass\n"
        "basicawareness\nautonomousblinking\nautonomousmoves\nautonomouslife\ndialog\n"
    )
    # The loader's modules and their folder, which naoqi-bin's process inherits.
    assert fakes.naoqi_bin("modules") == MODULES["2.1"]
    assert fakes.naoqi_bin("modules-dir") == f"{fakes.naoqi_home}/modules"


def test_sequence_on_2_8(fakes):
    ep = Entrypoint(fakes, "2.8")
    ep.wait_for_ready()
    ep.stop()

    url = URLS["2.8"]
    assert calls_only(fakes) == [f"call NaoqiSim.setReady {url}"]
    checked = REPLACED + ADDED["2.8"] + KEPT_28
    assert fakes.calls()[-len(checked) - 1 : -1] == [
        f"info {name} {url}" for name in checked
    ]
    assert fakes.naoqi_bin("args") == (
        f"--qi-listen-url tcp://127.0.0.1:9558 --autoload-file {fakes.tmp}/autoload.ini"
    )
    # Both built-ins' libraries left out, ours right after pythonbridge; nothing added.
    assert fakes.booted_autoload() == (
        "[core]\nlauncher\n[extra]\nbehaviormanager\naudioout\n#replaced audioplayer\n"
        f"#replaced ttsinterface\npythonbridge\n{OURS}animatedspeech\n"
        f"{MODULARITY['2.8']}{PEOPLE_OUT}{TRACKERS}alpanoramacompass\n"
        "autonomouslife\ndialog\n"
    )
    # naoqi-service inherits the loader's variables, and the port our qi services connect to.
    assert fakes.naoqi_bin("modules") == MODULES["2.8"]
    assert fakes.naoqi_bin("modules-dir") == f"{fakes.naoqi_home}/modules"
    assert fakes.naoqi_bin("port") == "9558"


def test_polls_until_naoqi_answers(fakes):
    ep = Entrypoint(fakes, "2.1", {"FAKE_QICLI_READY_AFTER": "4"})
    ep.wait_for_ready()
    ep.stop()
    assert (
        "NAOqi ready after 8 polls" in ep.output()
    )  # four refusals, then 1 + 3 stable


def test_waits_for_the_package_services_and_a_settled_list(fakes):
    # 2.8's ALDialog (a package service) only appears at the 3rd listing, and ALAudioPlayer keeps
    # the list changing until the 6th: stable at polls 7, 8, 9, so nothing is checked before.
    ep = Entrypoint(fakes, "2.8", {"FAKE_QICLI_LATE": "ALDialog:3,ALAudioPlayer:6"})
    ep.wait_for_ready()
    ep.stop()
    assert "NAOqi ready after 9 polls" in ep.output()
    assert listings(fakes) == 9


def test_gives_up_when_naoqi_never_answers(fakes):
    fakes.down("ALLauncher")
    ep = Entrypoint(fakes, "2.1", {"NAOQI_SIM_READY_TRIES": "3"})
    assert ep.wait_exit() == 1
    assert "not ready after 3 polls" in ep.output()
    assert "naoqi-sim ready" not in ep.output()
    assert calls_only(fakes) == []


@pytest.mark.parametrize(
    "version, missing",
    [("2.1", "ALPythonBridge"), ("2.1", "ALDialog"), ("2.8", "ALAutonomousLife")],
)
def test_gives_up_when_a_required_service_never_appears(fakes, version, missing):
    fakes.down(missing)
    ep = Entrypoint(fakes, version, {"NAOQI_SIM_READY_TRIES": "3"})
    assert ep.wait_exit() == 1
    assert "not ready after 3 polls" in ep.output()
    assert missing in ep.output()
    assert calls_only(fakes) == []


@pytest.mark.parametrize("version", ["2.1", "2.8"])
def test_fails_fast_when_naoqi_stops_answering(fakes, version):
    """Every poll hangs: the boot fails after three timed-out polls, in about a second here,
    not after the 120 polls (minutes) that only end when Docker calls the container unhealthy."""
    started = time.time()
    ep = Entrypoint(
        fakes, version, {"FAKE_QICLI_HANG": "1-999", "NAOQI_SIM_QICLI_TIMEOUT": "0.3"}
    )
    assert ep.wait_exit() == 1
    assert time.time() - started < 5
    out = ep.output()
    assert out.count("qicli info did not answer in 0.3s") == 3
    assert "NAOqi stopped answering: qicli info timed out 3 times in a row" in out
    assert "naoqi-sim ready" not in out


def test_a_poll_that_hangs_once_does_not_fail_the_boot(fakes):
    ep = Entrypoint(
        fakes, "2.8", {"FAKE_QICLI_HANG": "2-2", "NAOQI_SIM_QICLI_TIMEOUT": "0.3"}
    )
    ep.wait_for_ready()
    ep.stop()
    assert "qicli info did not answer in 0.3s (1 in a row)" in ep.output()


def test_says_what_it_is_still_waiting_for(fakes):
    fakes.down("ALDialog")
    ep = Entrypoint(fakes, "2.8", {"NAOQI_SIM_READY_TRIES": "12"})
    assert ep.wait_exit() == 1
    assert "[entrypoint] still waiting for: ALDialog (poll 10)" in ep.output()


@pytest.mark.parametrize("version", ["2.1", "2.8"])
@pytest.mark.parametrize(
    "missing, what",
    [
        (
            "ALTextToSpeech",
            "replaced",
        ),  # the speech front did not load: no ALTextToSpeech at all
        ("ALAudioPlayer", "replaced"),
        ("_NaoqiSimTextToSpeech", "added"),  # a core failed to import
        ("_NaoqiSimAudioPlayer", "added"),
        ("ALAudioDevice", "added"),
        ("_NaoqiSimAudioRelay", "added"),  # the relay registered nothing
        ("ALPeoplePerception", "replaced"),
        ("ALFaceDetection", "added"),
        ("ALEngagementZones", "added"),  # a stub
    ],
)
def test_fails_when_one_of_our_names_does_not_register(fakes, version, missing, what):
    fakes.down(missing)
    ep = Entrypoint(fakes, version)
    assert ep.wait_exit() == 1
    assert f"{what} service {missing} does not answer" in ep.output()
    assert "naoqi-sim ready" not in ep.output()
    assert not [c for c in fakes.calls() if "setReady" in c]


def test_fails_when_an_added_built_in_registers_nothing(fakes):
    fakes.down("ALBasicAwareness")
    ep = Entrypoint(fakes, "2.1")
    assert ep.wait_exit() == 1
    assert "added built-in service ALBasicAwareness does not answer" in ep.output()
    assert not [c for c in fakes.calls() if "setReady" in c]


@pytest.mark.parametrize(
    "version, entry", [("2.1", "audioout"), ("2.8", "pythonbridge")]
)
def test_refuses_a_suite_autoload_without_an_entry_it_edits(fakes, version, entry):
    # Without it the copy would boot without our modules, or with the built-ins in their place.
    fakes.autoload.write_text(AUTOLOAD.replace(f"{entry}\n", ""))
    ep = Entrypoint(fakes, version)
    assert ep.wait_exit() == 1
    assert f"has no entry {entry}" in ep.output()
    assert not fakes.started_naoqi()


def test_fails_when_the_status_module_is_missing(fakes):
    fakes.down("NaoqiSim")
    ep = Entrypoint(fakes, "2.1")
    assert ep.wait_exit() == 1
    assert "NaoqiSim.setReady failed" in ep.output()
    assert "naoqi-sim ready" not in ep.output()


def test_fails_when_naoqi_bin_dies(fakes):
    fakes.down("ALLauncher")
    ep = Entrypoint(fakes, "2.1", {"FAKE_NAOQI_EXIT": "3"})
    assert ep.wait_exit() == 1
    assert "naoqi-bin exited" in ep.output()


@pytest.mark.parametrize("style", ["2.1", "2.8"])
def test_healthcheck_follows_the_ready_flag(fakes, style):
    def run() -> int:
        env = fakes.env({"FAKE_QICLI_STYLE": style})
        return subprocess.run(
            ["bash", str(HEALTHCHECK)], env=env, check=False
        ).returncode

    assert run() == 1  # NaoqiSim answers false before setReady
    (fakes.dir / "ready").touch()
    assert run() == 0
    (fakes.dir / "down").write_text("NaoqiSim")
    assert run() == 1  # the service is gone
    assert all("tcp://127.0.0.1:9559" in c for c in fakes.calls())

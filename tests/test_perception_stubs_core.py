"""The perception stubs' core: the extractor bookkeeping every perception module shares, the
generated methods an ALModule binds by argspec, the stubs' tables and the user store behind 2.8's
_UserIdentification (specs/services/perception-stubs.md)."""

import inspect
from typing import Any, ClassVar

import naoqi_sim_perception_stubs_core as core
import pytest

# Code that runs in the Linux containers: its tests skip on Windows (tests/conftest.py).
pytestmark = pytest.mark.container_code


def shell(methods, varargs=False, **extractor) -> Any:
    """A class as the shells build them: the table's methods over an Extractor state (dynamic,
    hence Any)."""

    class Shell(core.Extractor):
        HANDLERS: ClassVar[dict] = {}

        def _call(self, name, args):
            return core.call(self, self.HANDLERS, name, args)

    core.install(Shell, methods, varargs)
    return Shell("Test", **extractor)


def test_subscriptions_give_the_period_and_are_listed_as_the_robot_lists_them():
    s = shell(core.GENERICS, default_period=500)
    s.subscribe("awareness")  # the one-argument form: the module's default period
    s.subscribe("client", 100, 0.5)
    assert s.getSubscribersInfo() == [["awareness", 500, 0.0], ["client", 100, 0.5]]
    assert s.getCurrentPeriod() == 100
    assert s.getMyPeriod("awareness") == 500 and s.getMyPrecision("client") == 0.5
    s.updatePeriod("awareness", 30)
    assert s.getCurrentPeriod() == 30
    s.unsubscribe("awareness")
    s.unsubscribe("never-subscribed")
    assert s.getSubscribersInfo() == [["client", 100, 0.5]]
    assert s.getCurrentPeriod() == 100
    s.unsubscribe("client")
    assert s.getCurrentPeriod() == -1 and s.getSubscribersInfo() == []


def test_a_stub_never_processes_whoever_subscribes():
    s = shell(core.GAZE_METHODS, settings=core.GAZE_SETTINGS, processes=False)
    s.subscribe("awareness", 200, 0.0)
    assert (
        s.getSubscribersInfo() == [["awareness", 200, 0.0]]
        and s.isProcessing() is False
    )


def test_pause_keeps_the_subscriptions_and_stops_the_processing():
    s = shell(core.GENERICS)
    assert not s.isProcessing()
    s.subscribe("a", 200, 0.0)
    assert s.isProcessing() and not s.isPaused()
    s.pause(True)
    assert s.isPaused() and not s.isProcessing()
    assert s.getSubscribersInfo() == [["a", 200, 0.0]]
    s.pause(False)
    assert s.isProcessing()


def test_generated_methods_have_real_argument_lists_for_an_almodule():
    s = shell(core.ENGAGEMENT_METHODS, settings=core.ENGAGEMENT_SETTINGS)
    spec = inspect.getfullargspec(type(s).subscribe)
    assert spec.args == ["self", "a0", "a1", "a2"] and spec.defaults == (-1, -1.0)
    assert inspect.getfullargspec(type(s).computeEngagementZone).args == [
        "self",
        "a0",
        "a1",
        "a2",
        "a3",
    ]
    assert type(s).setLimitAngle.__doc__ == "naoqi-sim: setLimitAngle"
    # the shorter overloads an ALModule binds explicitly
    assert core.overloads(core.ENGAGEMENT_METHODS) == [
        ("subscribe", 1),
        ("computeEngagementZone", 3),
    ]


def test_varargs_methods_complete_the_missing_arguments_with_the_defaults():
    s = shell(core.ENGAGEMENT_METHODS, varargs=True, settings=core.ENGAGEMENT_SETTINGS)
    assert inspect.getfullargspec(type(s).subscribe).varargs == "args"
    s.subscribe("awareness")
    s.subscribe("client", 100, 0.5)
    assert s.getSubscribersInfo() == [["awareness", 200, 0.0], ["client", 100, 0.5]]
    assert s.computeEngagementZone(1.0, 0.0, 0.0) == 0
    assert s.computeEngagementZone(1.0, 0.0, 0.0, [0.0] * 6) == 0


@pytest.mark.parametrize("stub", core.STUBS, ids=lambda s: str(s.name28))
def test_every_setting_round_trips_through_its_setter_and_getter(stub):
    s = shell(stub.methods, events=stub.events, keys=stub.keys, settings=stub.settings)
    getters = {m[0] for m in stub.methods if m[0].startswith(("get", "is", "_get"))}
    for name, arity, _, _ in stub.methods:
        if arity != 1 or not name.startswith(("set", "_set")):
            continue
        key = name.lstrip("_")[3:]
        getter = next(
            (
                g
                for g in getters
                if g.lstrip("_")[3:] == key or g.lstrip("_")[2:] == key
            ),
            None,
        )
        if getter is None:
            continue
        before = getattr(s, getter)()
        if isinstance(before, bool):
            value = not before
        elif isinstance(before, str):
            value = before + "x"
        else:
            value = before + 1
        getattr(s, name)(value)
        assert getattr(s, getter)() == value, name
    assert s.getEventList() == stub.events and s.getMemoryKeyList() == stub.keys


def test_the_trackers_start_and_stop_with_either_overload():
    s = shell(core.FINDHEAD_METHODS, varargs=True, settings=core.TRACKING_SETTINGS)
    assert not s.isSearching()
    s.startSearching()
    assert s.isSearching()
    s.stopSearching()
    s.startSearching([1.0, 0.0, 0.0])
    assert s.isSearching()
    s.setTrackingPosition(1.0, 2.0, 3.0)
    assert s.getTrackingPosition() == [1.0, 2.0, 3.0] and s.getDefaultPeriod() == 200


def test_each_version_serves_its_own_stubs():
    assert core.stub_names("2.1") == [
        "ALEngagementZones",
        "ALGazeAnalysis",
        "ALSittingPeopleDetection",
    ]
    assert core.stub_names("2.8") == [
        "ALEngagementZones",
        "ALGazeAnalysis",
        "ALSittingPeopleDetection",
        "ALWavingDetection",
    ]
    written = {}
    assert core.write_stubs_key(written.__setitem__, "2.8")[-1] == "_UserIdentification"
    assert written == {
        "NaoqiSim/Perception/Stubs": "ALEngagementZones,ALGazeAnalysis,ALSittingPeopleDetection,"
        "ALWavingDetection,_UserIdentification"
    }
    core.write_stubs_key(written.__setitem__, "2.1")
    assert (
        written["NaoqiSim/Perception/Stubs"]
        == "ALEngagementZones,ALGazeAnalysis,ALSittingPeopleDetection"
    )


def test_the_user_store_knows_nobody_until_the_manager_stores_a_user():
    store = core.UserStore()
    assert store.match(42) == (
        core.STATUS_OK,
        [],
    )  # unknown: the manager stores a new user
    assert store.store(42, 1) == core.STORE_OK == 0
    assert store.match(42) == (1, [(1, 1.0, core.STORAGE_TEMPORARY)])
    assert store.isTemporary(1) and not store.isPermanent(1)
    assert store.makePermanent(1) and store.match(42) == (
        1,
        [(1, 1.0, core.STORAGE_PERMANENT)],
    )
    assert not store.makePermanent(7)  # no such user
    store.store(43, 2)
    assert store.getStoredUsers() == [1, 2]
    assert store.remove(1) and not store.remove(1)
    assert store.match(42) == (1, []) and store.getStoredUsers() == [2]
    assert store.clear() and store.getStoredUsers() == []
    assert store.checkPhotoForIdentification("/tmp/photo.jpg") == 0


def test_the_user_store_serves_its_table_as_a_shell():
    class Shell(core.UserStore):
        HANDLERS: ClassVar[dict] = {}

        def _call(self, name, args):
            return core.call(self, self.HANDLERS, name, args)

    core.install(Shell, core.IDENT_METHODS, varargs=True)
    s: Any = Shell()
    assert s.store(42, 5) == 0 and s.getStoredUsers() == [5] and s.isTemporary(5)
    assert s.makePermanent(5) and s.isPermanent(5)
    assert s.clear() and s.getStoredUsers() == []


def test_a_handler_error_is_logged_and_raised():
    logged = []
    s = shell(core.GENERICS)
    s.log = lambda **f: logged.append(f)
    with pytest.raises(KeyError):
        core.call(s, {"boom": lambda st: st.settings["missing"]}, "boom", [], s.log)
    assert logged[-1]["method"] == "boom" and "KeyError" in logged[-1]["error"]
    core.call(s, s.HANDLERS, "subscribe", ["x", 100, 0.0], s.log)
    assert logged[-1] == {
        "service": "Test",
        "method": "subscribe",
        "args": ["x", 100, 0.0],
        "result": None,
    }

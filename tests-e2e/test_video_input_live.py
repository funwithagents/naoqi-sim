"""The render cameras on each NAOqi version, as a vision client sees them: it subscribes to
`ALVideoDevice` and reads frames with `getImageRemote`, which naoqi-viewer rendered and the video
input injected into both head cameras (the live tier runs it: headless viewer, placeholder
variant, the top camera at 15 fps and the bottom one at 5)."""

import math
import time
from collections.abc import Iterator

import numpy as np
import pytest

TOP, BOTTOM = 0, 1
QVGA, VGA = 1, 2
RGB, BGR = 11, 13
FPS = 15  # the top camera's rate in the live tier (CameraSettings' default)


@pytest.fixture
def camera(nao):
    """Subscribes to a camera like a client, and unsubscribes after the test."""
    video = nao.service("ALVideoDevice")
    handles: list[str] = []

    def subscribe(index=TOP, resolution=QVGA, colorspace=RGB):
        handles.append(
            video.subscribeCamera("naoqi_sim_e2e", index, resolution, colorspace, 30)
        )
        return handles[-1]

    yield video, subscribe
    for handle in handles:
        video.unsubscribe(handle)


def read(video, handle) -> tuple[np.ndarray, float]:
    """The subscriber's current frame and its timestamp."""
    reply = video.getImageRemote(handle)
    video.releaseImage(handle)
    width, height, layers = reply[0], reply[1], reply[2]
    image = np.frombuffer(bytes(reply[6]), np.uint8).reshape(height, width, layers)
    return image, reply[4] + reply[5] / 1e6


def next_frame(video, handle, after: float, timeout: float = 2.0) -> np.ndarray:
    """The first frame stamped after `after`."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        image, stamp = read(video, handle)
        if stamp > after:
            return image
        time.sleep(0.01)
    pytest.fail("no new frame")


def test_the_robot_says_its_cameras_are_the_render(nao):
    memory = nao.service("ALMemory")
    assert memory.getData("NaoqiSim/Camera/Top/Source") == "render"
    assert memory.getData("NaoqiSim/Camera/Bottom/Source") == "render"
    assert memory.getData("NaoqiSim/Camera/Source") == "render"  # the summary


def test_a_client_reads_rendered_frames_at_the_configured_rate(camera):
    """Never faster than `fps`, and frames keep coming. Not exactly `fps`: a CI runner renders
    in software (Mesa, no GPU) and reached about 9 VGA frames per second on 2.8 with one camera,
    where a Mac holds 30; with both cameras rendered each slot, about half that per camera."""
    video, subscribe = camera
    handle = subscribe(resolution=QVGA)

    image, stamp = read(video, handle)
    stamps = {stamp}
    seconds = 3.0
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        image, stamp = read(video, handle)
        stamps.add(stamp)
        time.sleep(0.005)
    rate = (len(stamps) - 1) / seconds

    # NAOqi scaled the VGA frame to the subscriber's resolution.
    assert image.shape == (240, 320, 3)
    assert image.std() > 1  # a render of the scene, not a flat placeholder
    assert 2 <= rate <= FPS + 1.5, f"{rate:.1f} frames per second"


def test_each_subscriber_gets_its_own_colorspace(camera):
    video, subscribe = camera
    rgb, bgr = subscribe(colorspace=RGB), subscribe(resolution=QVGA, colorspace=BGR)

    for _ in range(
        20
    ):  # the two reads can straddle an injection: retry until they match
        rgb_image, rgb_stamp = read(video, rgb)
        bgr_image, bgr_stamp = read(video, bgr)
        if rgb_stamp == bgr_stamp:
            break
    else:
        pytest.fail("never read both subscribers on the same frame")

    diff = np.abs(rgb_image.astype(int) - bgr_image[..., ::-1].astype(int))
    assert diff.max() <= 2


BALL_RADIUS = 0.1  # m
HALF_FOV = math.radians(60.97) / 2  # a NAO head camera's horizontal field of view
WORLD = 1  # ALMotion's FRAME_WORLD
BALL_AHEAD = (
    1.5,
    0.0,
    BALL_RADIUS,
)  # a red ball on the floor 1.5 m ahead, FRAME_ROBOT (m)


@pytest.fixture
def ball(nao) -> Iterator[tuple[float, float, float]]:
    """A red ball spawned on the floor 1.5 m ahead of the robot, as a prop; yields its centre in
    the world frame, where the viewer draws it. Placed in the robot's frame, not the scene's: the
    viewer places the robot at NAOqi's odometry (specs/host/props.md, "Frames")."""
    state = nao.sim.props.spawn("object", BALL_AHEAD, frame="robot", size=BALL_RADIUS)
    try:
        yield state.pos
    finally:
        nao.sim.props.despawn(state.name)


def target_pixels(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The rows and columns of the red ball's pixels in an RGB image."""
    red = (image[..., 0] > 150) & (image[..., 1] < 80) & (image[..., 2] < 80)
    rows, columns = np.nonzero(red)
    return rows, columns


def target_columns(image: np.ndarray) -> np.ndarray:
    return target_pixels(image)[1]


def bearing_to_target(motion, target: tuple[float, float, float]) -> float:
    """The ball's direction from CameraTop, relative to where it looks (positive: left)."""
    x, y, _, _, _, heading = motion.getPosition("CameraTop", WORLD, True)
    return math.atan2(target[1] - y, target[0] - x) - heading


def expected_column(bearing: float, width: int) -> float | None:
    """Where a pinhole camera sees the ball's centre at `bearing`, or None when the ball is
    out of the field of view."""
    if abs(bearing) > HALF_FOV + 0.07:  # the ball's half-width: 0.07 rad at 1.5 m
        return None
    return width / 2 * (1 - math.tan(bearing) / math.tan(HALF_FOV))


def look(motion, yaw: float) -> None:
    motion.angleInterpolation(["HeadYaw", "HeadPitch"], [yaw, 0.0], 0.8, True)
    time.sleep(0.5)  # the viewer follows the pose at 50 Hz


def test_the_camera_sees_what_the_head_faces(nao, camera, ball):
    """The red ball where the camera's pose says it is, as the head turns left and right of
    it, and gone once the head turns away. The head aims relative to the ball, not to the
    robot: NAOqi's world pose of the robot, which the viewer renders, starts about 0.13 rad
    off and drifts with gestures (specs/host/viewer.md, "In the live tier and CI")."""
    video, subscribe = camera
    motion = nao.service("ALMotion")
    handle = subscribe(resolution=QVGA)
    width = 320
    motion.setStiffnesses("Head", 1.0)
    try:
        look(motion, 0.0)
        aim = bearing_to_target(motion, ball)  # the HeadYaw that faces it, near enough
        for offset in (0.0, 0.25, -0.25, 1.2, -1.2):
            look(motion, aim + offset)
            seen = target_columns(
                next_frame(video, handle, after=read(video, handle)[1])
            )
            expected = expected_column(bearing_to_target(motion, ball), width)
            if expected is None:
                assert seen.size == 0, (
                    f"{offset:+} rad off: the ball should be out of view"
                )
            else:
                assert seen.size > 100, f"{offset:+} rad off: the ball is not in view"
                assert abs(seen.mean() - expected) < 15, f"{offset:+} rad off"
    finally:
        motion.angleInterpolation("HeadYaw", 0.0, 0.5, True)


def test_the_bottom_camera_gets_rendered_frames_too(camera):
    """Both cameras are fed, each from its render, and both keep coming. (That two cameras at
    the same rate share their slots is the fast tier's to pin: on a CI runner rendering in
    software, a render outlasts a slot and the two schedules drift apart.)"""
    video, subscribe = camera
    top = subscribe(index=TOP, resolution=QVGA)
    bottom = subscribe(index=BOTTOM, resolution=QVGA)

    image, stamp = read(video, bottom)
    assert image.shape == (240, 320, 3)
    assert image.std() > 1  # a render, not the placeholder of a camera never fed
    later = next_frame(video, bottom, after=stamp)  # and the frames keep coming
    assert later.std() > 1
    next_frame(video, top, after=read(video, top)[1])  # the top camera's too


VERTICAL_HALF_FOV = (
    math.radians(47.64) / 2
)  # a NAO head camera's vertical field of view


def centre_row(
    motion, camera_name: str, height: int, target: tuple[float, float, float]
) -> float:
    """Where a pinhole camera at `camera_name`'s pose sees the ball's centre: past `height`
    when it is below the camera's view."""
    x, y, z, _, pitch, _ = motion.getPosition(camera_name, WORLD, True)
    distance = math.hypot(target[0] - x, target[1] - y)
    below = (
        math.atan2(z - target[2], distance) - pitch
    )  # below the camera's axis (positive)
    return height / 2 * (1 + math.tan(below) / math.tan(VERTICAL_HALF_FOV))


def test_the_bottom_camera_looks_down_at_the_ball(nao, camera, ball):
    """The bottom camera tilts 39.7° further down than the top one, as on a NAO. With the head
    raised, the ball on the floor is on the row the bottom camera's pose predicts (a pinhole
    47.64° tall), while the top camera, looking over it, does not see it."""
    video, subscribe = camera
    motion = nao.service("ALMotion")
    top = subscribe(index=TOP, resolution=QVGA)
    bottom = subscribe(index=BOTTOM, resolution=QVGA)
    height = 240
    motion.setStiffnesses("Head", 1.0)
    try:
        look(motion, 0.0)
        aim = bearing_to_target(motion, ball)
        motion.angleInterpolation(["HeadYaw", "HeadPitch"], [aim, -0.3], 0.8, True)
        time.sleep(0.5)  # the viewer follows the pose at 50 Hz
        bottom_rows, _ = target_pixels(
            next_frame(video, bottom, after=read(video, bottom)[1])
        )
        top_rows, _ = target_pixels(next_frame(video, top, after=read(video, top)[1]))

        assert bottom_rows.size > 100, "the ball is not in the bottom camera's view"
        expected = centre_row(motion, "CameraBottom", height, ball)
        assert abs(bottom_rows.mean() - expected) < 15, f"centre at row {expected:.0f}"
        assert centre_row(motion, "CameraTop", height, ball) > height  # below its view
        assert top_rows.size == 0, "the top camera should look over the ball"
    finally:
        motion.angleInterpolation(["HeadYaw", "HeadPitch"], [0.0, 0.0], 0.5, True)


def test_a_face_spawned_ahead_appears_in_the_top_camera_and_goes(nao, camera):
    """A portrait spawned 1 m ahead is in the top camera's frame, straight ahead, and gone once
    it is despawned. naoqi-sim runs no detector, so that is all it checks:
    finding the face is a client's job."""
    video, subscribe = camera
    motion = nao.service("ALMotion")
    handle = subscribe(resolution=QVGA)
    motion.setStiffnesses("Head", 1.0)
    look(motion, 0.0)

    def frame_after_a_change() -> np.ndarray:
        # The video input renders and injects on two threads: the frame NAOqi serves next may
        # have been rendered before the change, so let one go by.
        time.sleep(3 / FPS)
        return next_frame(video, handle, after=read(video, handle)[1]).astype(int)

    def portrait_pixels(frame: np.ndarray) -> tuple[np.ndarray, ...]:
        # The portrait's near-black areas (its moon backdrop): nothing in the empty scene is
        # that dark, whatever the robot's small moves do to the floor and the horizon.
        return np.nonzero(frame.max(axis=2) < 50)

    assert portrait_pixels(frame_after_a_change())[0].size < 50  # nothing dark yet
    face = nao.sim.props.spawn("face", (1.0, 0.0, 0.45), frame="robot")
    try:
        assert face.image == "armstrong" and face.visible
        rows, columns = portrait_pixels(frame_after_a_change())
        assert rows.size > 200, "the face is not in the top camera's view"
        assert 80 < columns.mean() < 240, "the face is not straight ahead"
    finally:
        nao.sim.props.despawn(face.name)
    rows, _ = portrait_pixels(frame_after_a_change())
    assert rows.size < 50, "the face is still in view after despawn"

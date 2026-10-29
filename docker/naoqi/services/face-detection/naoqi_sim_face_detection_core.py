# -*- coding: utf-8 -*-
"""The face detection core (Python 2.7, inside NAOqi; importable under Python 3 for the host's
fast tier): ALFaceDetection, added to NAOqi with a NAO's extractor API and FaceDetected format
(specs/services/face-detection.md).

`Detector` owns the camera and the schedule (its ALVideoDevice and ALMotion proxies made at first
use: both load after our modules): while a consumer (this module, the people module)
wants detections, it subscribes to the active camera on ALVideoDevice, reads a VGA frame at the
smallest period the subscribers ask for, posts it to the perception engine
(specs/container/perception-engine.md) and hands every consumer a `Detection`: the faces with
NAOqi's own angles, the frame's timestamp and the camera's poses. `FaceModule` is the public
module's logic: the extractor bookkeeping, the settings, FaceDetected written and raised.
"""
import json
import math
import os
import threading
import time

try:
    import urllib2
except ImportError:  # Python 3, on the host
    import urllib.request as urllib2

import naoqi_sim_perception_stubs_core as ext

NAME = "ALFaceDetection"
ENGINE_URL = os.environ.get("NAOQI_SIM_PERCEPTION_URL", "")  # empty: no engine, nobody is ever seen
ENGINE_TIMEOUT_S = 2.0
SUBSCRIBER = "naoqi_sim_face_detection"  # our ALVideoDevice subscription's name
VGA = 2
RGB = 11
WIDTH, HEIGHT = 640, 480
MIN_PERIOD_MS = 100  # 10 Hz: the floor of the schedule
IDLE_TICK_S = 0.5  # how often a consumer that wants no detections gets on_idle (its timers)
DEFAULT_PERIOD_MS = 500  # a subscribe(name) with no period (the documentation's figure)
CAMERA_NAMES = {0: "CameraTop", 1: "CameraBottom"}
FRAME_TORSO, FRAME_WORLD, FRAME_ROBOT = 0, 1, 2
EVENTS = ["FaceDetected"]
EVENTS_21 = ["FaceDetected", "FaceDetection/FaceDetected"]  # the robot declares both on 2.1
KEYS = ["FaceDetected"]
SOURCE_KEY = "NaoqiSim/Perception/Source"
# the proportions of a face around the five landmarks, as fractions of the box (open question 2)
EYE_SIDE, EYE_UP, EYE_DOWN = 0.18, 0.08, 0.08
BROW_UP = 0.14
NOSE_DOWN, NOSE_SIDE = 0.05, 0.06
MOUTH_UP, MOUTH_DOWN = 0.03, 0.04


class Engine(object):
    """The perception engine's client: a VGA RGB frame in, the faces out."""

    def __init__(self, url=ENGINE_URL, timeout=ENGINE_TIMEOUT_S):
        self.url = url
        self.timeout = timeout

    @property
    def available(self):
        return bool(self.url)

    def detect(self, width, height, rgb):
        """[{"box": [x, y, w, h], "score": s, "landmarks": [[x, y] x 5]}, ...] in pixels."""
        req = urllib2.Request(self.url + "/detect", rgb, {
            "Content-Type": "application/octet-stream",
            "X-Width": str(width), "X-Height": str(height)})
        resp = urllib2.urlopen(req, timeout=self.timeout)
        body = resp.read()
        if not isinstance(body, str):  # Python 3: bytes
            body = body.decode("utf-8")
        return json.loads(body)["faces"]


class Face(object):
    """One detected face: the box and landmarks in pixels, the angles NAOqi's conventions give."""

    def __init__(self, box, score, landmarks, alpha, beta, size_x, size_y, track_id):
        self.box = box  # [x, y, w, h] pixels
        self.score = score
        self.landmarks = landmarks  # [[x, y] x 5]: right eye, left eye, nose tip, right and left mouth corners
        self.alpha = alpha  # the centre's yaw angle, radians
        self.beta = beta  # the centre's pitch angle
        self.size_x = size_x  # angular width
        self.size_y = size_y  # angular height
        self.track_id = track_id


class Detection(object):
    """What one processed frame gave: the faces, when, which camera, where the camera was."""

    def __init__(self, faces, stamp, camera, pose_torso, pose_robot, transforms, width=WIDTH, height=HEIGHT):
        self.faces = faces
        self.stamp = stamp  # [seconds, microseconds]
        self.camera = camera  # 0 or 1
        self.pose_torso = pose_torso  # ALMotion.getPosition(camera, FRAME_TORSO), 6 floats
        self.pose_robot = pose_robot
        self.transforms = transforms  # {frame: 16 floats, ALMotion.getTransform(camera, frame)}
        self.width = width
        self.height = height


class AngleMap(object):
    """Pixels to NAOqi's angles for one camera, from ALVideoDevice's own conversions
    (getAngularPositionFromImagePosition and getAngularSizeFromImageSize), measured once at the
    image's corners: the conversion is linear, so two calls give the whole map with NAOqi's signs."""

    def __init__(self, video, camera):
        a0 = video.getAngularPositionFromImagePosition(camera, [0.0, 0.0])
        a1 = video.getAngularPositionFromImagePosition(camera, [1.0, 1.0])
        self.alpha0, self.beta0 = float(a0[0]), float(a0[1])
        self.dalpha, self.dbeta = float(a1[0]) - self.alpha0, float(a1[1]) - self.beta0
        size = video.getAngularSizeFromImageSize(camera, [1.0, 1.0])
        self.fov_x, self.fov_y = float(size[0]), float(size[1])

    def angles(self, x, y, width=WIDTH, height=HEIGHT):
        """The angles of a pixel: [alpha, beta]."""
        return [self.alpha0 + self.dalpha * x / float(width), self.beta0 + self.dbeta * y / float(height)]

    def size(self, w, h, width=WIDTH, height=HEIGHT):
        return [self.fov_x * w / float(width), self.fov_y * h / float(height)]


class Detector(object):
    """Reads the camera and runs the engine on a thread, at the consumers' smallest period."""

    def __init__(self, video_factory, motion_factory, engine, log=None, clock=time.time, sleep=time.sleep):
        # ALVideoDevice loads after our modules (its autoload entry follows pythonbridge), so the
        # proxies are made at first use, never at load: factories, called once, kept.
        self.video_factory = video_factory
        self.motion_factory = motion_factory
        self._video = None
        self._motion = None
        self.engine = engine
        self.log = log or (lambda **f: None)
        self.clock = clock
        self.sleep = sleep
        self.consumers = []
        self.camera = 0
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.running = False
        self.thread = None
        self.subscription = None  # (name, camera) while subscribed
        self.maps = {}
        self.engine_ok = None  # None until the first call, then whether the last one worked
        self.camera_ok = True
        self.detections = 0

    @property
    def video(self):
        if self._video is None:
            self._video = self.video_factory()
        return self._video

    @property
    def motion(self):
        if self._motion is None:
            self._motion = self.motion_factory()
        return self._motion

    def add_consumer(self, consumer):
        """consumer.wants() -> period in ms, or None; consumer.on_detection(detection); and, if it
        has one, consumer.on_idle(), every IDLE_TICK_S while it wants no detections (the people
        module's timers keep running with nobody subscribed)."""
        with self.lock:
            self.consumers.append(consumer)
        self.poke()

    def set_camera(self, camera):
        self.camera = int(camera)
        self.poke()

    def poke(self):
        """A consumer's subscriptions changed: the schedule follows."""
        self.wake.set()

    def period_ms(self):
        wanted = [c.wants() for c in list(self.consumers)]
        wanted = [p for p in wanted if p is not None and p > 0]
        if not wanted:
            return None
        return max(MIN_PERIOD_MS, min(wanted))

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, name="naoqi-sim face detector")
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.running = False
        self.wake.set()
        if self.thread is not None:
            self.thread.join(5.0)
        self._unsubscribe()

    # -- the loop -------------------------------------------------------------------
    def idle(self):
        """on_idle for every consumer that wants no detections."""
        for consumer in list(self.consumers):
            if consumer.wants() is None and hasattr(consumer, "on_idle"):
                try:
                    consumer.on_idle()
                except Exception as e:  # noqa: BLE001
                    self.log(method="consumer-failed", consumer=consumer.service, error=repr(e))

    def _run(self):
        next_at = None
        last_idle = 0.0
        while self.running:
            if self.clock() - last_idle >= IDLE_TICK_S:
                last_idle = self.clock()
                self.idle()
            period = self.period_ms()
            if period is None:
                self._unsubscribe()
                self.wake.wait(IDLE_TICK_S)
                self.wake.clear()
                next_at = None
                continue
            now = self.clock()
            if next_at is None:
                next_at = now
            if now < next_at:
                self.wake.wait(min(next_at - now, IDLE_TICK_S))
                self.wake.clear()
                continue
            # a slot missed is skipped, never caught up
            next_at = now + period / 1000.0
            detection = self.capture()
            if detection is not None:
                self.detections += 1
                for consumer in list(self.consumers):
                    if consumer.wants() is not None:
                        try:
                            consumer.on_detection(detection)
                        except Exception as e:  # noqa: BLE001
                            self.log(method="consumer-failed", consumer=consumer.service, error=repr(e))

    def _subscribe(self):
        camera = self.camera
        if self.subscription is not None and self.subscription[1] == camera:
            return self.subscription[0]
        self._unsubscribe()
        fps = max(1, min(30, int(round(1000.0 / (self.period_ms() or DEFAULT_PERIOD_MS)))))
        name = self.video.subscribeCamera(SUBSCRIBER, camera, VGA, RGB, fps)
        self.subscription = (name, camera)
        if camera not in self.maps:
            self.maps[camera] = AngleMap(self.video, camera)
        self.log(method="camera-subscribed", camera=camera, fps=fps)
        return name

    def _unsubscribe(self):
        if self.subscription is None:
            return
        try:
            self.video.unsubscribe(self.subscription[0])
        except Exception as e:  # noqa: BLE001
            self.log(method="unsubscribe-failed", error=repr(e))
        self.log(method="camera-unsubscribed", camera=self.subscription[1])
        self.subscription = None

    def capture(self):
        """One frame through the engine: a Detection, or None when the camera gave nothing."""
        try:
            name = self._subscribe()
            image = self.video.getImageRemote(name)
            if not image:
                raise RuntimeError("no image")
            width, height, data = int(image[0]), int(image[1]), image[6]
            stamp = [int(image[4]), int(image[5])]
            if not self.camera_ok:
                self.camera_ok = True
                self.log(method="camera-recovered")
        except Exception as e:  # noqa: BLE001
            if self.camera_ok:
                self.camera_ok = False
                self.log(method="camera-failed", error=repr(e))
            return None
        camera = self.subscription[1]
        raw = []
        if self.engine is not None and self.engine.available:
            try:
                raw = self.engine.detect(width, height, data)
                if self.engine_ok is not True:
                    self.engine_ok = True
                    self.log(method="engine-ok", url=self.engine.url)
            except Exception as e:  # noqa: BLE001
                raw = []
                if self.engine_ok is not False:
                    self.engine_ok = False
                    self.log(method="engine-failed", url=self.engine.url, error=repr(e))
        elif self.engine_ok is None:
            self.engine_ok = False
            self.log(method="no-engine")
        amap = self.maps[camera]
        faces = []
        for i, f in enumerate(raw):
            x, y, w, h = [float(v) for v in f["box"]]
            alpha, beta = amap.angles(x + w / 2.0, y + h / 2.0, width, height)
            size_x, size_y = amap.size(w, h, width, height)
            faces.append(Face([x, y, w, h], float(f.get("score", 0.0)), [[float(p[0]), float(p[1])] for p in f.get("landmarks", [])],
                              alpha, beta, size_x, size_y, i))
        cam_name = CAMERA_NAMES[camera]
        pose_torso = [float(v) for v in self.motion.getPosition(cam_name, FRAME_TORSO, True)]
        pose_robot = [float(v) for v in self.motion.getPosition(cam_name, FRAME_ROBOT, True)]
        transforms = {}
        for frame in (FRAME_TORSO, FRAME_WORLD, FRAME_ROBOT):
            transforms[frame] = [float(v) for v in self.motion.getTransform(cam_name, frame, True)]
        return Detection(faces, stamp, camera, pose_torso, pose_robot, transforms, width, height)


# --- FaceDetected -----------------------------------------------------------------------

def _pt(amap, x, y, width, height):
    return amap.angles(x, y, width, height)


def face_points(face, amap, width, height):
    """The documented point lists, in angles: the five landmarks where the engine gives them, the
    rest placed at a face's proportions from the box."""
    x, y, w, h = face.box
    lm = face.landmarks if len(face.landmarks) == 5 else None
    if lm is None:  # no landmarks: a face's proportions in the box
        lm = [[x + 0.3 * w, y + 0.38 * h], [x + 0.7 * w, y + 0.38 * h], [x + 0.5 * w, y + 0.6 * h],
              [x + 0.35 * w, y + 0.8 * h], [x + 0.65 * w, y + 0.8 * h]]
    right_eye, left_eye, nose, right_mouth, left_mouth = lm

    def eye(centre, toward_nose):
        cx, cy = centre
        side = 1.0 if toward_nose > 0 else -1.0  # +1: the nose is to the right in the image
        nose_side = [cx + side * EYE_SIDE * w, cy]
        ear_side = [cx - side * EYE_SIDE * w, cy]
        top = [cx, cy - EYE_UP * h]
        bottom = [cx, cy + EYE_DOWN * h]
        mid_top_ear = [(ear_side[0] + top[0]) / 2.0, (ear_side[1] + top[1]) / 2.0]
        mid_top_nose = [(nose_side[0] + top[0]) / 2.0, (nose_side[1] + top[1]) / 2.0]
        out = []
        for px, py in (centre, nose_side, ear_side, top, bottom, mid_top_ear, mid_top_nose):
            out.extend(_pt(amap, px, py, width, height))
        return out

    def brow(centre, toward_nose):
        cx, cy = centre
        side = 1.0 if toward_nose > 0 else -1.0
        by = cy - BROW_UP * h
        out = []
        for px, py in ([cx - side * EYE_SIDE * w, by], [cx + side * EYE_SIDE * w, by], [cx, by]):  # outer, inner, mid
            out.extend(_pt(amap, px, py, width, height))
        return out

    # in an unmirrored image the subject's right eye is on the image's left: its nose side is +x
    right_eye_pts = eye(right_eye, +1)
    left_eye_pts = eye(left_eye, -1)
    right_brow = brow(right_eye, +1)
    left_brow = brow(left_eye, -1)
    nx, ny = nose
    nose_pts = []
    for px, py in ([nx, ny + NOSE_DOWN * h], [nx - NOSE_SIDE * w, ny + NOSE_DOWN * h], [nx + NOSE_SIDE * w, ny + NOSE_DOWN * h]):
        nose_pts.extend(_pt(amap, px, py, width, height))
    lx, ly = right_mouth  # the image's left corner is the subject's right
    rx, ry = left_mouth
    mx, my = (lx + rx) / 2.0, (ly + ry) / 2.0
    top = [mx, my - MOUTH_UP * h]
    bottom = [mx, my + MOUTH_DOWN * h]
    mouth = [[lx, ly], [rx, ry], top, bottom,
             [(lx + top[0]) / 2.0, (ly + top[1]) / 2.0], [(rx + top[0]) / 2.0, (ry + top[1]) / 2.0],
             [(rx + bottom[0]) / 2.0, (ry + bottom[1]) / 2.0], [(lx + bottom[0]) / 2.0, (ly + bottom[1]) / 2.0]]
    mouth_pts = []
    for px, py in mouth:
        mouth_pts.extend(_pt(amap, px, py, width, height))
    # the subject's left eye is the image's right one: NAOqi's "left" is the subject's
    return left_eye_pts, right_eye_pts, left_brow, right_brow, nose_pts, mouth_pts


def face_detected_value(detection, amap):
    """FaceDetected's documented value for a detection with faces."""
    faces = []
    for face in detection.faces:
        shape = [0, face.alpha, face.beta, face.size_x, face.size_y]
        left_eye, right_eye, left_brow, right_brow, nose, mouth = face_points(face, amap, detection.width, detection.height)
        extra = [face.track_id, 0.0, "", left_eye, right_eye, left_brow, right_brow, nose, mouth]
        faces.append([shape, extra])
    faces.append([])  # Time_Filtered_Reco_Info: no recognition
    return [detection.stamp, faces, detection.pose_torso, detection.pose_robot, detection.camera]


class FaceModule(ext.Extractor):
    """ALFaceDetection's logic over the detector: a consumer of its detections."""

    def __init__(self, detector, insert, raise_event, version="2.1", log=None):
        ext.Extractor.__init__(self, NAME, EVENTS_21 if version == "2.1" else EVENTS, KEYS, {
            "ActiveCamera": 0, "Resolution": 1, "FrameRate": 5, "RecognitionConfidenceThreshold": 0.4,
            "RecognitionEnabled": True, "TrackingEnabled": False, "_DetectionMode": 0, "_FaceAnalysisEnabled": False,
        }, DEFAULT_PERIOD_MS)
        self.detector = detector
        self.insert = insert
        self.raise_event = raise_event
        self.version = version
        self.log = log or (lambda **f: None)
        self.had_faces = False
        self.last_count = None
        self.learned = []
        self.params = {}
        detector.add_consumer(self)

    # -- the detector's consumer ------------------------------------------------
    def wants(self):
        if self.paused or not self.subscribers:
            return None
        return self.getCurrentPeriod()

    def subscriptions_changed(self):
        self.detector.poke()

    def on_detection(self, detection):
        count = len(detection.faces)
        if count:
            value = face_detected_value(detection, self.detector.maps[detection.camera])
            self.had_faces = True
        elif self.had_faces:
            value = []  # the faces are gone: the empty value, once
            self.had_faces = False
        else:
            value = None
        if value is not None:
            for key in self.events:
                self.insert(key, value)
                self.raise_event(key, value)
        if count != self.last_count:
            self.last_count = count
            self.log(method="faces", count=count, camera=detection.camera)

    # -- the module's own methods -----------------------------------------------------
    def set_active_camera(self, camera):
        camera = int(camera)
        if camera not in CAMERA_NAMES:
            return False
        self.set("ActiveCamera", camera)
        self.detector.set_camera(camera)
        return True

    def set_resolution(self, resolution):
        if int(resolution) not in (0, 1, 2, 3):
            return False
        self.set("Resolution", int(resolution))
        return True

    def set_frame_rate(self, fps):
        if not 1 <= int(fps) <= 30:
            return False
        self.set("FrameRate", int(fps))
        return True

    def set_parameter(self, name, value):
        self.params[str(name)] = value

    def learn_face(self, name):
        return False  # recognition is a stub: nothing is learnt, which the caller is told

    def forget_person(self, name):
        return True

    def clear_database(self):
        return True

    def learned_faces(self):
        return []

    def whoami(self):
        return "naoqi-sim ALFaceDetection (%s, engine %s)" % (self.version, self.detector.engine.url if self.detector.engine else "none")


METHODS = ext.GENERICS + [
    ("setActiveCamera", 1, {}, lambda s, c: s.set_active_camera(c)),
    ("getActiveCamera", 0, {}, ext.getter("ActiveCamera")),
    ("setResolution", 1, {}, lambda s, r: s.set_resolution(r)),
    ("getResolution", 0, {}, ext.getter("Resolution")),
    ("setFrameRate", 1, {}, lambda s, f: s.set_frame_rate(f)),
    ("getFrameRate", 0, {}, ext.getter("FrameRate")),
    ("setParameter", 2, {}, lambda s, n, v: s.set_parameter(n, v)),
    ("setTrackingEnabled", 1, {}, ext.setter("TrackingEnabled")),
    ("isTrackingEnabled", 0, {}, ext.getter("TrackingEnabled")),
    ("enableTracking", 1, {}, ext.setter("TrackingEnabled")),
    ("setRecognitionEnabled", 1, {}, ext.setter("RecognitionEnabled")),
    ("isRecognitionEnabled", 0, {}, ext.getter("RecognitionEnabled")),
    ("enableRecognition", 1, {}, ext.setter("RecognitionEnabled")),
    ("setRecognitionConfidenceThreshold", 1, {}, ext.setter("RecognitionConfidenceThreshold")),
    ("getRecognitionConfidenceThreshold", 0, {}, ext.getter("RecognitionConfidenceThreshold")),
    ("learnFace", 1, {}, lambda s, n: s.learn_face(n)),
    ("reLearnFace", 1, {}, lambda s, n: s.learn_face(n)),
    ("importOldDatabase", 1, {}, lambda s, n: False),
    ("forgetPerson", 1, {}, lambda s, n: s.forget_person(n)),
    ("clearDatabase", 0, {}, lambda s: s.clear_database()),
    ("getLearnedFacesList", 0, {}, lambda s: s.learned_faces()),
    ("_getDetectionMode", 0, {}, ext.getter("_DetectionMode")),
    ("_setDetectionMode", 1, {}, ext.setter("_DetectionMode")),
    ("_isFaceAnalysisEnabled", 0, {}, ext.getter("_FaceAnalysisEnabled")),
    ("_setFaceAnalysisEnabled", 1, {}, ext.setter("_FaceAnalysisEnabled")),
    ("_run", 0, {}, ext.const(None)),
    ("whoami", 0, {}, lambda s: s.whoami()),
]


def write_source_key(insert, url=ENGINE_URL):
    """NaoqiSim/Perception/Source: `engine` when an engine URL is set, `none` otherwise."""
    insert(SOURCE_KEY, "engine" if url else "none")

# -*- coding: utf-8 -*-
"""The brightness statistics core (Python 2.7, inside NAOqi 2.8; importable under Python 3 for the
host's fast tier): _ALBrightnessStatistics, which tells Autonomous Life how bright and how uniform
the top camera's picture is (specs/services/brightness-statistics.md).

Between `_start()` and `_stop()` a thread reads the top camera from ALVideoDevice (QQVGA, the
luminance) ten times a second and raises `_ALBrightnessStatistics/Avg` and `.../Std`, the mean
and the standard deviation of the picture's luminance, 0 to 255. Life's stop gesture on 2.8 reads
them: the front head sensor touched while they say dark.
"""
import math
import threading
import time

NAME = "_ALBrightnessStatistics"
AVG_KEY = "_ALBrightnessStatistics/Avg"
STD_KEY = "_ALBrightnessStatistics/Std"
SUBSCRIBER = "naoqi_sim_brightness_statistics"  # our ALVideoDevice subscription's name
TOP = 0
QQVGA = 0
Y = 0  # kYuvColorSpace: the luminance only, one byte a pixel
FPS = 10
PERIOD_S = 1.0 / FPS


def statistics(data):
    """(mean, standard deviation) of a picture's bytes; None for the placeholder an unfed camera
    serves, every byte 0 (video-input.md): no picture is not a covered camera."""
    values = bytearray(data)
    n = len(values)
    if n == 0 or not any(values):
        return None
    total = float(sum(values))
    mean = total / n
    squares = float(sum(v * v for v in values))
    variance = max(0.0, squares / n - mean * mean)
    return mean, math.sqrt(variance)


class BrightnessStatistics(object):
    """The service's logic: `start()` and `stop()` are Life's `_start()` and `_stop()`."""

    def __init__(self, video_factory, raise_event, log=None, sleep=time.sleep):
        # ALVideoDevice loads after our modules (its autoload entry follows pythonbridge): the
        # proxy is made at the first start, never at load.
        self.video_factory = video_factory
        self._video = None
        self.raise_event = raise_event
        self.log = log or (lambda **f: None)
        self.sleep = sleep
        self.lock = threading.Lock()
        self.running = False
        self.thread = None
        self.subscription = None
        self.camera_ok = True
        self.samples = 0

    @property
    def video(self):
        if self._video is None:
            self._video = self.video_factory()
        return self._video

    def start(self):
        """Starts reading the camera; a second start is the same start."""
        with self.lock:
            if self.running:
                return
            self.running = True
            self.thread = threading.Thread(target=self._run, name="naoqi-sim brightness statistics")
            self.thread.daemon = True
            self.thread.start()
        self.log(method="_start")

    def stop(self):
        """Stops reading and lets go of the camera; nothing is raised after it returns."""
        with self.lock:
            if not self.running:
                return
            self.running = False
            thread, self.thread = self.thread, None
        if thread is not None:
            thread.join(5.0)
        self._unsubscribe()
        self.log(method="_stop", samples=self.samples)

    def _run(self):
        while self.running:
            started = time.time()
            self.sample()
            self.sleep(max(0.0, PERIOD_S - (time.time() - started)))

    def sample(self):
        """One picture's statistics raised; None when the camera gave no picture."""
        try:
            if self.subscription is None:
                self.subscription = self.video.subscribeCamera(SUBSCRIBER, TOP, QQVGA, Y, FPS)
                self.log(method="camera-subscribed", name=self.subscription)
            image = self.video.getImageRemote(self.subscription)
            if not image:
                raise RuntimeError("no image")
            values = statistics(image[6])
            if not self.camera_ok:
                self.camera_ok = True
                self.log(method="camera-recovered")
        except Exception as e:  # noqa: BLE001 (the camera may come back)
            if self.camera_ok:
                self.camera_ok = False
                self.log(method="camera-failed", error=repr(e))
            return None
        if values is None or not self.running:
            return None
        mean, deviation = values
        self.raise_event(AVG_KEY, mean)
        self.raise_event(STD_KEY, deviation)
        self.samples += 1
        return values

    def _unsubscribe(self):
        subscription, self.subscription = self.subscription, None
        if subscription is None:
            return
        try:
            self.video.unsubscribe(subscription)
        except Exception as e:  # noqa: BLE001
            self.log(method="unsubscribe-failed", error=repr(e))

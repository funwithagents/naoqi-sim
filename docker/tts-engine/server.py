"""naoqi-sim speech engine: Piper, one HTTP endpoint, standard library only.

POST /say   {"id": <say id>, "language": "English", "rate": 100, "pitch": 100,
             "items": [{"type":"text","text":"Hello"}, {"type":"mark","id":1}, {"type":"pause","ms":500}]}
        ->  {"duration": s, "marks": {"1": offset_s}, "rate": 22050, "engine": "en_US-ljspeech-medium"}
            The PCM is streamed to the host audio output (NAOQI_SIM_SOUNDCARD) after the reply.
            `pitch` (percent) multiplies the voice's own pitch factor (PITCH): the voice is
            synthesized slower and played faster by it. 400 for a language not installed.
POST /stop  {"id": <say id>}: cancels that say (synthesizing, about to play, or not yet arrived),
            stops streaming and asks the audio output to stop the speech stream.
GET  /health  200 once every installed language's voice is loaded, 503 until then.

Languages: NAOQI_SIM_LANGUAGES names the installed ones (NAOqi names, comma-separated: the
config's `speech.languages`). Each has one Piper voice (VOICES). The default languages' voices
are in the image (BUILTIN_DIR); any other language's voice is downloaded on its first use into
the volume (VOICE_DIR), from the pinned piper-voices release (specs/container/tts-engine.md).

Markers are exact: every text item is synthesized on its own and concatenated, so a mark's
offset is the sum of the durations before it.
"""

import collections
import json
import os
import shutil
import signal
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

# The piper-voices release every voice comes from; the Dockerfile's VOICES_TAG is the same.
VOICES_TAG = "v1.0.0"
VOICES_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/" + VOICES_TAG + "/"
# NAOqi language name -> its Piper voice (<locale>-<name>-<quality>). One voice per language,
# single-speaker, chosen by ear; every voice's own dataset is CC0, public domain or CC BY 4.0
# (checked against each MODEL_CARD on Oct 26, 2026; the table with the lineage of each voice is
# in specs/container/tts-engine.md, "Voices"). The engine never ships a voice: the user's
# machine downloads it, at the image build or on the language's first use.
VOICES = {
    "English": "en_US-ljspeech-medium",
    "French": "fr_FR-siwis-medium",
    "German": "de_DE-thorsten-medium",
    "Dutch": "nl_NL-pim-medium",
    "Swedish": "sv_SE-nst-medium",
    "Spanish": "es_ES-davefx-medium",
    "Brazilian": "pt_BR-faber-medium",
    "Czech": "cs_CZ-jirka-medium",
    "Danish": "da_DK-talesyntese-medium",
    "Finnish": "fi_FI-harri-medium",
    "Italian": "it_IT-paola-medium",
    "Norwegian": "no_NO-talesyntese-medium",
    "Polish": "pl_PL-gosia-medium",
    "Portuguese": "pt_PT-tugão-medium",
    "Russian": "ru_RU-dmitri-medium",
    "Turkish": "tr_TR-fahrettin-medium",
}
# Their voices are in the image (the Dockerfile fetches exactly these); the config's default too.
DEFAULT_LANGUAGES = ("English", "French")
# A voice's pitch factor: the voice is synthesized slower by it and played faster by it, so
# its pitch and its formants both rise by it and the speech keeps its length, as a NAO's own
# voice is a pitched-up adult one. 1.15 (chosen by ear, Oct 29, 2026) turns the English and
# French voices from a woman's into a child's; the others are left as they are. A say's
# `pitch` (percent: NAOqi's pitchShift and \vct) multiplies it, within PITCH_RANGE.
PITCH = {"English": 1.15, "French": 1.15}
PITCH_RANGE = (0.5, 4.0)  # a NAO's pitchShift goes to 4
BUILTIN_DIR = os.environ.get("NAOQI_SIM_BUILTIN_VOICES", "/voices-builtin")
VOICE_DIR = os.environ.get("NAOQI_SIM_VOICES", "/voices")  # the volume
SOUNDCARD = os.environ.get("NAOQI_SIM_SOUNDCARD", "host.docker.internal:9562")
# The installed languages: set from NAOQI_SIM_LANGUAGES when the server starts.
LANGUAGES = DEFAULT_LANGUAGES

_voices = {}  # language -> its loaded PiperVoice
_lock = threading.Lock()
_ready = {"ok": False}  # every installed language's voice is loaded
_stop = threading.Event()
# The ids of the says that were stopped (the last few): a /stop names its say's id, so a stop
# cancels that say whether it is synthesizing, about to stream, or has not even arrived yet.
_cancelled: collections.deque[object] = collections.deque(maxlen=64)


class Cancelled(Exception):
    """The say was stopped while it was being rendered."""


class UnknownLanguage(Exception):
    """A language that is not installed (the NAOqi side refuses it first)."""


def stop_say(say_id) -> None:
    """Cancels the say with that id, now or when it arrives."""
    if say_id is not None:
        _cancelled.append(say_id)


def cancelled(say_id) -> bool:
    return say_id is not None and say_id in _cancelled


_current = {"sock": None}


# --- Languages and voices ---------------------------------------------------------------


def installed_languages(spec):
    """The languages NAOQI_SIM_LANGUAGES names (comma-separated), the defaults when empty; a
    name without a voice is an error (the config refuses it before any container starts)."""
    names = [n.strip() for n in spec.split(",") if n.strip()] or list(DEFAULT_LANGUAGES)
    unknown = [n for n in names if n not in VOICES]
    if unknown:
        raise ValueError(
            f"no voice for {', '.join(unknown)}; the languages with one: {', '.join(VOICES)}"
        )
    return tuple(dict.fromkeys(names))


def voice_path(key):
    """The voice's path in piper-voices: <language>/<locale>/<name>/<quality>/<key>."""
    locale, rest = key.split("-", 1)
    name, quality = rest.rsplit("-", 1)
    return f"{locale.split('_')[0]}/{locale}/{name}/{quality}/{key}"


def find_voice(key):
    """The voice's .onnx (its .onnx.json beside it) in the image, else in the volume; None when
    neither has it."""
    for root in (BUILTIN_DIR, VOICE_DIR):
        onnx = os.path.join(root, VOICES_TAG, key + ".onnx")
        if os.path.exists(onnx) and os.path.exists(onnx + ".json"):
            return onnx
    return None


def fetch(url, dest):
    """Downloads `url` to `dest` through a temporary name, so a download that dies leaves no
    half file under the final one."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    with urllib.request.urlopen(url, timeout=60) as response, open(part, "wb") as f:
        shutil.copyfileobj(response, f)
    os.replace(part, dest)


def ensure_voice(language):
    """The .onnx of the language's voice: from the image or the volume, else downloaded into
    the volume (the language's first use; about 60 MB)."""
    key = VOICES[language]
    onnx = find_voice(key)
    if onnx is not None:
        return onnx
    onnx = os.path.join(VOICE_DIR, VOICES_TAG, key + ".onnx")
    url = VOICES_URL + urllib.parse.quote(voice_path(key))  # a key may be non-ASCII
    print(
        f"fetching the {language} voice {key} into {VOICE_DIR} (about 60 MB)",
        flush=True,
    )
    t = time.time()
    fetch(url + ".onnx.json", onnx + ".json")
    fetch(url + ".onnx", onnx)
    print(f"fetched {key} in {time.time() - t:.1f}s", flush=True)
    return onnx


def piper_voice(language):
    """The loaded voice of an installed language, loading it (and fetching it) on first use."""
    with _lock:
        voice = _voices.get(language)
    if voice is not None:
        return voice
    if language not in LANGUAGES:
        raise UnknownLanguage(language)
    onnx = ensure_voice(language)
    from piper import PiperVoice

    voice = PiperVoice.load(onnx, config_path=onnx + ".json")
    with _lock:
        _voices[language] = voice
    return voice


def health():
    """The /health reply, and whether it is a 200: every installed language's voice loaded."""
    with _lock:
        loaded = set(_voices)
    return _ready["ok"], {
        "ok": _ready["ok"],
        "languages": {
            lang: {"voice": VOICES[lang], "loaded": lang in loaded}
            for lang in LANGUAGES
        },
        "voices_tag": VOICES_TAG,
        "soundcard": SOUNDCARD,
    }


# --- Synthesis ---------------------------------------------------------------------------


def pitch_factor(language, pitch):
    """The factor the language's voice is pitched up by: its own (PITCH) times the say's
    `pitch` (percent, 100 = as the voice is), kept within PITCH_RANGE."""
    factor = PITCH.get(language, 1.0) * float(pitch or 100) / 100.0
    return min(max(factor, PITCH_RANGE[0]), PITCH_RANGE[1])


def shift(pcm, factor):
    """`pcm` played `factor` times faster: pitch and formants up by `factor`, the length
    divided by it (the synthesis was slowed by the same factor, so it comes out unchanged)."""
    return pcm if factor == 1.0 else resample(pcm, factor, 1.0)


def synth_piper(text, language, rate, pitch=100):
    voice = piper_voice(language)
    sr = voice.config.sample_rate
    from piper import SynthesisConfig

    factor = pitch_factor(language, pitch)
    cfg = SynthesisConfig(length_scale=factor * 100.0 / max(rate, 20))
    chunks = [
        np.frombuffer(ch.audio_int16_bytes, dtype=np.int16)
        for ch in voice.synthesize(text, cfg)
    ]
    pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
    return shift(pcm, factor), sr, VOICES[language]


def resample(pcm, sr_from, sr_to):
    if sr_from == sr_to or len(pcm) == 0:
        return pcm
    n = int(len(pcm) * sr_to / sr_from)
    x = np.linspace(0, len(pcm) - 1, n)
    return np.interp(x, np.arange(len(pcm)), pcm.astype(np.float32)).astype(np.int16)


def render(req):
    """The request's audio, marks, rate and voice; `UnknownLanguage` for a language not
    installed, `Cancelled` when a /stop named its id, checked before each item (an item is
    synthesized whole)."""
    lang = req.get("language") or LANGUAGES[0]
    if lang not in LANGUAGES:
        raise UnknownLanguage(lang)
    rate = float(req.get("rate") or 100)
    pitch = float(req.get("pitch") or 100)
    say_id = req.get("id")
    parts, marks, sr, used = [], {}, None, VOICES[lang]
    total = 0.0
    for item in req.get("items", []):
        if cancelled(say_id):
            raise Cancelled()
        t = item.get("type")
        if t == "text":
            text = (item.get("text") or "").strip()
            if not text:
                continue
            pcm, sr_i, used = synth_piper(text, lang, rate, pitch)
            if sr is None:
                sr = sr_i
            pcm = resample(pcm, sr_i, sr)
            parts.append(pcm)
            total += len(pcm) / float(sr)
        elif t == "mark":
            marks[str(item.get("id"))] = round(total, 4)
        elif t == "pause":
            if sr is None:
                sr = 22050
            n = int(sr * float(item.get("ms") or 0) / 1000.0)
            parts.append(np.zeros(n, dtype=np.int16))
            total += n / float(sr)
    if sr is None:
        sr = 22050
    pcm = np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)
    return pcm, sr, marks, used


# --- The audio output ----------------------------------------------------------------------

# The audio output mixes named streams; speech is one, so stopping it leaves the sounds
# ALAudioPlayer plays (specs/host/audio-output.md, "Streams").
STREAM = "speech"


def soundcard_connect():
    host, port = SOUNDCARD.rsplit(":", 1)
    s = socket.create_connection((host, int(port)), timeout=5)
    return s


def stream_to_soundcard(pcm, sr, say_id=None):
    """Send a header line then raw PCM; the sound card plays as it receives. Returns when sent,
    or at once (nothing sent) when the say was stopped meanwhile."""
    if cancelled(say_id):
        return
    _stop.clear()
    s = soundcard_connect()
    _current["sock"] = s
    try:
        s.sendall(
            (
                json.dumps(
                    {
                        "cmd": "play",
                        "stream": STREAM,
                        "rate": sr,
                        "channels": 1,
                        "format": "s16le",
                    }
                )
                + "\n"
            ).encode()
        )
        data = pcm.tobytes()
        chunk = sr * 2 // 10  # 100 ms
        for i in range(0, len(data), chunk):
            if _stop.is_set() or cancelled(say_id):
                break
            s.sendall(data[i : i + chunk])
    finally:
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        s.close()
        _current["sock"] = None


def soundcard_stop():
    try:
        s = soundcard_connect()
        s.sendall((json.dumps({"cmd": "stop", "stream": STREAM}) + "\n").encode())
        s.close()
    except OSError as e:
        print("stop: sound card unreachable:", e)


# --- HTTP ----------------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            ok, reply = health()
            return self._json(200 if ok else 503, reply)
        self._json(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        req = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/stop":
            stop_say(req.get("id"))
            _stop.set()
            soundcard_stop()
            return self._json(200, {"stopped": True})
        if self.path != "/say":
            return self._json(404, {"error": "not found"})
        t0 = time.time()
        say_id = req.get("id")
        try:
            pcm, sr, marks, used = render(req)
        except UnknownLanguage as e:
            return self._json(
                400,
                {
                    "error": f"language {e} is not installed (installed: {', '.join(LANGUAGES)})"
                },
            )
        except Cancelled:
            print(f"say {say_id}: stopped during synthesis")
            return self._json(200, self._stopped(req, t0))
        except Exception as e:  # noqa: BLE001
            print("render error:", repr(e))
            return self._json(500, {"error": repr(e)})
        if cancelled(say_id):  # stopped after the last item: nothing to play
            print(f"say {say_id}: stopped before playing")
            return self._json(200, self._stopped(req, t0))
        synth = time.time() - t0
        duration = len(pcm) / float(sr)
        # Stream in the background so the reply (and the caller's clock) starts with the audio.
        th = threading.Thread(
            target=self._safe_stream, args=(pcm, sr, say_id), daemon=True
        )
        th.start()
        print(f"say: {used} {duration:.2f}s audio, synth {synth:.2f}s, marks {marks}")
        self._json(
            200,
            {
                "duration": round(duration, 4),
                "marks": marks,
                "rate": sr,
                "engine": used,
                "synth_time": round(synth, 3),
            },
        )

    def _stopped(self, req, t0):
        """The reply for a say stopped before it played: no audio, `stopped` set."""
        return {
            "duration": 0.0,
            "marks": {},
            "rate": 22050,
            "engine": VOICES.get(req.get("language") or LANGUAGES[0], ""),
            "synth_time": round(time.time() - t0, 3),
            "stopped": True,
        }

    def _safe_stream(self, pcm, sr, say_id=None):
        try:
            stream_to_soundcard(pcm, sr, say_id)
        except OSError as e:
            print(f"sound card unreachable ({e}): audio dropped")

    def log_message(self, fmt, *args):  # quieter
        pass


if __name__ == "__main__":
    # The server is the container's PID 1, to which the kernel applies no default signal action:
    # without a handler `docker stop` would wait its 10 s grace period, then kill it.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    try:
        LANGUAGES = installed_languages(os.environ.get("NAOQI_SIM_LANGUAGES", ""))
    except ValueError as e:
        print(f"naoqi-sim tts: {e}", flush=True)
        sys.exit(1)
    print(
        f"naoqi-sim tts: languages={','.join(LANGUAGES)} soundcard={SOUNDCARD} "
        f"voices {VOICES_TAG} from {BUILTIN_DIR} (image) and {VOICE_DIR} (volume)",
        flush=True,
    )
    # /health answers (503) while the voices load, so the healthcheck sees the engine starting.
    httpd = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    for (
        lang
    ) in LANGUAGES:  # pre-load (and fetch) the voices so the first say() does not pay
        t = time.time()
        try:
            piper_voice(lang)
        except Exception as e:  # noqa: BLE001
            print(f"naoqi-sim tts: cannot load the {lang} voice: {e!r}", flush=True)
            sys.exit(1)
        print(f"loaded {VOICES[lang]} ({lang}) in {time.time() - t:.2f}s", flush=True)
    _ready["ok"] = True
    print("naoqi-sim tts: ready", flush=True)
    while True:  # SIGTERM ends the process from here
        time.sleep(3600)

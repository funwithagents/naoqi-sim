"""naoqi-sim speech recognition engine: Vosk behind a small HTTP API, standard library only besides
vosk. It knows nothing about NAOqi (specs/container/asr-engine.md): it listens to the audio posted
to it for a list of phrases and says what it heard.

POST /start  {"language": "English", "phrases": [...], "word_spotting": false}
         ->  {"phrases": n, "dropped": [...], "build_ms": t}
             a new session for these phrases (any audio so far forgotten); `dropped` the phrases
             holding a word the model does not know. A phrase may begin or end with "<...>":
             unknown speech is then allowed there. An unknown language is a 400.
POST /audio  raw PCM, 16 kHz mono signed 16-bit little-endian, any length
         ->  {"speech": bool, "final": null | {"phrase": p, "confidence": c, "text": t,
                                               "lead": bool, "trail": bool}}
             `speech` true while words are being heard; `final` with the buffer that ends an
             utterance: `phrase` the phrase as given when what was heard equals one (unknown speech
             around it allowed with word spotting, or where the phrase has "<...>"), else "".
POST /stop   drops the session.
GET  /health 200 {"ok": true, "recognizer": "vosk", "languages": [...], "models": {...}} once
             every installed language's model is loaded, 503 {"ok": false, ...} before.

Languages: NAOQI_SIM_LANGUAGES names the installed ones (NAOqi names, comma-separated: the
config's `robot.available_languages`). Each has one Vosk model (MODELS). The default languages'
models are in the image (BUILTIN_DIR); any other language's model is downloaded on its first use
into the language packs volume (MODEL_DIR), its SHA-256 checked (MODEL_SHA256).
"""

import hashlib
import json
import os
import shutil
import signal
import sys
import threading
import time
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RECOGNIZER = "vosk"
SAMPLE_RATE = 16000
UNKNOWN = "[unk]"  # the token Vosk gives for speech outside the grammar
MARKER = "<...>"  # unknown speech allowed here, in a phrase
# NAOqi's language names with a Vosk model, in the speech engine's table order (the config's
# LANGUAGES repeats them: a language pack is a voice and a model; the fast tier checks both).
# One small model per language (asr-engine.md, "Models"); Portuguese has no model of its own
# and recognises with the Brazilian one.
MODELS = {
    "English": "vosk-model-small-en-us-0.15",
    "French": "vosk-model-small-fr-0.22",
    "German": "vosk-model-small-de-0.15",
    "Dutch": "vosk-model-small-nl-0.22",
    "Swedish": "vosk-model-small-sv-rhasspy-0.15",
    "Spanish": "vosk-model-small-es-0.42",
    "Brazilian": "vosk-model-small-pt-0.3",
    "Czech": "vosk-model-small-cs-0.4-rhasspy",
    "Italian": "vosk-model-small-it-0.22",
    "Polish": "vosk-model-small-pl-0.22",
    "Portuguese": "vosk-model-small-pt-0.3",
    "Russian": "vosk-model-small-ru-0.22",
    "Turkish": "vosk-model-small-tr-0.3",
}
# Each model's archive, as fetched from MODEL_URL (the Dockerfile pins the defaults' the same).
MODEL_SHA256 = {
    "vosk-model-small-en-us-0.15": "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498",
    "vosk-model-small-fr-0.22": "cabf6180e177eb9b3a9a9d43a437bd5e549f3a7d09525e5d69a3fed787be12ad",
    "vosk-model-small-de-0.15": "b7e53c90b1f0a38456f4cd62b366ecd58803cd97cd42b06438e2c131713d5e43",
    "vosk-model-small-nl-0.22": "039811c3b829de64e4f123a9f684a53784005b212a346ac0b899dc7efce2ed0a",
    "vosk-model-small-sv-rhasspy-0.15": "5b54f2ca8cacf9766588d05f6c8ca7e8921f054f050726e29d3516e78aefe054",
    "vosk-model-small-es-0.42": "09b239888f633ef2f0b4e09736e3d9936acfd810bc65d53fad45261762c6511f",
    "vosk-model-small-pt-0.3": "6e1ce909032e1afa7a88e68a3d628ecafff302bdf195befab308826c395e93b7",
    "vosk-model-small-cs-0.4-rhasspy": "287c3bbefc8ad67b4ab9636eecef3d62acc3719990777d03e226db5a7f19fbda",
    "vosk-model-small-it-0.22": "9ec65e75861d1c6c2e457cccd932705340dcdf233f5b239f00733b4de0bf3267",
    "vosk-model-small-pl-0.22": "c4cd16498ea544f446f9e9a55cbd602b71cfe5a2b6f2b0834d81e1b6fce15f0d",
    "vosk-model-small-ru-0.22": "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4",
    "vosk-model-small-tr-0.3": "8c8d07cec1bce31add14967c16891c84152cdf76d391e33c08278119b9ea96e5",
}
MODEL_URL = "https://alphacephei.com/vosk/models/"
# Their models are in the image (the Dockerfile fetches exactly these); the config's default too.
DEFAULT_LANGUAGES = ("English", "French")
BUILTIN_DIR = os.environ.get("NAOQI_SIM_BUILTIN_MODELS", "/asr-models-builtin")
MODEL_DIR = os.environ.get(
    "NAOQI_SIM_ASR_MODELS", "/language-packs/asr-models"
)  # the volume
# The installed languages: set from NAOQI_SIM_LANGUAGES when the server starts.
LANGUAGES = DEFAULT_LANGUAGES

_lock = threading.Lock()  # one session at a time, and the models while loading
_models = None  # language -> model, once loaded (`/health` answers 503 before)
_session = None


class VoskModel:
    """One language's model: whether it knows a word, and a recogniser for a phrase list."""

    def __init__(self, path):
        import vosk  # imported here so the HTTP plumbing is testable without vosk

        vosk.SetLogLevel(-1)
        self._vosk = vosk
        self._model = vosk.Model(path)

    def knows(self, word):
        return self._model.vosk_model_find_word(word) >= 0

    def recognizer(self, phrases):
        rec = self._vosk.KaldiRecognizer(
            self._model,
            SAMPLE_RATE,
            json.dumps(phrases + [UNKNOWN], ensure_ascii=False),
        )
        rec.SetWords(True)
        return rec


def normalise(text):
    """Lower case; letters, digits and apostrophes kept, anything else a space."""
    kept = "".join(c if c.isalnum() or c == "'" else " " for c in text.lower())
    return " ".join(kept.split())


def parse_phrase(phrase):
    """A phrase as given -> (its normalised words, unknown speech allowed before, after)."""
    text = phrase.strip()
    lead = text.startswith(MARKER)
    trail = text.endswith(MARKER) and len(text) > len(MARKER)
    return normalise(text.replace(MARKER, " ")), lead, trail


class Session:
    """One listening session: the phrases, the recogniser, whether speech is being heard."""

    def __init__(self, model, phrases, word_spotting):
        self.word_spotting = bool(word_spotting)
        self.phrases = {}  # normalised -> (phrase as given, lead allowed, trail allowed)
        self.dropped = []
        for phrase in phrases:
            key, lead, trail = parse_phrase(phrase)
            if not key or key in self.phrases:
                continue
            if all(model.knows(w) for w in key.split()):
                self.phrases[key] = (phrase, lead, trail)
            else:
                self.dropped.append(phrase)
        self.recognizer = model.recognizer(sorted(self.phrases))
        self.speech = False

    def feed(self, pcm):
        final = None
        if self.recognizer.AcceptWaveform(pcm):
            result = json.loads(self.recognizer.Result())
            if result.get("text") or self.speech:
                final = self.decide(result)
            self.speech = False
        else:
            partial = json.loads(self.recognizer.PartialResult()).get("partial", "")
            if partial:
                self.speech = True
        return {"speech": self.speech, "final": final}

    def decide(self, result):
        """What an utterance's result means: the phrase heard, or "" (unknown speech). Without
        word spotting the utterance must equal a phrase; with it (or on the side of a phrase
        that has a `<...>` marker) other speech may come before and after, whatever the
        recogniser made of it (it may hear an unknown word as one of the list's words), and
        the longest phrase found as consecutive words wins."""
        text = result.get("text", "")
        tokens = text.split()
        words = result.get("result", [])
        best = None
        for i in range(len(tokens)):
            for j in range(len(tokens), i, -1):
                if best is not None and j - i <= best[1] - best[0]:
                    break
                entry = self.phrases.get(" ".join(tokens[i:j]))
                if entry is None or UNKNOWN in tokens[i:j]:
                    continue
                _, lead_ok, trail_ok = entry
                if (i > 0 and not (self.word_spotting or lead_ok)) or (
                    j < len(tokens) and not (self.word_spotting or trail_ok)
                ):
                    continue
                best = (i, j, entry)
        if best is None:
            return {
                "phrase": "",
                "confidence": 0.0,
                "text": text,
                "lead": False,
                "trail": False,
            }
        i, j, entry = best
        # the phrase's own words' confidences, when the result lists every word of the text
        span = words[i:j] if len(words) == len(tokens) else words
        confidences = [
            float(w.get("conf", 1.0)) for w in span if w.get("word") != UNKNOWN
        ]
        return {
            "phrase": entry[0],
            "confidence": round(min(confidences), 4) if confidences else 0.0,
            "text": text,
            "lead": i > 0,
            "trail": j < len(tokens),
        }


def set_models(models):
    """The models the handler uses (the real ones at start, fakes in the tests); None unloads."""
    global _models, _session
    with _lock:
        _models = models
        _session = None


def start(request):
    global _session
    language = request.get("language")
    phrases = request.get("phrases") or []
    if not isinstance(phrases, list) or not all(isinstance(p, str) for p in phrases):
        return 400, {"error": "phrases must be a list of strings"}
    with _lock:
        if _models is None:
            return 503, {"error": "the models are not loaded"}
        if language not in _models:
            return 400, {"error": f"no model for the language {language!r}"}
        t0 = time.perf_counter()
        _session = Session(
            _models[language], phrases, request.get("word_spotting", False)
        )
        return 200, {
            "phrases": len(_session.phrases),
            "dropped": _session.dropped,
            "build_ms": round((time.perf_counter() - t0) * 1000, 2),
        }


def audio(pcm):
    if len(pcm) % 2:
        return 400, {"error": "16-bit samples: the body must have an even length"}
    with _lock:
        if _session is None:
            return 200, {"speech": False, "final": None}
        return 200, _session.feed(pcm)


def stop():
    global _session
    with _lock:
        _session = None
    return 200, {"ok": True}


def health():
    with _lock:
        if _models is None:
            return 503, {"ok": False, "languages": list(LANGUAGES)}
        return 200, {
            "ok": True,
            "recognizer": RECOGNIZER,
            "languages": list(_models),
            "models": {lang: MODELS[lang] for lang in _models},
        }


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._reply(*health())
        else:
            self._reply(404, {"error": "unknown path"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            if self.path == "/start":
                try:
                    request = json.loads(body or b"{}")
                except ValueError as e:
                    self._reply(400, {"error": f"not JSON: {e}"})
                    return
                if not isinstance(request, dict):
                    self._reply(400, {"error": "a JSON object is expected"})
                    return
                self._reply(*start(request))
            elif self.path == "/audio":
                self._reply(*audio(body))
            elif self.path == "/stop":
                self._reply(*stop())
            else:
                self._reply(404, {"error": "unknown path"})
        except Exception as e:  # noqa: BLE001  (the caller gets the reason)
            self._reply(500, {"error": repr(e)})

    def log_message(self, fmt, *args):  # quieter
        pass


# --- Languages and models ----------------------------------------------------------------


def installed_languages(spec):
    """The languages NAOQI_SIM_LANGUAGES names (comma-separated), the defaults when empty; a
    name without a model is an error (the config refuses it before any container starts)."""
    names = [n.strip() for n in spec.split(",") if n.strip()] or list(DEFAULT_LANGUAGES)
    unknown = [n for n in names if n not in MODELS]
    if unknown:
        raise ValueError(
            f"no model for {', '.join(unknown)}; the languages with one: {', '.join(MODELS)}"
        )
    return tuple(dict.fromkeys(names))


def find_model(name):
    """The model's folder in the image, else in the volume; None when neither has it."""
    for root in (BUILTIN_DIR, MODEL_DIR):
        path = os.path.join(root, name)
        if os.path.isdir(path):
            return path
    return None


def fetch_model(name):
    """Downloads a model's archive into the volume, checks its SHA-256 and unpacks it. The
    archive goes through a temporary name and the folder appears by a rename, so a container
    killed mid-download leaves no half model under the final name."""
    os.makedirs(MODEL_DIR, exist_ok=True)
    part = os.path.join(MODEL_DIR, name + ".zip.part")
    unpacked = os.path.join(MODEL_DIR, "." + name + ".unpacking")
    digest = hashlib.sha256()
    try:
        url = MODEL_URL + name + ".zip"
        with urllib.request.urlopen(url, timeout=60) as response, open(part, "wb") as f:
            for chunk in iter(lambda: response.read(1 << 20), b""):
                digest.update(chunk)
                f.write(chunk)
        if digest.hexdigest() != MODEL_SHA256[name]:
            raise ValueError(
                f"{name}.zip has SHA-256 {digest.hexdigest()}, not {MODEL_SHA256[name]}"
            )
        shutil.rmtree(unpacked, ignore_errors=True)
        with zipfile.ZipFile(part) as archive:
            archive.extractall(unpacked)
        os.replace(os.path.join(unpacked, name), os.path.join(MODEL_DIR, name))
    finally:
        shutil.rmtree(unpacked, ignore_errors=True)
        if os.path.exists(part):
            os.remove(part)
    return os.path.join(MODEL_DIR, name)


def ensure_model(language):
    """The folder of the language's model: from the image or the volume, else downloaded into
    the volume (the language's first use; 30 to 290 MB)."""
    name = MODELS[language]
    path = find_model(name)
    if path is not None:
        return path
    print(f"fetching the {language} model {name} into {MODEL_DIR}", flush=True)
    t = time.time()
    path = fetch_model(name)
    print(f"fetched {name} in {time.time() - t:.1f}s", flush=True)
    return path


def load_models(languages, model_class=VoskModel):
    """language -> loaded model, for the installed languages, each model fetched if missing and
    loaded once (Portuguese and Brazilian share theirs)."""
    loaded = {}
    models = {}
    for lang in languages:
        name = MODELS[lang]
        if name not in loaded:
            t = time.time()
            loaded[name] = model_class(ensure_model(lang))
            print(f"loaded {name} ({lang}) in {time.time() - t:.2f}s", flush=True)
        models[lang] = loaded[name]
    return models


if __name__ == "__main__":
    # The server is the container's PID 1, to which the kernel applies no default signal action:
    # without this handler `docker stop` would wait its grace period and kill it.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    try:
        LANGUAGES = installed_languages(os.environ.get("NAOQI_SIM_LANGUAGES", ""))
    except ValueError as e:
        print(f"naoqi-sim asr: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
    print(
        f"naoqi-sim asr: languages={','.join(LANGUAGES)}, models from {BUILTIN_DIR} (image) "
        f"and {MODEL_DIR} (volume)",
        flush=True,
    )
    # /health answers (503) while the models load, so the healthcheck sees the engine starting.
    httpd = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        set_models(load_models(LANGUAGES))
    except Exception as e:  # noqa: BLE001
        print(
            f"naoqi-sim asr: cannot load the models: {e!r}", file=sys.stderr, flush=True
        )
        sys.exit(1)
    print(
        f"speech recognition engine ready: {RECOGNIZER}, {', '.join(LANGUAGES)}",
        flush=True,
    )
    while True:
        time.sleep(3600)

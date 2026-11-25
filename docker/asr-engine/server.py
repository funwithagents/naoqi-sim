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
GET  /health 200 {"ok": true, "recognizer": "vosk", "languages": [...]} once the models are
             loaded, 503 {"ok": false} before.
"""

import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RECOGNIZER = "vosk"
SAMPLE_RATE = 16000
UNKNOWN = "[unk]"  # the token Vosk gives for speech outside the grammar
MARKER = "<...>"  # unknown speech allowed here, in a phrase
MODEL_DIR = os.environ.get("NAOQI_SIM_ASR_MODELS", "/models")
MODELS = {
    "English": "vosk-model-small-en-us-0.15",
    "French": "vosk-model-small-fr-0.22",
}

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
            return 503, {"ok": False}
        return 200, {"ok": True, "recognizer": RECOGNIZER, "languages": sorted(_models)}


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


def load_models(model_dir=MODEL_DIR):
    return {
        lang: VoskModel(os.path.join(model_dir, name)) for lang, name in MODELS.items()
    }


if __name__ == "__main__":
    # The server is the container's PID 1, to which the kernel applies no default signal action:
    # without this handler `docker stop` would wait its grace period and kill it.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    httpd = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        set_models(load_models())
    except Exception as e:  # noqa: BLE001
        print(
            f"cannot load the speech recognition models from {MODEL_DIR}: {e!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(
        f"speech recognition engine ready: {RECOGNIZER}, {', '.join(sorted(MODELS))}",
        flush=True,
    )
    while True:
        time.sleep(3600)

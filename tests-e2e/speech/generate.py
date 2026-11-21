"""Generates the live speech recognition tests' sentences (tests-e2e/speech/*.wav) with Piper, in a
throwaway Linux container (Piper's macOS wheels cannot synthesize). Run it again only to change
a sentence or a voice; the WAVs are committed, the tests never synthesize. The voices and their
licences are in README.md.

    uv run python tests-e2e/speech/generate.py
"""

import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RATE = 16000
PIPER = "piper-tts==1.8.0"
VOICES_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
# Both trained from scratch on a permissive dataset (README.md, "Voices"). The French voice is
# multi-speaker: speaker 14 was picked as one Vosk recognises cleanly (none of its speakers said
# "je veux une pomme" well enough, so the French sentence is a longer one).
VOICES = {
    "English": ("en/en_US/ljspeech/medium/en_US-ljspeech-medium", None),
    "French": ("fr/fr_FR/mls/medium/fr_FR-mls-medium", 14),
}
SENTENCES = {
    "English": [
        "hello robot",
        "what time is it",
        "the weather is nice today",
        "tell me what time is it please",
    ],
    "French": ["bonjour je voudrais une pomme rouge"],
}

# Runs in the container: reads the jobs as JSON on stdin, writes one raw int16 file per job to
# /out, prints each voice's sample rate.
INNER = """
import json, os, sys, urllib.request
from piper import PiperVoice, SynthesisConfig
jobs = json.load(sys.stdin)
rates = {}
for voice_path, speaker, text, name in jobs:
    onnx = "/tmp/" + os.path.basename(voice_path) + ".onnx"
    if not os.path.exists(onnx):
        for ext in (".onnx", ".onnx.json"):
            urllib.request.urlretrieve(VOICES_URL + "/" + voice_path + ext, "/tmp/" + os.path.basename(voice_path) + ext)
    voice = PiperVoice.load(onnx)
    rates[name] = voice.config.sample_rate
    pcm = b"".join(c.audio_int16_bytes for c in voice.synthesize(text, SynthesisConfig(speaker_id=speaker)))
    open("/out/" + name + ".raw", "wb").write(pcm)
print(json.dumps(rates))
"""


def file_name(text: str) -> str:
    return text.replace(" ", "_").replace("'", "")


def main() -> None:
    jobs = [
        (
            VOICES[language][0],
            VOICES[language][1],
            text,
            f"{language.lower()}-{file_name(text)}",
        )
        for language, texts in SENTENCES.items()
        for text in texts
    ]
    out = HERE / ".raw"
    out.mkdir(exist_ok=True)
    inner = f"VOICES_URL = {VOICES_URL!r}\n" + INNER
    run = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            "-v",
            f"{out}:/out",
            "-e",
            f"INNER={inner}",
            "python:3.12-slim",
            "sh",
            "-c",
            f'pip install -q --root-user-action=ignore {PIPER} >&2 && python -c "$INNER"',
        ],
        input=json.dumps(jobs).encode(),
        capture_output=True,
        check=False,
    )
    if run.returncode:
        sys.exit(run.stderr.decode())
    rates = json.loads(run.stdout.decode().strip().splitlines()[-1])
    for name, rate in rates.items():
        raw = out / f"{name}.raw"
        pcm = np.frombuffer(raw.read_bytes(), dtype="<i2").astype(np.float64)
        n = int(len(pcm) * RATE / rate)
        mono = np.interp(
            np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm
        ).astype("<i2")
        with wave.open(str(HERE / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(mono.tobytes())
        raw.unlink()
        print(f"{name}.wav  {n / RATE:.2f} s")
    out.rmdir()


if __name__ == "__main__":
    main()

"""Records the live speech recognition tests' sentences (tests-e2e/speech/*.wav) from a real NAO's
front microphone: the robot says "recording", records for `--seconds` while you say the
sentences below in this order with about 2 s of silence between them, says "done"; the
recording is copied back over SSH (as `nao`), deleted from the robot, and cut into one file per
sentence at the silences. Only ALAudioRecorder is used: nothing on the robot is replaced.
Listen to the files and check them against the tests before committing (README.md).

    uv run python tests-e2e/speech/record.py <robot-ip> [--seconds 45]
"""

import argparse
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import qi

HERE = Path(__file__).resolve().parent
RATE = 16000
FRAME = 320  # 20 ms
REMOTE = "/home/nao/naoqi_sim_speech_take.wav"
SENTENCES = [
    "english-hello_robot",
    "english-what_time_is_it",
    "english-the_weather_is_nice_today",
    "english-tell_me_what_time_is_it_please",
    "french-je_veux_une_pomme",
]


def record(ip: str, seconds: float, local: Path) -> None:
    session = qi.Session()
    session.connect(f"tcp://{ip}:9559")
    tts = session.service("ALTextToSpeech")
    recorder = session.service("ALAudioRecorder")
    tts.say("recording")
    time.sleep(0.3)
    recorder.startMicrophonesRecording(REMOTE, "wav", RATE, [0, 0, 1, 0])  # front only
    try:
        time.sleep(seconds)
    finally:
        recorder.stopMicrophonesRecording()
    tts.say("done")
    subprocess.run(["scp", "-q", f"nao@{ip}:{REMOTE}", str(local)], check=True)
    subprocess.run(["ssh", f"nao@{ip}", "rm", "-f", REMOTE], check=True)


def sentences(pcm: np.ndarray) -> list[tuple[int, int]]:
    """The sample ranges where someone speaks: 20 ms frames louder than the room, gaps shorter
    than 0.6 s joined, blips under 0.25 s dropped."""
    frames = pcm[: len(pcm) // FRAME * FRAME].astype(np.float64).reshape(-1, FRAME)
    energy = np.sqrt(np.mean(frames**2, axis=1))
    room = np.percentile(energy, 20)
    loud = np.flatnonzero(energy > max(4 * room, room + 150))
    spans: list[list[int]] = []
    for i in loud.tolist():
        if spans and i - spans[-1][1] <= 30:
            spans[-1][1] = i
        else:
            spans.append([i, i])
    return [(a * FRAME, (b + 1) * FRAME) for a, b in spans if b - a > 12]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Records the test sentences from a NAO."
    )
    parser.add_argument("ip")
    parser.add_argument("--seconds", type=float, default=45.0)
    args = parser.parse_args()
    print("Say, in this order, about 2 s apart:", *SENTENCES, sep="\n  ")
    with tempfile.TemporaryDirectory() as tmp:
        take = Path(tmp) / "take.wav"
        record(args.ip, args.seconds, take)
        with wave.open(str(take)) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    found = sentences(pcm)
    if len(found) != len(SENTENCES):
        sys.exit(
            f"{len(found)} sentences heard, {len(SENTENCES)} expected: record again"
        )
    for (start, end), name in zip(found, SENTENCES, strict=True):
        cut = pcm[max(0, start - RATE // 4) : end + int(0.3 * RATE)]
        with wave.open(str(HERE / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(cut.tobytes())
        print(f"{name}.wav  {len(cut) / RATE:.2f} s")


if __name__ == "__main__":
    main()

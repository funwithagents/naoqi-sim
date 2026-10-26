# naoqi-sim speech engine container: Piper (onnxruntime), native architecture (no emulation).
# Knows nothing about NAOqi: it synthesizes a list of text / mark / pause items, streams PCM to
# the host audio output and returns the timings (specs/container/tts-engine.md).
FROM python:3.12-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# piper-tts is GPL-3.0-or-later (it embeds eSpeak NG): it lives in this container, built on the
# user's machine and never pushed (specs/_overview.md, "Licensing").
RUN pip install --no-cache-dir piper-tts==1.8.0 numpy

# The default languages' voices (server.py's DEFAULT_LANGUAGES, the config's default), so a default
# config speaks with no download at run time. Any other installed language's voice is downloaded
# on its first use into the volume at /voices. Every voice comes from the same piper-voices
# release (server.py's VOICES_TAG); each voice's licence is in tts-engine.md, "Voices".
ARG VOICES_TAG=v1.0.0
ARG VOICE_BASE=https://huggingface.co/rhasspy/piper-voices/resolve/$VOICES_TAG
WORKDIR /voices-builtin/$VOICES_TAG
RUN for v in en/en_US/ljspeech/medium/en_US-ljspeech-medium fr/fr_FR/siwis/medium/fr_FR-siwis-medium; do \
      n=$(basename $v); curl -sSL -o $n.onnx $VOICE_BASE/$v.onnx && curl -sSL -o $n.onnx.json $VOICE_BASE/$v.onnx.json; \
    done && ls -la

WORKDIR /app
COPY server.py /app/server.py
ENV NAOQI_SIM_SOUNDCARD=host.docker.internal:9562 \
    NAOQI_SIM_LANGUAGES=English,French
EXPOSE 8080
CMD ["python", "-u", "/app/server.py"]

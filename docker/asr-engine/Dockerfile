# naoqi-sim speech recognition engine container: Vosk with its small English and French models,
# native architecture (no emulation). Knows nothing about NAOqi: it listens to the audio posted to
# it for a list of phrases (specs/container/asr-engine.md).
FROM python:3.12-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl ca-certificates libatomic1 \
 && rm -rf /var/lib/apt/lists/*

# Apache-2.0 (specs/_overview.md, "Licensing").
RUN pip install --no-cache-dir vosk==0.3.45

# The two models (Apache-2.0), from the project's model site, hash-checked: never in the
# repository, fetched on the user's machine at the build.
ARG EN_MODEL=vosk-model-small-en-us-0.15
ARG EN_SHA256=30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498
ARG FR_MODEL=vosk-model-small-fr-0.22
ARG FR_SHA256=cabf6180e177eb9b3a9a9d43a437bd5e549f3a7d09525e5d69a3fed787be12ad
WORKDIR /models
RUN for pair in "$EN_MODEL:$EN_SHA256" "$FR_MODEL:$FR_SHA256"; do \
      model=${pair%%:*}; sum=${pair##*:}; \
      curl -sSfL -o $model.zip https://alphacephei.com/vosk/models/$model.zip \
      && echo "$sum  $model.zip" | sha256sum -c - \
      && python -m zipfile -e $model.zip . \
      && rm $model.zip || exit 1; \
    done

WORKDIR /app
COPY server.py /app/server.py
ENV NAOQI_SIM_ASR_MODELS=/models
EXPOSE 8080
CMD ["python", "-u", "/app/server.py"]

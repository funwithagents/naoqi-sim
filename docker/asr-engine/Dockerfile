# naoqi-sim speech recognition engine container: Vosk with one small model per language, native
# architecture (no emulation). Knows nothing about NAOqi: it listens to the audio posted to
# it for a list of phrases (specs/container/asr-engine.md).
FROM python:3.12-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl ca-certificates libatomic1 \
 && rm -rf /var/lib/apt/lists/*

# Apache-2.0 (specs/_overview.md, "Licensing").
RUN pip install --no-cache-dir vosk==0.3.45

# The default languages' models (server.py's DEFAULT_LANGUAGES, the config's default; Apache-2.0),
# from the project's model site, hash-checked (server.py's MODEL_SHA256), so a default config hears
# with no download at run time: never in the repository, fetched on the user's machine at the
# build. Any other installed language's model is downloaded on its first use into the language
# packs volume (asr-engine.md, "Models").
ARG EN_MODEL=vosk-model-small-en-us-0.15
ARG EN_SHA256=30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498
ARG FR_MODEL=vosk-model-small-fr-0.22
ARG FR_SHA256=cabf6180e177eb9b3a9a9d43a437bd5e549f3a7d09525e5d69a3fed787be12ad
WORKDIR /asr-models-builtin
RUN for pair in "$EN_MODEL:$EN_SHA256" "$FR_MODEL:$FR_SHA256"; do \
      model=${pair%%:*}; sum=${pair##*:}; \
      curl -sSfL -o $model.zip https://alphacephei.com/vosk/models/$model.zip \
      && echo "$sum  $model.zip" | sha256sum -c - \
      && python -m zipfile -e $model.zip . \
      && rm $model.zip || exit 1; \
    done

WORKDIR /app
COPY server.py /app/server.py
ENV NAOQI_SIM_BUILTIN_MODELS=/asr-models-builtin \
    NAOQI_SIM_ASR_MODELS=/language-packs/asr-models \
    NAOQI_SIM_LANGUAGES=English,French
EXPOSE 8080
CMD ["python", "-u", "/app/server.py"]

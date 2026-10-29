# naoqi-sim perception engine container: OpenCV's YuNet face detector, native architecture (no
# emulation). Knows nothing about NAOqi: it answers the faces of a frame posted to it
# (specs/container/perception-engine.md).
FROM python:3.12-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Both Apache-2.0 (specs/_overview.md, "Licensing").
RUN pip install --no-cache-dir opencv-python-headless==5.0.0.93 numpy==2.5.4

# The YuNet model (Apache-2.0) from opencv/opencv_zoo at a pinned commit (through github.com/raw,
# which resolves the repository's Git LFS pointer to the file), hash-checked: never in
# the repository, fetched on the user's machine at the build.
ARG ZOO_COMMIT=48b10fa505aeb51fbd127fc60a5c660040e823b7
ARG MODEL=face_detection_yunet_2023mar.onnx
ARG MODEL_SHA256=8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4
WORKDIR /models
RUN curl -sSL -o $MODEL https://github.com/opencv/opencv_zoo/raw/$ZOO_COMMIT/models/face_detection_yunet/$MODEL \
 && echo "$MODEL_SHA256  $MODEL" | sha256sum -c -

WORKDIR /app
COPY server.py /app/server.py
ENV NAOQI_SIM_YUNET_MODEL=/models/face_detection_yunet_2023mar.onnx
EXPOSE 8080
CMD ["python", "-u", "/app/server.py"]

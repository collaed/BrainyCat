FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    sox \
    libsox-fmt-all \
    espeak-ng \
    fonts-dejavu-core \
    wget \
    calibre \
    && rm -rf /var/lib/apt/lists/*

# Piper TTS voice model
RUN pip install --no-cache-dir piper-tts && \
    mkdir -p /opt/piper-voices && \
    wget -nv -O /opt/piper-voices/en_US-lessac-medium.onnx \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" && \
    wget -nv -O /opt/piper-voices/en_US-lessac-medium.onnx.json \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /data/books /data/incoming

ENV PIPER_VOICE=/opt/piper-voices/en_US-lessac-medium.onnx

EXPOSE 8000
CMD ["uvicorn", "brainycat.web:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Stage 1: compile the in-house Rust ebook converter ──────────────────────
# Requires Rust 1.85+ (Cargo edition 2024) — the Debian/apt rustc is too old, hence a dedicated
# builder stage rather than installing rustc in the final image.
FROM rust:1.90-bookworm AS rust-builder
WORKDIR /build
COPY ebook-convert-rs/ .
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/build/target \
    cargo build --release && cp target/release/ebook-convert /tmp/ebook-convert-rs

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    sox \
    libsox-fmt-all \
    espeak-ng \
    fonts-dejavu-core \
    wget \
    calibre \
    libzbar0 \
    tesseract-ocr \
    tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/*

# Piper TTS voice model
RUN pip install --no-cache-dir piper-tts && \
    mkdir -p /opt/piper-voices && \
    wget -nv -O /opt/piper-voices/en_US-lessac-medium.onnx \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" && \
    wget -nv -O /opt/piper-voices/en_US-lessac-medium.onnx.json \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"

COPY --from=rust-builder /tmp/ebook-convert-rs /usr/local/bin/ebook-convert-rs
RUN chmod +x /usr/local/bin/ebook-convert-rs

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /data/books /data/incoming

ENV PIPER_VOICE=/opt/piper-voices/en_US-lessac-medium.onnx

EXPOSE 8000
CMD ["uvicorn", "brainycat.web:app", "--host", "0.0.0.0", "--port", "8000"]

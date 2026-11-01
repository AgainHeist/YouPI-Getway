# BhashaFlix AI — single-service deployment (CPU).
# For studio-quality models switch the base image to a CUDA runtime and
# install requirements-ai.txt; see docs/DEPLOYMENT.md.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BFLIX_STORAGE_DIR=/data \
    PORT=8000

# ffmpeg provides both the encoder and ffprobe (better probing than the PyAV fallback)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts

RUN mkdir -p /data && useradd -m -u 10001 bflix && chown -R bflix:bflix /data /app
USER bflix

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]

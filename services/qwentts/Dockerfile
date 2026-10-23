FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1 HF_HOME=/models/.hf-cache \
    HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_XET=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg sox libsndfile1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir torch==2.9.1+cpu torchaudio==2.9.1+cpu --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt
RUN groupadd --gid 1000 tts && useradd --uid 1000 --gid 1000 --no-create-home tts \
    && mkdir -p /app/data /voices /models /run/local-ai && chown -R tts:tts /app/data /voices /models /run/local-ai
COPY --chown=tts:tts src ./src
COPY --chown=tts:tts web ./web
USER tts:tts
EXPOSE 8791
CMD ["python", "-m", "qwentts"]

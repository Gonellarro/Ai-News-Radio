FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 newsservice && useradd --uid 1000 --gid 1000 --no-create-home newsservice \
    && mkdir -p /app/data && chown newsservice:newsservice /app/data
RUN pip install --no-cache-dir Pillow==13.0.0
COPY --chown=newsservice:newsservice src ./src
COPY --chown=newsservice:newsservice web ./web
COPY --chown=newsservice:newsservice config ./config
USER newsservice:newsservice
EXPOSE 8792
CMD ["python", "-m", "news_orchestrator"]

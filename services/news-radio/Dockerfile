ARG PYTHON_IMAGE=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

FROM ${PYTHON_IMAGE} AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    NEWS_RADIO_DATA_DIR=/app/data
WORKDIR /app
RUN groupadd --gid 1000 newsradio \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin newsradio \
    && mkdir -p /app/data /app/logs \
    && chown -R newsradio:newsradio /app/data /app/logs

FROM base AS development
COPY --chown=newsradio:newsradio src ./src
COPY --chown=newsradio:newsradio web ./web
COPY --chown=newsradio:newsradio LICENSE ./LICENSE
USER newsradio:newsradio
CMD ["python", "-m", "news_radio"]

FROM base AS runtime
COPY --chown=newsradio:newsradio src ./src
COPY --chown=newsradio:newsradio web ./web
COPY --chown=newsradio:newsradio LICENSE ./LICENSE
USER newsradio:newsradio
EXPOSE 8790
CMD ["python", "-m", "news_radio"]

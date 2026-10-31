FROM python:3.15-slim AS wheels
WORKDIR /build
COPY requirements-services.txt .
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements-services.txt

FROM python:3.15-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN groupadd --system app && useradd --system --gid app --home-dir /app app
WORKDIR /app
COPY --from=wheels /wheels /wheels
COPY requirements-services.txt .
RUN python -m pip install --no-index --find-links=/wheels -r requirements-services.txt \
    && rm -rf /wheels
COPY offloader/ ./offloader/
COPY offloading.py ./offloading.py
COPY services/ ./services/
RUN mkdir -p /results && chown app:app /results
USER app:app
EXPOSE 8080
HEALTHCHECK --interval=20s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)" || exit 1
CMD ["python", "-m", "uvicorn", "services.edge_gateway:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]

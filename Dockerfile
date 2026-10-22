FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS dependencies
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/bid-review
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
RUN useradd --uid 10001 --create-home app && mkdir -p /data/blobs && chown app:app /data/blobs

FROM dependencies AS mineru-dependencies
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements-mineru.lock ./
RUN python -m venv /opt/mineru && /opt/mineru/bin/pip install --no-cache-dir -r requirements-mineru.lock && /opt/mineru/bin/pip check
RUN mkdir -p /data/mineru && chown app:app /data/mineru

FROM mineru-dependencies AS mineru-worker
RUN apt-get update && apt-get install -y --no-install-recommends fontconfig fonts-noto-cjk && fc-cache -f && rm -rf /var/lib/apt/lists/*
COPY --chown=app:app . .
USER app
ENV MINERU_HOME=/data/mineru MINERU_MODEL_SMALL_BACKEND=onnx MINERU_TABLE_DEVICE=cpu
CMD ["python", "-m", "celery", "-A", "app.worker:celery_app", "worker", "-Q", "parse", "--concurrency=1", "--loglevel=INFO"]

FROM dependencies AS converter
COPY scripts/pin_debian_snapshot.py /tmp/pin_debian_snapshot.py
RUN python /tmp/pin_debian_snapshot.py && apt-get -o Acquire::Check-Valid-Until=false update && apt-get install -y --no-install-recommends libreoffice-writer fonts-noto-cjk fonts-liberation fontconfig && fc-cache -f && rm -rf /var/lib/apt/lists/*
COPY --chown=app:app . .
RUN dpkg-query -W libreoffice-core libreoffice-writer fonts-noto-cjk fonts-liberation > config/conversion-runtime.txt
USER app
CMD ["python", "-m", "celery", "-A", "app.worker:celery_app", "worker", "-Q", "convert", "--concurrency=1", "--loglevel=INFO"]

FROM dependencies AS semantic
COPY requirements-semantic.lock ./
RUN pip install --no-cache-dir -r requirements-semantic.lock && pip check
RUN mkdir -p /data/semantic && chown app:app /data/semantic
COPY --chown=app:app . .
USER app
CMD ["python", "-m", "uvicorn", "app.semantic_runtime:app", "--host", "0.0.0.0", "--port", "8010"]

FROM dependencies AS app
COPY --chown=app:app . .
USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/bid-review
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
RUN useradd --uid 10001 --create-home app && mkdir -p /data/blobs && chown app:app /data/blobs
COPY --chown=app:app . .
USER app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

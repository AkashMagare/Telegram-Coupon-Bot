FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/coupons.db

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app app \
    && mkdir --parents /data \
    && chown --recursive app:app /data

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

USER app

CMD ["python", "main.py"]

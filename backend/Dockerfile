FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/base.txt requirements/base.txt
RUN pip install -r requirements/base.txt

COPY . .

RUN addgroup --system regx && adduser --system --ingroup regx regx
USER regx

EXPOSE 8000

CMD ["gunicorn", "regx.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30"]

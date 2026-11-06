# Pinned by digest (python:3.12-slim as of 2026-10-28, Python 3.12.16). The tag moves;
# bump the digest deliberately in its own PR, together with the lock scripts
# (scripts/lock_*_deps.sh), and run the full suites.
FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# base.txt is a lock file (scripts/lock_backend_deps.sh): every package, direct
# and indirect, at an exact version with sha256 hashes. --require-hashes makes
# pip refuse anything not in it; --no-deps stops it resolving anything extra.
COPY requirements/base.txt requirements/base.txt
RUN pip install --require-hashes --no-deps -r requirements/base.txt

COPY . .

RUN addgroup --system regx && adduser --system --ingroup regx regx
# document_storage is created and written to at runtime (local document
# storage backend) by the non-root user below; COPY above leaves /app
# root-owned, which otherwise makes every upload fail with a permission
# error the moment a real request tries to create it.
RUN mkdir -p document_storage && chown -R regx:regx document_storage
USER regx

EXPOSE 8000

CMD ["gunicorn", "regx.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30"]

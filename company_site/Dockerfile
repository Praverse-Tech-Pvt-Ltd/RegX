# Company website (booking-demo-final) carried into REGX verbatim.
#
# This Dockerfile is the only file authored inside company_site/ apart from
# RAAI/settings_integration.py and requirements.docker.txt — the application
# code, templates, static assets and database are exact copies of the source
# we were given.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=RAAI.settings_integration \
    # `adduser --system` gives the runtime user no home directory, so HOME
    # resolves to /nonexistent: gunicorn's control server fails to start and
    # matplotlib rebuilds its font cache in a fresh temp dir on every single
    # import, which the company's pandas/matplotlib views do constantly.
    HOME=/tmp \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

# pandas/matplotlib/pillow wheels need a toolchain on slim; libmagic-free.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# The company's own requirements.txt is UTF-16 encoded, which pip cannot
# parse. requirements.docker.txt is the identical package list re-encoded as
# UTF-8; the original file is left untouched.
COPY requirements.docker.txt ./
RUN pip install -r requirements.docker.txt

COPY . .

RUN addgroup --system company && adduser --system --ingroup company company
# The SQLite database is written to on login (session rows) and on demo
# bookings, so both the file and its directory must be writable by the
# runtime user — SQLite needs directory write access to create its -wal and
# -journal siblings. /app/data must exist in the image before the named
# volume is mounted over it, otherwise Docker creates it root-owned and
# every write fails.
RUN mkdir -p /app/data && chown -R company:company /app
RUN chmod +x /app/docker-entrypoint.sh
USER company

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]

# 3 workers with a longer timeout: the homepage and Audit IQ views build
# pandas dataframes over the FDA-483 dataset, which is well past gunicorn's
# 30s default on a cold cache.
CMD ["gunicorn", "RAAI.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "120"]

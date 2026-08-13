# Preserve the existing PostGIS 17 runtime and add only the official TimescaleDB extension.
FROM postgis/postgis:17-3.5

ARG TIMESCALEDB_PACKAGE=timescaledb-2-postgresql-17

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates gnupg wget \
    && wget -qO- https://packagecloud.io/timescale/timescaledb/gpgkey \
       | gpg --dearmor -o /usr/share/keyrings/timescaledb.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/timescaledb.gpg] https://packagecloud.io/timescale/timescaledb/debian/ bullseye main" \
       > /etc/apt/sources.list.d/timescaledb.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends "${TIMESCALEDB_PACKAGE}" \
    && rm -rf /var/lib/apt/lists/*

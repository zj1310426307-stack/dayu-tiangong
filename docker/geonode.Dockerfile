# Preserve the official GeoNode runtime while removing its three plaintext
# database diagnostics from the entrypoint log.
FROM geonode/geonode:5.1.0

RUN sed -i \
    -e 's/^echo POSTGRES_PASSWORD=.*/echo POSTGRES_PASSWORD=[redacted]/' \
    -e 's/^echo DATABASE_URL=.*/echo DATABASE_URL=[redacted]/' \
    -e 's/^echo GEODATABASE_URL=.*/echo GEODATABASE_URL=[redacted]/' \
    /usr/src/geonode/entrypoint.sh

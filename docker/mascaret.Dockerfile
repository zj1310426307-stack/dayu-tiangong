# syntax=docker/dockerfile:1.7
ARG DEBIAN_RELEASE=bookworm
FROM debian:${DEBIAN_RELEASE}-slim AS builder

ARG MASCARET_SOURCE_URL="https://gitlab.pam-retd.fr/api/v4/projects/otm%2Ftelemac-mascaret/repository/archive.tar.gz?sha=1fe3b5141f7d9c9fa8fe6d6d0316c994a39c2d95"
ARG MASCARET_SOURCE_SHA256="54b52798435baeb294ad3418c2fe146b5c10ef0d6e8e3e9d72d606e0f9fdb5e3"

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        ca-certificates cmake curl gcc gfortran make \
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail --location --retry 3 --output /tmp/mascaret-source.tar.gz "$MASCARET_SOURCE_URL" \
    && echo "$MASCARET_SOURCE_SHA256  /tmp/mascaret-source.tar.gz" | sha256sum --check --strict \
    && mkdir -p /src \
    && tar --extract --gzip --file /tmp/mascaret-source.tar.gz --directory /src --strip-components=1
RUN cmake -S /src -B /build \
        -DCMAKE_BUILD_TYPE=Release \
        -DUSE_MPI=OFF \
        -DUSE_MED=OFF \
        -DUSE_MUMPS=OFF \
        -DBUILD_TELAPY=OFF \
        -DBUILD_HERMES_WRAPPER=OFF \
    && cmake --build /build --target homere_mascaret --parallel 2

FROM debian:${DEBIAN_RELEASE}-slim AS runtime

ARG MASCARET_UPSTREAM_TAG="v9.1.1"
ARG MASCARET_UPSTREAM_COMMIT="1fe3b5141f7d9c9fa8fe6d6d0316c994a39c2d95"
ARG MASCARET_BUILD_TIMESTAMP

LABEL org.opencontainers.image.title="Dayu verified MASCARET runtime" \
      org.opencontainers.image.source="https://gitlab.pam-retd.fr/otm/telemac-mascaret" \
      org.opencontainers.image.version="$MASCARET_UPSTREAM_TAG" \
      org.opencontainers.image.revision="$MASCARET_UPSTREAM_COMMIT" \
      org.opencontainers.image.created="$MASCARET_BUILD_TIMESTAMP" \
      org.opencontainers.image.licenses="GPL-3.0-only"

RUN test -n "$MASCARET_BUILD_TIMESTAMP" \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends libgfortran5 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/mascaret/bin /opt/mascaret/lib /opt/mascaret/data /work
COPY --from=builder /build/bin/mascaret /opt/mascaret/bin/mascaret
COPY --from=builder /build/lib/libmascaret.so /opt/mascaret/lib/libmascaret.so
COPY --from=builder /src/sources/mascaret/data/ /opt/mascaret/data/
COPY --from=builder /src/LICENSE.txt /opt/mascaret/LICENSE.txt
COPY docker/mascaret-entrypoint.sh /usr/local/bin/mascaret-entrypoint

ENV LD_LIBRARY_PATH=/opt/mascaret/lib
WORKDIR /work
ENTRYPOINT ["/bin/sh", "/usr/local/bin/mascaret-entrypoint"]

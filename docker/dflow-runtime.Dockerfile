ARG RUNTIME_BASE_IMAGE=dayu-dflow-official@sha256:948707c51d2fac58cee2d4a607ca70d16a257e741ffa7c83dd52859549622463
FROM ${RUNTIME_BASE_IMAGE}

ARG PROVENANCE_SHA256

LABEL org.opencontainers.image.source="https://github.com/Deltares/Delft3D" \
      org.opencontainers.image.version="DIMRset_2026.02" \
      org.opencontainers.image.revision="5a4649830b1e5072caf019fb4850bbdefd9ad431" \
      io.dayu-tiangong.dflow.provenance-sha256="${PROVENANCE_SHA256}"

RUN groupadd --gid 65532 dayu-runtime \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /sbin/nologin dayu-runtime

ENV PATH="/delft3d/bin:${PATH}"
USER 65532:65532
WORKDIR /work

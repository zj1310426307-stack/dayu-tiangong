# syntax=docker/dockerfile:1.7
# Downstream equivalent of Deltares doc/delft3d.Dockerfile at
# DIMRset_2026.02. BUILD_INSTANCE only isolates /source/build between the
# independently audited A/B builds; no upstream source file is modified.
ARG INTEL_ONEAPI_VERSION=2024
ARG INTEL_FORTRAN_COMPILER=ifx
ARG BUILD_TYPE=Release
ARG CONFIGURATION=fm-suite
ARG THIRDPARTYLIBS_IMAGE_URL=dayu-dflow-third-party-libs
ARG BASE_IMAGE_URL=containers.deltares.nl/base_linux_containers/8-base:latest
ARG BASE_TAG=oneapi-${INTEL_ONEAPI_VERSION}-${INTEL_FORTRAN_COMPILER}-${BUILD_TYPE}

FROM ${THIRDPARTYLIBS_IMAGE_URL}:${BASE_TAG} AS build

ARG BUILD_TYPE
ARG CONFIGURATION
ARG BUILD_INSTANCE

WORKDIR /source
COPY . .

RUN --mount=type=cache,target=/source/build,id=dayu-dflow-${BUILD_INSTANCE},sharing=locked <<"EOF"
#!/usr/bin/env bash
source /etc/bashrc
set -eo pipefail
test -n "${BUILD_INSTANCE}"
export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
export CMAKE_PREFIX_PATH=/usr/local:$CMAKE_PREFIX_PATH
export CMAKE_INCLUDE_PATH=/usr/local/include:$CMAKE_INCLUDE_PATH
export CMAKE_LIBRARY_PATH=/usr/local/lib:$CMAKE_LIBRARY_PATH

# DIMRset_2026.02's official Dockerfile advertises CONFIGURATION=fm-suite,
# while build.sh at the same commit omits that otherwise valid case from its
# argument parser. Invoke the exact CMake entry point used by build.sh so the
# official fm-suite configuration is built without changing upstream source.
cmake ./src/cmake -G "Unix Makefiles" -B "${PWD}/build" \
    -D CONFIGURATION_TYPE="${CONFIGURATION}" \
    -D CMAKE_BUILD_TYPE="${BUILD_TYPE}" \
    -D CMAKE_INSTALL_PREFIX=/delft3d
cmake --build "${PWD}/build" --parallel --target install
EOF

FROM ${BASE_IMAGE_URL}
COPY --from=build /delft3d/ /delft3d/

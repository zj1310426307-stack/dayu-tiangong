FROM docker.osgeo.org/geoserver:2.28.0

USER root

# GeoServer renders labels server-side.  Install an explicit Simplified Chinese
# font so WMS/WMTS output never depends on an accidental fallback font.
RUN chmod 1777 /tmp \
    && apt-get update \
    && apt-get install -y --no-install-recommends fontconfig fonts-noto-cjk \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

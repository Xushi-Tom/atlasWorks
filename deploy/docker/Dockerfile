ARG BASE_IMAGE=debian:bullseye
FROM ${BASE_IMAGE}

LABEL maintainer="AtlasWorks Team"
LABEL description="AtlasWorks geographic tiling platform with GDAL, CTB and embedded console"

ARG APT_MIRROR=http://deb.debian.org/debian
ARG APT_SECURITY_MIRROR=http://deb.debian.org/debian-security
ARG NODE_MAJOR=20

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    PYTHONPATH=/app/services/common:/app/services/control:/app/services/publisher:/app/services/tiling/vector:/app/services/tiling/raster:/app/services/tiling/terrain:/app/services/tiling/tiles3d \
    LD_LIBRARY_PATH=/usr/local/lib \
    TZ=Asia/Shanghai

WORKDIR /tmp/build

RUN printf "deb %s bullseye main contrib non-free\n" "${APT_MIRROR}" > /etc/apt/sources.list \
    && printf "deb %s bullseye-updates main contrib non-free\n" "${APT_MIRROR}" >> /etc/apt/sources.list \
    && printf "deb %s bullseye-security main contrib non-free\n" "${APT_SECURITY_MIRROR}" >> /etc/apt/sources.list \
    && apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --fix-missing --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    curl \
    dnsutils \
    gdal-bin \
    git \
    gnupg \
    gunicorn \
    iproute2 \
    iputils-ping \
    jq \
    less \
    libgdal-dev \
    libgl1 \
    libglu1-mesa \
    libsqlite3-dev \
    lsof \
    nano \
    net-tools \
    netcat-openbsd \
    zlib1g-dev \
    openscenegraph \
    p7zip-full \
    procps \
    python3 \
    python3-dev \
    python3-gdal \
    python3-numpy \
    python3-pil \
    python3-pip \
    python3-setuptools \
    telnet \
    tzdata \
    unzip \
    vim \
    wget \
    && apt-get -f install -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime \
    && echo "${TZ}" > /etc/timezone

RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --no-install-recommends nodejs \
    && node --version \
    && npm --version \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --upgrade pip setuptools wheel \
    && python3 -m pip install \
    flask==2.2.5 \
    flask-cors==4.0.0 \
    laspy \
    lxml \
    pillow \
    py3dtiles \
    pygltflib \
    psutil==5.9.0 \
    psycopg2-binary==2.9.9 \
    requests==2.28.0 \
    trimesh \
    lazrs

RUN npm install -g obj2gltf@3.2.0

COPY cesium-terrain-builder /tmp/build/cesium-terrain-builder

RUN cmake -S /tmp/build/cesium-terrain-builder -B /tmp/build/cesium-terrain-builder/build \
    && cmake --build /tmp/build/cesium-terrain-builder/build --parallel \
    && cmake --install /tmp/build/cesium-terrain-builder/build \
    && echo "/usr/local/lib" > /etc/ld.so.conf.d/atlasworks.conf \
    && ldconfig

RUN git clone --depth 1 https://github.com/felt/tippecanoe.git /tmp/build/tippecanoe \
    && cd /tmp/build/tippecanoe \
    && make -j$(nproc) \
    && make install \
    && rm -rf /tmp/build/tippecanoe

RUN wget -O /usr/local/bin/gdal2tiles.py https://raw.githubusercontent.com/OSGeo/gdal/v2.4.0/gdal/swig/python/scripts/gdal2tiles.py \
    && chmod +x /usr/local/bin/gdal2tiles.py \
    && ln -sf /usr/local/bin/gdal2tiles.py /usr/bin/gdal2tiles.py

WORKDIR /app

RUN mkdir -p /app/dataSource /app/tiles /app/log /app/logs \
    && chmod -R 777 /app

COPY services/ /app/services/
COPY frontend/dist/ /app/frontend/
COPY deploy/docker/entrypoint.sh /entrypoint.sh

RUN sed -i 's/\r$//' /entrypoint.sh \
    && chmod +x /entrypoint.sh \
    && python3 -m compileall -q /app/services \
    && python3 -c "import flask, flask_cors, psutil, psycopg2, requests, lxml, laspy, trimesh; from osgeo import ogr; print('python-imports:ok')" \
    && ctb-tile --version >/tmp/ctb-version.txt \
    && gdalinfo --version >/tmp/gdal-version.txt \
    && command -v obj2gltf >/tmp/obj2gltf-path.txt \
    && command -v osgconv >/tmp/osgconv-path.txt

EXPOSE 18000

ENTRYPOINT ["/entrypoint.sh"]
CMD []

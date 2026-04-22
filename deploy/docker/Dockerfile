FROM debian:bullseye

LABEL maintainer="AtlasWorks Team"
LABEL description="AtlasWorks geographic tiling platform with GDAL, CTB and embedded console"

ARG APT_MIRROR=http://deb.debian.org/debian
ARG APT_SECURITY_MIRROR=http://security.debian.org/debian-security
ARG NODE_MAJOR=20

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
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
    gdal-bin \
    git \
    gnupg \
    gunicorn \
    libgdal-dev \
    libgl1 \
    libglu1-mesa \
    openscenegraph \
    p7zip-full \
    python3 \
    python3-dev \
    python3-gdal \
    python3-numpy \
    python3-pil \
    python3-pip \
    python3-setuptools \
    tzdata \
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

RUN wget -O /usr/local/bin/gdal2tiles.py https://raw.githubusercontent.com/OSGeo/gdal/v2.4.0/gdal/swig/python/scripts/gdal2tiles.py \
    && chmod +x /usr/local/bin/gdal2tiles.py \
    && ln -sf /usr/local/bin/gdal2tiles.py /usr/bin/gdal2tiles.py

WORKDIR /app

RUN mkdir -p /app/dataSource /app/tiles /app/log /app/logs \
    && chmod -R 777 /app

COPY backend/ /app/
COPY frontend/dist/ /app/static/
COPY deploy/docker/entrypoint.sh /entrypoint.sh

RUN sed -i 's/\r$//' /entrypoint.sh \
    && chmod +x /app/app.py /entrypoint.sh \
    && python3 -m py_compile /app/*.py \
    && python3 -c "import flask, flask_cors, psutil, psycopg2, requests, lxml, laspy, trimesh; from osgeo import ogr; print('python-imports:ok')" \
    && ctb-tile --version >/tmp/ctb-version.txt \
    && gdalinfo --version >/tmp/gdal-version.txt \
    && command -v obj2gltf >/tmp/obj2gltf-path.txt \
    && command -v osgconv >/tmp/osgconv-path.txt

EXPOSE 18000

ENTRYPOINT ["/entrypoint.sh"]
CMD []

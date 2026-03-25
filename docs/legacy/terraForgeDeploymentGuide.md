# TerraForge 完整部署文档

## 📋 概述

TerraForge是一个完整的地理信息处理平台，集成了Java后端服务和Python切片引擎，支持高精度地形切片、地图瓦片生成、量化网格算法等先进技术。

### 🏗️ 系统架构
- **Java后端**: Spring Boot + MyBatis Plus，提供Web API和业务逻辑
- **Python引擎**: Flask微服务，专门处理地理数据切片
- **地理引擎**: GDAL、CTB、GeoTools等专业地理信息处理库
- **数据库**: MySQL（可选），用于工作空间和任务管理
- **存储**: 文件系统存储，支持大容量数据处理

### 🎯 核心能力
- **量化网格地形**: 基于半边数据结构的高精度三维地形网格
- **精准地图切片**: 解决瓦片缝隙问题的Java原生算法
- **批量并行处理**: 支持多文件、多进程并行处理
- **智能参数推荐**: 根据数据特征自动推荐最佳处理参数
- **实时进度监控**: 完整的任务生命周期管理

## 📦 镜像信息

### Java后端镜像
- **镜像名称**: `terraforge-server:latest`
- **基础镜像**: openjdk:8-jdk-alpine
- **文件大小**: ~200MB
- **端口**: 8080
- **包含组件**: Spring Boot应用、GeoTools、量化网格算法

### Python切片引擎镜像
- **镜像名称**: `terra-forge:release-1.0`
- **基础镜像**: debian:bullseye
- **文件大小**: 841MB
- **端口**: 8000
- **包含工具**: CTB, GDAL, Flask, PIL等地理信息处理工具

### 集成部署镜像
- **镜像名称**: `terraforge-complete:latest`
- **文件大小**: ~1GB
- **端口**: 8080 (Java), 8000 (Python)
- **包含组件**: 完整的TerraForge服务栈

## 🚀 快速部署

### 部署方式选择

TerraForge支持三种部署方式：

1. **Java后端独立部署** - 适用于已有Python环境的场景
2. **Python引擎独立部署** - 适用于只需要切片功能的场景  
3. **完整集成部署** - 推荐方式，包含所有功能

### 方式一：Java后端独立部署

#### 1.1 构建Java应用

```bash
# 克隆代码
git clone <repository-url>
cd terraforge-server

# Maven打包
mvn clean package -Dmaven.test.skip=true

# 构建Docker镜像
docker build -t terraforge-server:latest .
```

#### 1.2 启动Java服务

```bash
# 基础启动
docker run -d --name terraforge-java \
  -p 8080:8080 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/tiles:/app/tiles \
  -e SPRING_PROFILES_ACTIVE=prod \
  terraforge-server:latest

# 生产环境启动（推荐）
docker run -d --name terraforge-java \
  --restart=unless-stopped \
  --memory=8g \
  --cpus=4 \
  -p 8080:8080 \
  -v $(pwd)/data:/app/dataSource \
  -v $(pwd)/tiles:/app/tiles \
  -v $(pwd)/logs:/app/logs \
  -e SPRING_PROFILES_ACTIVE=prod \
  -e JAVA_OPTS="-Xmx6g -Xms2g -XX:+UseG1GC" \
  terraforge-server:latest
```

### 方式二：Python引擎独立部署

#### 2.1 加载Python镜像

```bash
# 从tar文件加载镜像
docker load -i terraforge-image.tar

# 验证镜像加载成功
docker images | grep terra-forge
```

#### 2.2 启动Python服务

```bash
# 基础启动
docker run -d --name terraforge-python \
  -p 8000:8000 \
  -v $(pwd)/data/dataSource:/app/dataSource \
  -v $(pwd)/data/tiles:/app/tiles \
  terra-forge:release-1.0 python3 /app/app.py

# 生产环境启动（推荐）
docker run -d --name terraforge-python \
  --restart=unless-stopped \
  --memory=16g \
  --shm-size=4g \
  --cpus=8 \
  -p 8000:8000 \
  -v $(pwd)/data/dataSource:/app/dataSource \
  -v $(pwd)/data/tiles:/app/tiles \
  -v $(pwd)/logs:/app/logs \
  -e GDAL_CACHEMAX=4096 \
  -e GDAL_NUM_THREADS=8 \
  terra-forge:release-1.0 python3 /app/app.py
```

### 方式三：完整集成部署（推荐）

#### 3.1 使用Docker Compose

创建 `dockerCompose.yml` 文件：

```yaml
version: '3.8'

services:
  # Java后端服务
  terraforge-java:
    image: terraforge-server:latest
    container_name: terraforge-java
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/app/dataSource
      - ./tiles:/app/tiles
      - ./logs:/app/logs
    environment:
      - SPRING_PROFILES_ACTIVE=prod
      - JAVA_OPTS=-Xmx6g -Xms2g -XX:+UseG1GC
      - TERRAFORGE_PYTHON_URL=http://terraforge-python:8000
    depends_on:
      - terraforge-python
    deploy:
      resources:
        limits:
          memory: 8G
          cpus: '4'
    networks:
      - terraforge-network

  # Python切片引擎
  terraforge-python:
    image: terra-forge:release-1.0
    container_name: terraforge-python
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data/dataSource:/app/dataSource
      - ./data/tiles:/app/tiles
      - ./logs:/app/logs
    environment:
      - GDAL_CACHEMAX=4096
      - GDAL_NUM_THREADS=8
      - PYTHONUNBUFFERED=1
    command: python3 /app/app.py
    deploy:
      resources:
        limits:
          memory: 16G
          cpus: '8'
    networks:
      - terraforge-network

  # 数据库（可选）
  mysql:
    image: mysql:8.0
    container_name: terraforge-mysql
    restart: unless-stopped
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
      - ./sql:/docker-entrypoint-initdb.d
    environment:
      - MYSQL_ROOT_PASSWORD=terraforge2024
      - MYSQL_DATABASE=terraforge
      - MYSQL_USER=terraforge
      - MYSQL_PASSWORD=terraforge123
    deploy:
      resources:
        limits:
          memory: 2G
    networks:
      - terraforge-network

  # Nginx代理（可选）
  nginx:
    image: nginx:alpine
    container_name: terraforge-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./nginx/ssl:/etc/nginx/ssl
      - ./tiles:/usr/share/nginx/html/tiles
    depends_on:
      - terraforge-java
      - terraforge-python
    networks:
      - terraforge-network

volumes:
  mysql_data:
    driver: local

networks:
  terraforge-network:
    driver: bridge
```

#### 3.2 启动完整服务

```bash
# 启动所有服务
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

## 📁 目录结构和配置

### 目录挂载说明

| 本地目录 | 容器目录 | 说明 | 推荐大小 |
|---------|---------|-----|----------|
| `./data/dataSource` | `/app/dataSource` | 输入数据目录（TIF等源文件） | 根据数据量 |
| `./tiles` | `/app/tiles` | 输出瓦片目录 | 源文件大小的3-10倍 |
| `./logs` | `/app/logs` | 日志文件目录 | 1-5GB |
| `./config` | `/app/config` | 配置文件目录（可选） | 10MB |
| `./cache` | `/app/cache` | 缓存目录（可选） | 1-10GB |
| `./sql` | `/docker-entrypoint-initdb.d` | 数据库初始化脚本 | 1MB |

### 创建目录结构

```bash
# 创建完整目录结构
mkdir -p {data/dataSource,tiles,logs,config,cache,sql,nginx}

# 设置目录权限
chmod -R 755 data tiles logs config cache
chmod 644 sql/*.sql

# 创建配置文件
touch config/application.yml
touch nginx/nginx.conf
```

### 环境变量配置

#### Java后端环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `SPRING_PROFILES_ACTIVE` | dev | 运行环境：dev、test、prod |
| `TILES_BASE_DIR` | /app/tiles | 瓦片输出目录 |
| `DATA_SOURCE_DIR` | /app/dataSource | 数据源目录 |
| `JAVA_OPTS` | -Xmx4g -Xms1g | JVM参数 |
| `MYSQL_URL` | jdbc:mysql://localhost:3306/terraforge | 数据库连接 |
| `MYSQL_USERNAME` | terraforge | 数据库用户名 |
| `MYSQL_PASSWORD` | terraforge123 | 数据库密码 |
| `TERRAFORGE_PYTHON_URL` | http://localhost:8000 | Python服务URL |

#### Python引擎环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `GDAL_CACHEMAX` | 2048 | GDAL缓存大小（MB） |
| `GDAL_NUM_THREADS` | 4 | GDAL线程数 |
| `GDAL_HTTP_TIMEOUT` | 60 | HTTP超时时间（秒） |
| `GDAL_DISABLE_READDIR_ON_OPEN` | EMPTY_DIR | 禁用目录读取优化 |
| `OMP_NUM_THREADS` | 4 | OpenMP线程数 |
| `PYTHONUNBUFFERED` | 1 | Python输出不缓冲 |
| `FLASK_ENV` | production | Flask运行环境 |
| `TILE_CACHE_SIZE` | 1000 | 瓦片缓存数量 |

### 3. 启动容器

```bash
# 基础启动（推荐）
docker run -d \
  --name terraforge \
  -v $(pwd)/data/dataSource:/app/dataSource \
  -v $(pwd)/data/tiles:/app/tiles \
  terraforge:latest tail -f /dev/null
```

## ⚙️ 高级配置

### 内存和CPU限制

```bash
# 设置内存限制（8GB）和CPU限制（4核）
docker run -d \
  --name terraforge \
  --memory=8g \
  --memory-swap=8g \
  --cpus=4 \
  -v $(pwd)/data/dataSource:/app/dataSource \
  -v $(pwd)/data/tiles:/app/tiles \
  terraforge:latest tail -f /dev/null
```

### 完整配置启动

```bash
# 生产环境推荐配置
docker run -d \
  --name terraforge \
  --restart=unless-stopped \
  --memory=8g \
  --memory-swap=12g \
  --cpus=4 \
  --shm-size=2g \
  -v $(pwd)/data/dataSource:/app/dataSource \
  -v $(pwd)/data/tiles:/app/tiles \
  -v $(pwd)/logs:/app/logs \
  -e GDAL_CACHEMAX=2048 \
  -e GDAL_SWATH_SIZE=1000000 \
  -e GDAL_MAX_DATASET_POOL_SIZE=1000 \
  terraforge:latest tail -f /dev/null
```

## 📁 目录挂载说明

| 本地目录 | 容器目录 | 说明 |
|---------|---------|-----|
| `./data/dataSource` | `/app/dataSource` | 输入文件目录（tif文件等） |
| `./data/tiles` | `/app/tiles` | 输出瓦片目录 |
| `./logs` | `/app/logs` | 日志文件目录（可选） |

## 🛠️ 使用方法

### 进入容器

```bash
# 进入容器交互式命令行
docker exec -it terraforge bash

# 在容器外执行单个命令
docker exec terraforge [命令]
```

### CTB地形切片

```bash
# 基础地形切片
docker exec terraforge ctb-tile \
  -f Mesh \
  -C \
  -o /app/tiles/terrain_output \
  -s 10 -e 0 \
  -m 6291456 \
  /app/dataSource/input.tif

# 检查输出文件
docker exec terraforge ls -la /app/tiles/terrain_output/
```

### GDAL2Tiles地图切片

```bash
# 基础地图切片
docker exec terraforge gdal2tiles.py \
  /app/dataSource/input.tif \
  /app/tiles/map_output/

# 高性能切片（多进程）
docker exec terraforge gdal2tiles.py \
  --processes=4 \
  --resampling=near \
  -z 0-18 \
  /app/dataSource/input.tif \
  /app/tiles/map_output/
```

### 智能分级切片

```bash
# 复制智能切片脚本到容器
docker cp auto_zoom_tiles.sh terraforge:/app/

# 执行智能切片
docker exec terraforge bash -c \
  'cd /app && ./auto_zoom_tiles.sh dataSource/input.tif tiles/smart_output'
```

## 📊 性能调优指南

### 硬件资源配置建议

#### 处理不同规模数据的硬件配置

| 数据规模 | 文件大小 | CPU | 内存 | 存储 | 预估处理时间 |
|----------|----------|-----|------|------|-------------|
| 小规模 | <1GB | 4核 | 8GB | 100GB | 5-15分钟 |
| 中等规模 | 1-10GB | 8核 | 16GB | 500GB | 15分钟-2小时 |
| 大规模 | 10-50GB | 16核 | 32GB | 2TB | 2-8小时 |
| 超大规模 | >50GB | 32核 | 64GB | 5TB | 8-24小时 |

### Java后端性能调优

#### JVM参数优化

```bash
# 小规模数据处理
JAVA_OPTS="-Xmx4g -Xms1g -XX:+UseG1GC -XX:MaxGCPauseMillis=200"

# 中等规模数据处理  
JAVA_OPTS="-Xmx8g -Xms2g -XX:+UseG1GC -XX:MaxGCPauseMillis=200 -XX:+UseCompressedOops"

# 大规模数据处理
JAVA_OPTS="-Xmx16g -Xms4g -XX:+UseG1GC -XX:MaxGCPauseMillis=200 -XX:+UseCompressedOops -XX:+UseLargePages"

# 超大规模数据处理
JAVA_OPTS="-Xmx32g -Xms8g -XX:+UseG1GC -XX:MaxGCPauseMillis=200 -XX:+UseCompressedOops -XX:+UseLargePages -XX:G1HeapRegionSize=32m"
```

#### 量化网格算法优化参数

| 参数名 | 范围 | 建议值 | 影响 |
|--------|------|--------|------|
| `intensity` | 1.0-16.0 | 4.0-8.0 | 网格密度，影响精度和文件大小 |
| `maxTriangles` | 1000-10000000 | 6291456 | 最大三角形数，限制内存使用 |
| `rasterMaxSize` | 1024-65536 | 16384 | 最大栅格尺寸，影响内存占用 |
| `mosaicSize` | 8-128 | 16-64 | 拼接缓冲区，影响边界处理精度 |

### Python引擎性能调优

#### GDAL参数优化

```bash
# 基础优化（适用于大部分场景）
GDAL_CACHEMAX=2048                      # 缓存大小2GB
GDAL_NUM_THREADS=ALL_CPUS               # 使用所有CPU核心
GDAL_HTTP_TIMEOUT=120                   # 超时时间2分钟

# 大文件处理优化
GDAL_CACHEMAX=8192                      # 缓存大小8GB
GDAL_SWATH_SIZE=5000000                 # 增大扫描行缓冲
GDAL_MAX_DATASET_POOL_SIZE=2000         # 增大数据集池
GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR  # 禁用目录扫描

# 超大文件处理优化
GDAL_CACHEMAX=16384                     # 缓存大小16GB
GDAL_FORCE_CACHING=YES                  # 强制缓存
GDAL_MAX_BAND_COUNT=10000              # 增大波段限制
```

#### CTB（Cesium Terrain Builder）参数优化

| 参数 | 小文件 | 中等文件 | 大文件 | 超大文件 |
|------|--------|----------|--------|----------|
| `-c` (threads) | 4 | 8 | 16 | 32 |
| `-m` (memory) | 2g | 8g | 16g | 32g |
| `-s/-e` (levels) | 0-12 | 0-14 | 0-16 | 0-18 |
| `maxTriangles` | 1048576 | 4194304 | 8388608 | 16777216 |

#### 地图切片并行处理优化

```bash
# GDAL2Tiles并行参数调优
--processes=8                   # 进程数=CPU核心数
--resampling=near              # 最快的重采样方法
--profile=mercator             # 使用Web墨卡托投影
--tilesize=256                 # 标准瓦片大小
--verbose                      # 显示详细进度
--resume                       # 支持断点续传

# 针对不同数据类型的重采样方法选择
# 遥感影像: bilinear 或 cubic
# 电子地图: near
# DEM数据: cubic 或 cubicspline
```

### 内存和存储优化

#### 容器资源配置

```bash
# 小规模处理容器配置
docker run --memory=8g --cpus=4 --shm-size=2g

# 中等规模处理容器配置
docker run --memory=16g --cpus=8 --shm-size=4g

# 大规模处理容器配置  
docker run --memory=32g --cpus=16 --shm-size=8g

# 超大规模处理容器配置
docker run --memory=64g --cpus=32 --shm-size=16g
```

#### 存储优化策略

1. **SSD存储**: 使用SSD存储瓦片输出目录，提升I/O性能
2. **分离存储**: 将输入数据和输出瓦片放在不同磁盘
3. **临时目录**: 设置独立的临时处理目录
4. **网络存储**: 大规模部署可考虑使用NFS或分布式存储

```bash
# 存储挂载优化示例
-v /fast-ssd/tiles:/app/tiles              # 瓦片输出到SSD
-v /storage/data:/app/dataSource           # 源数据在大容量存储
-v /tmp/terraforge:/tmp                    # 独立临时目录
```

### 网络和并发优化

#### Nginx反向代理配置

```nginx
upstream terraforge_java {
    server terraforge-java:8080 max_fails=3 fail_timeout=30s;
}

upstream terraforge_python {
    server terraforge-python:8000 max_fails=3 fail_timeout=30s;
}

server {
    listen 80;
    
    # 静态瓦片服务优化
    location /tiles/ {
        alias /usr/share/nginx/html/tiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
        gzip_static on;
    }
    
    # Java API代理
    location /api/ {
        proxy_pass http://terraforge_java;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_timeout 300s;
        proxy_buffering off;
    }
    
    # Python切片引擎代理
    location /tile/ {
        proxy_pass http://terraforge_python;
        proxy_set_header Host $host;
        proxy_timeout 1800s;  # 30分钟超时
        proxy_buffering off;
    }
}
```

### 监控和调试

#### 性能监控命令

```bash
# 查看容器资源使用
docker stats

# 查看详细系统资源
htop
iostat -x 1
free -h

# 查看GDAL处理进度
docker logs -f terraforge-python | grep "progress"

# 查看Java应用JVM状态
docker exec terraforge-java jstat -gc 1 5s
```

#### 调试和排错

```bash
# 开启详细日志
-e GDAL_DEBUG=ON
-e CPL_DEBUG=ON
-e SPRING_LOGGING_LEVEL=DEBUG

# 查看处理统计
docker exec terraforge-python gdalinfo --stats /app/dataSource/input.tif

# 检查瓦片完整性
find /tiles -name "*.png" -size 0 -delete
find /tiles -name "*.terrain" -size 0 -delete
```

### 最佳实践建议

1. **预处理优化**: 使用 `gdaladdo` 为大文件创建金字塔概览
2. **分块处理**: 超大文件先用 `gdal_translate` 分块处理
3. **格式转换**: 将源文件转换为优化的GeoTIFF格式
4. **缓存预热**: 首次处理前预热缓存和索引
5. **批量处理**: 相似参数的文件批量处理，减少启动开销

## 📝 常用操作

### 容器管理

```bash
# 启动容器
docker start terraforge

# 停止容器
docker stop terraforge

# 重启容器
docker restart terraforge

# 删除容器
docker rm terraforge

# 查看容器状态
docker ps | grep terraforge

# 查看容器资源使用
docker stats terraforge
```

### 文件操作

```bash
# 复制文件到容器
docker cp local_file.tif terraforge:/app/dataSource/

# 从容器复制文件
docker cp terraforge:/app/tiles/output ./output

# 查看容器内文件
docker exec terraforge ls -la /app/dataSource/
docker exec terraforge ls -la /app/tiles/
```

### 日志查看

```bash
# 查看容器日志
docker logs terraforge

# 实时查看日志
docker logs -f terraforge

# 查看最近100行日志
docker logs --tail 100 terraforge
```

## 🔧 故障排查

### 常见问题

1. **内存不足**
   ```bash
   # 检查容器内存使用
   docker stats terraforge
   
   # 增加内存限制
   docker update --memory=8g terraforge
   ```

2. **磁盘空间不足**
   ```bash
   # 检查磁盘使用
   df -h
   docker exec terraforge df -h
   
   # 清理Docker缓存
   docker system prune -f
   ```

3. **权限问题**
   ```bash
   # 检查目录权限
   ls -la data/
   
   # 修复权限
   sudo chown -R $(whoami) data/
   chmod -R 755 data/
   ```

4. **容器无法启动**
   ```bash
   # 查看详细错误信息
   docker logs terraforge
   
   # 重新加载镜像
   docker load -i terraforge-image.tar
   ```

### 性能监控

```bash
# 查看系统资源
htop

# 查看Docker资源使用
docker stats

# 查看磁盘IO
iostat -x 1

# 查看网络状态
netstat -i
```

## 📚 切片参数说明

### CTB参数

| 参数 | 说明 | 推荐值 |
|-----|------|--------|
| `-f Mesh` | 输出格式 | 固定值 |
| `-C` | 启用压缩 | 推荐 |
| `-s` | 起始层级 | 0-12 |
| `-e` | 结束层级 | 0-18 |
| `-m` | 最大三角形数 | 6291456 |

### GDAL2Tiles参数

| 参数 | 说明 | 推荐值 |
|-----|------|--------|
| `--processes` | 并行进程数 | CPU核数 |
| `--resampling` | 重采样方法 | near/bilinear |
| `-z` | 缩放级别 | 0-18 |
| `--resume` | 恢复中断的切片 | 可选 |

## 🌐 Web服务部署

如需要Web服务访问切片，可以使用nginx：

```bash
# 启动nginx容器提供切片服务
docker run -d \
  --name terraforge-web \
  -p 8080:80 \
  -v $(pwd)/data/tiles:/usr/share/nginx/html \
  nginx:alpine

# 访问地址：http://localhost:8080
```

## 📞 技术支持

- 遇到问题请检查Docker日志
- 确保系统有足够的内存和磁盘空间
- 大文件处理建议分批进行
- 关键配置请做好备份

## 🔧 技术架构详解

### 量化网格算法（Java后端核心技术）

TerraForge的Java后端集成了先进的量化网格算法，这是处理大规模地形数据的核心技术：

#### 核心特性
1. **半边数据结构**: 高效存储和处理三角网拓扑关系
2. **自适应细分**: 根据地形复杂度动态调整网格密度
3. **重心坐标插值**: 保证高精度的高程插值
4. **边界约束**: 确保相邻瓦片完美拼接

#### 算法流程
1. **数据预处理**: 标准化坐标系和数据格式
2. **网格初始化**: 创建基础三角网格
3. **自适应细分**: 基于地形复杂度细分三角形
4. **顶点优化**: 优化顶点位置和连接关系
5. **量化编码**: 将坐标和高程量化为16位整数
6. **边界处理**: 处理瓦片边界确保连续性

### 防缝隙算法（地图切片核心技术）

Java后端的地图切片采用精确的防缝隙算法：

#### 技术原理
1. **精确像素计算**: 基于Web墨卡托投影的精确坐标转换
2. **边界扩展策略**: 在瓦片边界扩展采样区域
3. **双线性插值**: 高质量的像素插值算法
4. **抗锯齿处理**: 多级采样消除锯齿效应

### Python引擎技术栈

1. **GDAL库集成**: 支持200+地理数据格式
2. **Flask微服务**: 轻量级Web框架，支持异步处理
3. **CTB集成**: Cesium Terrain Builder，专业地形瓦片生成
4. **PIL图像处理**: 高性能图像处理和分析
5. **多进程架构**: 充分利用多核CPU资源

## 📞 技术支持和维护

### 常见问题解决

1. **内存不足**: 减少并行进程数，增加交换空间
2. **磁盘空间不足**: 清理临时文件，使用符号链接
3. **处理速度慢**: 调整GDAL参数，使用SSD存储
4. **瓦片质量问题**: 调整重采样方法和缓冲区参数
5. **服务无响应**: 检查容器状态和资源限制

### 版本兼容性

| 组件 | 版本 | 兼容性说明 |
|------|------|-----------|
| Java后端 | 8+ | 支持OpenJDK 8、11、17 |
| Python引擎 | 3.8+ | 推荐Python 3.9 |
| GDAL | 3.0+ | 支持GDAL 3.x版本 |
| Docker | 20.0+ | 支持Docker Compose v2 |
| 数据库 | MySQL 8.0+ | 可选组件 |

### 升级指南

#### Java后端升级
```bash
# 备份当前版本
docker save terraforge-server:latest > backup.tar

# 拉取新版本
docker pull terraforge-server:v2.0

# 升级数据库（如有需要）
docker exec terraforge-mysql mysql -u root -p < upgrade.sql

# 重启服务
docker-compose restart terraforge-java
```

#### Python引擎升级
```bash
# 备份数据
cp -r ./tiles ./tiles.backup

# 加载新镜像
docker load -i terra-forge-v2.0.tar

# 更新配置
docker-compose up -d terraforge-python
```

### 监控和维护

#### 日志管理
```bash
# 日志轮转配置
echo '{
  "/app/logs/*.log": {
    "rotate": 7,
    "daily": true,
    "compress": true,
    "maxsize": "100M"
  }
}' > /etc/logrot.d/terraforge

# 查看关键日志
docker logs --tail 100 terraforge-java
docker logs --tail 100 terraforge-python
```

#### 健康检查
```bash
# Java后端健康检查
curl http://localhost:8080/api/health

# Python引擎健康检查  
curl http://localhost:8000/api/health

# 系统资源检查
docker stats --no-stream
```

#### 数据备份策略
```bash
# 配置文件备份
tar -czf config-backup-$(date +%Y%m%d).tar.gz ./config

# 重要瓦片数据备份
rsync -av --progress ./tiles/ /backup/tiles/

# 数据库备份（如使用）
docker exec terraforge-mysql mysqldump -u root -p terraforge > backup.sql
```

### 开发和扩展

#### 自定义开发
- **Java扩展**: 基于Spring Boot框架添加新的API接口
- **Python插件**: 开发自定义的切片算法和处理流程
- **Web界面**: 基于Vue.js或React开发管理界面
- **移动端**: 开发Android/iOS客户端应用

#### API集成示例
```javascript
// JavaScript集成示例
const TerraForgeClient = {
  async createTerrainTiles(params) {
    const response = await fetch('http://localhost:8080/terrain/cut/tile/terrain', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    });
    return response.json();
  },
  
  async getTaskStatus(taskId) {
    const response = await fetch(`http://localhost:8000/api/tasks/${taskId}`);
    return response.json();
  }
};
```

---

**TerraForge完整部署文档**  
**版本**: v2.8  
**最后更新**: 2025年7月26日  
**维护团队**: TerraForge开发团队  
**技术支持**: support@terraforge.com

### 相关文档
- [API接口文档](./terraForgeApiGuide.md)
- [CTB使用指南](./CTB使用指南.md)
- [GDAL2Tiles使用指南](./GDAL2Tiles使用指南.md)
- [智能分级测试示例](./智能分级测试示例.md)

**注意**: 本文档持续更新中，最新版本请查看项目仓库。 

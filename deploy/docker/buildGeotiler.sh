#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_banner() {
    echo -e "${BLUE}"
    echo "===================================="
    echo "    AtlasWorks GeoTiler 构建脚本"
    echo "===================================="
    echo -e "${NC}"
}

# 检查必要条件
check_requirements() {
    cd "${REPO_ROOT}"

    if ! command -v docker &> /dev/null; then
        print_error "Docker未安装！请先安装Docker"
        exit 1
    fi
    
    if [ ! -f "atlasWorks/deploy/docker/Dockerfile" ]; then
        print_error "atlasWorks/deploy/docker/Dockerfile不存在！"
        exit 1
    fi
    
    if [ ! -d "cesium-terrain-builder" ]; then
        print_error "cesium-terrain-builder目录不存在！"
        exit 1
    fi

    ensure_local_image "debian:bullseye"
    ensure_local_image "${ATLASWORKS_POSTGRES_IMAGE:-postgres:15}"
    
    print_success "环境检查通过"
}

ensure_local_image() {
    local image_name="$1"
    if docker image inspect "${image_name}" >/dev/null 2>&1; then
        print_info "基础镜像已存在本地: ${image_name}"
        return 0
    fi

    print_info "基础镜像不存在，开始拉取: ${image_name}"
    docker pull "${image_name}"
}

# 构建镜像
build_image() {
    cd "${REPO_ROOT}"
    print_info "构建AtlasWorks 独立镜像（Debian + GDAL + 本地 CTB 源码）..."
    
    # 清理旧镜像
    docker rmi atlasworks:release-2.0.0 2>/dev/null || true
    
    # 构建新镜像
    docker build \
      --build-arg APT_MIRROR="${ATLASWORKS_APT_MIRROR:-http://mirrors.tuna.tsinghua.edu.cn/debian}" \
      --build-arg APT_SECURITY_MIRROR="${ATLASWORKS_APT_SECURITY_MIRROR:-http://mirrors.tuna.tsinghua.edu.cn/debian-security}" \
      -f atlasWorks/deploy/docker/Dockerfile \
      -t atlasworks:release-2.0.0 \
      .
    
    if [ $? -eq 0 ]; then
        print_success "镜像构建成功！镜像名: atlasworks:release-2.0.0"
    else
        print_error "镜像构建失败！"
        exit 1
    fi
}

# 测试镜像
test_image() {
    cd "${REPO_ROOT}"
    print_info "测试镜像工具..."
    
    # 测试GDAL
    docker run --rm atlasworks:release-2.0.0 gdalinfo --version | head -1
    
    # 测试CTB
    docker run --rm atlasworks:release-2.0.0 ctb-tile --version
    
    print_success "工具测试完成"
}

# 创建数据目录
create_directories() {
    cd "${REPO_ROOT}"
    print_info "创建数据目录..."
    mkdir -p atlasWorks/runtime/dataSource atlasWorks/runtime/tiles atlasWorks/runtime/log
    print_success "数据目录创建完成"
}

# 显示使用说明
show_usage() {
    print_success "构建完成！"
    echo ""
    echo "推荐直接使用 docker compose："
    echo "  cd atlasWorks"
    echo "  docker compose -f dockerCompose.yml up -d --build"
    echo ""
    echo "如需单独运行镜像："
    echo "  docker run -d --name atlasworks-api \\"
    echo "    -e HOST=0.0.0.0 \\"
    echo "    -e PORT=8000 \\"
    echo "    -p 8000:8000 \\"
    echo "    -v \${PWD}/atlasWorks/runtime/dataSource:/app/dataSource \\"
    echo "    -v \${PWD}/atlasWorks/runtime/tiles:/app/tiles \\"
    echo "    -v \${PWD}/atlasWorks/runtime/log:/app/log \\"
    echo "    atlasworks:release-2.0.0"
    echo ""
    echo "使用工具："
    echo "  docker exec -it atlasworks-api bash"
    echo "  docker exec atlasworks-api ctb-tile -f Mesh -C -o /app/tiles/output /app/dataSource/input.tif"
    echo "  docker exec atlasworks-api gdal2tiles.py /app/dataSource/input.tif /app/tiles/output/"
    echo ""
    echo "访问API服务："
    echo "  http://localhost:8000/api/health"
}

# 主函数
main() {
    print_banner
    
    check_requirements
    build_image
    test_image
    create_directories
    show_usage
}

# 执行
main "$@" 

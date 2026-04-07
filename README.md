# AtlasWorks

AtlasWorks 是一个面向地理空间数据构建与发布场景的开源服务平台，聚焦于将 GeoTIFF、DEM 等数据资产组织为可执行任务、可追踪产物以及可对外访问的发布资源。项目以 Python 后端为核心，结合前端控制台、任务管理、产物清单和发布入口，提供一套从数据准备到成果交付的完整工作流。

与单一用途的切片脚本相比，AtlasWorks 更强调工程化与产品化能力，包括构建前校验、任务状态追踪、产物元数据沉淀、发布访问封装以及工作空间治理。

## Overview

AtlasWorks 适用于需要对栅格地图或地形数据进行批量处理、统一构建和集中发布的场景，例如：

- GeoTIFF 等栅格数据的地图瓦片构建
- DEM 数据的地形瓦片构建
- 构建任务的跟踪、查询与回溯
- 构建产物的清单管理与发布访问
- 面向本地部署或私有环境的可视化控制台接入

## Key Features

- Unified build workflow
  将数据源解析、预检查、任务执行、产物登记和发布访问串联为统一流程。
- Preflight validation
  在正式构建前检查输入文件、工具链可用性、输出覆盖风险与资源消耗预估。
- Raster and terrain pipelines
  同时支持地图瓦片与地形瓦片两类核心处理链路。
- Task-oriented execution
  长任务以 `taskId` 作为统一入口，支持状态查询、停止、清理与事件流查看。
- Artifact manifest
  构建完成后自动生成 `manifest.json`，用于产物元数据记录与后续追踪。
- Publication endpoints
  支持将构建结果封装为发布记录，并通过静态路径或 WMTS 方式提供访问。
- Embedded web console
  内置 Vue 3 控制台，便于在本地部署环境中直接使用和验证。

## Architecture

AtlasWorks 由以下几个主要部分组成：

- `backend/`
  基于 Flask 的后端服务，负责 API、任务编排、产物/发布管理以及静态资源分发。
- `frontend/`
  基于 Vue 3 + Vite 的控制台界面，构建后由后端统一托管。
- `db/init/`
  PostgreSQL 初始化脚本，用于基础表结构和持久化能力接入。
- `deploy/docker/`
  Docker 构建文件与容器启动脚本。
- `docs/`
  项目规划、后端接口与模块职责说明文档。

## Core Capabilities

- 数据源浏览、文件解析与基础元信息读取
- 构建前预检查与参数推荐
- Indexed tiles 地图瓦片构建
- Terrain 地形瓦片构建与辅助运维工具
- 任务列表、任务详情与任务事件流查询
- 产物列表、产物详情与 `manifest.json` 查询
- 发布记录创建、更新、删除与访问地址封装
- 工作空间浏览、重命名、移动、删除和缓存信息查看

## Quick Start

项目根目录提供了基于 Docker Compose 的本地部署入口：

```bash
docker compose -f dockerCompose.yml up -d --build
```

服务启动后，默认可访问以下入口：

- Console: `http://localhost:18000/`
- Console alias: `http://localhost:18000/console`
- Health check: `http://localhost:18000/api/health`
- API docs: `http://localhost:18000/api/docs`

## Deployment Notes

- 默认 Compose 配置使用 PostgreSQL，并将 API 暴露在 `18000` 端口。
- `dockerCompose.yml` 中包含面向本地开发环境的示例挂载路径，启动前请根据你的机器路径进行调整。
- 数据源目录、瓦片输出目录、日志目录和数据库配置均可通过环境变量覆盖。
- 由于任务状态同步和后台线程的存在，示例配置默认采用 `1 worker + 多线程` 的运行方式。

## Technology Stack

- Backend: Python, Flask, Gunicorn
- Frontend: Vue 3, Vite, Element Plus
- Database: PostgreSQL 15
- Deployment: Docker, Docker Compose
- Geospatial toolchain: GDAL, Cesium Terrain Builder

## API Surface

以下接口构成了 AtlasWorks 的主要能力入口：

- `/api/dataSources`
  数据源浏览与文件信息读取
- `/api/preflight`
  构建前预检查
- `/api/tile/indexedTiles`
  地图瓦片构建
- `/api/tile/terrain`
  地形瓦片构建
- `/api/tasks`
  任务列表与任务详情
- `/api/artifacts`
  产物列表与产物详情
- `/api/publications`
  发布记录管理
- `/published/*`
  静态发布资源访问入口
- `/wmts`
  WMTS 服务入口

更完整的接口说明见 [docs/backendApiGuide.md](docs/backendApiGuide.md)。

## Repository Layout

```text
atlasWorks/
├─ backend/              # Flask API, task orchestration, static serving
├─ frontend/             # Vue 3 console
├─ db/init/              # PostgreSQL initialization scripts
├─ deploy/docker/        # Docker build and runtime files
├─ docs/                 # Design, API, and planning documents
├─ runtime/              # Runtime data and local persistence
├─ tests/                # Backend tests
└─ dockerCompose.yml     # Local orchestration entrypoint
```

## Documentation

- [docs/backendApiGuide.md](docs/backendApiGuide.md)
- [docs/backendPyResponsibilities.md](docs/backendPyResponsibilities.md)
- [docs/planning/pythonProductPlan.md](docs/planning/pythonProductPlan.md)
- [frontend/README.md](frontend/README.md)

## Project Status

AtlasWorks 目前处于持续演进阶段，已经具备较完整的本地构建、任务追踪、产物登记和发布访问能力。现阶段的重点仍然是继续提升以下方面：

- 更稳定的任务状态机与错误码体系
- 更完善的鉴权与权限控制
- 更清晰的版本治理与发布流程
- 更完整的测试覆盖与部署说明

如果你希望将其用于长期维护或生产环境，建议在接入前结合自身场景补充配置管理、安全策略和运维约束。

# AtlasWorks

`atlasWorks` 是当前产品化重组后的根目录，用来承载 Python 服务端、数据库初始化、Docker 部署和产品规划文档。

## 目录结构

- `backend`
  Python API 服务代码。
  当前已拆出 `preflight.py`、`artifacts.py`、`catalog.py`、`dataSourceOps.py`、`fileSplitOps.py`、`indexedTilesOps.py`、`routeRegistry.py`、`taskState.py`、`terrainOps.py`、`taskCenter.py`、`systemOps.py`、`tileAdminOps.py`、`workspaceOps.py` 等模块，`app.py` 已收敛为启动入口。
- `db/init`
  PostgreSQL 初始化脚本。
- `deploy/docker`
  Dockerfile 和镜像构建脚本。
- `docs/planning`
  产品规划与架构设计文档。
- `docs/legacy`
  旧版 TerraForge 文档，作为历史资料保留。
- `dockerCompose.yml`
  AtlasWorks 的统一本地编排入口。

## 当前约定

- PostgreSQL 宿主机端口固定为 `25432`
- API 宿主机默认端口为 `18000`
  这样可以避免和旧版 `terraforge-api` 占用的 `8000` 冲突；如需改回，可通过 `ATLASWORKS_HOST_PORT` 覆盖。
- 运行时目录统一放在 `atlasWorks/runtime`
- Python 服务代码统一以 `atlasWorks/backend` 为主工作区
- 当前已具备基础 `preflight` 预检查能力和 `manifest.json` 产物描述能力
- 已内置控制台页面，默认入口为 `/`，也可通过 `/console` 访问
- 后端模块职责说明见 `docs/backendPyResponsibilities.md`
- 后端 API 说明见 `docs/backendApiGuide.md`

## 当前新增能力

- `POST /api/preflight`
  在正式执行地图或地形构建前，检查输入文件、工具链、波段情况、输出覆盖风险与粗略资源预估。
- 构建成功后自动写出 `manifest.json`
  当前已接入索引切图与地形切片任务，产物目录中会自动生成 `manifest.json`，并尝试同步产物记录到 PostgreSQL。
- `GET /api/artifacts`、`GET /api/artifacts/<artifactId>`
  可查看已生成产物的列表和详情，数据库不可用时会回退扫描 `manifest.json`。
- `GET /api/artifacts/<artifactId>/manifest`
  可直接查看产物目录中的 `manifest.json` 内容。
- `GET/POST /api/publications`
  可为已有产物创建基础发布记录，并写入 `atlasWorks/runtime/tiles/_publications/<alias>/publication.json`。
- `GET /api/tasks/<taskId>/events`
  可读取任务的结构化事件流；数据库可用时返回 `tf_job_events`，否则回退到内存 `processLog`。
- 产物生成与发布创建也会写入任务事件流
  当前事件链已覆盖任务状态变化、`manifest` 生成、发布记录创建。
- 内嵌控制台页面
  当前已提供内嵌静态页面，可直接查看系统状态、数据源、任务、产物与发布，并提交预检查、索引切片和地形切片 JSON 请求。

## 启动方式

```bash
cd atlasWorks
docker compose -f dockerCompose.yml up -d --build
```

启动后可访问：

- `http://localhost:18000/`
- `http://localhost:18000/console`

## Docker 说明

- 当前默认 Dockerfile 为 `atlasWorks/deploy/docker/Dockerfile`
- 当前默认基础镜像为 `terraforge:v3.0`
  这是为了复用本机已有的 GDAL/CTB 运行底座，避免当前环境下 Docker Hub 拉取失败导致构建中断。
- 如需切换基础镜像，可在构建时覆盖 `BASE_IMAGE`

```bash
docker build \
  --build-arg BASE_IMAGE=debian:bullseye \
  -f atlasWorks/deploy/docker/Dockerfile \
  -t atlasworks:release-2.0.0 .
```

- `docker compose` 目前支持以下覆盖变量：
  `ATLASWORKS_BASE_IMAGE`
  `ATLASWORKS_POSTGRES_IMAGE`
  `ATLASWORKS_HOST_PORT`

- API 容器当前默认使用 `gunicorn` 启动，并固定为 `1 worker + 多线程`
  因为当前服务里仍有进程内任务状态表和后台同步线程，多 worker 会把任务状态拆到不同进程里。

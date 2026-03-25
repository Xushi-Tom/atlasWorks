# AtlasWorks Backend API Guide

本文档描述当前 AtlasWorks Python 后端已经开放的主要接口，方便前端、脚本调用方和后续联调使用。

## 约定

- 默认基础路径：`/api`
- 返回格式：JSON
- 长任务接口通常立即返回 `taskId`
- 长任务状态查询接口：`GET /api/tasks/<taskId>`
- 内嵌控制台页面入口：`/` 或 `/console`

## 系统与文档

- `GET /api/health`
  健康检查，返回服务状态、数据库状态和基础任务统计。

- `GET /api/system/info`
  返回系统配置、资源信息、数据库健康和任务统计。

- `POST /api/container/update`
  更新容器运行环境、时间、配置、环境变量和缓存信息。

- `GET /api/routes`
  返回当前已注册路由的清单与分类统计。

## 数据源

- `GET /api/dataSources`
- `GET /api/dataSources/<subpath>`
  浏览数据源目录，返回子目录和可识别数据文件。

- `GET /api/dataSources/info/<filename>`
  获取单个数据源详细信息，包括基础元数据与推荐配置。

- `POST /api/dataSources/resolve`
  根据 `folderPaths` 和 `filePatterns` 解析匹配到的源文件。

- `POST /api/dataSources/split`
  将超大栅格拆成多个较小 TIF 文件。

- `POST /api/preflight`
  正式构建前预检查，返回工具链、输入文件、输出覆盖风险和资源估算。

- `POST /api/config/recommend`
  根据源文件大小和机器资源推荐切片参数。

## 瓦片与地形构建

- `POST /api/tile/indexedTiles`
  执行 indexed tiles 切片任务。

- `POST /api/tile/terrain`
  执行 terrain 切片任务。

- `POST /api/tile/convert`
  在 `z/x_y.ext` 与 `z/x/y.ext` 两种目录结构之间转换瓦片目录。

- `POST /api/tiles/nodata/scan`
  扫描包含透明或 nodata 的 PNG 瓦片。

- `POST /api/tiles/nodata/delete`
  删除扫描到的透明或 nodata 瓦片。

- `POST /api/terrain/layer`
  更新 terrain 目录中的 `layer.json`。

- `POST /api/terrain/decompress`
  解压 `.terrain.gz` 文件。

## 工作空间与缓存

- `GET /api/results`
  浏览结果目录。

- `GET /api/fileDetails`
  获取单个文件详情。
  支持通过查询参数 `type=datasource|results` 和 `path=<relativePath>` 指向数据源文件或结果文件。

- `GET /api/workspace/info`
  获取工作空间总大小、文件数量、目录数量等统计。

- `POST /api/workspace/createFolder`
  在结果目录中创建文件夹。

- `DELETE /api/workspace/folder/<folderPath>`
  删除指定文件夹。

- `PUT /api/workspace/folder/<folderPath>/rename`
  重命名指定文件夹。

- `DELETE /api/workspace/file/<filePath>`
  删除指定文件。

- `GET /api/cache/info`
  返回缓存目录、元数据文件、索引文件和实际瓦片数量等信息。

## 任务中心

- `GET /api/tasks`
  列出最近任务。

- `GET /api/tasks/<taskId>`
  获取任务详情。

- `GET /api/tasks/<taskId>/events`
  获取任务事件流。

- `POST /api/tasks/cleanup`
  清理旧任务。

- `POST /api/tasks/<taskId>/stop`
  停止任务。

- `DELETE /api/tasks/<taskId>`
  删除任务。

## 产物与发布

- `GET /api/artifacts`
  列出产物。

- `GET /api/artifacts/<artifactId>`
  获取产物详情。

- `GET /api/artifacts/<artifactId>/manifest`
  获取产物 `manifest.json`。

- `GET /api/publications`
  列出发布记录。

- `POST /api/publications`
  创建发布记录。

- `GET /api/publications/<publicationId>`
  获取发布详情。

## 当前仍未覆盖的部分

- 还没有标准 OpenAPI/Swagger 文档
- 还没有接口鉴权和权限模型
- 3D Tiles、GeoJSON、OBJ、GLB 发布链路当前未纳入范围

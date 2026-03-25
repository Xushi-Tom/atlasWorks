# AtlasWorks Python 产品化规划

注意：代码注释一定要写好，最好每行一注释

## 1. 文档目的

这份文档用于沉淀当前对 AtlasWorks Python 服务的产品化思考，避免后续讨论内容丢失。

当前共识如下：

- 核心实现以 Python 为主，不以 Java 为核心演进方向。
- Python 服务应逐步从“工具型脚本接口”演进为“可交付的产品型服务”。
- 页面可以内嵌在 Python 服务中，作为最终形态之一。
- 当前阶段先做规划沉淀，不急于立即修改大规模代码。

## 1.1 已落地基础项

当前已开始落地的产品化基础能力：

- PostgreSQL 初始化与任务快照同步已接入
- `dockerCompose.yml` 已统一管理 API 与 PostgreSQL
- 新增 `POST /api/preflight` 预检查接口
- 索引切图与地形切片完成后会自动写出 `manifest.json`
- 产物基础记录会尝试同步到 `tf_artifacts`
- 已新增产物查询与发布记录 API，形成基础产物台账
- 已开始沉淀 `tf_job_events` 任务事件流，便于后续做任务中心与控制台
- `artifact.manifest_written`、`publication.created` 已开始写入任务事件流

这些能力目前属于第一版基础实现，后续仍需继续补齐更精细的状态机、错误码、版本治理和发布流程。

## 2. 产品定位

AtlasWorks Python 服务未来应定位为一个地理空间构建与发布引擎，而不是单纯的切片脚本集合。

建议目标能力：

- 栅格地图切片构建
- DEM 地形切片构建
- 构建结果管理与版本化发布
- 工作空间与任务管理
- 产物元数据治理
- 后续可扩展到更多格式和发布能力

建议避免继续沿着“每加一种能力就新增一个零散接口”的方式发展，而是逐步形成统一的任务、产物、发布模型。

## 3. 当前核心判断

### 3.1 Python 才是核心

未来的核心方向应是：

- Python 直接暴露 API
- Python 直接管理任务
- Python 直接管理产物
- Python 直接管理发布
- 前端页面可以由 Python 内嵌提供

Java 后续即使保留，也更适合作为外围适配层，而不是核心业务承载层。

### 3.2 当前 service.py 的本质

`atlasWorks/backend/service.py` 目前承担了过多职责：

- HTTP 入参处理
- 业务编排
- GDAL/CTB 命令执行
- 任务状态管理
- 文件扫描与目录操作
- 地理元数据解析
- 地图瓦片构建
- 地形瓦片构建
- 系统工具类接口

它现在更像一个“单文件服务层总装模块”，不利于产品级演进。

### 3.3 当前的主要问题不是功能少，而是产品能力不完整

当前最重要的问题并不是再加几个接口，而是以下能力尚未形成闭环：

- 任务持久化
- 构建恢复
- 构建前预检查
- 产物版本化
- 发布流程
- 资源治理
- 观测能力
- 运行可靠性

## 4. 未来推荐的核心模型

建议后续逐步围绕以下 4 个核心对象做架构收敛：

### 4.1 SourceAsset

表示输入数据资产。

建议字段：

- id
- name
- type
- path
- source_kind
- crs
- bounds
- band_info
- nodata
- file_size
- checksum
- metadata

可支持类型：

- raster
- dem
- vector
- model3d

### 4.2 BuildJob

表示一次构建任务。

建议字段：

- id
- job_type
- status
- stage
- params
- source_assets
- created_at
- started_at
- finished_at
- error_code
- error_message
- progress
- retry_count
- resume_token

典型 job_type：

- map_tiles
- terrain_tiles
- geojson_extract
- obj_convert
- glb_convert
- tiles3d_build

### 4.3 Artifact

表示构建产物。

建议字段：

- id
- artifact_type
- build_job_id
- version
- output_path
- format
- bounds
- crs
- metadata_path
- manifest_path
- file_count
- total_size
- status

典型 artifact_type：

- xyz_tiles
- terrain
- geojson
- obj
- glb
- 3dtiles

### 4.4 Publication

表示一次对外发布结果。

建议字段：

- id
- artifact_id
- publish_type
- publish_path
- alias
- status
- published_at
- visibility
- metadata

典型 publish_type：

- static
- wmts
- terrain_service
- tileset_service

## 5. 产品级必须补齐的能力

下面这些点比“新增某个接口”更重要。

### 5.1 任务持久化

当前任务状态是内存态，服务重启会丢失。

产品化后必须支持：

- 任务记录持久化
- 任务阶段日志持久化
- 任务结果持久化
- 重启后恢复任务历史
- 支持排队、运行、失败、完成、取消等稳定状态

### 5.2 崩溃恢复与断点续跑

长任务不应只支持“失败后全部重来”。

建议支持：

- 从已有 metadata 恢复
- 从已有 tile index 恢复
- 从已有输出目录恢复
- 失败分片重试
- 局部补算

### 5.3 构建前预检查

建议为所有构建任务增加 `preflight` 机制。

预检查内容应包括：

- 输入文件数量
- 文件格式是否支持
- 坐标系是否一致
- 波段情况
- nodata 情况
- 预计输出瓦片数
- 预计磁盘占用
- 预计运行时长
- 是否会覆盖已有目录
- 工具链是否可用

### 5.4 产物 manifest

每次构建完成后应写出统一的 `manifest.json`。

建议至少记录：

- 输入源文件列表
- 输入文件校验和
- 使用参数
- 工具版本
- 构建时间
- 结果 bounds
- 输出格式
- 瓦片数量
- 失败样本
- 性能统计

### 5.5 版本化发布

产物不应只是“写进某个目录”。

建议支持：

- draft
- built
- published
- archived

同时支持：

- 当前版本
- 历史版本
- 回滚到上一版本
- 删除旧版本
- 发布别名切换

### 5.6 资源治理

产品环境中最容易出问题的是资源失控。

建议后续增加：

- 单任务最大磁盘占用
- 单任务最大输出文件数
- 单任务最大运行时长
- 单工作空间并发数限制
- 全局任务队列上限
- 磁盘空间水位检查
- 内存告警与自动降载

### 5.7 结构化日志与监控指标

当前文本日志对排障有帮助，但不够产品化。

建议逐步支持：

- JSON 结构化日志
- task_id、job_type、workspace、stage、duration、error_code 等字段
- 指标上报
- Prometheus 监控
- 构建耗时分布
- 失败率统计
- 工具调用成功率统计

### 5.8 稳定的错误码体系

建议所有产品级接口返回稳定错误码，而不是只返回自然语言字符串。

示例：

- DATASET_NOT_FOUND
- UNSUPPORTED_FORMAT
- PROJECTION_MISMATCH
- TOOL_UNAVAILABLE
- INSUFFICIENT_DISK
- INVALID_PARAMETERS
- BUILD_INTERRUPTED

### 5.9 运行方式升级

当前 Python 服务更偏开发运行模式。

产品化后建议：

- API 进程与重任务执行进程分离
- 生产级 WSGI/ASGI 启动方式
- 明确 worker 模型
- 明确超时与退出策略
- 明确系统信号处理

### 5.10 回归测试与金样本

GIS 类系统最怕“看起来能跑，结果 quietly 变了”。

建议建立固定测试资产：

- 小型地图 GeoTIFF 样本
- 单波段 DEM 样本
- 多波段 DEM 样本
- 含 nodata 的样本
- 坐标系不一致样本

并建立以下测试：

- manifest 对比
- 输出目录结构快照
- layer.json 快照
- 结果范围对比
- 关键瓦片校验

## 6. 地图与 DEM 的产品化差异

地图切片和 DEM 地形切片虽然都属于“切片”，但产品模型不能完全混用。

### 6.1 地图切片

当前地图切片能力相对更成熟，后续应继续强化：

- 波段映射
- stretch
- nodata 控制
- 透明阈值
- 增量更新
- 索引复用

### 6.2 DEM 地形切片

DEM 切片不应直接套用 RGB 模型。

未来建议引入专门参数：

- heightBand
- nodataValue
- zScale
- zOffset
- verticalDatum
- outputFormat
- meshQuality
- skirtHeight

当前如果输入是多波段 DEM，需要明确到底取哪一个高程波段，不能依赖隐式假设。

## 7. 未来扩展方向

后续可扩展的方向很多，但不建议直接平铺接口。

建议未来逐步支持以下产物类型：

- 3dtiles
- geojson
- obj
- glb
- gltf

建议注意：

- 先统一构建模型，再扩格式
- 先统一产物元数据，再扩发布方式
- 先统一版本治理，再扩多格式输出

## 8. 页面内嵌方向

Python 内嵌页面是合理方向。

建议未来页面承担的角色：

- 任务发起
- 任务状态查看
- 构建预检查结果展示
- 产物浏览
- 版本发布与回滚
- 日志和错误查看
- 资源占用查看

建议页面不要只做“表单集合”，而是逐步变成构建控制台。

## 9. 数据持久化方案

### 9.1 为什么必须持久化

当前状态保存在内存中，存在以下问题：

- 服务重启后任务记录丢失
- 无法做历史审计
- 无法做版本治理
- 无法稳定支持队列与恢复
- 无法构建产品级任务中心

因此，任务、产物、发布记录都应落库。

### 9.2 推荐数据库

建议使用 PostgreSQL。

原因：

- 本地已在使用 PostgreSQL Docker 镜像
- 对 JSON/JSONB 支持好
- 适合存任务参数、manifest、元数据
- 后续扩展空间大

### 9.3 容器管理方式

建议后续统一使用 `docker-compose` 管理。

当前建议方向：

- 一个 Python API 服务容器
- 一个 PostgreSQL 容器
- 后续如有需要再加 Redis 或独立 worker

### 9.4 PostgreSQL 端口约束

数据库容器端口固定使用：

- `25432:5432`

这样做的原因：

- 避免与本地已有 PostgreSQL 默认端口冲突
- 降低本地开发环境冲突概率

### 9.5 建议的数据库用途

第一阶段建议 PostgreSQL 主要承担以下数据：

- build_jobs
- build_job_logs
- artifacts
- publications
- workspaces
- source_assets

第二阶段再考虑：

- 用户与权限
- 配额与策略
- 审计日志
- 统计报表

## 10. docker-compose 规划约束

后续建议新增统一的 `dockerCompose.yml`，至少管理：

- `atlasworks-api`
- `atlasworks-postgres`

设计约束：

- PostgreSQL 对外端口为 `25432`
- API 与 PostgreSQL 使用 compose 网络通信
- 数据库数据目录必须挂载到本地卷
- API 输出目录与数据源目录必须可挂载

建议后续 compose 中区分：

- 开发环境
- 本地产品演示环境
- 生产部署环境

## 11. 建议的落地阶段

### 阶段 A：先做基础产品化地基

- 明确 Python 为唯一核心方向
- 梳理 service.py 功能边界
- 引入 PostgreSQL 持久化
- 设计任务表、产物表、发布表
- 建立 `manifest.json` 规范

### 阶段 B：把任务系统做完整

- 任务状态落库
- 队列化管理
- 可恢复
- 可取消
- 有阶段日志
- 有错误码

### 阶段 C：把构建做成产品能力

- 预检查
- 产物版本化
- 发布与回滚
- 构建审计
- 指标监控

### 阶段 D：再扩展格式与发布

- terrain
- xyz/tms
- geojson
- obj/glb
- 3dtiles
- WMTS/静态发布

## 12. 当前不建议优先做的事

以下内容暂时不建议排在最前面：

- 继续在 `service.py` 中堆更多零散接口
- 过早做大量前端视觉优化
- 先做很多格式转换而不做任务与产物治理
- 先做复杂权限系统而没有任务中心

## 13. 当前最值得优先推进的 5 件事

1. 引入 PostgreSQL 持久化任务与产物数据
2. 设计统一的 BuildJob / Artifact / Publication 模型
3. 建立构建前预检查能力
4. 建立 manifest 与版本化发布机制
5. 升级日志、错误码、运行方式

## 14. 后续文档建议

建议后续继续补充以下文档：

- 数据库表结构设计
- manifest 规范
- build job 状态机设计
- 产物发布规范
- Python 服务模块拆分方案
- docker-compose 部署方案

---

本文档是当前阶段的产品化共识稿，后续可以作为 Python 重构和产品升级的基础说明文档持续迭代。

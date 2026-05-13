# GeoServer 发布与地图切片工作日志

## 1. 本阶段目标

- 将影像数据源发布和地图切片主链路从 TiTiler/GDAL 直接出图，收敛到 GeoServer。
- 保留 GDAL 基础能力，用于元数据读取、坐标范围识别、NoData/透明瓦片检测，以及地形/三维/矢量等非地图影像出图场景。
- 优化发布中心和切片生产页面，减少 Demo 感，让配置项、预览、启停、列表加载更接近产品化使用。
- 保证 Docker Compose 启动链路移除 TiTiler 后仍可正常运行。

## 2. 集成 GeoServer 后可以做什么

- **影像服务发布**：将单个 GeoTIFF 或多个 GeoTIFF 发布为 GeoServer 图层，提供 WMS/WMTS/GWC 访问能力。
- **实时服务预览**：发布中心预览可以直接使用 GeoServer WMS/WMTS 地址加载影像。
- **GWC 缓存瓦片**：发布提交后可触发 GeoServer GWC Seed，提前生成缓存瓦片，减少首次访问压力。
- **地图切片生产**：地图切片任务使用 GeoServer WMS 渲染瓦片，再写出到本地 XYZ/TMS 目录，产物仍可走原发布产物链路。
- **图层管理能力**：后端新增 GeoServer 图层发布、详情、删除、Seed、Seed 状态查询、Seed 取消接口。

## 3. 已完成工作

### 3.1 移除 TiTiler 链路

- **做了什么**
  - 从 Docker Compose 启动链路中移除 `atlasworks-titiler`。
  - 前端发布方式和预览逻辑不再依赖 TiTiler。
  - 后端发布中心影像数据源默认走 GeoServer WMS/WMTS。

- **为什么改**
  - TiTiler 和 GeoServer 同时存在会造成发布链路分散，预览、缓存、权限、启停状态难以统一管理。
  - 生产环境更适合将影像服务集中交给 GeoServer/GWC 管理。

- **解决的问题**
  - 减少一个服务容器，降低部署和运维复杂度。
  - 发布、预览、缓存统一到 GeoServer 体系内。

### 3.2 GeoServer 数据源影像发布

- **做了什么**
  - 新增 GeoServer 发布接口，支持工作空间、CoverageStore、Coverage、样式、预览 URL 生成。
  - 发布记录中保存 WMS、WMTS、GWC Tile URL、图层名、工作空间、范围等信息。
  - 发布后可自动提交 GWC Seed。

- **为什么改**
  - 原列表和详情接口中部分 URL/元数据计算过重，影响发布中心加载速度。
  - 影像服务应该由 GeoServer 提供标准 OGC 能力，前端只消费服务地址。

- **解决的问题**
  - 发布中心可以直接复制和预览 GeoServer 服务地址。
  - 列表加载减少详情级计算，启停操作更接近字段更新。

### 3.3 地图切片切换为 GeoServer 出图

- **做了什么**
  - 地图切片主流程改为：解析源 TIFF → 发布临时 GeoServer 图层 → 通过 WMS GetMap 渲染瓦片 → 写入本地瓦片目录 → 清理临时图层。
  - 移除旧 GDAL 地图影像直接出图分支。
  - 保留 GDAL 本体及 `gdalinfo` 等能力，不影响元数据读取和其他切片类型。

- **为什么改**
  - 地图影像切片既然已经统一到 GeoServer 渲染，就不应该再维护两套出图逻辑。
  - 旧 GDAL 出图代码参数多、分支多，和当前产品页面已经不匹配。

- **解决的问题**
  - 地图切片渲染逻辑单一，后续调试集中在 GeoServer/WMS/GWC。
  - 减少旧代码维护成本，避免用户配置项和实际执行链路不一致。

### 3.4 GeoServer 切片稳定性增强

- **做了什么**
  - WMS 单瓦片请求增加重试。
  - 支持增量续切，已有瓦片不重复写。
  - 失败瓦片写入 `failed_tiles.json`。
  - 临时 GeoServer 图层和样式清理结果写入 `geoserver_cleanup.json`。
  - 增加任务停止检测。
  - 增加波段配置校验，避免 RGB 波段超过源文件实际波段数。
  - 增加透明瓦片后处理，PNG 输出下可按阈值清理透明瓦片。
  - 增加 `scripts/geoserver_smoke.py` 冒烟检查脚本。

- **为什么改**
  - GeoServer WMS 出图可能因为瞬时压力、源 TIFF 读取、网络抖动失败，需要可恢复机制。
  - 切片失败后必须知道具体失败瓦片，否则无法补切和定位问题。
  - 临时图层不清理会污染 GeoServer 工作空间。

- **解决的问题**
  - 提升长任务可靠性。
  - 失败可定位、可补救。
  - GeoServer 资源生命周期更清楚。

### 3.5 发布预览优化

- **做了什么**
  - 发布预览抽屉遮罩支持单独指定背景色。
  - 修复发布预览打开后，后面的系统背景被蓝黑色遮罩影响的问题。
  - 保留 Cesium 全球底图，不改变预览球体和底图加载逻辑。
  - 去掉预览下方“使用 GeoServer GWC/WMTS...”这类说明条。
  - 飞到区域优先使用发布范围或样例瓦片范围，避免大范围数据飞到异常高度。

- **为什么改**
  - 用户关注的是抽屉背后的系统背景一致性，不是 Cesium 球体底图。
  - 预览弹层应该干净，不展示调试式说明文案。

- **解决的问题**
  - 预览打开后的整体视觉统一为黑色系统背景。
  - 发布预览更像正式产品界面。

### 3.6 地图切片页面产品化

- **做了什么**
  - 最小层级、最大层级、瓦片尺寸、投影、格式等输入框宽度统一。
  - 高级配置默认收起，点击后展开。
  - 获取波段信息只在高级配置展开后展示。
  - 页面文案改为 GeoServer 渲染语义。

- **为什么改**
  - 原页面配置项堆叠明显，像 Demo 工具页。
  - 常用参数和高级参数需要区分，降低用户首次使用成本。

- **解决的问题**
  - 表单更规整。
  - 用户优先关注必要参数，高级配置按需展开。

### 3.7 Docker 启动链路验证

- **做了什么**
  - 使用 `docker-compose.external-db.yml` 验证非内置数据库启动链路。
  - 重建 `atlasworks:release-20260506` 镜像。
  - 验证 API、Publisher、Worker、GeoServer、Nginx 容器健康。

- **为什么改**
  - 移除 TiTiler 后必须确认容器编排不再引用旧服务。
  - 当前实际使用的是 external-db compose，需要按真实链路验证。

- **解决的问题**
  - 确认删除 TiTiler 后容器可以正常起。
  - 确认 GeoServer 容器和 AtlasWorks 主服务可联通。

## 4. 当前验证结果

- 前端构建：`npm run build` 通过。
- Python 编译：`py_compile` 通过。
- Docker 镜像：`atlasworks:release-20260506` 构建通过。
- Compose 启动：`docker-compose.external-db.yml` 启动通过。
- 健康检查：`/api/health` 返回 healthy。
- GeoServer 冒烟：`scripts/geoserver_smoke.py` 通过。

## 5. 当前仍需继续做的工作

### 5.1 GeoServer/GWC

- Seed 进度需要在前端任务面板中可视化，不只是后端接口可查。
- Seed 取消按钮需要接到发布中心或图层详情。
- GWC 缓存大小、缓存清理、缓存命中率需要补展示。
- 临时图层清理失败时，需要提供管理页一键清理。

### 5.2 地图切片

- 增加真实样例集成测试：单 TIFF、多 TIFF、NoData、RGB 多波段、不同 CRS。
- 增加失败瓦片补切入口，读取 `failed_tiles.json` 后只补失败瓦片。
- 增加切片产物校验：瓦片数量、空瓦片比例、层级完整性。
- 补充大范围数据的层级推荐，避免用户直接切过高层级导致任务过大。

### 5.3 发布中心

- 发布详情页增加 GeoServer 图层健康状态。
- 发布列表增加 Seed 状态和缓存状态。
- 支持批量启停、批量删除、批量刷新 URL。
- 区分“实时发布”和“预切片产物发布”的展示文案。

### 5.4 预览能力

- DEM 地形预览需要单独优化，目前应支持更明确的地形高度、地形 exaggeration、飞行视角。
- 3D Tiles 预览需要展示 tileset 信息、包围盒、加载错误。
- 二维矢量瓦片建议接入 MapLibre 或 Cesium vector provider 预览。
- GeoServer WMS/WMTS 预览需要增加图层加载错误提示和重试。

### 5.5 页面产品化

- 切片生产页面继续按“基础参数 / 数据处理 / 输出设置 / 诊断信息”分组。
- 任务列表增加失败原因摘要和一键复制错误。
- 发布预览抽屉底部增加服务 URL、复制按钮、打开 GeoServer 预览按钮。
- 表单建议增加层级成本估算，提前提示预计瓦片数量和耗时。

## 6. 关键提交记录

- `dafe428 UI 大变更`：完成整体 UI 框架重构、侧边栏、主题、页面结构调整。
- `921f3b4 feat: refine console ui and publication interactions`：优化控制台 UI 和发布交互。
- `0d56fc5 feat: refine preview and dark theme polish`：优化发布预览、暗色主题和抽屉交互。
- `9611a5a 完善 GeoServer 发布与预览体验`：移除 TiTiler，完善 GeoServer 发布、预览、切片页面。
- `af9c56f 收敛 GeoServer 地图切片链路`：删除旧 GDAL 地图出图分支，补强 GeoServer WMS 切片稳定性。


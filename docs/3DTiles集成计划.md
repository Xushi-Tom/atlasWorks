# 3D Tiles 集成计划（开源版）

> 目标：在 AtlasWorks 现有架构上，新增 3D Tiles 处理能力，严格采用开源工具链，复用已有任务、产物、发布体系。

---

## 一、范围与原则

### 1.1 本期范围

- 支持输入：`.las/.laz`、`.geojson/.shp`、`.obj`、`.osgb`
- 支持输出：标准 3D Tiles 目录（`tileset.json` + `.pnts/.b3dm/...`）
- 支持发布：复用现有 `artifact + publication + /published/*`

### 1.2 明确不做

- 不新增独立 3D Tiles 静态服务接口（不新增 `/api/3dtiles/serve/*`）
- 不依赖商业转换工具（如付费 CLI）

### 1.3 关键结论

- 3D Tiles 流程与现有 `TIF/DEM -> terrain` 流程是并行关系，不替代彼此。
- 3D Tiles 输入不以 `tif` 为主，核心输入是点云、矢量、模型和倾斜摄影数据。

---

## 二、输入与产出定义

| 输入类型 | 典型输入 | 典型输出 | 难度 |
|---|---|---|---|
| 点云 | `.las/.laz` | `tileset.json + .pnts` | 低-中 |
| 矢量建筑 | `.geojson/.shp`（含高度字段） | `tileset.json + .b3dm/.glb`（可选） | 中 |
| 通用模型 | `.obj` | `tileset.json + .b3dm/.glb`（可选） | 中 |
| 倾斜摄影 | 单个 `.osgb` 或目录（递归） | `tileset.json + chunk_*.b3dm/.glb`（可选） | 中-高 |

说明：

- Cesium 实际加载入口始终是 `tileset.json`。
- `.b3dm` 不是唯一产物，点云场景通常是 `.pnts`。

---

## 三、架构复用策略

本期不新建发布体系，直接复用现有能力：

- 任务生命周期：复用 `taskCenter.py` / `taskState.py`
- 任务状态查询：复用 `/api/tasks/*`
- 产物登记：复用 `artifacts.py`
- 发布管理：复用 `catalog.py` 与 `/api/publications`
- 访问地址：复用 `/published/*`

目标交付形态：

- 任务完成后，生成 3D Tiles 输出目录
- 自动写入 artifact 记录
- 通过 publication 发布后，对外使用 `/published/<path>/tileset.json`

---

## 四、开源工具链（仅开源）

### 4.1 Python 依赖

```txt
py3dtiles
laspy
lazrs
trimesh
pygltflib
numpy
scipy
```

### 4.2 命令行工具

```txt
obj2gltf           # OBJ -> GLB
3d-tiles-tools     # GLB/B3DM/tileset 处理
osgconv            # OSGB 中间转换（来自 OpenSceneGraph）
```

### 4.3 许可原则

- 所有新增依赖必须是可审计的开源许可（Apache/MIT/BSD/OSGPL 等）。
- 引入前在仓库记录版本与许可证。

---

## 五、后端功能开发清单

### 5.1 新增 3D Tiles 任务模块

新增文件建议：

```txt
backend/tiles3dOps.py
backend/tiles3dPointCloud.py
backend/tiles3dVector.py
backend/tiles3dModel.py
backend/tiles3dOsgb.py
```

职责：

- 参数校验与输入解析
- 任务创建、进度更新、错误落库
- 调用对应转换链路
- 输出目录完整性检查（必须包含 `tileset.json`）
- 产物归档（artifact）

### 5.2 新增任务创建接口

仅新增一个入口接口：

```txt
POST /api/tile/3dtiles
```

复用现有接口：

```txt
GET /api/tasks/<taskId>
GET /api/tasks
POST /api/tasks/<taskId>/stop
DELETE /api/tasks/<taskId>
POST /api/publications
GET /published/<path>/tileset.json
```

### 5.3 产物类型扩展

在 `artifacts.py` 中新增：

- `artifactType: 3dtiles`
- `format: 3d-tiles`
- `manifest` 中记录 `tileset.json` 相对路径

### 5.4 发布与 MIME

- 复用现有 `/published/*` 文件分发逻辑
- 补充 3D Tiles 常用扩展名 MIME 识别：
  - `.json`
  - `.pnts`
  - `.b3dm`
  - `.i3dm`
  - `.cmpt`
  - `.glb`

---

## 六、各输入类型处理链路

### 6.1 LAS/LAZ（点云）

```txt
LAS/LAZ
 -> 坐标识别与必要重投影
 -> py3dtiles convert
 -> tileset.json + pnts
```

### 6.2 GeoJSON/SHP（矢量建筑）

```txt
GeoJSON/SHP
 -> 提取高度字段/默认高度策略
 -> 面拉伸生成 3D 几何
 -> 输出 GLB
 -> 封装 B3DM + tileset.json
```

### 6.3 OBJ（通用模型）

```txt
OBJ
 -> obj2gltf 生成 GLB
 -> 封装 B3DM
 -> 生成 tileset.json
```

### 6.4 OSGB（倾斜摄影，开源路径）

```txt
OSGB（单文件/目录批量）
 -> 递归收集 .osgb
 -> osgconv 转中间模型
 -> 按单体切块（chunk_*）
 -> 按配置输出 GLB 或封装 B3DM
 -> 生成 tileset.json
```

说明：

- OSGB 为本期最高风险输入类型，需单独留出调试与样本验证时间。

---

## 七、前端功能开发清单

新增页面建议：

```txt
frontend/src/views/Tiles3DView.vue
```

新增能力：

- 输入类型选择：pointcloud/vector/model/osgb
- 不同输入类型展示不同参数区
- 提交 `POST /api/tile/3dtiles`
- 跳转现有任务页查看进度
- 使用现有发布页完成 publication

`api.js` 新增方法：

```txt
create3DTiles(params)
```

---

## 八、Docker 与环境改造

`deploy/docker/Dockerfile` 需要新增：

- Python 包：`py3dtiles/laspy/lazrs/trimesh/pygltflib/scipy`
- CLI：`obj2gltf`、`3d-tiles-tools`、`osgconv`（可执行路径可被后端调用）

要求：

- 镜像构建阶段做工具可用性校验（`--version`）
- 运行时日志明确输出实际调用命令与退出码

---

## 九、实施顺序（建议）

| 周次 | 任务 | 产出 |
|---|---|---|
| Week 1 | 环境改造 + 点云链路 | LAS/LAZ 可稳定生成 `tileset.json + pnts` |
| Week 2 | 矢量与 OBJ 链路 | GeoJSON/SHP/OBJ 可生成 `tileset.json + b3dm` |
| Week 3 | OSGB 开源链路打通 | 可处理样本 OSGB，完成基础验证 |
| Week 4 | 稳定性优化 + 联调发布 | 全类型接入任务/产物/发布体系 |

---

## 十、验收标准

### 10.1 通用验收

- 任一输入类型均可创建任务并查询状态
- 成功任务输出目录包含 `tileset.json`
- artifact 列表可看到 `3dtiles` 类型
- publication 成功后可通过 `/published/.../tileset.json` 访问
- Cesium 加载无报错

### 10.2 分类型验收

- 点云：生成 `.pnts`，可按视角分级加载
- 矢量：建筑高度与属性映射正确
- OBJ：模型坐标与纹理正确
- OSGB：纹理不丢失、层级切换可用

---

## 十一、主要风险与应对

| 风险 | 说明 | 应对 |
|---|---|---|
| OSGB 工具链稳定性 | 开源链路复杂，样本差异大 | 单独测试集 + 失败回退策略 |
| 大数据量性能 | 点云/模型数据可能很大 | 分块处理 + 并行参数暴露 |
| 坐标不一致 | 输入 CRS 混杂 | 统一预处理与强校验 |
| MIME 兼容性 | 浏览器或客户端识别差异 | 明确扩展名映射并实测 |

---

## 十二、参考资料

- 3D Tiles 规范：https://github.com/CesiumGS/3d-tiles
- py3dtiles：https://py3dtiles.org
- obj2gltf：https://github.com/CesiumGS/obj2gltf
- 3d-tiles-tools：https://github.com/CesiumGS/3d-tiles-tools
- OpenSceneGraph 许可与工具：https://openscenegraph.github.io/openscenegraph.io/about/license.html

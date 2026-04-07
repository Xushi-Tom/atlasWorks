# AtlasWorks HTTP服务 API接口文档

## 📋 概述

AtlasWorks HTTP服务提供地形切片和地图切片的RESTful API接口，支持智能多配置推荐和实时进度监控。

**服务地址**: `http://localhost:8000`  
**API版本**: v2.8  
**接口总数**: 30+个接口，涵盖14大功能模块  
**支持格式**: TIF, GeoTIFF等栅格数据  
**更新时间**: 2025-07-26

### 🏗️ 核心架构
- **Java后端**: Spring Boot + MyBatis Plus，提供高性能Web服务
- **Python服务**: Flask微服务，专门处理地理数据切片任务
- **地理引擎**: 集成GDAL、CTB、GeoTools等专业地理信息处理库
- **量化网格算法**: 基于半边数据结构的高精度地形网格生成
- **分布式处理**: 支持多进程并行处理，智能内存管理

### 📊 接口统计

| 功能模块 | 接口数量 | 说明 |
|----------|----------|------|
| **Python微服务接口** |  |  |
| 任务管理 | 5个 | 任务状态监控、停止、删除、清理 |
| 工作空间管理 | 4个 | 文件夹创建、删除、重命名、信息查询 |
| 数据源管理 | 3个 | 数据源浏览、详情获取、智能推荐 |
| 瓦片生成 | 3个 | 地形瓦片、索引瓦片、格式转换 |
| 地形处理 | 2个 | 地形瓦片解压、layer.json更新 |
| 透明瓦片管理 | 2个 | 扫描和删除包含透明/nodata值的瓦片 |
| 系统信息 | 2个 | 系统资源监控、容器更新 |
| 系统监控 | 1个 | 健康检查 |
| 配置管理 | 1个 | 智能配置推荐 |
| 分析工具 | 1个 | 缩放级别推荐 |
| API文档 | 1个 | 接口路由列表 |
| **Java后端接口** |  |  |
| Java地形切片 | 3个 | 文件上传地形切片、路径地形切片、AtlasWorks API |
| Java地图切片 | 4个 | 文件上传地图切片、路径地图切片、索引瓦片、透明瓦片管理 |
| 瓦片服务 | 4个 | TMS瓦片、XYZ瓦片、WMTS标准服务、RESTful瓦片 |
| 地形服务 | 2个 | 地形瓦片获取、layer.json获取 |
| 工作空间服务 | 6个 | 工作空间创建、删除、状态管理等 |
| **总计** | **44个** | **完整的地理信息处理生态系统** |

### 🆕 最新功能
- 🔥 **地形瓦片合并**: 自动合并多个地形文件夹到统一目录，智能处理layer.json和瓦片文件，支持硬链接优化
- 🔥 **透明瓦片管理**: 智能检测和清理包含透明/nodata值的瓦片，零容忍模式确保瓦片质量
- 🔥 **索引瓦片处理**: 基于空间索引的高性能瓦片生成，支持多进程并行处理
- 🔥 **智能瓦片合并**: 自动检测空间冲突，支持透明度混合和覆盖策略，解决边界重叠问题
- 🔥 **工作空间管理**: 提供完整的文件和文件夹管理API，包括创建、删除、重命名等操作
- 🔥 **工作空间统计**: 自动统计存储使用情况，按文件类型分类展示，支持最近修改记录
- 🛡️ **安全路径验证**: 防止目录遍历攻击，确保工作空间操作安全性
- ⭐ **分级处理策略**: 解决高级别地图切片卡死问题，0-6级一起处理，7级以上单独处理
- ⭐ **智能文件优化**: 预先优化TIF文件结构，重新分块和压缩，提升切片效率
- ⭐ **概览金字塔**: 自动创建多级概览，加速数据访问和渲染
- ⭐ **自适应内存管理**: 根据级别动态调整GDAL缓存和环境变量
- ✅ **地理范围筛选**: 支持按经纬度范围筛选TIF文件，支持多种格式和多个范围
- ✅ **任务停止控制**: 支持停止正在运行的切片任务，优雅终止进程
- ✅ **逐级目录浏览**: 支持数据源目录的多级路径导航
- ✅ **智能多配置推荐**: 自动生成高配、中配、低配三套完整方案
- ✅ **自动参数优化**: 根据文件大小智能推荐级别范围和硬件配置  
- ✅ **精确时间估算**: 基于推荐配置计算真实处理时间
- ✅ **实时进度监控**: 支持瓦片生成进度、处理速度、预计剩余时间
- ✅ **小驼峰参数格式**: 统一使用小驼峰命名的请求和响应参数
- ✅ **安全路径控制**: 防止目录遍历攻击，确保数据安全

### 🎯 核心优势
- **高效处理**: 分级处理策略彻底解决大文件高级别切片卡死问题
- **智能推荐**: 基于文件大小和系统资源自动推荐最佳配置
- **索引优化**: 支持基于空间索引的精确瓦片生成，大幅提升处理效率
- **空间智能**: 自动检测文件空间冲突，智能合并重叠区域
- **生产就绪**: 完整的任务管理、错误处理、安全控制机制

## 🚀 快速开始

### 容器部署
```bash
# 导入镜像
docker load -i atlasworks-latest.tar

# 启动服务（推荐配置）
docker run -d --name atlasworks-api --memory=16g --shm-size=4g --cpus=4 \
  -p 8000:8000 \
  -v /Users/xushi/TIF:/app/dataSource \
  -v /Users/xushi/tiles:/app/tiles \
  -v /Users/xushi/log:/app/log \
  atlasworks:latest python3 /app/app.py
```

### 健康检查
```bash
curl http://localhost:8000/api/health
```

## 📊 系统状态

### 健康检查

**GET** `/api/health`

检查服务运行状态。

#### 📝 接口逻辑
1. **状态检查**: 验证Flask应用是否正常运行
2. **时间戳生成**: 使用当前系统时间生成时间戳
3. **版本信息**: 返回固定的API版本信息
4. **JSON响应**: 封装健康状态信息并返回

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| status | string | 服务状态，固定值"healthy" |
| timestamp | string | 时间戳，格式：yyyy-MM-dd HH:mm:ss |
| version | string | API版本号 |

#### 响应示例
```json
{
  "status": "healthy",
  "timestamp": "2025-01-08 16:45:00",
  "version": "1.0.0"
}
```

### 系统信息

**GET** `/api/system/info`

获取系统资源使用情况。

#### 📝 接口逻辑
1. **CPU监控**: 使用psutil获取CPU使用率、核心数等信息
2. **内存分析**: 获取内存使用率、总量、可用量等
3. **磁盘统计**: 分析磁盘使用情况和剩余空间
4. **任务统计**: 统计当前活跃任务和历史任务数量
5. **格式化处理**: 将字节数转换为人类可读格式
6. **JSON封装**: 结构化返回系统信息

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| cpu.percent | number | CPU使用率百分比 (0-100) |
| cpu.count | number | 逻辑CPU核心数 |
| cpu.physicalCount | number | 物理CPU核心数 |
| memory.percent | number | 内存使用率百分比 (0-100) |
| memory.totalFormatted | string | 总内存容量，带单位 |
| memory.availableFormatted | string | 可用内存，带单位 |
| disk.percent | number | 磁盘使用率百分比 (0-100) |
| disk.totalFormatted | string | 磁盘总容量，带单位 |
| disk.freeFormatted | string | 剩余容量，带单位 |
| tasks.activeTasks | number | 当前活跃任务数量 |
| tasks.totalTasks | number | 历史任务总数 |

#### 响应示例
```json
{
  "cpu": {
    "percent": 25.5,
    "count": 10,
    "physicalCount": 5
  },
  "memory": {
    "percent": 45.2,
    "totalFormatted": "16.0 GB",
    "availableFormatted": "8.7 GB"
  },
  "disk": {
    "percent": 35.8,
    "totalFormatted": "500.0 GB",
    "freeFormatted": "321.0 GB"
  },
  "tasks": {
    "activeTasks": 2,
    "totalTasks": 15
  }
}
```

### 容器更新

**POST** `/api/container/update`

更新Docker容器系统信息。

#### 📝 接口逻辑
1. **时间同步**: 同步容器时间与宿主机时间
2. **配置刷新**: 重新加载系统配置文件
3. **缓存清理**: 清理系统状态缓存
4. **环境更新**: 更新环境变量和系统参数
5. **状态确认**: 验证更新操作是否成功
6. **结果返回**: 返回更新状态和时间戳

#### 请求参数
| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| updateType | string | 否 | 更新类型：'all', 'time', 'config', 'environment', 'system' (默认: 'all') |
| timezone | string | 否 | 时区设置，如 'Asia/Shanghai' |
| environment | object | 否 | 环境变量更新对象 |
| config | object | 否 | 配置更新对象 |

#### 请求示例
```json
{
  "updateType": "all",
  "timezone": "Asia/Shanghai",
  "environment": {
    "GDAL_CACHEMAX": "1024",
    "GDAL_HTTP_TIMEOUT": "60"
  },
  "config": {
    "maxWorkers": 8,
    "tileSize": 256
  }
}
```

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| timestamp | string | 更新时间戳 |
| updateType | string | 更新类型 |
| version | string | 系统版本 |
| results | object | 更新结果详情 |

#### 响应示例
```json
{
  "timestamp": "2025-07-16T16:45:00.123456",
  "updateType": "all",
  "version": "v2.72",
  "results": {
    "time": {
      "actions": ["使用ntpdate同步网络时间成功"],
      "before": {
        "localTime": "2025-07-16 16:44:55",
        "utcTime": "2025-07-16 08:44:55 UTC"
      },
      "after": {
        "localTime": "2025-07-16 16:45:00",
        "utcTime": "2025-07-16 08:45:00 UTC"
      }
    },
    "environment": {
      "actions": ["更新环境变量 GDAL_CACHEMAX"],
      "updated": {
        "GDAL_CACHEMAX": {
          "old": "512",
          "new": "1024"
        }
      }
    },
    "config": {
      "actions": ["更新配置 maxWorkers"],
      "updated": {
        "maxWorkers": {
          "old": 4,
          "new": 8
        }
      }
    }
  }
}
```

## 📁 数据源管理

### 浏览数据源目录

**GET** `/api/dataSources`  
**GET** `/api/dataSources/<path:subpath>`

逐级浏览数据源目录和文件，支持多级路径和地理范围筛选。

#### 📝 接口逻辑
1. **路径安全验证**: 检查路径是否存在目录遍历攻击，确保路径在允许范围内
2. **目录扫描**: 使用os.walk或os.listdir扫描指定目录
3. **文件过滤**: 筛选.tif、.tiff等地理数据文件
4. **文件信息获取**: 获取文件大小、修改时间、格式等基本信息
5. **地理范围解析**: 解析bounds查询参数，支持多种格式
6. **GDAL分析**: 使用GDAL解析TIF文件的地理边界信息
7. **地理筛选**: 根据边界参数筛选符合条件的文件
8. **结果排序**: 按文件名或修改时间排序
9. **JSON封装**: 返回结构化的目录和文件信息

#### 路径参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| subpath | string | 否 | 子目录路径，支持多级，如"folder1/folder2/folder3" |

#### 查询参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| bounds | string | 否 | 地理范围筛选，JSON格式，支持多种格式 |

#### 地理范围格式支持
- **单个范围数组**: `[west, south, east, north]`
- **多个范围数组**: `[[west1, south1, east1, north1], [west2, south2, east2, north2]]`
- **对象格式**: `[{"west": 116, "south": 39, "east": 117, "north": 40}]`

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| currentPath | string | 当前路径 |
| parentPath | string\|null | 父级路径，根目录时为null |
| directories | array | 子目录列表 |
| directories[].name | string | 目录名 |
| directories[].path | string | 相对路径 |
| directories[].itemCount | number | 目录内文件数量 |
| directories[].type | string | 固定值"directory" |
| datasources | array | 数据源文件列表 |
| datasources[].name | string | 文件名 |
| datasources[].path | string | 相对路径 |
| datasources[].fullPath | string | 完整文件路径 |
| datasources[].size | number | 文件大小（字节） |
| datasources[].sizeFormatted | string | 格式化的文件大小 |
| datasources[].format | string | 文件格式（如".tif"） |
| datasources[].type | string | 固定值"file" |
| datasources[].fileType | string | 文件类型："geotiff"或"image" |
| datasources[].modified | string | 最后修改时间 |
| totalDirectories | number | 子目录总数 |
| totalFiles | number | 文件总数 |
| filterInfo | object | 筛选信息（使用地理筛选时） |

#### 响应示例
```json
{
  "currentPath": "",
  "parentPath": null,
  "directories": [
    {
      "name": "satellite",
      "path": "satellite",
      "itemCount": 15,
      "type": "directory"
    }
  ],
  "datasources": [
    {
      "name": "taiwan.tif",
      "path": "taiwan.tif",
      "fullPath": "/app/dataSource/taiwan.tif",
      "size": 1139867648,
      "sizeFormatted": "1.06 GB",
      "format": ".tif",
      "type": "file",
      "fileType": "geotiff",
      "modified": "2024-06-30 16:45:00"
    }
  ],
  "totalDirectories": 1,
  "totalFiles": 1
}
```

### 获取数据源详情

**GET** `/api/dataSources/info/<filename>`

获取指定数据源的详细信息和智能多配置推荐。

#### 📝 接口逻辑
1. **文件安全验证**: 检查文件是否存在，验证路径安全性
2. **GDAL元数据解析**: 使用gdalinfo解析TIF文件的详细信息
3. **地理信息提取**: 提取坐标系、投影、地理边界等信息
4. **波段分析**: 分析波段数量、数据类型、颜色解释
5. **分辨率计算**: 计算像素分辨率和地面分辨率
6. **智能级别推荐**: 根据分辨率和文件大小计算推荐缩放级别
7. **配置生成**: 如果指定tileType，生成高中低三套配置方案
8. **性能预测**: 预测不同配置的处理时间和资源消耗
9. **JSON封装**: 返回完整的文件信息和推荐配置

#### 路径参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| filename | string | 是 | 数据源文件名 |

#### 查询参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| tileType | string | 否 | 切片类型："map"或"terrain"，提供时返回智能配置推荐 |

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| fileInfo | object | 文件基本信息 |
| fileInfo.filename | string | 文件名 |
| fileInfo.size | number | 文件大小（字节） |
| fileInfo.sizeFormatted | string | 格式化的文件大小 |
| fileInfo.path | string | 文件完整路径 |
| fileInfo.gdalinfo | object | GDAL文件信息详情 |
| suggestedZoom | object | 智能分级建议 |
| suggestedZoom.minZoom | number | 建议最小缩放级别 |
| suggestedZoom.maxZoom | number | 建议最大缩放级别 |
| suggestedZoom.strategy | string | 分级策略（"conservative"或"full"） |
| recommendations | object | 智能配置推荐（tileType提供时） |

#### 响应示例
```json
{
  "fileInfo": {
    "filename": "taiwan.tif",
    "size": 1139867648,
    "sizeFormatted": "1.06 GB",
    "path": "/app/dataSource/taiwan.tif",
    "gdalinfo": {
      "driver": "GTiff/GeoTIFF",
      "size": "18892, 15028",
      "coordinateSystem": "WGS 84",
      "bands": [
        "Band 1: Block=18892x1 Type=Byte, ColorInterp=Red",
        "Band 2: Block=18892x1 Type=Byte, ColorInterp=Green",
        "Band 3: Block=18892x1 Type=Byte, ColorInterp=Blue"
      ]
    }
  },
  "suggestedZoom": {
    "minZoom": 5,
    "maxZoom": 15,
    "strategy": "conservative"
  }
}
```

## 🗺️ 瓦片生成

### 创建地形瓦片

**POST** `/api/tile/terrain`

使用CTB（Cesium Terrain Builder）批量创建地形瓦片。

#### 📝 接口逻辑
1. **参数验证**: 验证输入参数的有效性，设置合理的默认值
2. **文件搜索**: 根据folderPaths和filePatterns查找匹配的TIF文件
3. **批量处理**: 支持多个文件的批量地形切片处理
4. **任务创建**: 生成唯一的任务ID，创建任务记录
5. **顺序处理**: 依次处理每个文件，避免资源冲突
6. **CTB命令构建**: 根据参数构建CTB命令行参数
7. **异步进程启动**: 启动异步进程执行地形切片
8. **进度监控**: 设置进度监控和状态更新机制
9. **后处理配置**: 配置自动解压和layer.json更新
10. **地形合并**: 当mergeTerrains=true时，自动合并多个地形文件夹到统一目录
11. **响应返回**: 返回任务信息和状态查询URL

#### 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| folderPaths | array | 是 | - | 搜索文件夹路径列表（相对于数据源目录） |
| filePatterns | array | 否 | ["*.tif", "*.tiff"] | 文件匹配模式列表，支持通配符和txt文件列表 |
| outputPath | array | 是 | - | 输出路径数组，如["terrain", "project", "v1"] |
| startZoom | number | 否 | 0 | 起始缩放级别（粗糙级别） |
| endZoom | number | 否 | 8 | 结束缩放级别（详细级别，最小为8） |
| maxTriangles | number | 否 | 6291456 | 最大三角形数量 |
| bounds | array | 否 | null | 地理边界，格式：[west, south, east, north] |
| compression | boolean | 否 | true | 是否启用压缩 |
| decompress | boolean | 否 | true | 是否自动解压输出文件 |
| threads | number | 否 | 4 | 线程数 |
| maxMemory | string | 否 | "8g" | 最大内存限制，支持格式：数字+单位（如"8m"、"16g"、"1024k"） |
| autoZoom | boolean | 否 | false | 是否自动计算缩放级别 |
| zoomStrategy | string | 否 | "conservative" | 缩放策略："conservative"或"aggressive" |
| mergeTerrains | boolean | 否 | false | **[NEW]** 是否在切片完成后自动合并成一个文件夹 |

#### 📁 参数格式说明
`folderPaths` 和 `filePatterns` 参数格式与索引瓦片接口相同：
- **folderPaths**: 相对于数据源目录的路径列表
- **filePatterns**: 支持通配符模式和txt文件列表，默认值为 `["*.tif", "*.tiff"]`

详细格式说明请参考上文索引瓦片接口的参数格式说明。

#### 请求示例

**示例1: 基本通配符模式**
```json
{
  "folderPaths": ["data/elevation", "data/dem"],
  "filePatterns": ["*.tif", "elevation_*.tif"],
  "outputPath": ["terrain", "project", "v1"],
  "startZoom": 0,
  "endZoom": 12,
  "maxTriangles": 8388608,
  "bounds": [119.31, 21.75, 124.56, 25.93],
  "compression": true,
  "decompress": true,
  "threads": 6,
  "maxMemory": "16m",
  "autoZoom": false,
  "zoomStrategy": "conservative",
  "mergeTerrains": false
}
```

**示例2: 使用txt文件列表**
```json
{
  "folderPaths": ["terrain/high_res", "terrain/backup"],
  "filePatterns": ["priority_dem.txt", "*.tiff"],
  "outputPath": ["terrain", "batch_v2"],
  "startZoom": 2,
  "endZoom": 14,
  "maxTriangles": 12582912,
  "bounds": null,
  "compression": false,
  "decompress": false,
  "threads": 8,
  "maxMemory": "32m",
  "autoZoom": true,
  "zoomStrategy": "aggressive",
  "mergeTerrains": false
}
```

**示例3: 地形合并模式 [NEW]**
```json
{
  "folderPaths": ["region1", "region2", "region3"],
  "filePatterns": ["*.tif"],
  "outputPath": ["terrain", "merged_areas"],
  "startZoom": 0,
  "endZoom": 12,
  "maxTriangles": 32768,
  "compression": true,
  "decompress": true,
  "mergeTerrains": true,
  "threads": 4,
  "maxMemory": "8m"
}
```

#### 🔥 地形合并功能说明

当设置 `mergeTerrains: true` 时，系统会在所有地形切片完成后自动执行合并操作：

1. **瓦片文件合并**: 按 z/x/y.terrain 结构合并所有地形瓦片
2. **layer.json 智能合并**: 自动合并所有 layer.json 文件的元数据
3. **边界计算**: 自动计算合并后的地理边界范围
4. **空间优化**: 使用硬链接节省磁盘空间，失败时自动降级为复制
5. **冲突处理**: 相同坐标的瓦片文件自动跳过，避免重复
6. **进度监控**: 在任务状态中显示合并进度和结果统计

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| success | boolean | 任务启动是否成功 |
| taskId | string | 任务ID，用于查询任务状态 |
| message | string | 任务启动消息 |
| statusUrl | string | 任务状态查询URL |
| parameters | object | 任务参数信息 |
| parameters.totalFiles | number | 总文件数量 |
| parameters.outputPath | array | 输出路径数组 |
| parameters.zoomRange | string | 缩放级别范围 |
| parameters.threads | number | 线程数 |
| parameters.maxMemory | string | 最大内存限制 |
| parameters.type | string | 任务类型，固定值"terrain" |

#### 响应示例
```json
{
  "success": true,
  "taskId": "terrain1751266765",
  "message": "地形切片任务已启动，将处理 3 个文件",
  "statusUrl": "/api/tasks/terrain1751266765",
  "parameters": {
    "totalFiles": 3,
    "outputPath": ["terrain", "project", "v1"],
    "zoomRange": "0-12",
    "threads": 6,
    "maxMemory": "16m",
    "type": "terrain"
  }
}
```

### 创建索引瓦片

**POST** `/api/tile/indexedTiles`

基于空间索引的高性能瓦片生成，支持多进程并行处理。

#### 📝 接口逻辑
1. **文件模式解析**: 解析folderPaths和filePatterns参数
2. **文件匹配**: 根据通配符模式或txt文件列表匹配TIF文件
3. **增量更新检查**: 如果启用增量更新，检查现有瓦片是否可复用
4. **空间索引构建**: 生成SHP分幅矢量索引文件
5. **瓦片网格计算**: 计算指定缩放级别的瓦片网格
6. **空间关系分析**: 分析每个瓦片与TIF文件的空间关系
7. **元数据记录**: 记录瓦片的位置、关联文件、像素统计等信息
8. **多进程切片**: 使用多进程并行精确切割每个瓦片
9. **质量控制**: 检测和处理透明瓦片、nodata值等
10. **透明瓦片处理**: 根据skipNodataTiles参数决定是否跳过透明瓦片
11. **清理操作**: 自动清理临时文件和索引文件

#### 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| folderPaths | array | 是 | - | 搜索文件夹路径列表（相对于数据源目录） |
| filePatterns | array | 否 | ["*.tif", "*.tiff"] | 文件匹配模式列表，支持通配符和txt文件列表 |
| outputPath | array | 是 | - | 输出路径数组 |
| minZoom | number | 否 | 0 | 最小缩放级别 |
| maxZoom | number | 否 | 12 | 最大缩放级别 |
| processes | number | 否 | 4 | 进程数 |
| maxMemory | string | 否 | "8g" | 最大内存限制，支持格式：数字+单位（如"8g"、"512m"、"1024k"） |
| tileSize | number | 否 | 256 | 瓦片大小 |
| generateShpIndex | boolean | 否 | true | 是否生成SHP索引 |
| resampling | string | 否 | "near" | 重采样方法：near、bilinear、cubic、cubicspline、lanczos、average、mode |
| enableIncrementalUpdate | boolean | 否 | false | 是否启用增量更新（复用现有瓦片） |
| skipNodataTiles | boolean | 否 | false | 是否跳过透明瓦片的生成 |

#### 📁 `folderPaths` 参数格式说明
- **路径格式**: 相对于数据源目录的路径
- **多级目录**: 支持多级目录，如 `["data/images", "data/elevation"]`
- **根目录**: 使用空字符串或空数组表示根目录：`[""]` 或 `[]`
- **示例**:
  ```json
  // 搜索多个文件夹
  "folderPaths": ["data/images", "data/elevation", "backup/files"]
  
  // 搜索根目录
  "folderPaths": [""]
  
  // 搜索子目录
  "folderPaths": ["project/dem", "project/ortho"]
  ```

#### 📋 `filePatterns` 参数格式说明
支持两种格式：**通配符模式** 和 **txt文件列表**

**1. 通配符模式（推荐）**
- **基本通配符**: `*`（任意字符）、`?`（单个字符）
- **支持扩展名**: `.tif`、`.tiff`
- **示例**:
  ```json
  // 基本通配符
  "filePatterns": ["*.tif", "*.tiff"]
  
  // 前缀匹配
  "filePatterns": ["elevation_*.tif", "dem_*.tiff"]
  
  // 复杂匹配
  "filePatterns": ["*_dem.tif", "ortho_2024_*.tif"]
  ```

**2. txt文件列表**
- **文件格式**: 以 `.txt` 结尾的文件名
- **文件位置**: 位于数据源目录下
- **文件内容**: 每行一个文件名，支持相对路径和绝对路径
- **注释支持**: 以 `#` 开头的行为注释，空行会被忽略
- **示例**:
  ```json
  // 使用txt文件列表
  "filePatterns": ["file_list.txt", "priority_files.txt"]
  ```
  
  **file_list.txt 文件内容示例**:
  ```
  # 这是注释行
  taiwan.tif
  elevation/dem_01.tif
  data/ortho/image_2024.tiff
  /absolute/path/to/file.tif
  
  # 另一个文件
  backup/archive.tif
  ```

**3. 混合使用**
```json
// 同时使用通配符和txt文件
"filePatterns": ["*.tif", "priority_files.txt", "backup_*.tiff"]
```

#### 🎯 `resampling` 重采样方法说明
支持以下GDAL重采样方法：
- **near**: 最近邻插值（默认，速度最快，适用于分类数据）
- **bilinear**: 双线性插值（平滑效果，适用于连续数据）
- **cubic**: 三次卷积插值（质量更高，处理速度较慢）
- **cubicspline**: 三次样条插值（高质量，边缘清晰）
- **lanczos**: Lanczos插值（高质量，适用于缩放）
- **average**: 平均值（适用于降采样）
- **mode**: 众数（适用于分类数据的降采样）

#### 💾 `maxMemory` 内存参数格式说明
支持以下格式：
- **格式**: 数字 + 单位后缀
- **支持单位**: 
  - `k` 或 `K`: 千字节（KB）
  - `m` 或 `M`: 兆字节（MB）
  - `g` 或 `G`: 吉字节（GB）
- **示例**: 
  - `"512m"`: 512MB
  - `"8g"`: 8GB
  - `"1024k"`: 1024KB

#### 请求示例

**示例1: 基本通配符模式**
```json
{
  "folderPaths": ["data/images", "data/elevation"],
  "filePatterns": ["*.tif", "elevation_*.tif"],
  "outputPath": ["indexed", "project_v1"],
  "minZoom": 0,
  "maxZoom": 14,
  "processes": 8,
  "maxMemory": "16g",
  "tileSize": 256,
  "generateShpIndex": true,
  "resampling": "bilinear",
  "enableIncrementalUpdate": false,
  "skipNodataTiles": true
}
```

**示例2: 使用txt文件列表**
```json
{
  "folderPaths": ["project/dem", "project/ortho"],
  "filePatterns": ["high_priority.txt", "*.tiff"],
  "outputPath": ["indexed", "batch_processing"],
  "minZoom": 2,
  "maxZoom": 16,
  "processes": 12,
  "maxMemory": "32g",
  "tileSize": 512,
  "generateShpIndex": true,
  "resampling": "cubic",
  "enableIncrementalUpdate": true,
  "skipNodataTiles": false
}
```

**示例3: 搜索根目录**
```json
{
  "folderPaths": [""],
  "filePatterns": ["taiwan_*.tif", "dem_2024_*.tiff"],
  "outputPath": ["root_tiles"],
  "minZoom": 0,
  "maxZoom": 12,
  "processes": 4,
  "maxMemory": "8g",
  "tileSize": 256,
  "generateShpIndex": false,
  "resampling": "near",
  "enableIncrementalUpdate": false,
  "skipNodataTiles": true
}
```

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| taskId | string | 任务ID |
| message | string | 任务启动消息 |
| statusUrl | string | 任务状态查询URL |
| method | string | 处理方法，固定值"瓦片索引精确切片" |
| indexInfo | object | 索引信息 |
| indexInfo.totalFiles | number | 总文件数量 |
| indexInfo.zoomLevels | string | 缩放级别范围 |
| indexInfo.tileSize | number | 瓦片大小 |
| indexInfo.generateShpIndex | boolean | 是否生成SHP索引 |
| indexInfo.enableIncrementalUpdate | boolean | 是否启用增量更新 |
| indexInfo.skipNodataTiles | boolean | 是否跳过透明瓦片 |
| processingInfo | object | 处理配置信息 |
| processingInfo.processes | number | 进程数 |
| processingInfo.maxMemory | string | 最大内存限制 |
| processingInfo.resampling | string | 重采样方法 |
| processingInfo.outputPathArray | array | 输出路径数组 |

#### 响应示例
```json
{
  "taskId": "indexedTiles1751266792",
  "message": "瓦片索引切片任务已启动，将处理 3 个文件",
  "statusUrl": "/api/tasks/indexedTiles1751266792",
  "method": "瓦片索引精确切片",
  "indexInfo": {
    "totalFiles": 3,
    "zoomLevels": "0-14",
    "tileSize": 256,
    "generateShpIndex": true,
    "enableIncrementalUpdate": false,
    "skipNodataTiles": true
  },
  "processingInfo": {
    "processes": 8,
    "maxMemory": "16g",
    "resampling": "bilinear",
    "outputPathArray": ["indexed", "project_v1"]
  }
}
```

### 瓦片格式转换

**POST** `/api/tile/convert`

支持瓦片格式转换：z/x_y.png（扁平格式）↔ z/x/y.png（嵌套格式）

#### 📝 接口逻辑
1. **格式自动识别**: 扫描目录结构，自动识别当前瓦片格式
2. **目录结构分析**: 分析所有级别的目录和文件分布
3. **转换策略制定**: 根据源格式和目标格式制定转换策略
4. **并行处理**: 使用多进程并行处理瓦片文件转换
5. **目录重建**: 创建新格式的目录结构
6. **文件移动/复制**: 根据keepOriginal参数处理原文件
7. **完整性验证**: 验证转换后的文件完整性
8. **清理操作**: 清理临时文件和空目录

#### 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| sourcePath | string | 是 | - | 源瓦片目录路径（相对于tiles目录） |
| targetPath | string | 是 | - | 目标瓦片目录路径（相对于tiles目录） |
| sourceFormat | string | 是 | - | 源格式："flat"（z/x_y.png）或"nested"（z/x/y.png） |
| targetFormat | string | 是 | - | 目标格式："flat"（z/x_y.png）或"nested"（z/x/y.png） |
| overwrite | boolean | 否 | false | 是否覆盖已存在的目标文件 |

#### 请求示例
```json
{
  "sourcePath": "maps/project_v1",
  "targetPath": "maps/project_v1_flat",
  "sourceFormat": "nested",
  "targetFormat": "flat",
  "overwrite": false
}
```

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| taskId | string | 任务ID |
| message | string | 任务启动消息 |
| statusUrl | string | 任务状态查询URL |
| conversionInfo | object | 转换信息 |
| conversionInfo.sourceFormat | string | 源格式 |
| conversionInfo.targetFormat | string | 目标格式 |
| conversionInfo.totalFiles | number | 总文件数量 |

#### 响应示例
```json
{
  "taskId": "convert_1751266800",
  "message": "瓦片格式转换任务已启动",
  "statusUrl": "/api/tasks/convert_1751266800",
  "conversionInfo": {
    "sourceFormat": "nested",
    "targetFormat": "flat",
    "totalFiles": 1024
  }
}
```

## 🔧 分析工具

### 缩放级别推荐

**POST** `/api/analyze/zoomLevels`

根据TIF文件分辨率分析，推荐最佳缩放级别范围。

#### 📝 接口逻辑
1. **文件验证**: 检查TIF文件是否存在和可访问
2. **分辨率解析**: 使用GDAL解析文件的像素分辨率
3. **地理范围计算**: 计算文件的地理覆盖范围
4. **Web墨卡托转换**: 将地理坐标转换为Web墨卡托投影
5. **级别算法**: 根据分辨率和覆盖范围计算最佳级别
6. **策略应用**: 应用保守或激进的推荐策略
7. **质量评估**: 评估不同级别的瓦片质量
8. **建议生成**: 生成详细的级别推荐和使用建议

#### 请求参数
支持两种模式：**单文件模式**和**批量模式**

**单文件模式（推荐）**：
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| sourceFile | string | 是 | - | 源文件名（相对于数据源目录） |

**批量模式**：
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| folderPaths | array | 是 | - | 搜索文件夹路径列表（相对于数据源目录） |
| filePatterns | array | 否 | ["*.tif", "*.tiff"] | 文件匹配模式列表，支持通配符和txt文件列表 |

#### 请求示例

**示例1: 单文件模式**
```json
{
  "sourceFile": "taiwan.tif"
}
```

**示例2: 批量模式（分析第一个文件）**
```json
{
  "folderPaths": ["data/elevation"],
  "filePatterns": ["*.tif", "dem_*.tiff"]
}
```

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| recommendedZoom | object | 推荐级别 |
| recommendedZoom.minZoom | number | 推荐最小级别 |
| recommendedZoom.maxZoom | number | 推荐最大级别 |
| recommendedZoom.strategy | string | 使用的策略 |
| analysis | object | 分析结果 |
| analysis.resolution | number | 像素分辨率 |
| analysis.fileSize | number | 文件大小 |
| analysis.dimensions | object | 图像尺寸 |

#### 响应示例
```json
{
  "recommendedZoom": {
    "minZoom": 5,
    "maxZoom": 15,
    "strategy": "conservative"
  },
  "analysis": {
    "resolution": 0.0001,
    "fileSize": 1139867648,
    "dimensions": {
      "width": 18892,
      "height": 15028
    }
  }
}
```

## 📈 任务管理

### 查询任务状态

**GET** `/api/tasks/<taskId>`

查询指定任务的详细状态。

#### 📝 接口逻辑
1. **任务查找**: 根据taskId在全局任务池中查找任务记录
2. **状态实时更新**: 检查任务进程状态，更新任务信息
3. **进度计算**: 解析日志文件，计算瓦片生成进度
4. **速度统计**: 计算瓦片生成速度（瓦片/秒）
5. **时间预估**: 根据当前速度预估剩余处理时间
6. **错误检测**: 检查任务是否出现错误或异常
7. **结果处理**: 如果任务完成，处理最终结果
8. **JSON封装**: 返回完整的任务状态信息

#### 路径参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| taskId | string | 是 | 任务ID |

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| status | string | 任务状态："running"/"completed"/"failed"/"stopped" |
| progress | number | 进度百分比 (0-100) |
| message | string | 任务状态消息 |
| startTime | string | 任务开始时间 |
| endTime | string | 任务结束时间（如果已完成） |
| currentStage | string | 当前所处的阶段（如"初始化"/"文件处理"/"任务完成"） |
| processLog | array | 过程记录列表，详细记录任务各个阶段的执行情况 |
| processLog[].stage | string | 阶段名称 |
| processLog[].status | string | 阶段状态："completed"/"failed"/"running" |
| processLog[].message | string | 阶段描述信息 |
| processLog[].timestamp | string | 阶段完成时间(ISO格式) |
| processLog[].progress | number | 阶段完成时的进度百分比 |
| processLog[].fileInfo | object | 文件相关信息（如果有） |
| progressDetails | object | 详细进度信息 |
| progressDetails.currentTiles | number | 当前已生成瓦片数 |
| progressDetails.estimatedTotal | number | 预计总瓦片数 |
| progressDetails.tilesPerSecond | number | 瓦片生成速度 |
| progressDetails.elapsedTime | number | 已用时间（秒） |
| progressDetails.estimatedRemainingTime | number | 预计剩余时间（秒） |

#### 响应示例
```json
{
  "status": "running",
  "progress": 45,
  "message": "正在处理文件 2/3: terrain_data.tif",
  "startTime": "2024-06-30 16:45:00",
  "currentStage": "文件处理",
  "processLog": [
    {
      "stage": "初始化",
      "status": "completed",
      "message": "任务初始化完成，准备处理3个文件",
      "timestamp": "2024-06-30T16:45:00.123Z",
      "progress": 0
    },
    {
      "stage": "文件处理",
      "status": "completed",
      "message": "文件 terrain_base.tif 处理成功，生成了 256 个地形文件",
      "timestamp": "2024-06-30T16:45:15.456Z",
      "progress": 33,
      "fileInfo": {
        "filename": "terrain_base.tif",
        "outputPath": "terrain/project/v1/base",
        "terrainFiles": 256
      }
    },
    {
      "stage": "文件处理",
      "status": "running",
      "message": "正在处理文件 terrain_data.tif",
      "timestamp": "2024-06-30T16:45:16.789Z",
      "progress": 45
    }
  ],
  "progressDetails": {
    "currentTiles": 630,
    "estimatedTotal": 1398,
    "tilesPerSecond": 52.5,
    "elapsedTime": 12,
    "estimatedRemainingTime": 15
  }
}
```

### 查询所有任务

**GET** `/api/tasks`

获取所有任务的状态列表。

#### 📝 接口逻辑
1. **任务池遍历**: 遍历全局任务池中的所有任务记录
2. **状态汇总**: 收集每个任务的基本状态信息
3. **实时更新**: 更新所有任务的最新状态
4. **排序处理**: 按创建时间倒序排列任务
5. **分页支持**: 支持分页返回大量任务数据
6. **统计计算**: 计算各种状态任务的数量统计
7. **过滤功能**: 支持按状态、类型等过滤任务
8. **JSON封装**: 返回任务列表和统计信息

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| tasks | array | 任务列表 |
| tasks[].taskId | string | 任务ID |
| tasks[].status | string | 任务状态 |
| tasks[].progress | number | 进度百分比 |
| tasks[].message | string | 状态消息 |
| tasks[].startTime | string | 开始时间 |
| tasks[].endTime | string | 结束时间（如果已完成） |
| count | number | 任务总数 |

#### 响应示例
```json
{
  "tasks": [
    {
      "taskId": "terrain_1751266765",
      "status": "completed",
      "progress": 100,
      "message": "地形瓦片创建完成",
      "startTime": "2024-06-30 16:45:00",
      "endTime": "2024-06-30 16:48:30"
    },
    {
      "taskId": "indexedTiles_1751266792",
      "status": "running",
      "progress": 32,
      "message": "正在创建索引瓦片...",
      "startTime": "2024-06-30 16:50:00"
    }
  ],
  "count": 2
}
```

### 停止任务

**POST** `/api/tasks/<taskId>/stop`

停止正在运行的任务。

#### 📝 接口逻辑
1. **任务验证**: 验证任务ID是否存在且处于可停止状态
2. **进程查找**: 查找任务对应的系统进程ID
3. **优雅停止**: 发送SIGTERM信号请求进程优雅终止
4. **等待确认**: 等待进程响应停止信号
5. **强制终止**: 如果优雅停止失败，发送SIGKILL信号
6. **状态更新**: 更新任务状态为"stopped"
7. **清理操作**: 清理临时文件和资源
8. **结果返回**: 返回停止操作的结果

#### 路径参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| taskId | string | 是 | 要停止的任务ID |

#### 请求示例
```json
{}
```

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| message | string | 操作结果消息 |
| taskId | string | 任务ID |
| status | string | 任务状态，固定值"stopped" |
| stoppedAt | string | 停止时间 |

#### 响应示例
```json
{
  "message": "任务已停止",
  "taskId": "terrain_1751266765",
  "status": "stopped",
  "stoppedAt": "2025-01-08 16:45:00"
}
```

### 删除任务

**DELETE** `/api/tasks/<taskId>`

删除指定的任务记录。

#### 📝 接口逻辑
1. **任务验证**: 验证任务ID是否存在
2. **状态检查**: 确保任务不在运行状态
3. **权限检查**: 验证是否有删除权限
4. **数据清理**: 删除任务记录和相关数据
5. **文件清理**: 清理任务相关的临时文件
6. **引用清理**: 从任务池中移除任务引用
7. **日志处理**: 处理任务日志文件
8. **结果返回**: 返回删除确认信息

#### 路径参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| taskId | string | 是 | 要删除的任务ID |

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| message | string | 操作结果消息 |
| taskId | string | 任务ID |
| deletedTask | object | 被删除的任务信息 |

#### 响应示例
```json
{
  "message": "任务删除成功",
  "taskId": "terrain_1751266765",
  "deletedTask": {
    "status": "completed",
    "progress": 100,
    "message": "地形瓦片创建完成",
    "startTime": "2024-06-30 16:45:00",
    "endTime": "2024-06-30 16:48:30"
  }
}
```

### 任务清理

**POST** `/api/tasks/cleanup`

批量清理任务记录。

#### 📝 接口逻辑
1. **策略解析**: 解析清理策略和参数
2. **任务筛选**: 根据策略筛选要清理的任务
3. **安全检查**: 确保不删除正在运行的任务
4. **批量删除**: 批量删除符合条件的任务记录
5. **文件清理**: 清理相关的临时文件和日志
6. **统计计算**: 计算清理数量和剩余任务数
7. **更新索引**: 更新任务索引和缓存
8. **结果报告**: 生成清理操作报告

#### 请求参数
此接口不需要任何参数。固定按数量清理，保留最新的100个任务。

#### 请求示例
```json
{}
```

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| success | boolean | 操作是否成功 |
| message | string | 操作结果消息 |
| remainingTasks | number | 剩余任务数量 |

#### 响应示例
```json
{
  "success": true,
  "message": "任务清理完成",
  "remainingTasks": 85
}
```

## 🔧 配置管理

### 智能配置推荐

**POST** `/api/config/recommend`

根据文件特征和系统资源推荐最优切片配置。

#### 📝 接口逻辑
1. **文件分析**: 分析TIF文件的大小、分辨率、地理范围
2. **系统评估**: 评估当前系统的CPU、内存、磁盘资源
3. **负载评估**: 评估系统当前负载和可用资源
4. **策略匹配**: 根据文件特征匹配最适合的处理策略
5. **配置生成**: 生成高、中、低三套配置方案
6. **性能预测**: 预测不同配置的处理时间和资源消耗
7. **风险评估**: 评估不同配置的稳定性和失败风险
8. **推荐输出**: 输出最优配置推荐和使用建议

#### 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| sourceFile | string | 是 | - | 源文件名（相对于数据源目录） |
| tileType | string | 否 | "map" | 切片类型："map"或"terrain" |
| minZoom | number | 否 | - | 最小缩放级别（可选，用于定制推荐） |
| maxZoom | number | 否 | - | 最大缩放级别（可选，用于定制推荐） |

#### 请求示例

**示例1: 基本推荐**
```json
{
  "sourceFile": "taiwan.tif",
  "tileType": "map"
}
```

**示例2: 自定义缩放级别**
```json
{
  "sourceFile": "elevation.tif",
  "tileType": "terrain",
  "minZoom": 0,
  "maxZoom": 12
}
```

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| success | boolean | 请求是否成功 |
| fileSize | number | 文件大小（GB） |
| systemInfo | object | 系统信息 |
| systemInfo.cpuCount | number | CPU核心数 |
| systemInfo.memoryTotalGb | number | 系统总内存（GB） |
| recommendations | object | 配置推荐 |
| recommendations.maxZoom | number | 推荐的最大缩放级别 |
| recommendations.minZoom | number | 推荐的最小缩放级别 |
| recommendations.tileFormat | string | 推荐的瓦片格式 |
| recommendations.quality | number | 推荐的质量设置 |
| recommendations.processes | number | 推荐的并行进程数 |
| recommendations.maxMemory | string | 推荐的最大内存限制（仅地形瓦片，单位：m） |

#### 响应示例

**地图瓦片推荐**
```json
{
  "success": true,
  "fileSize": 1.06,
  "systemInfo": {
    "cpuCount": 10,
    "memoryTotalGb": 16
  },
  "recommendations": {
    "maxZoom": 16,
    "minZoom": 0,
    "tileFormat": "webp",
    "quality": 80,
    "processes": 6
  }
}
```

**地形瓦片推荐**
```json
{
  "success": true,
  "fileSize": 0.52,
  "systemInfo": {
    "cpuCount": 8,
    "memoryTotalGb": 12
  },
  "recommendations": {
    "maxZoom": 15,
    "minZoom": 0,
    "tileFormat": "png",
    "quality": 100,
    "processes": 4,
    "maxMemory": "8g"
  }
}
```

## 💼 工作空间管理

### 创建工作空间文件夹

**POST** `/api/workspace/createFolder`

在工作空间中创建新的文件夹。

#### 📝 接口逻辑
1. **参数验证**: 验证folderPath参数是否提供且格式正确
2. **路径安全验证**: 使用validateWorkspacePath验证路径安全性
3. **路径映射**: 将相对路径映射到工作空间的完整路径
4. **存在性检查**: 检查目标文件夹是否已存在
5. **权限验证**: 验证是否有创建文件夹的权限
6. **递归创建**: 使用os.makedirs递归创建文件夹及其父目录
7. **创建确认**: 验证文件夹创建成功
8. **响应返回**: 返回创建结果和文件夹信息

#### 请求参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| folderPath | string | 是 | 要创建的文件夹路径（相对于工作空间根目录） |

#### 请求示例
```json
{
  "folderPath": "new-project/maps"
}
```

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| success | boolean | 操作是否成功 |
| message | string | 操作结果消息 |
| folderPath | string | 创建的文件夹路径 |

#### 响应示例
```json
{
  "success": true,
  "message": "文件夹创建成功",
  "folderPath": "new-project/maps"
}
```

### 删除工作空间文件夹

**DELETE** `/api/workspace/folder/<path:folderPath>`

删除指定的文件夹及其所有内容。

#### 📝 接口逻辑
1. **路径验证**: 验证folderPath的安全性和有效性
2. **路径映射**: 将相对路径映射到完整的文件系统路径
3. **存在性检查**: 检查文件夹是否存在且确实是目录
4. **权限验证**: 验证是否有删除权限
5. **安全检查**: 确保不删除重要的系统目录
6. **递归删除**: 使用shutil.rmtree递归删除文件夹
7. **删除确认**: 验证删除操作成功
8. **响应返回**: 返回删除结果信息

#### 路径参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| folderPath | string | 是 | 要删除的文件夹路径 |

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| success | boolean | 操作是否成功 |
| message | string | 操作结果消息 |
| folderPath | string | 被删除的文件夹路径 |

#### 响应示例
```json
{
  "success": true,
  "message": "文件夹删除成功",
  "folderPath": "old-project"
}
```

### 重命名工作空间文件夹

**PUT** `/api/workspace/folder/<path:folderPath>/rename`

重命名指定的文件夹。

#### 📝 接口逻辑
1. **参数验证**: 验证newName参数是否提供且合法
2. **路径验证**: 验证原文件夹路径的安全性
3. **存在性检查**: 检查源文件夹是否存在
4. **名称检查**: 验证新名称的合法性（不包含非法字符）
5. **目标路径构建**: 构建新的完整路径
6. **冲突检测**: 检查目标路径是否已存在
7. **原子重命名**: 使用os.rename执行原子性重命名
8. **路径转换**: 将绝对路径转换为相对路径返回

#### 路径参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| folderPath | string | 是 | 要重命名的文件夹路径 |

#### 请求参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| newName | string | 是 | 新的文件夹名称 |

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| success | boolean | 操作是否成功 |
| message | string | 操作结果消息 |
| oldPath | string | 原路径 |
| newPath | string | 新路径 |

#### 响应示例
```json
{
  "success": true,
  "message": "文件夹重命名成功",
  "oldPath": "old-project",
  "newPath": "updated-project"
}
```

### 获取工作空间信息

**GET** `/api/workspace/info`

获取工作空间的详细统计信息。

#### 📝 接口逻辑
1. **目录遍历**: 使用os.walk递归遍历工作空间所有文件和目录
2. **大小统计**: 计算每个文件的大小，累计总大小
3. **数量统计**: 统计文件总数和目录总数
4. **类型分析**: 按文件扩展名分类统计
5. **异常处理**: 处理文件访问异常，跳过无法访问的文件
6. **格式化处理**: 使用formatFileSize将字节数转换为可读格式
7. **时间记录**: 记录统计信息的更新时间
8. **JSON封装**: 返回结构化的工作空间信息

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| success | boolean | 操作是否成功 |
| workspaceInfo | object | 工作空间信息 |
| workspaceInfo.basePath | string | 基础路径 |
| workspaceInfo.totalSize | number | 总大小（字节） |
| workspaceInfo.totalSizeFormatted | string | 格式化总大小 |
| workspaceInfo.totalFiles | number | 总文件数 |
| workspaceInfo.totalDirectories | number | 总目录数 |
| workspaceInfo.lastUpdated | string | 最后更新时间 |

#### 响应示例
```json
{
  "success": true,
  "workspaceInfo": {
    "basePath": "/app/tiles",
    "totalSize": 50438742016,
    "totalSizeFormatted": "46.98 GB",
    "totalFiles": 1247,
    "totalDirectories": 23,
    "lastUpdated": "2025-01-08T15:45:00"
  }
}
```

## 🧹 透明瓦片管理

### 扫描透明瓦片

**POST** `/api/tiles/nodata/scan`

扫描指定目录中包含透明（nodata）值的PNG瓦片。

#### 📝 接口逻辑
1. **路径验证**: 验证瓦片目录路径的有效性和安全性
2. **递归扫描**: 递归扫描指定目录下的所有PNG文件
3. **图像分析**: 使用PIL或OpenCV分析PNG文件的Alpha通道
4. **透明度检测**: 检测像素的透明度值，识别透明像素
5. **阈值判断**: 根据透明度阈值判断瓦片是否为透明瓦片
6. **统计计算**: 统计各级别的透明瓦片数量和比例
7. **结果记录**: 记录透明瓦片的文件路径和详细信息
8. **报告生成**: 生成详细的扫描报告和统计数据

#### 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| tilesPath | string | 是 | - | 瓦片目录路径（相对于tiles目录） |
| includeDetails | boolean | 否 | false | 是否返回详细文件列表 |

#### 请求示例
```json
{
  "tilesPath": "project/taiwan/v1",
  "includeDetails": true
}
```

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| success | boolean | 扫描是否成功 |
| summary | object | 扫描摘要信息 |
| summary.totalChecked | number | 检查的瓦片总数 |
| summary.nodataTiles | number | 包含透明值的瓦片数 |
| summary.validTiles | number | 有效瓦片数 |
| summary.errors | number | 检查错误数 |
| summary.nodataPercentage | number | 透明瓦片百分比 |
| zoomLevelStats | object | 按缩放级别统计 |
| nodataFiles | array | 透明瓦片文件列表（includeDetails=true时） |
| message | string | 扫描结果消息 |

#### 响应示例
```json
{
  "success": true,
  "summary": {
    "totalChecked": 2048,
    "nodataTiles": 156,
    "validTiles": 1892,
    "errors": 0,
    "nodataPercentage": 7.6
  },
  "zoomLevelStats": {
    "0": {"total": 1, "nodata": 0},
    "1": {"total": 4, "nodata": 0},
    "2": {"total": 16, "nodata": 2},
    "3": {"total": 64, "nodata": 8},
    "4": {"total": 256, "nodata": 24},
    "5": {"total": 1024, "nodata": 67},
    "6": {"total": 683, "nodata": 55}
  },
  "nodataFiles": [
    "2/1_2.png",
    "2/2_1.png",
    "3/5_6.png"
  ],
  "message": "扫描完成！检查了2048个瓦片，发现156个透明瓦片 (7.6%)"
}
```

### 删除透明瓦片

**POST** `/api/tiles/nodata/delete`

删除包含透明（nodata）值的PNG瓦片。

#### 📝 接口逻辑
1. **路径验证**: 验证瓦片目录路径的有效性
2. **扫描分析**: 重新扫描或引用之前的扫描结果
3. **文件验证**: 验证要删除的每个文件是否存在
4. **批量删除**: 批量删除识别出的透明瓦片文件
5. **目录检查**: 检查删除后的空目录
6. **空目录清理**: 删除完全空的目录结构
7. **统计计算**: 统计删除的文件数量和释放的空间
8. **结果报告**: 生成删除操作的详细报告

#### 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| tilesPath | string | 是 | - | 瓦片目录路径（相对于tiles目录） |
| includeDetails | boolean | 否 | true | 是否返回删除文件列表 |

#### 请求示例
```json
{
  "tilesPath": "project/taiwan/v1",
  "includeDetails": true
}
```

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| success | boolean | 删除是否成功 |
| summary | object | 删除摘要信息 |
| summary.totalChecked | number | 检查的瓦片总数 |
| summary.deletedTiles | number | 删除的瓦片数 |
| summary.cleanedDirectories | number | 清理的目录数 |
| summary.errors | number | 删除错误数 |
| deletedFiles | array | 删除的文件列表（includeDetails=true时） |
| message | string | 删除结果消息 |

#### 响应示例
```json
{
  "success": true,
  "summary": {
    "totalChecked": 2048,
    "deletedTiles": 156,
    "cleanedDirectories": 23,
    "errors": 0
  },
  "deletedFiles": [
    "2/1_2.png",
    "2/2_1.png",
    "3/5_6.png"
  ],
  "message": "删除完成！检查了2048个瓦片，删除了156个透明瓦片，清理了23个目录"
}
```

## 🏔️ 地形处理

### 更新Layer.json

**POST** `/api/terrain/layer`

更新地形瓦片的layer.json元数据文件。

#### 📝 接口逻辑
1. **路径验证**: 验证地形目录路径的有效性
2. **目录扫描**: 扫描地形目录中的所有.terrain文件
3. **级别分析**: 分析现有瓦片的级别分布和结构
4. **瓦片统计**: 统计每个级别的瓦片数量和覆盖范围
5. **边界计算**: 计算所有瓦片的地理边界范围
6. **JSON生成**: 生成符合Cesium标准的layer.json文件
7. **文件写入**: 将layer.json写入地形目录
8. **验证确认**: 验证生成的文件格式正确性

#### 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| terrainPath | array | 是 | - | 地形目录路径数组，如["terrain", "taiwan", "v1"] |
| bounds | array | 否 | - | 自定义地理边界，格式：[west, south, east, north] |
| sourceFile | string | 否 | "taiwan.tif" | 源文件名提示（用于补充信息） |

#### 请求示例
```json
{
  "terrainPath": ["terrain", "taiwan", "v1"],
  "bounds": [-180.0, -90.0, 180.0, 90.0],
  "sourceFile": "taiwan.tif"
}
```

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| success | boolean | 操作是否成功 |
| message | string | 操作结果消息 |
| layerPath | string | layer.json文件路径 |
| terrainInfo | object | 地形信息 |
| terrainInfo.levels | array | 级别信息 |
| terrainInfo.bounds | object | 地理边界 |

#### 响应示例
```json
{
  "success": true,
  "message": "layer.json更新成功",
  "layerPath": "terrain/taiwan/v1/layer.json",
  "terrainInfo": {
    "levels": [0, 1, 2, 3, 4, 5, 6, 7, 8],
    "bounds": {
      "west": 119.31,
      "south": 21.75,
      "east": 124.56,
      "north": 25.93
    }
  }
}
```

### 解压地形瓦片

**POST** `/api/terrain/decompress`

解压地形瓦片文件（.terrain.gz → .terrain）。

#### 📝 接口逻辑
1. **路径验证**: 验证地形目录路径的有效性
2. **文件扫描**: 扫描目录中的所有.terrain.gz压缩文件
3. **格式识别**: 识别和验证压缩文件格式
4. **解压处理**: 使用gzip模块解压每个文件
5. **完整性验证**: 验证解压后文件的完整性
6. **文件替换**: 用解压后的文件替换压缩文件
7. **清理操作**: 根据keepCompressed参数处理原文件
8. **结果统计**: 统计解压成功和失败的文件数量

#### 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| terrainPath | array | 是 | - | 地形目录路径数组，如["terrain", "taiwan", "v1"] |

#### 请求示例
```json
{
  "terrainPath": ["terrain", "taiwan", "v1"]
}
```

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| success | boolean | 操作是否成功 |
| message | string | 操作结果消息 |
| decompressInfo | object | 解压信息 |
| decompressInfo.terrainDir | string | 地形目录 |
| decompressInfo.totalFiles | number | 总文件数 |
| decompressInfo.successCount | number | 成功解压数 |
| decompressInfo.failCount | number | 失败数 |

#### 响应示例
```json
{
  "success": true,
  "message": "地形解压完成",
  "decompressInfo": {
    "terrainDir": "terrain/taiwan/v1",
    "totalFiles": 1398,
    "successCount": 1398,
    "failCount": 0
  }
}
```

## 🔥 Java后端API接口

### 📋 Java后端概述

Java后端基于Spring Boot框架，提供高性能的地形和地图切片服务，集成了先进的量化网格算法和半边数据结构，支持复杂的三维地形网格生成和优化。

**基础地址**: `http://localhost:8080`  
**技术栈**: Spring Boot 2.x + MyBatis Plus + GeoTools + GDAL  
**核心特性**: 量化网格、半边数据结构、多级细分、自适应优化

---

## 🏔️ Java地形切片服务

### 地形切片（文件上传）- Java原生实现

**POST** `/terrain/cut/terrainCutOfFile`

使用Java原生算法进行高精度地形切片，基于量化网格和半边数据结构实现。

#### 📝 核心技术
1. **量化网格算法**: 将地形高度数据量化为16位整数，大幅减少数据量
2. **半边数据结构**: 高效存储和处理三角网拓扑关系
3. **自适应细分**: 根据地形复杂度动态调整三角网密度
4. **重心坐标插值**: 使用重心坐标进行高精度高程插值
5. **边界约束**: 智能处理瓦片边界，确保相邻瓦片无缝拼接

#### 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| file | MultipartFile | 是 | - | TIF格式的地形数据文件 |
| workspaceGroup | String | 是 | - | 工作空间组名称 |
| workspace | String | 是 | - | 工作空间名称 |
| minZoom | Integer | 否 | 0 | 最小缩放级别（范围：0-22） |
| maxZoom | Integer | 否 | 14 | 最大缩放级别（范围：0-22） |
| intensity | Double | 否 | 4.0 | 网格细化强度（范围：1.0-16.0），值越大三角网越密集 |
| calculateNormals | boolean | 否 | false | 是否计算顶点法线，用于光照效果 |
| interpolationType | String | 否 | "bilinear" | 插值类型：nearest（最近邻）、bilinear（双线性） |
| nodataValue | Integer | 否 | -9999 | 无数据值，用于标识无效高程数据 |
| mosaicSize | Integer | 否 | 16 | 瓦片拼接缓冲区大小（像素） |
| rasterMaxSize | Integer | 否 | 16384 | 最大栅格尺寸限制 |
| isContinue | boolean | 否 | false | 是否继续中断的任务 |

#### 请求示例
```bash
curl -X POST "http://localhost:8080/terrain/cut/terrainCutOfFile" \
  -F "file=@elevation.tif" \
  -F "workspaceGroup=project" \
  -F "workspace=terrain_v1" \
  -F "minZoom=0" \
  -F "maxZoom=12" \
  -F "intensity=6.0" \
  -F "calculateNormals=true" \
  -F "interpolationType=bilinear" \
  -F "mosaicSize=32"
```

#### 响应示例
```json
{
  "message": "地形切片任务启动成功",
  "workspace": "project/terrain_v1",
  "processedLevels": "0-12",
  "estimatedTime": "约15分钟",
  "outputPath": "/app/tiles/project/terrain_v1"
}
```

### 地形切片（路径）- Java原生实现

**POST** `/terrain/cut/terrainCutOfPath`

通过文件路径进行地形切片，适用于服务器本地文件处理。

#### 📝 核心技术
1. **地形数据预处理**: 自动检测坐标系并进行标准化转换
2. **多分辨率处理**: 智能生成多级别的地形网格
3. **内存优化**: 采用分块处理策略，支持大文件处理
4. **拓扑优化**: 自动优化三角网拓扑结构，减少退化三角形

#### 请求参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| workspaceGroup | String | 是 | 工作空间组名称 |
| workspace | String | 是 | 工作空间名称 |
| filePath | String | 是 | TIF文件的完整路径 |
| minZoom | Integer | 否 | 最小缩放级别 |
| maxZoom | Integer | 否 | 最大缩放级别 |
| intensity | Double | 否 | 网格细化强度 |
| calculateNormals | boolean | 否 | 是否计算顶点法线 |
| interpolationType | String | 否 | 插值类型 |
| nodataValue | Integer | 否 | 无数据值 |
| mosaicSize | Integer | 否 | 拼接缓冲区大小 |
| rasterMaxSize | Integer | 否 | 最大栅格尺寸 |
| isContinue | boolean | 否 | 是否继续中断任务 |

#### 请求示例
```json
{
  "workspaceGroup": "elevation",
  "workspace": "dem_2024",
  "filePath": "/data/terrain/elevation.tif",
  "minZoom": 0,
  "maxZoom": 15,
  "intensity": 8.0,
  "calculateNormals": true,
  "interpolationType": "bilinear",
  "nodataValue": -9999,
  "mosaicSize": 64,
  "rasterMaxSize": 32768,
  "isContinue": false
}
```

### 创建地形瓦片（AtlasWorks API兼容）

**POST** `/terrain/cut/tile/terrain`

与Python AtlasWorks API完全兼容的地形切片接口，支持批量处理和地形合并。

#### 📝 核心技术
1. **批量处理引擎**: 支持多文件并行处理，智能任务调度
2. **地形合并算法**: 自动合并多个地形区域，智能处理边界
3. **任务进度监控**: 实时跟踪处理进度，支持任务恢复
4. **智能级别推荐**: 根据数据特征自动推荐最佳缩放级别

#### 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| folderPaths | List<String> | 是 | - | 搜索文件夹路径列表（相对于数据源目录） |
| filePatterns | List<String> | 否 | ["*.tif", "*.tiff"] | 文件匹配模式，支持通配符和txt文件列表 |
| outputPath | String | 是 | - | 输出路径（支持/分隔） |
| startZoom | Integer | 否 | 0 | 起始缩放级别（粗糙级别） |
| endZoom | Integer | 否 | 8 | 结束缩放级别（详细级别），最小值8 |
| maxTriangles | Integer | 否 | 6291456 | 最大三角形数量限制 |
| bounds | List<Double> | 否 | null | 地理边界 [west, south, east, north] |
| compression | Boolean | 否 | true | 是否启用压缩 |
| decompress | Boolean | 否 | true | 是否自动解压输出文件 |
| threads | Integer | 否 | 4 | 线程数 |
| maxMemory | String | 否 | "8g" | 最大内存限制 |
| autoZoom | Boolean | 否 | false | 是否启用智能分级 |
| zoomStrategy | String | 否 | "conservative" | 缩放策略：conservative、aggressive |
| mergeTerrains | Boolean | 否 | false | 是否自动合并多个地形文件夹 |

#### 请求示例
```json
{
  "folderPaths": ["elevation", "dem"],
  "filePatterns": ["*.tif", "priority_files.txt"],
  "outputPath": "terrain/merged/v1",
  "startZoom": 0,
  "endZoom": 12,
  "maxTriangles": 8388608,
  "bounds": [119.31, 21.75, 124.56, 25.93],
  "compression": true,
  "decompress": true,
  "threads": 8,
  "maxMemory": "16g",
  "autoZoom": true,
  "zoomStrategy": "conservative",
  "mergeTerrains": true
}
```

#### 响应示例
```json
{
  "taskId": "terrain_java_1752666579",
  "message": "地形切片任务已启动，将处理 5 个文件",
  "statusUrl": "/api/tasks/terrain_java_1752666579",
  "success": true,
  "parameters": {
    "maxMemory": "16g",
    "outputPath": ["terrain", "merged", "v1"],
    "threads": 8,
    "totalFiles": 5,
    "type": "terrain",
    "zoomRange": "0-12"
  }
}
```

---

## 🗺️ Java地图切片服务

### 地图切片（文件上传）- Java精准算法

**POST** `/map/cut/mapCutOfFile`

使用Java原生算法进行高精度地图切片，采用精确像素计算和边界扩展策略解决瓦片间缝隙问题。

#### 📝 核心技术
1. **精确像素计算**: 基于Web墨卡托投影的精确坐标转换
2. **防缝隙算法**: 采用边界扩展和双线性插值消除瓦片间缝隙
3. **内存分块处理**: 智能分块策略，支持超大图像处理
4. **坐标系转换**: 自动检测并转换为标准Web墨卡托（EPSG:3857）
5. **质量优化**: 多级采样和抗锯齿处理，确保瓦片质量

#### 请求参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | MultipartFile | 是 | 地图图像文件（支持TIF、TIFF等格式） |
| workspaceGroup | String | 是 | 工作空间组名称 |
| workspace | String | 是 | 工作空间名称 |
| type | String | 是 | 文件类型：1（电子地图）、2（遥感影像） |
| minZoom | Integer | 是 | 最小缩放级别 |
| maxZoom | Integer | 是 | 最大缩放级别 |

#### 请求示例
```bash
curl -X POST "http://localhost:8080/map/cut/mapCutOfFile" \
  -F "file=@satellite.tif" \
  -F "workspaceGroup=maps" \
  -F "workspace=satellite_2024" \
  -F "type=2" \
  -F "minZoom=0" \
  -F "maxZoom=18"
```

### 地图切片（路径）- Java精准算法

**POST** `/map/cut/mapCutOfPath`

通过文件路径进行地图切片，适用于服务器本地大文件处理。

#### 📝 核心技术
1. **Web墨卡托标准化**: 严格按照Web墨卡托标准进行坐标转换
2. **瓦片边界计算**: 精确计算每个瓦片的地理边界
3. **重叠区域处理**: 智能处理图像与瓦片的重叠区域
4. **高质量渲染**: 使用高质量渲染算法，确保视觉效果

#### 请求参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| workspaceGroup | String | 是 | 工作空间组名称 |
| workspace | String | 是 | 工作空间名称 |
| type | String | 是 | 文件类型 |
| tifDir | String | 是 | TIF文件完整路径 |
| minZoom | Integer | 是 | 最小缩放级别 |
| maxZoom | Integer | 是 | 最大缩放级别 |
| backSuccessUrl | String | 否 | 成功回调地址 |
| backFailUrl | String | 否 | 失败回调地址 |

### 索引瓦片切片（AtlasWorks API兼容）

**POST** `/map/cut/tile/indexedTiles`

基于空间索引的高性能瓦片生成，与Python AtlasWorks API完全兼容。

#### 📝 核心技术
1. **空间索引构建**: 生成SHP分幅矢量索引，精确记录空间关系
2. **元数据管理**: 详细记录每个瓦片的位置、关联文件、像素统计等
3. **精确切割**: 直接使用GDAL进行精确切割，无中间VRT层
4. **多进程并行**: 支持多进程并行处理，大幅提升处理效率
5. **增量更新**: 支持增量更新，复用现有瓦片
6. **透明瓦片处理**: 智能检测和处理透明瓦片

#### 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| folderPaths | List<String> | 是 | - | 数据源文件夹路径列表 |
| filePatterns | List<String> | 是 | - | 文件模式列表（支持通配符和txt文件） |
| outputPath | String | 是 | - | 输出路径（支持/分隔） |
| minZoom | Integer | 否 | 0 | 最小缩放级别 |
| maxZoom | Integer | 否 | 12 | 最大缩放级别 |
| tileSize | Integer | 否 | 256 | 瓦片大小 |
| processes | Integer | 否 | 4 | 进程数 |
| maxMemory | String | 否 | "8g" | 最大内存限制 |
| resampling | String | 否 | "near" | 重采样方法：near、bilinear、cubic、average |
| generateShpIndex | Boolean | 否 | true | 是否生成SHP矢量索引 |
| enableIncrementalUpdate | Boolean | 否 | false | 是否启用增量更新 |
| skipNodataTiles | Boolean | 否 | false | 是否跳过透明瓦片 |

### 扫描透明瓦片（AtlasWorks API兼容）

**POST** `/map/cut/tiles/nodata/scan`

扫描指定目录中包含透明（nodata）值的PNG瓦片。

#### 📝 核心技术
1. **Alpha通道分析**: 使用PIL/OpenCV分析PNG文件的Alpha通道
2. **透明度检测**: 基于阈值判断瓦片透明度
3. **统计分析**: 按缩放级别统计透明瓦片分布
4. **批量处理**: 高效批量扫描大量瓦片文件

#### 请求参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| tilesPath | String | 是 | - | 瓦片目录路径（相对于tiles目录） |
| includeDetails | Boolean | 否 | false | 是否返回详细文件列表 |

### 删除透明瓦片（AtlasWorks API兼容）

**POST** `/map/cut/tiles/nodata/delete`

删除包含透明（nodata）值的PNG瓦片，并清理空目录。

#### 📝 核心技术
1. **批量删除**: 高效批量删除透明瓦片文件
2. **目录清理**: 自动清理删除后的空目录结构
3. **安全验证**: 删除前进行安全验证，防止误删
4. **统计报告**: 生成详细的删除操作统计报告

---

## 🌐 Java瓦片服务

### TMS瓦片服务

**GET** `/map/{workspaceGroup}/{workspace}/{z}/{x}_{y}.png`

提供标准TMS（Tile Map Service）格式的瓦片服务。

#### 📝 核心技术
1. **TMS坐标系**: 标准TMS坐标系，Y轴从下到上
2. **本地缓存**: 集成本地缓存服务，提升访问性能
3. **工作空间管理**: 基于工作空间的瓦片组织和权限控制
4. **坐标转换**: 自动处理TMS与标准XYZ坐标的转换

#### 路径参数
| 参数 | 类型 | 说明 |
|------|------|------|
| workspaceGroup | String | 工作空间组名称 |
| workspace | String | 工作空间名称 |
| z | int | 缩放级别 |
| x | int | X坐标（列号） |
| y | int | Y坐标（行号，TMS格式） |

### XYZ瓦片服务

**GET** `/map/{workspaceGroup}/{workspace}/{z}/{x}/{y}.png`

提供标准XYZ格式的瓦片服务，兼容大多数地图客户端。

#### 📝 核心技术
1. **XYZ坐标系**: 标准XYZ坐标系，Y轴从上到下
2. **标准兼容**: 完全兼容OpenStreetMap等标准XYZ服务
3. **高性能访问**: 优化的文件访问和缓存策略

### WMTS标准服务

**GET** `/map/wmts/capabilities`

提供符合OGC WMTS标准的服务能力描述文档。

#### 📝 核心技术
1. **OGC标准**: 完全符合OGC WMTS 1.0.0标准
2. **元数据管理**: 自动生成服务元数据和能力描述
3. **多格式支持**: 支持PNG、JPEG等多种图像格式
4. **缓存优化**: 智能缓存策略，提升服务性能

#### 查询参数
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| SERVICE | String | WMTS | 服务类型，固定值"WMTS" |
| REQUEST | String | GetCapabilities | 请求类型 |
| VERSION | String | 1.0.0 | WMTS版本号 |

### WMTS GetTile请求

**GET** `/map/wmts/tile`

标准WMTS GetTile请求，获取指定瓦片。

#### 📝 核心技术
1. **参数验证**: 严格按照WMTS标准验证请求参数
2. **图层管理**: 支持多图层管理和权限控制
3. **格式转换**: 支持多种输出格式的动态转换
4. **错误处理**: 标准化的错误响应和状态码

#### 查询参数
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| SERVICE | String | 否 | WMTS | 服务类型 |
| REQUEST | String | 否 | GetTile | 请求类型 |
| VERSION | String | 否 | 1.0.0 | 版本号 |
| LAYER | String | 是 | - | 图层标识符（格式：workspaceGroup/workspace） |
| STYLE | String | 否 | default | 样式名称 |
| FORMAT | String | 否 | image/png | 图像格式 |
| TILEMATRIXSET | String | 是 | - | 瓦片矩阵集合标识符 |
| TILEMATRIX | String | 是 | - | 瓦片矩阵标识符（缩放级别） |
| TILEROW | Integer | 是 | - | 瓦片行号 |
| TILECOL | Integer | 是 | - | 瓦片列号 |

### WMTS RESTful服务

**GET** `/map/wmts/{workspaceGroup}/{workspace}/{tileMatrix}/{tileRow}/{tileCol}.{format}`

RESTful风格的WMTS瓦片服务。

#### 📝 核心技术
1. **RESTful设计**: 符合REST设计原则的URL结构
2. **格式协商**: 基于URL扩展名的格式协商
3. **性能优化**: 针对RESTful访问模式的性能优化

---

## 🏔️ Java地形服务

### 地形瓦片获取

**GET** `/terrain/{workspaceGroup}/{workspace}/{z}/{x}/{y}.terrain`

获取Cesium格式的地形瓦片数据。

#### 📝 核心技术
1. **Cesium兼容**: 完全兼容Cesium地形瓦片格式
2. **量化网格**: 高效的量化网格数据结构
3. **流式传输**: 支持大文件的流式传输
4. **压缩优化**: 智能压缩策略，平衡文件大小和质量

#### 路径参数
| 参数 | 类型 | 说明 |
|------|------|------|
| workspaceGroup | String | 工作空间组名称 |
| workspace | String | 工作空间名称 |
| z | int | 缩放级别 |
| x | int | X坐标 |
| y | int | Y坐标 |

### Layer.json获取

**GET** `/terrain/{workspaceGroup}/{workspace}/layer.json`

获取地形图层的元数据文件。

#### 📝 核心技术
1. **元数据管理**: 自动生成和维护地形元数据
2. **边界计算**: 精确计算地形数据的地理边界
3. **级别统计**: 统计可用的缩放级别范围
4. **JSON优化**: 优化的JSON结构，支持快速解析

---

## 🗂️ Java工作空间服务

### 创建工作空间

**POST** `/workspace/createWorkspace/{workspaceGroup}/{workspace}`

创建新的工作空间目录。

#### 📝 核心技术
1. **目录管理**: 自动创建目录结构
2. **权限控制**: 设置合适的目录权限
3. **冲突检测**: 检测目录是否已存在
4. **原子操作**: 确保创建操作的原子性

### 删除工作空间

**DELETE** `/workspace/deleteWorkspace/{workspaceGroup}/{workspace}`

递归删除工作空间及其所有内容。

#### 📝 核心技术
1. **递归删除**: 安全的递归删除算法
2. **事务保护**: 删除失败时的回滚机制
3. **权限验证**: 删除前进行权限验证
4. **清理优化**: 高效的文件清理策略

### 工作空间状态管理

**GET** `/workspace/updateStatusWorkspace/{workspaceGroup}/{workspace}/{status}`

更新工作空间的状态。

#### 📝 核心技术
1. **状态机**: 基于状态机的工作空间状态管理
2. **数据库同步**: 状态变更与数据库同步
3. **缓存更新**: 自动更新本地缓存
4. **事件通知**: 状态变更事件通知机制

### 创建工作空间组

**POST** `/workspace/createWorkspaceGroup/{workspaceGroup}`

创建工作空间组。

### 删除工作空间组

**DELETE** `/workspace/deleteWorkspaceGroup/{workspaceGroup}`

删除工作空间组及其所有子工作空间。

---

## 📚 API文档

### 获取API路由列表

**GET** `/api/routes`

获取所有API接口的详细信息和统计数据。

#### 📝 接口逻辑
1. **代码文件读取**: 读取当前Python文件的源代码
2. **正则表达式匹配**: 使用正则表达式匹配所有@app.route装饰器
3. **路由信息提取**: 提取路由路径、HTTP方法、函数名等信息
4. **文档字符串解析**: 解析函数的文档字符串作为接口描述
5. **分类处理**: 根据路径特征对接口进行功能分类
6. **参数分析**: 分析路径参数和查询参数
7. **统计计算**: 计算接口总数、分类统计、方法统计
8. **JSON封装**: 返回结构化的API文档信息

#### 响应参数
| 参数 | 类型 | 说明 |
|------|------|------|
| success | boolean | 操作是否成功 |
| routes | array | 路由列表 |
| routes[].path | string | 路由路径 |
| routes[].methods | array | HTTP方法 |
| routes[].function | string | 函数名 |
| routes[].description | string | 接口描述 |
| routes[].category | string | 功能分类 |
| routes[].parameters | array | 路径参数（如果有） |
| stats | object | 统计信息 |
| stats.totalRoutes | number | 总接口数 |
| stats.categories | object | 分类统计 |
| stats.methods | object | 方法统计 |
| generatedAt | string | 生成时间 |

#### 响应示例
```json
{
  "success": true,
  "routes": [
    {
      "path": "/api/health",
      "methods": ["GET"],
      "function": "health_check",
      "description": "健康检查",
      "category": "系统监控"
    },
    {
      "path": "/api/tile/terrain",
      "methods": ["POST"],
      "function": "create_terrain_tiles",
      "description": "创建地形瓦片（支持自动合并）",
      "category": "瓦片生成"
    }
  ],
  "stats": {
    "totalRoutes": 25,
    "categories": {
      "系统监控": 1,
      "瓦片生成": 3,
      "任务管理": 5
    },
    "methods": {
      "GET": 8,
      "POST": 12,
      "PUT": 1,
      "DELETE": 4
    }
  },
  "generatedAt": "2025-01-08T16:45:00"
}
```

## 🎯 接口设计原则

### 安全性原则
- **路径验证**: 所有涉及路径的操作都经过严格的安全验证
- **参数过滤**: 输入参数经过验证和过滤，防止注入攻击
- **权限控制**: 实现基于角色的访问控制
- **错误处理**: 统一的错误处理机制，避免信息泄露

### 性能原则
- **异步处理**: 长时间任务采用异步处理，避免阻塞
- **资源管理**: 智能的内存和CPU资源分配
- **缓存机制**: 合理使用缓存提升响应速度
- **批量操作**: 支持批量操作提高处理效率

### 可用性原则
- **状态管理**: 完整的任务状态跟踪和进度监控
- **错误恢复**: 支持任务重启和错误恢复机制
- **用户友好**: 提供清晰的错误信息和操作指导
- **文档完整**: 详细的API文档和使用示例

### 扩展性原则
- **模块化设计**: 功能模块化，易于扩展和维护
- **插件架构**: 支持插件式扩展新功能
- **版本控制**: 支持API版本管理和向后兼容
- **配置灵活**: 丰富的配置选项满足不同需求

## 🔧 最佳实践

### 接口调用建议
1. **健康检查**: 定期调用健康检查接口监控服务状态
2. **参数验证**: 在客户端进行参数验证，减少错误请求
3. **错误处理**: 实现完善的错误处理和重试机制
4. **进度监控**: 长时间任务要定期查询进度状态
5. **资源清理**: 及时清理不需要的任务和临时文件

### 性能优化建议
1. **合理配置**: 根据系统资源选择合适的处理参数
2. **批量处理**: 优先使用批量接口处理多个文件
3. **异步调用**: 使用异步方式调用长时间任务
4. **缓存利用**: 合理利用缓存机制提升性能
5. **监控告警**: 实现资源监控和告警机制

### 错误处理建议
1. **状态码检查**: 始终检查HTTP状态码和响应结果
2. **重试机制**: 实现指数退避的重试机制
3. **日志记录**: 记录详细的操作日志便于排查问题
4. **超时处理**: 设置合理的请求超时时间
5. **降级策略**: 实现服务降级和熔断机制

---

**文档版本**: v2.7  
**最后更新**: 2025-07-16  
**维护团队/个人**: 徐实 

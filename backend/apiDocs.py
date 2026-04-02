#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy
import json
import re

from flask import Response, current_app, jsonify, request

from api_response import normalize_envelope
from config import config


_PATH_PARAM_PATTERN = re.compile(r"<(?:[^:>]+:)?([^>]+)>")
_OPENAPI_PARAM_PATTERN = re.compile(r"{([^}]+)}")


_OPERATION_OVERRIDES = {
    ("/api/health", "get"): {
        "summary": "健康检查",
        "responses": {
            "200": {
                "description": "服务健康状态",
                "content": {
                    "application/json": {
                        "examples": {
                            "ok": {
                                "summary": "健康响应",
                                "value": {
                                    "status": "healthy",
                                    "timestamp": "2026-03-25 00:30:00",
                                    "version": "2.0.0",
                                    "database": {"enabled": True, "status": "healthy", "connected": True},
                                    "tasks": {"inMemoryTotal": 2, "running": 1, "queued": 0},
                                    "catalog": {"artifacts": 5, "publications": 3, "taskEvents": 18},
                                },
                            }
                        }
                    }
                },
            }
        },
    },
    ("/api/system/info", "get"): {
        "summary": "系统信息",
        "responses": {
            "200": {
                "description": "系统配置、资源与任务统计",
                "content": {
                    "application/json": {
                        "examples": {
                            "system_info": {
                                "summary": "系统信息示例",
                                "value": {
                                    "timestamp": "2026-03-25T00:30:00",
                                    "version": "2.0.0",
                                    "config": {
                                        "dataSourceDir": "/app/dataSource",
                                        "tilesDir": "/app/tiles",
                                        "publicBaseMode": "container_ip",
                                        "publicBaseUrl": "",
                                    },
                                    "database": {"enabled": True, "status": "healthy"},
                                    "tasks": {"total": 12, "running": 1, "completed": 9, "failed": 2},
                                    "catalog": {"artifacts": 8, "publications": 4, "taskEvents": 53},
                                },
                            }
                        }
                    }
                },
            }
        },
    },
    ("/api/dataSources", "get"): {
        "summary": "获取数据源列表",
        "responses": {
            "200": {
                "description": "返回当前目录下的数据源文件与子目录",
                "content": {
                    "application/json": {
                        "examples": {
                            "datasource_list": {
                                "summary": "数据源列表",
                                "value": {
                                    "success": True,
                                    "currentPath": "",
                                    "folders": [{"name": "20260325", "path": "20260325"}],
                                    "files": [{"name": "sample.tif", "path": "sample.tif", "extension": ".tif"}],
                                },
                            }
                        }
                    }
                },
            }
        },
    },
    ("/api/dataSources/info/{filename}", "get"): {
        "summary": "数据源文件详情",
        "parameters": [
            {
                "name": "filename",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": "本地相对路径，或 URL 编码后的 http/https 远程地址。",
            },
            {"name": "tileType", "in": "query", "schema": {"type": "string"}, "description": "推荐配置类型，可选 map/terrain。"},
            {"name": "minZoom", "in": "query", "schema": {"type": "integer", "minimum": 0}, "description": "用于推荐配置的最小层级。"},
            {"name": "maxZoom", "in": "query", "schema": {"type": "integer", "minimum": 0}, "description": "用于推荐配置的最大层级。"},
        ],
        "responses": {
            "200": {
                "description": "返回文件元数据、范围、波段和分辨率信息",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeDataSourceFileDetail"},
                        "examples": {
                            "file_detail": {
                                "value": {
                                    "name": "sample.tif",
                                    "path": "20260325/sample.tif",
                                    "format": "tif",
                                    "size": 24536621,
                                    "sizeFormatted": "23.4 MB",
                                    "metadata": {
                                        "driver": "GTiff",
                                        "rasterSize": {"width": 4096, "height": 4096},
                                        "pixelSize": {"x": 0.00028, "y": 0.00028},
                                        "bandCount": 3,
                                        "bounds": {"west": 120.0, "south": 30.0, "east": 121.0, "north": 31.0},
                                        "dataType": "Byte",
                                    },
                                    "geoBounds": {"west": 120.0, "south": 30.0, "east": 121.0, "north": 31.0},
                                }
                            }
                        },
                    }
                },
            },
            "403": {
                "description": "路径不允许访问",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"forbidden": {"value": {"error": "路径不允许访问"}}},
                    }
                },
            },
            "404": {
                "description": "文件不存在",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"not_found": {"value": {"error": "文件不存在"}}},
                    }
                },
            },
        },
    },
    ("/api/dataSources/resolve", "post"): {
        "summary": "解析数据源文件",
        "description": "支持本地模式匹配，也支持在 filePatterns 里直接传 http/https 地址。",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/DatasourceResolveRequest"},
                    "examples": {
                        "remote_tif": {
                            "summary": "直接传网络 TIF 地址",
                            "value": {
                                "folderPaths": [],
                                "filePatterns": ["https://example.com/demo/remote.tif"],
                                "maxFiles": 200,
                            },
                        },
                        "remote_txt": {
                            "summary": "传网络 txt 清单地址",
                            "value": {
                                "folderPaths": [],
                                "filePatterns": ["https://example.com/demo/input-list.txt"],
                                "maxFiles": 200,
                            },
                        },
                    },
                }
            },
        },
        "responses": {
            "200": {
                "description": "解析成功，返回匹配结果与波段摘要",
                "content": {
                    "application/json": {
                        "examples": {
                            "resolved": {
                                "summary": "解析成功",
                                "value": {
                                    "success": True,
                                    "totalMatched": 2,
                                    "files": ["20260325/a_3f3c2d2f.tif", "20260325/b_8af31e4b.tif"],
                                    "truncated": False,
                                    "bandSummary": {"commonBandCount": 3, "minBandCount": 3, "maxBandCount": 4},
                                },
                            }
                        }
                    }
                },
            },
            "400": {
                "description": "参数错误",
                "content": {
                    "application/json": {
                        "examples": {
                            "bad_request": {"value": {"success": False, "error": "缺少参数: filePatterns"}}
                        }
                    }
                },
            },
        },
    },
    ("/api/tile/convert", "post"): {
        "summary": "瓦片结构转换",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/TileConvertRequest"},
                    "examples": {
                        "convert": {
                            "value": {
                                "sourcePath": "demo/source",
                                "targetPath": "demo/converted",
                                "sourceFormat": "nested",
                                "targetFormat": "flat",
                                "overwrite": False,
                            }
                        }
                    },
                }
            },
        },
        "responses": {
            "200": {
                "description": "转换任务已启动",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeTileConvert"},
                        "examples": {
                            "started": {
                                "value": {
                                    "success": True,
                                    "message": "瓦片格式转换任务已启动",
                                    "taskId": "tileConvert1774351000",
                                    "statusUrl": "/api/tasks/tileConvert1774351000",
                                    "sourcePath": "demo/source",
                                    "targetPath": "demo/converted",
                                    "sourceFormat": "nested",
                                    "targetFormat": "flat",
                                }
                            }
                        },
                    }
                },
            },
            "400": {
                "description": "参数错误",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"bad_request": {"value": {"error": "缺少参数: sourcePath"}}},
                    }
                },
            },
            "403": {
                "description": "路径不允许访问",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"forbidden": {"value": {"error": "路径不允许访问"}}},
                    }
                },
            },
            "404": {
                "description": "源目录不存在",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"not_found": {"value": {"error": "源目录不存在: /app/tiles/demo/source"}}},
                    }
                },
            },
        },
    },
    ("/api/tiles/nodata/scan", "post"): {
        "summary": "扫描透明瓦片",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/NodataScanRequest"},
                    "examples": {
                        "scan": {
                            "value": {
                                "tilesPath": "测试切片-20260321/0327",
                                "transparencyThreshold": 0.1,
                                "includeDetails": True,
                            }
                        }
                    },
                }
            },
        },
        "responses": {
            "200": {
                "description": "扫描完成",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeNodataScan"},
                        "examples": {
                            "scan_result": {
                                "value": {
                                    "success": True,
                                    "message": "扫描完成",
                                    "summary": {
                                        "totalChecked": 320,
                                        "nodataTiles": 18,
                                        "validTiles": 302,
                                        "errors": 0,
                                        "nodataPercentage": 5.63,
                                        "transparencyThreshold": 0.1,
                                    },
                                    "zoomLevelStats": {"8": {"total": 120, "nodata": 8}},
                                    "nodataFiles": ["8/120/88.png"],
                                }
                            }
                        },
                    }
                },
            },
            "400": {
                "description": "参数错误",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"bad_request": {"value": {"error": "缺少瓦片目录路径参数 tilesPath"}}},
                    }
                },
            },
            "404": {
                "description": "瓦片目录不存在",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"not_found": {"value": {"error": "瓦片目录不存在"}}},
                    }
                },
            },
        },
    },
    ("/api/tiles/nodata/delete", "post"): {
        "summary": "删除透明瓦片",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/NodataDeleteRequest"},
                    "examples": {
                        "delete": {
                            "value": {
                                "tilesPath": "测试切片-20260321/0327",
                                "transparencyThreshold": 0.1,
                                "includeDetails": True,
                            }
                        }
                    },
                }
            },
        },
        "responses": {
            "200": {
                "description": "删除完成",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeNodataDelete"},
                        "examples": {
                            "delete_result": {
                                "value": {
                                    "success": True,
                                    "message": "删除完成",
                                    "summary": {
                                        "total_checked": 320,
                                        "deleted_count": 18,
                                        "error_count": 0,
                                        "cleaned_dirs": 3,
                                        "transparency_threshold": 0.1,
                                    },
                                    "deleted_files": ["8/120/88.png"],
                                }
                            }
                        },
                    }
                },
            },
            "400": {
                "description": "参数错误或删除失败",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"bad_request": {"value": {"error": "缺少瓦片目录路径参数 tilesPath"}}},
                    }
                },
            },
        },
    },
    ("/api/terrain/layer", "post"): {
        "summary": "修复 layer.json",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/TerrainLayerRequest"},
                    "examples": {
                        "update_layer": {
                            "value": {
                                "terrainPath": ["terrain", "demo"],
                                "bounds": [120.0, 30.0, 121.0, 31.0],
                            }
                        }
                    },
                }
            },
        },
        "responses": {
            "200": {
                "description": "更新成功",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeTerrainLayer"},
                        "examples": {
                            "updated": {
                                "value": {
                                    "message": "layer.json更新成功",
                                    "terrainPathArray": ["terrain", "demo"],
                                    "terrainDir": "terrain/demo",
                                    "bounds": [120.0, 30.0, 121.0, 31.0],
                                    "layerFile": "/app/tiles/terrain/demo/layer.json",
                                    "method": "ctb-tile",
                                    "detectedLevels": {"minZoom": 0, "maxZoom": 12, "availableLevels": [0, 1, 2]},
                                }
                            }
                        },
                    }
                },
            },
            "400": {
                "description": "参数错误",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"bad_request": {"value": {"error": "缺少参数: terrainPath"}}},
                    }
                },
            },
            "404": {
                "description": "地形目录不存在",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"not_found": {"value": {"error": "地形目录不存在"}}},
                    }
                },
            },
        },
    },
    ("/api/terrain/decompress", "post"): {
        "summary": "解压地形瓦片",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/TerrainDecompressRequest"},
                    "examples": {
                        "decompress": {
                            "value": {
                                "terrainPath": ["terrain", "demo"],
                            }
                        }
                    },
                }
            },
        },
        "responses": {
            "200": {
                "description": "解压成功",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeTerrainDecompress"},
                        "examples": {
                            "ok": {
                                "value": {
                                    "message": "地形瓦片解压成功",
                                    "terrainPathArray": ["terrain", "demo"],
                                    "terrainDir": "terrain/demo",
                                    "terrainPath": "/app/tiles/terrain/demo",
                                }
                            }
                        },
                    }
                },
            },
            "400": {
                "description": "参数错误",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"bad_request": {"value": {"error": "缺少参数: terrainPath"}}},
                    }
                },
            },
            "404": {
                "description": "地形目录不存在",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"not_found": {"value": {"error": "地形目录不存在"}}},
                    }
                },
            },
        },
    },
    ("/api/tile/indexedTiles", "post"): {
        "summary": "创建地图切片任务（返回 taskId）",
        "description": "filePatterns 支持通配符、txt、以及 http/https 网络地址。",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/IndexedTilesRequest"},
                    "examples": {
                        "remote_source": {
                            "summary": "网络地址切片（地图）",
                            "value": {
                                "folderPaths": [],
                                "filePatterns": ["https://example.com/imagery/aoi_20260324.tif"],
                                "outputPath": "map/remote-demo",
                                "minZoom": 0,
                                "maxZoom": 16,
                                "tileSize": 256,
                                "processes": 4,
                                "threads": 4,
                                "projection": "EPSG:3857",
                                "dataFormat": "xyz",
                                "imageFormat": "png",
                                "tileScheme": "tms",
                                "redBand": 1,
                                "greenBand": 2,
                                "blueBand": 3,
                            },
                        }
                    },
                }
            },
        },
        "responses": {
            "200": {
                "description": "任务创建成功，响应中包含 taskId 与 statusUrl",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeTaskCreate"},
                        "examples": {
                            "task_started": {
                                "value": {
                                    "success": True,
                                    "taskId": "indexedTiles1774342374",
                                    "status": "queued",
                                    "message": "地图切片任务已启动",
                                }
                            }
                        }
                    }
                },
            },
            "400": {
                "description": "参数错误",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {
                            "invalid": {"value": {"success": False, "message": "缺少参数: outputPath"}}
                        }
                    }
                },
            },
        },
    },
    ("/api/tile/terrain", "post"): {
        "summary": "创建地形切片任务",
        "description": "filePatterns 支持通配符、txt、以及 http/https 网络地址。",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/TerrainTilesRequest"},
                    "examples": {
                        "remote_source": {
                            "summary": "网络地址切片（地形）",
                            "value": {
                                "folderPaths": [],
                                "filePatterns": ["https://example.com/terrain/dem_30m.tif"],
                                "outputPath": "terrain/remote-demo",
                                "startZoom": 0,
                                "endZoom": 12,
                                "threads": 4,
                                "maxMemory": "8g",
                                "compression": True,
                                "decompress": True,
                            },
                        }
                    },
                }
            },
        },
        "responses": {
            "200": {
                "description": "任务创建成功",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeTaskCreate"},
                        "examples": {
                            "task_started": {
                                "value": {
                                    "success": True,
                                    "taskId": "terrain1774349999",
                                    "status": "queued",
                                    "message": "地形切片任务已启动",
                                }
                            }
                        }
                    }
                },
            },
            "400": {
                "description": "参数错误",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {
                            "invalid": {"value": {"error": "缺少参数: filePatterns"}}
                        }
                    }
                },
            },
        },
    },
    ("/api/tasks", "get"): {
        "summary": "任务列表",
        "parameters": [
            {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1, "minimum": 1}, "description": "页码"},
            {"name": "pageSize", "in": "query", "schema": {"type": "integer", "default": 10, "minimum": 1, "maximum": 500}, "description": "每页条数"},
            {"name": "keyword", "in": "query", "schema": {"type": "string"}, "description": "按任务 ID、状态、阶段、消息和输出信息模糊搜索"},
            {"name": "status", "in": "query", "schema": {"$ref": "#/components/schemas/TaskStatus"}, "description": "按任务状态过滤"},
            {"name": "dateFrom", "in": "query", "schema": {"type": "string", "format": "date"}, "description": "开始日期，按任务开始时间过滤"},
            {"name": "dateTo", "in": "query", "schema": {"type": "string", "format": "date"}, "description": "结束日期，按任务开始时间过滤"},
        ],
        "responses": {
            "200": {
                "description": "返回任务状态快照",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeTaskList"},
                        "examples": {
                            "tasks": {
                                "value": {
                                    "count": 1,
                                    "total": 12,
                                    "page": 1,
                                    "pageSize": 10,
                                    "totalPages": 2,
                                    "hasPrev": False,
                                    "hasNext": True,
                                    "tasks": {
                                        "indexedTiles1774342374": {
                                            "taskId": "indexedTiles1774342374",
                                            "status": "completed",
                                            "progress": 100,
                                            "currentStage": "done",
                                        }
                                    },
                                }
                            }
                        }
                    }
                },
            }
        },
    },
    ("/api/tasks/{taskId}", "get"): {
        "summary": "任务详情",
        "responses": {
            "200": {
                "description": "返回指定任务详情",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeTaskDetail"},
                        "examples": {
                            "task_detail": {
                                "value": {
                                    "taskId": "indexedTiles1774342374",
                                    "status": "running",
                                    "progress": 58,
                                    "currentStage": "tile-build",
                                    "message": "切片处理中",
                                }
                            }
                        }
                    }
                },
            },
            "404": {
                "description": "任务不存在",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"not_found": {"value": {"error": "任务不存在"}}}
                    }
                },
            },
        },
    },
    ("/api/tasks/{taskId}/events", "get"): {
        "summary": "任务事件流",
        "responses": {
            "200": {
                "description": "返回任务事件列表",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeTaskEvents"},
                        "examples": {
                            "events": {
                                "value": {
                                    "success": True,
                                    "events": [
                                        {"eventType": "task.started", "eventAt": "2026-03-25T00:30:00", "details": {"stage": "prepare"}},
                                        {"eventType": "task.progress", "eventAt": "2026-03-25T00:31:00", "details": {"progress": 35}},
                                    ],
                                }
                            }
                        }
                    }
                },
            },
            "404": {
                "description": "任务不存在或暂无事件",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"not_found": {"value": {"error": "任务不存在或暂无事件"}}}
                    }
                },
            },
        },
    },
    ("/api/tasks/{taskId}", "delete"): {
        "summary": "删除任务",
        "description": "删除指定任务记录；如果任务仍在运行，会先尝试停止。",
        "responses": {
            "200": {
                "description": "删除成功",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeTaskDelete"},
                        "examples": {
                            "deleted": {
                                "value": {
                                    "success": True,
                                    "taskId": "indexedTiles1774342374",
                                    "deletedFromMemory": True,
                                    "deletedFromDatabase": True,
                                }
                            }
                        }
                    }
                },
            },
            "404": {
                "description": "任务不存在",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"not_found": {"value": {"error": "任务不存在"}}}
                    }
                },
            },
        },
    },
    ("/api/tasks/cleanup", "post"): {
        "summary": "清理任务",
        "responses": {
            "200": {
                "description": "清理完成",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeTaskCleanup"},
                        "examples": {
                            "cleaned": {
                                "value": {
                                    "success": True,
                                    "message": "任务清理完成",
                                    "remainingTasks": 0,
                                }
                            }
                        },
                    }
                },
            }
        },
    },
    ("/api/tasks/{taskId}/stop", "post"): {
        "summary": "停止任务",
        "responses": {
            "200": {
                "description": "停止成功",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeTaskStop"},
                        "examples": {
                            "stopped": {
                                "value": {
                                    "success": True,
                                    "message": "任务已停止",
                                    "taskId": "indexedTiles1774342374",
                                }
                            }
                        },
                    }
                },
            },
            "404": {
                "description": "任务不存在或无法停止",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"not_found": {"value": {"error": "任务不存在或无法停止"}}}
                    }
                },
            },
        },
    },
    ("/api/publications", "get"): {
        "summary": "发布列表",
        "parameters": [
            {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1, "minimum": 1}, "description": "页码"},
            {"name": "pageSize", "in": "query", "schema": {"type": "integer", "default": 10, "minimum": 1, "maximum": 200}, "description": "每页条数"},
            {"name": "keyword", "in": "query", "schema": {"type": "string"}, "description": "按发布 ID、别名、路径、任务和发布方式模糊搜索"},
            {"name": "publishType", "in": "query", "schema": {"type": "string", "enum": ["imagery", "electronic-map", "terrain", "3dtiles", "geo"]}, "description": "按发布类型过滤"},
            {"name": "status", "in": "query", "schema": {"$ref": "#/components/schemas/PublicationStatus"}, "description": "按发布状态过滤"},
        ],
        "responses": {
            "200": {
                "description": "返回发布记录列表",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopePublicationList"},
                        "examples": {
                            "publication_list": {
                                "value": {
                                    "count": 1,
                                    "total": 5,
                                    "page": 1,
                                    "pageSize": 10,
                                    "totalPages": 1,
                                    "hasPrev": False,
                                    "hasNext": False,
                                    "publications": [
                                        {
                                            "publicationId": "publication-0324-test",
                                            "artifactId": "artifact-indexedTiles1774342374",
                                            "publishType": "imagery",
                                            "publishMethod": "wmts",
                                            "publishPath": "demo/output",
                                            "alias": "0324-test",
                                            "status": "enabled",
                                            "visibility": "private",
                                            "enabled": True,
                                            "note": "记录来源、用途和版本说明",
                                            "publishedAt": "2026-04-01T10:21:35",
                                            "createdAt": "2026-04-01T10:21:35",
                                            "updatedAt": "2026-04-01T10:21:35",
                                            "accessUrl": "http://172.20.0.3:8000/published/demo/output/{z}/{x}/{y}.png",
                                        }
                                    ],
                                }
                            }
                        }
                    }
                },
            }
        },
    },
    ("/api/publications", "post"): {
        "summary": "创建发布",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/PublicationUpsertRequest"},
                    "examples": {
                        "01_create_from_task": {
                            "summary": "按任务创建发布",
                            "value": {
                                "sourceMode": "task",
                                "taskId": "indexedTiles1774342374",
                                "alias": "0324-task-publish",
                                "publicationId": "publication-0324-task-publish",
                                "publishType": "imagery",
                                "publishMethod": "wmts",
                                "enabled": True,
                                "visibility": "private",
                                "note": "记录来源、用途和版本说明",
                                "customMetadata": {
                                    "version": "2026.04",
                                    "department": "cartography"
                                },
                            },
                        },
                        "02_create_from_artifact": {
                            "summary": "按产物创建发布",
                            "value": {
                                "sourceMode": "artifact",
                                "artifactId": "artifact-indexedTiles1774342374",
                                "alias": "0324-test",
                                "publishType": "imagery",
                                "publishMethod": "xyz",
                                "enabled": True,
                                "visibility": "private",
                                "note": "地图切片发布示例",
                            },
                        },
                        "03_create_from_manual_workspace": {
                            "summary": "按手动目录创建发布",
                            "value": {
                                "sourceMode": "manual",
                                "workspacePath": "测试切片-20260321/0327",
                                "publishPath": "测试切片-20260321/0327",
                                "alias": "imagery-release-v1",
                                "publicationId": "publication-imagery-release-v1",
                                "publishType": "imagery",
                                "publishMethod": "wmts",
                                "enabled": True,
                                "visibility": "internal",
                                "note": "记录来源、用途和版本说明",
                                "customMetadata": {
                                    "owner": "ops-team",
                                    "ticket": "AW-1248"
                                }
                            },
                        },
                    },
                }
            },
        },
        "responses": {
            "200": {
                "description": "创建成功",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopePublicationMutation"},
                        "examples": {
                            "created": {
                                "value": {
                                    "success": True,
                                    "publication": {
                                        "publicationId": "publication-0324-test",
                                        "artifactId": "artifact-indexedTiles1774342374",
                                        "publishType": "imagery",
                                        "publishMethod": "wmts",
                                        "publishPath": "demo/output",
                                        "alias": "0324-test",
                                        "status": "enabled",
                                        "visibility": "private",
                                        "enabled": True,
                                        "note": "记录来源、用途和版本说明",
                                        "publishedAt": "2026-04-01T10:21:35",
                                        "createdAt": "2026-04-01T10:21:35",
                                        "updatedAt": "2026-04-01T10:21:35",
                                        "accessUrl": "http://172.20.0.3:8000/published/demo/output/{z}/{x}/{y}.png",
                                    },
                                }
                            }
                        }
                    }
                },
            },
            "400": {
                "description": "参数错误",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"invalid": {"value": {"error": "缺少参数: taskId、artifactId、workspacePath 或 sourcePath"}}}
                    }
                },
            },
        },
    },
    ("/api/publications/{publicationId}", "get"): {
        "summary": "发布详情",
        "responses": {
            "200": {
                "description": "返回发布详情",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopePublicationDetail"},
                        "examples": {
                            "publication_detail": {
                                "value": {
                                    "success": True,
                                    "publication": {
                                        "publicationId": "publication-0324-test",
                                        "artifactId": "artifact-indexedTiles1774342374",
                                        "alias": "0324-test",
                                        "publishType": "imagery",
                                        "publishMethod": "wmts",
                                        "publishPath": "demo/output",
                                        "status": "enabled",
                                        "visibility": "private",
                                        "enabled": True,
                                        "note": "记录来源、用途和版本说明",
                                        "publishedAt": "2026-04-01T10:21:35",
                                        "createdAt": "2026-04-01T10:21:35",
                                        "updatedAt": "2026-04-01T10:21:35",
                                        "browserUrl": "http://172.20.0.3:8000/published/demo/output",
                                        "accessUrl": "http://172.20.0.3:8000/published/demo/output/{z}/{x}/{y}.png",
                                    },
                                }
                            }
                        }
                    }
                },
            },
            "404": {
                "description": "发布不存在",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"not_found": {"value": {"error": "发布记录不存在"}}}
                    }
                },
            },
        },
    },
    ("/api/publications/{publicationId}", "put"): {
        "summary": "更新发布",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/PublicationUpsertRequest"},
                    "examples": {
                        "update_publication": {
                            "summary": "更新发布方式或启用状态",
                            "value": {
                                "sourceMode": "task",
                                "taskId": "indexedTiles1774342374",
                                "alias": "0324-test",
                                "publicationId": "publication-0324-test",
                                "publishType": "imagery",
                                "publishMethod": "wmts",
                                "enabled": False,
                                "visibility": "private",
                                "note": "临时关闭外部访问",
                                "customMetadata": {
                                    "reason": "maintenance"
                                }
                            },
                        }
                    },
                }
            },
        },
        "responses": {
            "200": {
                "description": "更新成功",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopePublicationMutation"},
                        "examples": {
                            "updated": {
                                "value": {
                                    "success": True,
                                    "publication": {
                                        "publicationId": "publication-0324-test",
                                        "artifactId": "artifact-indexedTiles1774342374",
                                        "publishType": "imagery",
                                        "publishMethod": "wmts",
                                        "publishPath": "demo/output",
                                        "alias": "0324-test",
                                        "status": "disabled",
                                        "visibility": "private",
                                        "enabled": False,
                                        "note": "临时关闭外部访问",
                                        "publishedAt": "2026-04-01T10:25:08",
                                        "createdAt": "2026-04-01T10:21:35",
                                        "updatedAt": "2026-04-01T10:25:08",
                                        "accessUrl": "http://172.20.0.3:8000/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=publication-0324-test&STYLE=default&TILEMATRIXSET=GoogleMapsCompatible&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png",
                                    },
                                }
                            }
                        }
                    }
                },
            },
            "404": {
                "description": "发布不存在",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"not_found": {"value": {"error": "发布记录不存在"}}}
                    }
                },
            },
        },
    },
    ("/api/publications/{publicationId}", "delete"): {
        "summary": "删除发布",
        "description": "删除指定发布记录及其描述文件。",
        "responses": {
            "200": {
                "description": "删除成功",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopePublicationDelete"},
                        "examples": {
                            "deleted": {
                                "value": {
                                    "success": True,
                                    "publicationId": "publication-0324-test",
                                }
                            }
                        }
                    }
                },
            },
            "404": {
                "description": "发布不存在",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ApiEnvelopeError"},
                        "examples": {"not_found": {"value": {"error": "发布记录不存在"}}}
                    }
                },
            },
        },
    },
    ("/api/artifacts", "get"): {
        "summary": "产物列表",
        "parameters": [
            {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1, "minimum": 1}, "description": "页码"},
            {"name": "pageSize", "in": "query", "schema": {"type": "integer", "default": 10, "minimum": 1, "maximum": 200}, "description": "每页条数"},
            {"name": "artifactType", "in": "query", "schema": {"type": "string"}, "description": "按产物类型过滤"},
            {"name": "keyword", "in": "query", "schema": {"type": "string"}, "description": "按产物 ID、类型、格式、输出路径模糊搜索"},
        ],
        "responses": {
            "200": {
                "description": "返回产物列表",
                "content": {
                    "application/json": {
                        "examples": {
                            "artifacts": {
                                "value": {
                                    "count": 1,
                                    "total": 5,
                                    "page": 1,
                                    "pageSize": 10,
                                    "totalPages": 1,
                                    "hasPrev": False,
                                    "hasNext": False,
                                    "artifacts": [
                                        {
                                            "artifactId": "artifact-indexedTiles1774342374",
                                            "artifactType": "imagery",
                                            "outputPath": "/app/tiles/demo/output",
                                        }
                                    ],
                                }
                            }
                        }
                    }
                },
            }
        },
    },
    ("/api/routes", "get"): {
        "summary": "接口清单",
        "parameters": [
            {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1, "minimum": 1}, "description": "页码"},
            {"name": "pageSize", "in": "query", "schema": {"type": "integer", "default": 10, "minimum": 1, "maximum": 200}, "description": "每页条数"},
            {"name": "keyword", "in": "query", "schema": {"type": "string"}, "description": "按路径、分类、说明和方法模糊搜索"},
        ],
        "responses": {
            "200": {
                "description": "返回接口清单和分页结果",
                "content": {
                    "application/json": {
                        "examples": {
                            "routes": {
                                "value": {
                                    "count": 2,
                                    "total": 53,
                                    "page": 2,
                                    "pageSize": 10,
                                    "totalPages": 6,
                                    "hasPrev": True,
                                    "hasNext": True,
                                    "categories": ["任务管理", "发布管理"],
                                    "routes": [
                                        {"path": "/api/tasks", "methods": ["GET"], "category": "任务管理", "description": "获取任务列表"},
                                        {"path": "/api/publications", "methods": ["GET", "POST"], "category": "发布管理", "description": "管理发布记录"},
                                    ],
                                    "stats": {
                                        "totalRoutes": 53,
                                    },
                                }
                            }
                        }
                    }
                },
            }
        },
    },
}


_PATH_DOCS = {
    "/api/health": {
        "summary": "健康检查",
        "description": "返回服务健康状态、数据库连接情况、运行中的任务数量和基础目录统计。",
    },
    "/api/system/info": {
        "summary": "系统信息",
        "description": "返回运行配置、系统资源、任务统计以及数据库健康状态。",
    },
    "/api/dataSources": {
        "summary": "浏览数据源目录",
        "description": "浏览数据源根目录或子目录，返回子目录和文件清单。",
    },
    "/api/dataSources/{subpath}": {
        "summary": "浏览数据源子目录",
        "description": "浏览指定数据源子目录，返回子目录和文件清单。",
    },
    "/api/dataSources/info/{filename}": {
        "summary": "数据源文件详情",
        "description": "读取单个数据源文件的元数据、空间范围、波段信息和推荐配置。支持本地文件，也支持 URL 编码后的 http/https 地址（仅临时下载解析）。",
    },
    "/api/dataSources/raw/{filename}": {
        "summary": "预览数据源图片",
        "description": "直接返回数据源目录中的 PNG/JPG/JPEG 文件内容。",
    },
    "/api/dataSources/workspace": {
        "summary": "数据源挂载信息",
        "description": "返回数据源目录的容器内路径、宿主机挂载路径和目录状态。",
    },
    "/api/dataSources/resolve": {
        "summary": "解析数据源文件",
        "description": "根据目录和文件模式解析待处理的栅格文件，支持 HTTP/HTTPS 地址。",
    },
    "/api/dataSources/split": {
        "summary": "拆分大文件",
        "description": "将超大栅格按像素窗口拆分为多个小 TIF 文件，返回异步任务信息。",
    },
    "/api/datasources/createFolder": {
        "summary": "创建数据源文件夹",
        "description": "在数据源目录下创建新的文件夹。",
    },
    "/api/datasources/folder/{folderPath}": {
        "summary": "删除数据源文件夹",
        "description": "删除指定数据源文件夹及其内容。",
    },
    "/api/datasources/file/{filePath}": {
        "summary": "删除数据源文件",
        "description": "删除指定的数据源文件。",
    },
    "/api/preflight": {
        "summary": "构建预检查",
        "description": "在正式切片前检查输入文件、输出目录、工具链和资源估算。",
    },
    "/api/upload/file": {
        "summary": "上传单文件",
        "description": "以 multipart/form-data 上传单个文件到数据源目录或工作空间。",
    },
    "/api/upload/zip": {
        "summary": "上传 ZIP 并解压",
        "description": "上传 ZIP 到目标目录并在服务端安全解压。",
    },
    "/api/upload/folder": {
        "summary": "上传文件夹",
        "description": "通过 multipart/form-data 批量上传文件并保留相对路径结构。",
    },
    "/api/files/extract": {
        "summary": "解压现有压缩包",
        "description": "解压数据源或工作空间中已存在的 zip、tar、7z 文件。",
    },
    "/api/results": {
        "summary": "浏览目录",
        "description": "按目录层级浏览结果目录或数据源目录。",
    },
    "/api/fileDetails": {
        "summary": "文件详情",
        "description": "读取结果目录或数据源中的单个文件详情。",
    },
    "/api/workspace/raw/{filename}": {
        "summary": "预览工作空间图片",
        "description": "直接返回工作空间中的 PNG/JPG/JPEG 文件内容。",
    },
    "/api/tile/terrain": {
        "summary": "创建地形切片任务",
        "description": "创建地形切片异步任务，支持自动缩放、压缩、解压和多结果合并。",
    },
    "/api/tile/indexedTiles": {
        "summary": "创建地图切片任务",
        "description": "创建基于空间索引的地图切片异步任务，支持网络源文件和多进程。",
    },
    "/api/tile/convert": {
        "summary": "瓦片结构转换",
        "description": "在 flat 和 nested 两种瓦片目录结构之间转换。",
    },
    "/api/tasks": {
        "summary": "任务列表",
        "description": "返回当前内存与数据库快照中的任务列表，支持 page、pageSize、keyword、status、dateFrom、dateTo 分页筛选。",
    },
    "/api/tasks/{taskId}": {
        "summary": "任务详情",
        "description": "读取任务状态、阶段、统计信息和结果概要；删除时可移除任务记录。",
    },
    "/api/tasks/{taskId}/events": {
        "summary": "任务事件流",
        "description": "返回任务事件流；数据库不可用时回退到 processLog。",
    },
    "/api/tasks/cleanup": {
        "summary": "清理任务",
        "description": "清理历史任务记录，降低内存和快照数量。",
    },
    "/api/tasks/{taskId}/stop": {
        "summary": "停止任务",
        "description": "停止指定任务并更新其状态。",
    },
    "/api/artifacts": {
        "summary": "产物列表",
        "description": "列出数据库和 manifest 中可见的构建产物，支持 page、pageSize、artifactType、keyword 分页筛选。",
    },
    "/api/artifacts/{artifactId}": {
        "summary": "产物详情",
        "description": "读取指定产物的元数据、输出目录和访问地址。",
    },
    "/api/artifacts/{artifactId}/manifest": {
        "summary": "产物 Manifest",
        "description": "返回指定产物的 manifest.json 内容。",
    },
    "/api/publications": {
        "summary": "发布记录",
        "description": "列出或创建发布记录，为产物生成对外访问配置；列表查询支持 page、pageSize、keyword、publishType、status 分页筛选。",
    },
    "/api/publications/{publicationId}": {
        "summary": "发布详情",
        "description": "读取、更新或删除指定的发布记录。",
    },
    "/published": {
        "summary": "发布目录入口",
        "description": "浏览已发布目录根节点。",
    },
    "/published/{relative_path}": {
        "summary": "访问发布资源",
        "description": "读取已发布的目录或具体文件内容。",
    },
    "/wmts": {
        "summary": "WMTS 服务",
        "description": "提供 WMTS GetCapabilities 与 GetTile 访问能力。",
    },
    "/api/config/recommend": {
        "summary": "推荐切片配置",
        "description": "根据源文件大小和系统资源返回推荐切片配置。",
    },
    "/api/cache/info": {
        "summary": "缓存信息",
        "description": "扫描瓦片输出目录，返回缓存目录、元数据和实际瓦片数量。",
    },
    "/api/container/update": {
        "summary": "更新容器信息",
        "description": "更新容器时间、环境变量及基础系统状态。",
    },
    "/api/routes": {
        "summary": "接口清单",
        "description": "返回后端维护的接口清单、分类和统计信息，支持 page、pageSize、keyword 分页筛选。",
    },
    "/api/workspace/createFolder": {
        "summary": "创建工作空间文件夹",
        "description": "在工作空间目录中创建新文件夹。",
    },
    "/api/workspace/folder/{folderPath}": {
        "summary": "删除工作空间文件夹",
        "description": "删除指定工作空间文件夹及其内容。",
    },
    "/api/workspace/folder/{folderPath}/rename": {
        "summary": "重命名工作空间文件夹",
        "description": "重命名指定的工作空间文件夹。",
    },
    "/api/workspace/file/{filePath}": {
        "summary": "删除工作空间文件",
        "description": "删除指定工作空间文件。",
    },
    "/api/workspace/file/{filePath}/rename": {
        "summary": "重命名工作空间文件",
        "description": "重命名指定的工作空间文件。",
    },
    "/api/workspace/move": {
        "summary": "移动工作空间项目",
        "description": "移动工作空间中的文件或文件夹到新路径。",
    },
    "/api/workspace/info": {
        "summary": "工作空间统计",
        "description": "返回工作空间总大小、文件数和目录数。",
    },
    "/api/tiles/nodata/scan": {
        "summary": "扫描透明瓦片",
        "description": "扫描指定瓦片目录中透明或 nodata 的 PNG 瓦片。",
    },
    "/api/tiles/nodata/delete": {
        "summary": "删除透明瓦片",
        "description": "删除达到透明阈值的 PNG 瓦片并清理空目录。",
    },
    "/api/terrain/layer": {
        "summary": "修复 layer.json",
        "description": "更新或重建地形目录中的 layer.json 元数据。",
    },
    "/api/terrain/decompress": {
        "summary": "解压地形瓦片",
        "description": "将地形目录中的压缩 terrain 文件解压为可直接访问的文件。",
    },
}


_DOC_HIDDEN_PATHS = {
    "/api/dataSources/resolve",
}


_GENERIC_JSON_REQUEST_EXAMPLES = {
    ("/api/dataSources/split", "post"): {
        "sourceFile": "20260327/large.tif",
        "outputPath": "split/demo",
        "tileSize": 4096,
        "overlap": 0,
    },
    ("/api/datasources/createFolder", "post"): {
        "folderPath": "20260327/new-folder",
    },
    ("/api/preflight", "post"): {
        "jobType": "map_tiles",
        "folderPaths": [],
        "filePatterns": ["20260327/*.tif"],
        "outputPath": "preflight/demo",
        "minZoom": 0,
        "maxZoom": 16,
    },
    ("/api/tile/convert", "post"): {
        "sourcePath": "demo/source",
        "targetPath": "demo/converted",
        "sourceFormat": "nested",
        "targetFormat": "flat",
        "overwrite": False,
    },
    ("/api/files/extract", "post"): {
        "path": "imports/demo.zip",
        "targetType": "datasource",
        "overwrite": False,
    },
    ("/api/config/recommend", "post"): {
        "sourceFile": "20260327/demo.tif",
        "tileType": "map",
        "minZoom": 0,
        "maxZoom": 16,
    },
    ("/api/container/update", "post"): {
        "updateType": "environment",
        "environment": {"GDAL_CACHEMAX": "512"},
    },
    ("/api/workspace/createFolder", "post"): {
        "folderPath": "demo/output",
    },
    ("/api/workspace/folder/{folderPath}/rename", "put"): {
        "newName": "renamed-folder",
    },
    ("/api/workspace/file/{filePath}/rename", "put"): {
        "newName": "renamed.png",
    },
    ("/api/workspace/move", "put"): {
        "sourcePath": "demo/a.png",
        "targetPath": "archive/demo/a.png",
    },
    ("/api/tiles/nodata/scan", "post"): {
        "tilesPath": "测试切片-20260321/0327",
        "transparencyThreshold": 0.1,
        "includeDetails": True,
    },
    ("/api/tiles/nodata/delete", "post"): {
        "tilesPath": "测试切片-20260321/0327",
        "transparencyThreshold": 0.1,
        "includeDetails": True,
    },
    ("/api/terrain/layer", "post"): {
        "terrainPath": ["terrain", "demo"],
        "bounds": [120.0, 30.0, 121.0, 31.0],
    },
    ("/api/terrain/decompress", "post"): {
        "terrainPath": ["terrain", "demo"],
    },
}


_MULTIPART_REQUESTS = {
    ("/api/upload/file", "post"): {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "targetPath": {"type": "string"},
                        "targetType": {"type": "string", "enum": ["datasource", "workspace"]},
                        "overwrite": {"type": "string", "description": "0/1 或 true/false"},
                    },
                    "required": ["file"],
                }
            }
        },
    },
    ("/api/upload/zip", "post"): {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "targetPath": {"type": "string"},
                        "targetType": {"type": "string", "enum": ["datasource", "workspace"]},
                        "overwrite": {"type": "string"},
                        "stripTopLevel": {"type": "string"},
                    },
                    "required": ["file"],
                }
            }
        },
    },
    ("/api/upload/folder", "post"): {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "files": {
                            "type": "array",
                            "items": {"type": "string", "format": "binary"},
                        },
                        "paths": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "targetPath": {"type": "string"},
                        "targetType": {"type": "string", "enum": ["datasource", "workspace"]},
                        "overwrite": {"type": "string"},
                    },
                    "required": ["files"],
                }
            }
        },
    },
}


def _tag_for_path(path):
    normalized_path = str(path or "").lower()
    if normalized_path.startswith("/api/health") or normalized_path.startswith("/api/system") or normalized_path.startswith("/api/container"):
        return "系统"
    if normalized_path.startswith("/api/datasource") or normalized_path.startswith("/api/upload") or normalized_path.startswith("/api/files/extract") or normalized_path.startswith("/api/preflight"):
        return "数据源"
    if normalized_path.startswith("/api/tile") or normalized_path.startswith("/api/terrain") or normalized_path.startswith("/api/tiles"):
        return "切片任务"
    if normalized_path.startswith("/api/task"):
        return "任务管理"
    if normalized_path.startswith("/api/publication") or normalized_path.startswith("/api/artifact"):
        return "发布管理"
    if normalized_path.startswith("/api/workspace") or normalized_path.startswith("/api/results") or normalized_path.startswith("/api/filedetails"):
        return "工作空间"
    if normalized_path.startswith("/api/config") or normalized_path.startswith("/api/cache"):
        return "配置"
    if normalized_path.startswith("/api/docs") or normalized_path.startswith("/api/openapi") or normalized_path.startswith("/api/routes"):
        return "接口文档"
    return "其他"


def _canonical_doc_path(path):
    normalized_path = str(path or "")
    alias_prefixes = {
        "/api/datasources/info/": "/api/dataSources/info/",
        "/api/datasources/raw/": "/api/dataSources/raw/",
        "/api/datasources/workspace": "/api/dataSources/workspace",
        "/api/datasources/resolve": "/api/dataSources/resolve",
        "/api/datasources/split": "/api/dataSources/split",
        "/api/datasources": "/api/dataSources",
    }
    for alias_prefix, canonical_prefix in alias_prefixes.items():
        if normalized_path == alias_prefix or normalized_path.startswith(alias_prefix):
            return canonical_prefix + normalized_path[len(alias_prefix):]
    return normalized_path


def _flask_path_to_openapi(path):
    return _PATH_PARAM_PATTERN.sub(lambda match: "{" + match.group(1) + "}", str(path or ""))


def _build_path_parameters(openapi_path):
    parameters = []
    for name in _OPENAPI_PARAM_PATTERN.findall(openapi_path):
        parameters.append(
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": f"Path parameter: {name}",
            }
        )
    return parameters


def _merge_operation(base_operation, override_operation):
    merged = dict(base_operation)
    for key, value in (override_operation or {}).items():
        merged[key] = value
    return merged


def _wrap_operation_response_examples(operation):
    wrapped = copy.deepcopy(operation)
    responses = wrapped.get("responses")
    if not isinstance(responses, dict):
        return wrapped

    for status_code, response_spec in responses.items():
        if not isinstance(response_spec, dict):
            continue
        content = response_spec.get("content")
        if not isinstance(content, dict):
            continue
        json_content = content.get("application/json")
        if not isinstance(json_content, dict):
            continue
        examples = json_content.get("examples")
        if not isinstance(examples, dict):
            continue

        try:
            status_value = int(status_code)
        except (TypeError, ValueError):
            status_value = 200

        for example_name, example_spec in examples.items():
            if not isinstance(example_spec, dict) or "value" not in example_spec:
                continue
            examples[example_name]["value"] = normalize_envelope(example_spec["value"], status_value)

    return wrapped


def _build_paths():
    paths = {}

    for rule in current_app.url_map.iter_rules():
        route_path = str(rule.rule or "")
        if route_path.startswith("/static"):
            continue
        if route_path in {"/", "/console"}:
            continue
        if not (route_path.startswith("/api/") or route_path.startswith("/published") or route_path.startswith("/wmts")):
            continue

        raw_openapi_path = _flask_path_to_openapi(route_path)
        openapi_path = _canonical_doc_path(raw_openapi_path)
        if openapi_path in _DOC_HIDDEN_PATHS:
            continue
        methods = sorted(method.lower() for method in (rule.methods or set()) if method not in {"HEAD", "OPTIONS"})
        if not methods:
            continue

        path_item = paths.setdefault(openapi_path, {})
        for method in methods:
            if method in path_item:
                continue

            operation = {
                "tags": [_tag_for_path(openapi_path)],
                "summary": rule.endpoint.replace("_", " "),
                "operationId": f"{rule.endpoint}_{method}",
                "responses": {
                    "200": {"description": "Success"},
                },
            }

            path_parameters = _build_path_parameters(openapi_path)
            if path_parameters:
                operation["parameters"] = path_parameters

            doc_path = openapi_path
            path_doc = _PATH_DOCS.get(doc_path) or _PATH_DOCS.get(raw_openapi_path)
            if path_doc:
                operation["summary"] = path_doc.get("summary", operation["summary"])
                operation["description"] = path_doc.get("description", operation.get("description"))

            generic_key = None
            if (doc_path, method) in _GENERIC_JSON_REQUEST_EXAMPLES:
                generic_key = (doc_path, method)
            elif (raw_openapi_path, method) in _GENERIC_JSON_REQUEST_EXAMPLES:
                generic_key = (raw_openapi_path, method)

            if generic_key:
                operation["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "additionalProperties": True,
                            },
                            "example": _GENERIC_JSON_REQUEST_EXAMPLES[generic_key],
                        }
                    },
                }

            multipart_request = _MULTIPART_REQUESTS.get((doc_path, method)) or _MULTIPART_REQUESTS.get((raw_openapi_path, method))
            if multipart_request:
                operation["requestBody"] = multipart_request

            override = _OPERATION_OVERRIDES.get((doc_path, method)) or _OPERATION_OVERRIDES.get((raw_openapi_path, method))
            operation = _merge_operation(operation, override)
            operation = _wrap_operation_response_examples(operation)
            path_item[method] = operation

    return dict(sorted(paths.items(), key=lambda item: item[0]))


def _enum_value_to_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def _annotate_enum_descriptions(node):
    if isinstance(node, dict):
        enum_values = node.get("enum")
        if isinstance(enum_values, list) and enum_values:
            enum_texts = [_enum_value_to_text(item) for item in enum_values]
            description = node.get("description")
            if isinstance(description, str) and description.strip():
                desc_lower = description.lower()
                if not all(text.lower() in desc_lower for text in enum_texts):
                    node["description"] = f"{description.rstrip()} 可选值：{', '.join(enum_texts)}。"
            else:
                node["description"] = f"可选值：{', '.join(enum_texts)}。"

        for value in node.values():
            _annotate_enum_descriptions(value)
        return
    if isinstance(node, list):
        for item in node:
            _annotate_enum_descriptions(item)


def _strip_enum_definitions(node):
    if isinstance(node, dict):
        node.pop("enum", None)
        for value in node.values():
            _strip_enum_definitions(value)
        return
    if isinstance(node, list):
        for item in node:
            _strip_enum_definitions(item)


def _openapi_spec():
    server_url = request.host_url.rstrip("/")
    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "AtlasWorks API",
            "version": "2.0.0",
            "description": (
                "AtlasWorks 瓦片生产与发布接口文档。"
                "已自动暴露当前服务中全部 API 路由。"
            ),
        },
        "servers": [{"url": server_url}],
        "tags": [
            {"name": "系统", "description": "系统与健康状态"},
            {"name": "数据源", "description": "数据源解析与预处理"},
            {"name": "切片任务", "description": "地图/地形切片任务"},
            {"name": "任务管理", "description": "任务管理"},
            {"name": "发布管理", "description": "发布与产物管理"},
            {"name": "工作空间", "description": "工作空间与文件管理"},
            {"name": "配置", "description": "配置与缓存相关接口"},
            {"name": "接口文档", "description": "接口文档相关接口"},
            {"name": "其他", "description": "其他接口"},
        ],
        "paths": _build_paths(),
        "components": {
            "schemas": {
                "DatasourceResolveRequest": {
                    "type": "object",
                    "properties": {
                        "folderPaths": {"type": "array", "items": {"type": "string"}},
                        "filePatterns": {"type": "array", "items": {"type": "string"}},
                        "maxFiles": {"type": "integer", "minimum": 1},
                    },
                    "required": ["filePatterns"],
                },
                "GeoBounds": {
                    "type": "object",
                    "properties": {
                        "west": {"type": "number"},
                        "south": {"type": "number"},
                        "east": {"type": "number"},
                        "north": {"type": "number"},
                    },
                    "additionalProperties": True,
                },
                "DataSourceFileMetadata": {
                    "type": "object",
                    "properties": {
                        "driver": {"type": "string"},
                        "driverLongName": {"type": "string"},
                        "rasterSize": {
                            "type": "object",
                            "properties": {
                                "width": {"type": "integer"},
                                "height": {"type": "integer"},
                            },
                            "additionalProperties": True,
                        },
                        "pixelSize": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                            },
                            "additionalProperties": True,
                        },
                        "bandCount": {"type": "integer"},
                        "dataType": {"type": "string"},
                        "bandDataTypes": {"type": "array", "items": {"type": "string"}},
                        "nodata": {"description": "NoData 值，可能是单值或数组。"},
                        "compression": {"type": "string"},
                        "bounds": {"$ref": "#/components/schemas/GeoBounds"},
                        "srs": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "DataSourceFileDetailData": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "path": {"type": "string"},
                        "fullPath": {"type": "string"},
                        "format": {"type": "string"},
                        "size": {"type": "integer"},
                        "sizeFormatted": {"type": "string"},
                        "lastModified": {"type": "string"},
                        "modifiedTime": {"type": "number"},
                        "type": {"type": "string"},
                        "extension": {"type": "string"},
                        "previewUrl": {"type": "string"},
                        "geoBounds": {"$ref": "#/components/schemas/GeoBounds"},
                        "metadata": {"$ref": "#/components/schemas/DataSourceFileMetadata"},
                        "recommendations": {"type": "object", "additionalProperties": True},
                    },
                    "additionalProperties": True,
                },
                "ApiEnvelopeDataSourceFileDetail": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/DataSourceFileDetailData"},
                        "meta": {"type": "object", "additionalProperties": True},
                        "error": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "TileConvertRequest": {
                    "type": "object",
                    "properties": {
                        "sourcePath": {"type": "string"},
                        "targetPath": {"type": "string"},
                        "sourceFormat": {"type": "string", "enum": ["flat", "nested"]},
                        "targetFormat": {"type": "string", "enum": ["flat", "nested"]},
                        "overwrite": {"type": "boolean"},
                    },
                    "required": ["sourcePath", "targetPath", "sourceFormat", "targetFormat"],
                },
                "TileConvertData": {
                    "type": "object",
                    "properties": {
                        "taskId": {"type": "string"},
                        "statusUrl": {"type": "string"},
                        "sourcePath": {"type": "string"},
                        "targetPath": {"type": "string"},
                        "sourceFormat": {"type": "string", "enum": ["flat", "nested"]},
                        "targetFormat": {"type": "string", "enum": ["flat", "nested"]},
                    },
                    "additionalProperties": True,
                },
                "ApiEnvelopeTileConvert": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/TileConvertData"},
                        "meta": {"type": "object", "additionalProperties": True},
                        "error": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "NodataScanRequest": {
                    "type": "object",
                    "properties": {
                        "tilesPath": {"type": "string"},
                        "transparencyThreshold": {"type": "number", "minimum": 0, "maximum": 1},
                        "includeDetails": {"type": "boolean"},
                    },
                    "required": ["tilesPath"],
                },
                "NodataDeleteRequest": {
                    "type": "object",
                    "properties": {
                        "tilesPath": {"type": "string"},
                        "transparencyThreshold": {"type": "number", "minimum": 0, "maximum": 1},
                        "includeDetails": {"type": "boolean"},
                    },
                    "required": ["tilesPath"],
                },
                "NodataScanData": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "object", "additionalProperties": True},
                        "zoomLevelStats": {"type": "object", "additionalProperties": True},
                        "nodataFiles": {"type": "array", "items": {"type": "string"}},
                        "note": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "NodataDeleteData": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "object", "additionalProperties": True},
                        "deleted_files": {"type": "array", "items": {"type": "string"}},
                    },
                    "additionalProperties": True,
                },
                "ApiEnvelopeNodataScan": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/NodataScanData"},
                        "meta": {"type": "object", "additionalProperties": True},
                        "error": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "ApiEnvelopeNodataDelete": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/NodataDeleteData"},
                        "meta": {"type": "object", "additionalProperties": True},
                        "error": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "TerrainLayerRequest": {
                    "type": "object",
                    "properties": {
                        "terrainPath": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        "bounds": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                        "sourceFile": {"type": "string"},
                        "maxMemory": {"type": "string"},
                        "threads": {"type": "integer", "minimum": 1},
                    },
                    "required": ["terrainPath"],
                },
                "TerrainLayerData": {
                    "type": "object",
                    "properties": {
                        "terrainPathArray": {"type": "array", "items": {"type": "string"}},
                        "terrainDir": {"type": "string"},
                        "bounds": {"type": "array", "items": {"type": "number"}},
                        "layerFile": {"type": "string"},
                        "method": {"type": "string"},
                        "detectedLevels": {"type": "object", "additionalProperties": True},
                        "sourceFile": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "ApiEnvelopeTerrainLayer": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/TerrainLayerData"},
                        "meta": {"type": "object", "additionalProperties": True},
                        "error": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "TerrainDecompressRequest": {
                    "type": "object",
                    "properties": {
                        "terrainPath": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    },
                    "required": ["terrainPath"],
                },
                "TerrainDecompressData": {
                    "type": "object",
                    "properties": {
                        "terrainPathArray": {"type": "array", "items": {"type": "string"}},
                        "terrainDir": {"type": "string"},
                        "terrainPath": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "ApiEnvelopeTerrainDecompress": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/TerrainDecompressData"},
                        "meta": {"type": "object", "additionalProperties": True},
                        "error": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "IndexedTilesRequest": {
                    "type": "object",
                    "properties": {
                        "folderPaths": {"type": "array", "items": {"type": "string"}},
                        "filePatterns": {"type": "array", "items": {"type": "string"}},
                        "outputPath": {"type": "string"},
                        "minZoom": {"type": "integer", "minimum": 0},
                        "maxZoom": {"type": "integer", "minimum": 0},
                        "tileSize": {"type": "integer", "minimum": 64},
                        "processes": {"type": "integer", "minimum": 1, "maximum": 128},
                        "threads": {"type": "integer", "minimum": 1, "maximum": 64},
                        "maxMemory": {"type": "string", "example": "8g"},
                        "resampling": {
                            "type": "string",
                            "enum": ["near", "bilinear", "cubic", "cubicspline", "lanczos", "average", "mode", "max", "min", "med", "q1", "q3"],
                            "example": "near",
                        },
                        "projection": {
                            "type": "string",
                            "enum": ["EPSG:3857", "EPSG:4326", "EPSG:4490"],
                            "description": "常用投影枚举；后端也支持传其他投影字符串。",
                        },
                        "dataFormat": {"type": "string", "enum": ["xyz", "tms"], "example": "xyz"},
                        "imageFormat": {"type": "string", "enum": ["png", "jpeg"], "example": "png"},
                        "tileScheme": {"type": "string", "enum": ["tms", "google"], "example": "tms"},
                        "redBand": {"type": "integer"},
                        "greenBand": {"type": "integer"},
                        "blueBand": {"type": "integer"},
                        "nodataValue": {"type": "number"},
                        "srcNodataValue": {"type": "number"},
                        "dstNodataValue": {"type": "number"},
                        "stretchType": {"type": "string", "enum": ["none", "percent", "minmax"], "example": "percent"},
                        "stretchLowPercent": {"type": "number"},
                        "stretchHighPercent": {"type": "number"},
                        "jpegQuality": {"type": "integer", "minimum": 1, "maximum": 100},
                        "pngCompression": {"type": "integer", "minimum": 0, "maximum": 9},
                        "transparencyThreshold": {"type": "number", "minimum": 0, "maximum": 1},
                        "bandMismatchPolicy": {"type": "string", "enum": ["auto", "strict", "skip"], "example": "auto"},
                        "generateShpIndex": {"type": "boolean"},
                        "enableIncrementalUpdate": {"type": "boolean"},
                        "skipNodataTiles": {"type": "boolean"},
                    },
                    "required": ["filePatterns", "outputPath"],
                },
                "TerrainTilesRequest": {
                    "type": "object",
                    "properties": {
                        "folderPaths": {"type": "array", "items": {"type": "string"}},
                        "filePatterns": {"type": "array", "items": {"type": "string"}},
                        "outputPath": {"type": "string"},
                        "startZoom": {"type": "integer", "minimum": 0},
                        "endZoom": {"type": "integer", "minimum": 0},
                        "maxTriangles": {"type": "integer", "minimum": 1024},
                        "bounds": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                        "threads": {"type": "integer", "minimum": 1},
                        "maxMemory": {"type": "string"},
                        "compression": {"type": "boolean"},
                        "decompress": {"type": "boolean"},
                        "autoZoom": {"type": "boolean"},
                        "zoomStrategy": {"type": "string", "enum": ["conservative", "balanced", "aggressive"], "example": "conservative"},
                        "mergeTerrains": {"type": "boolean"},
                    },
                    "required": ["filePatterns", "outputPath"],
                },
                "TaskStatus": {
                    "type": "string",
                    "enum": ["queued", "running", "completed", "failed", "stopped"],
                    "description": "任务运行状态。映射：queued=排队中，running=执行中，completed=已完成，failed=失败，stopped=已停止。",
                },
                "TaskCreateData": {
                    "type": "object",
                    "properties": {
                        "taskId": {"type": "string"},
                        "status": {"$ref": "#/components/schemas/TaskStatus"},
                        "statusUrl": {"type": "string"},
                        "message": {"type": "string"},
                        "method": {"type": "string"},
                        "parameters": {"type": "object", "additionalProperties": True},
                        "indexInfo": {"type": "object", "additionalProperties": True},
                        "processingInfo": {"type": "object", "additionalProperties": True},
                        "errors": {"type": "array", "items": {"type": "string"}},
                    },
                    "additionalProperties": True,
                },
                "ApiEnvelopeTaskCreate": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/TaskCreateData"},
                        "meta": {"type": "object", "additionalProperties": True},
                        "error": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "TaskResultSummary": {
                    "type": "object",
                    "properties": {
                        "completedFiles": {"type": "integer"},
                        "failedFiles": {"type": "integer"},
                        "totalFiles": {"type": "integer"},
                        "totalTerrainFiles": {"type": "integer"},
                        "outputPath": {"type": "string"},
                        "mergedOutputPath": {"type": "string"},
                        "deletedNodataTiles": {"type": "integer"},
                        "method": {"type": "string"},
                        "artifactId": {"type": "string"},
                        "artifactType": {"type": "string"},
                        "manifestFile": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "TaskSummary": {
                    "type": "object",
                    "properties": {
                        "taskId": {"type": "string"},
                        "status": {"$ref": "#/components/schemas/TaskStatus"},
                        "progress": {"type": "integer"},
                        "message": {"type": "string"},
                        "startTime": {"type": "string"},
                        "endTime": {"type": "string"},
                        "currentStage": {"type": "string"},
                        "result": {"$ref": "#/components/schemas/TaskResultSummary"},
                        "stats": {"type": "object", "additionalProperties": True},
                        "files": {
                            "description": "任务文件清单，结构随任务类型变化。",
                        },
                    },
                    "additionalProperties": True,
                },
                "TaskListData": {
                    "type": "object",
                    "properties": {
                        "tasks": {
                            "type": "object",
                            "additionalProperties": {"$ref": "#/components/schemas/TaskSummary"},
                        },
                        "count": {"type": "integer"},
                        "total": {"type": "integer"},
                        "page": {"type": "integer"},
                        "pageSize": {"type": "integer"},
                        "totalPages": {"type": "integer"},
                        "hasPrev": {"type": "boolean"},
                        "hasNext": {"type": "boolean"},
                    },
                    "additionalProperties": True,
                },
                "TaskDetailData": {
                    "type": "object",
                    "properties": {
                        "taskId": {"type": "string"},
                        "status": {"$ref": "#/components/schemas/TaskStatus"},
                        "progress": {"type": "integer"},
                        "message": {"type": "string"},
                        "startTime": {"type": "string"},
                        "endTime": {"type": "string"},
                        "currentStage": {"type": "string"},
                        "result": {"type": "object", "additionalProperties": True},
                        "stats": {"type": "object", "additionalProperties": True},
                        "files": {
                            "description": "任务文件清单，结构随任务类型变化。",
                        },
                    },
                    "additionalProperties": True,
                },
                "TaskEventRecord": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "eventType": {"type": "string"},
                        "eventAt": {"type": "string"},
                        "details": {"type": "object", "additionalProperties": True},
                    },
                    "additionalProperties": True,
                },
                "TaskEventsData": {
                    "type": "object",
                    "properties": {
                        "taskId": {"type": "string"},
                        "source": {"type": "string"},
                        "count": {"type": "integer"},
                        "events": {"type": "array", "items": {"$ref": "#/components/schemas/TaskEventRecord"}},
                    },
                    "additionalProperties": True,
                },
                "TaskDeleteData": {
                    "type": "object",
                    "properties": {
                        "taskId": {"type": "string"},
                        "deletedFromMemory": {"type": "boolean"},
                        "deletedFromDatabase": {"type": "boolean"},
                    },
                    "additionalProperties": True,
                },
                "TaskStopData": {
                    "type": "object",
                    "properties": {
                        "taskId": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "TaskCleanupData": {
                    "type": "object",
                    "properties": {
                        "remainingTasks": {"type": "integer"},
                    },
                    "additionalProperties": True,
                },
                "ApiEnvelopeTaskList": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/TaskListData"},
                        "meta": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "ApiEnvelopeTaskDetail": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/TaskDetailData"},
                        "meta": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "ApiEnvelopeTaskEvents": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/TaskEventsData"},
                        "meta": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "ApiEnvelopeTaskDelete": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/TaskDeleteData"},
                        "meta": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "ApiEnvelopeTaskStop": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/TaskStopData"},
                        "meta": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "ApiEnvelopeTaskCleanup": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/TaskCleanupData"},
                        "meta": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "PublicationUpsertRequest": {
                    "type": "object",
                    "properties": {
                        "sourceMode": {
                            "type": "string",
                            "enum": ["task", "manual", "artifact"],
                            "description": "发布来源模式。前端发布中心使用 task 或 manual。",
                            "example": "task",
                        },
                        "publicationId": {
                            "type": "string",
                            "description": "发布 ID。为空时服务端自动生成。",
                            "example": "publication-imagery-release-v1",
                        },
                        "taskId": {
                            "type": "string",
                            "description": "任务发布时使用的任务 ID。",
                            "example": "indexedTiles1774342374",
                        },
                        "artifactId": {
                            "type": "string",
                            "description": "按产物发布时使用的产物 ID。",
                            "example": "artifact-indexedTiles1774342374",
                        },
                        "workspacePath": {
                            "type": "string",
                            "description": "手动目录发布时的工作空间相对路径。",
                            "example": "测试切片-20260321/0327",
                        },
                        "sourcePath": {
                            "type": "string",
                            "description": "workspacePath 的别名字段；两者任选其一。",
                        },
                        "publishPath": {
                            "type": "string",
                            "description": "实际对外发布的目录相对路径；通常与 workspacePath 一致。",
                            "example": "测试切片-20260321/0327",
                        },
                        "alias": {
                            "type": "string",
                            "description": "发布别名，对应前端“发布别名”。",
                            "example": "imagery-release-v1",
                        },
                        "publishType": {
                            "type": "string",
                            "enum": ["imagery", "electronic-map", "terrain", "3dtiles", "geo"],
                            "description": "发布类型，对应前端“发布类型”。",
                            "example": "imagery",
                        },
                        "publishMethod": {
                            "type": "string",
                            "enum": ["xyz", "tms", "wmts", "terrain", "cesium-terrain", "quantized-mesh", "3d-tiles", "wms", "wfs", "static-download"],
                            "description": "发布方式，对应前端“发布方式”。",
                            "example": "wmts",
                        },
                        "visibility": {
                            "type": "string",
                            "enum": ["private", "internal", "public"],
                            "description": "可见性，对应前端“可见性”。",
                            "example": "private",
                        },
                        "enabled": {
                            "type": "boolean",
                            "description": "是否启用发布，对应前端“启用状态”。",
                            "example": True,
                        },
                        "note": {
                            "type": "string",
                            "description": "发布说明，对应前端“发布说明”。",
                            "example": "记录来源、用途和版本说明",
                        },
                        "customMetadata": {
                            "type": "object",
                            "description": "业务扩展字段，推荐通过扁平请求中的 customMetadata 传入。",
                            "additionalProperties": True,
                        },
                    },
                    "anyOf": [
                        {"required": ["taskId"]},
                        {"required": ["artifactId"]},
                        {"required": ["workspacePath"]},
                        {"required": ["sourcePath"]},
                    ],
                    "description": "创建或更新发布记录。推荐使用扁平字段：sourceMode、taskId/artifactId/workspacePath/sourcePath、alias、publicationId、publishType、publishMethod、visibility、enabled、note、customMetadata。",
                },
                "PublicationStatus": {
                    "type": "string",
                    "enum": ["enabled", "disabled", "published", "active", "draft", "failed"],
                    "description": "发布状态。映射：enabled=已启用，disabled=未启用，published=已发布(兼容)，active=激活(兼容)，draft=草稿，failed=失败。当前系统主要写入 enabled/disabled。",
                },
                "PublicationSourceMode": {
                    "type": "string",
                    "enum": ["task", "manual", "artifact"],
                },
                "PublicationPublishType": {
                    "type": "string",
                    "enum": ["imagery", "electronic-map", "terrain", "3dtiles", "geo"],
                },
                "PublicationPublishMethod": {
                    "type": "string",
                    "enum": ["xyz", "tms", "wmts", "terrain", "cesium-terrain", "quantized-mesh", "3d-tiles", "wms", "wfs", "static-download"],
                },
                "PublicationVisibility": {
                    "type": "string",
                    "enum": ["private", "internal", "public"],
                },
                "PublicationMetadata": {
                    "type": "object",
                    "properties": {
                        "workspacePath": {"type": "string"},
                        "taskId": {"type": "string"},
                        "sourceMode": {"$ref": "#/components/schemas/PublicationSourceMode"},
                        "publishMethod": {"$ref": "#/components/schemas/PublicationPublishMethod"},
                        "visibility": {"$ref": "#/components/schemas/PublicationVisibility"},
                        "note": {"type": "string"},
                        "enabled": {"type": "boolean"},
                        "customMetadata": {"type": "object", "additionalProperties": True},
                    },
                    "additionalProperties": True,
                },
                "PublicationRecord": {
                    "type": "object",
                    "properties": {
                        "publicationId": {"type": "string"},
                        "artifactId": {"type": "string"},
                        "publishType": {"$ref": "#/components/schemas/PublicationPublishType"},
                        "publishPath": {"type": "string"},
                        "alias": {"type": "string"},
                        "status": {"$ref": "#/components/schemas/PublicationStatus"},
                        "publishMethod": {"$ref": "#/components/schemas/PublicationPublishMethod"},
                        "visibility": {"$ref": "#/components/schemas/PublicationVisibility"},
                        "enabled": {"type": "boolean"},
                        "note": {"type": "string"},
                        "customMetadata": {"type": "object", "additionalProperties": True},
                        "metadata": {"$ref": "#/components/schemas/PublicationMetadata"},
                        "browserUrl": {"type": "string"},
                        "accessUrl": {"type": "string"},
                        "launchUrl": {"type": "string"},
                        "sampleUrl": {"type": "string"},
                        "publicBaseUrl": {"type": "string"},
                        "publishedAt": {"type": "string"},
                        "createdAt": {"type": "string"},
                        "updatedAt": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "PublicationListData": {
                    "type": "object",
                    "properties": {
                        "publications": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/PublicationRecord"},
                        },
                        "count": {"type": "integer"},
                        "total": {"type": "integer"},
                        "page": {"type": "integer"},
                        "pageSize": {"type": "integer"},
                        "totalPages": {"type": "integer"},
                        "hasPrev": {"type": "boolean"},
                        "hasNext": {"type": "boolean"},
                    },
                    "additionalProperties": True,
                },
                "PublicationDetailData": {
                    "type": "object",
                    "properties": {
                        "publication": {"$ref": "#/components/schemas/PublicationRecord"},
                    },
                    "additionalProperties": True,
                },
                "PublicationDeleteData": {
                    "type": "object",
                    "properties": {
                        "publicationId": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
                "ApiEnvelopePublicationList": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/PublicationListData"},
                        "meta": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "ApiEnvelopePublicationDetail": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/PublicationDetailData"},
                        "meta": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "ApiEnvelopePublicationMutation": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/PublicationDetailData"},
                        "meta": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "ApiEnvelopePublicationDelete": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"$ref": "#/components/schemas/PublicationDeleteData"},
                        "meta": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta"],
                },
                "ApiEnvelopeError": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean", "enum": [False]},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "data": {"type": "object", "nullable": True, "additionalProperties": True},
                        "meta": {"type": "object", "additionalProperties": True},
                        "error": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["success", "code", "message", "data", "meta", "error"],
                },
            }
        },
    }
    _annotate_enum_descriptions(spec)
    _strip_enum_definitions(spec)
    return spec


def _unauthorized_response():
    return Response(
        "Unauthorized",
        status=401,
        headers={"WWW-Authenticate": 'Basic realm="AtlasWorks API Docs"'},
        mimetype="text/plain; charset=utf-8",
    )


def _is_docs_auth_valid():
    expected_password = str(config.get("docsAuthPassword") or "").strip()
    if not expected_password:
        return True

    auth = request.authorization
    if not auth:
        return False

    expected_user = str(config.get("docsAuthUser") or "").strip()
    if expected_user and str(auth.username or "").strip() != expected_user:
        return False

    return str(auth.password or "") == expected_password


def _require_docs_auth():
    if _is_docs_auth_valid():
        return None
    return _unauthorized_response()


def getOpenApiSpec():
    auth_result = _require_docs_auth()
    if auth_result:
        return auth_result
    return jsonify(_openapi_spec())


def getSwaggerUi():
    auth_result = _require_docs_auth()
    if auth_result:
        return auth_result

    spec_json = json.dumps(_openapi_spec(), ensure_ascii=False).replace("</", "<\\/")

    html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AtlasWorks API Reference</title>
  <style>
    :root {
      color-scheme: light only;
      --aw-bg: #f4f7fb;
      --aw-panel: #ffffff;
      --aw-text: #1f2d3d;
      --aw-muted: #64748b;
      --aw-border: #d8e2f0;
      --aw-primary: #2563eb;
      --aw-shadow: 0 14px 40px rgba(15, 23, 42, 0.08);
    }

    * {
      box-sizing: border-box;
    }

    html, body {
      margin: 0;
      height: 100%;
      background: var(--aw-bg);
      color: var(--aw-text);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }

    .docs-shell {
      display: flex;
      flex-direction: column;
      height: 100%;
    }

    .docs-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 16px;
      border-bottom: 1px solid var(--aw-border);
      background: var(--aw-panel);
      box-shadow: var(--aw-shadow);
    }

    .docs-title {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
      font-size: 16px;
      font-weight: 700;
      color: #162638;
    }

    .docs-title small {
      font-size: 12px;
      color: var(--aw-muted);
      font-weight: 600;
    }

    .docs-links {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      font-size: 13px;
    }

    .docs-links a {
      color: var(--aw-primary);
      text-decoration: none;
      font-weight: 600;
    }

    .docs-links a:hover {
      text-decoration: underline;
    }

    #api-reference {
      flex: 1 1 auto;
      min-height: 0;
    }

    @media (max-width: 900px) {
      .docs-head {
        flex-direction: column;
        align-items: flex-start;
      }
    }
  </style>
</head>
<body>
  <div class="docs-shell">
    <header class="docs-head">
      <div class="docs-title">
        AtlasWorks API Reference
        <small>Scalar UI</small>
      </div>
      <div class="docs-links">
        <a href="/api/openapi.json" target="_blank" rel="noreferrer">OpenAPI JSON</a>
      </div>
    </header>
    <div id="api-reference"></div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
  <script>
    window.addEventListener("DOMContentLoaded", function () {
      const inlineSpec = """ + json.dumps(spec_json) + """;
      Scalar.createApiReference("#api-reference", {
        content: inlineSpec,
        theme: "kepler",
        forceDarkModeState: "light",
        hideDarkModeToggle: true,
        hideModels: true,
        showDeveloperTools: "never",
        hideClientButton: true,
        showSidebar: true,
        withDefaultFonts: true,
        mcp: {
          name: "AtlasWorks",
          url: "https://mcp.example.com",
          disabled: true
        },
        agent: {
          disabled: true
        }
      });

      const sidebarLabelMap = {
        "Introduction": "简介",
        "Models": "模型"
      };
      const localizeSidebarLabels = function () {
        const sidebar = document.querySelector("#api-reference aside");
        if (!sidebar) {
          return;
        }
        const allNodes = sidebar.querySelectorAll("*");
        allNodes.forEach(function (node) {
          if (!node || node.children.length > 0) {
            return;
          }
          const raw = (node.textContent || "").trim();
          const mapped = sidebarLabelMap[raw];
          if (mapped) {
            node.textContent = mapped;
          }
        });
      };

      localizeSidebarLabels();
      const observer = new MutationObserver(localizeSidebarLabels);
      const root = document.getElementById("api-reference");
      if (root) {
        observer.observe(root, { childList: true, subtree: true });
      }
    });
  </script>
</body>
</html>
"""
    return Response(html, mimetype="text/html; charset=utf-8")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re

from flask import Response, current_app, jsonify, request

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
        "responses": {
            "200": {
                "description": "返回任务状态快照",
                "content": {
                    "application/json": {
                        "examples": {
                            "tasks": {
                                "value": {
                                    "success": True,
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
            }
        },
    },
    ("/api/publications", "get"): {
        "summary": "发布列表",
        "responses": {
            "200": {
                "description": "返回发布记录列表",
                "content": {
                    "application/json": {
                        "examples": {
                            "publication_list": {
                                "value": {
                                    "success": True,
                                    "count": 1,
                                    "publications": [
                                        {
                                            "publicationId": "publication-0324-test",
                                            "publishType": "imagery",
                                            "publishPath": "demo/output",
                                            "status": "enabled",
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
        "responses": {
            "200": {
                "description": "创建成功",
                "content": {
                    "application/json": {
                        "examples": {
                            "created": {
                                "value": {
                                    "success": True,
                                    "publication": {
                                        "publicationId": "publication-0324-test",
                                        "status": "enabled",
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
                        "examples": {"invalid": {"value": {"error": "缺少参数: taskId、artifactId 或 workspacePath"}}}
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
                        "examples": {
                            "publication_detail": {
                                "value": {
                                    "success": True,
                                    "publication": {
                                        "publicationId": "publication-0324-test",
                                        "alias": "0324-test",
                                        "publishType": "imagery",
                                        "publishPath": "demo/output",
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
                        "examples": {"not_found": {"value": {"error": "发布记录不存在"}}}
                    }
                },
            },
        },
    },
    ("/api/artifacts", "get"): {
        "summary": "产物列表",
        "responses": {
            "200": {
                "description": "返回产物列表",
                "content": {
                    "application/json": {
                        "examples": {
                            "artifacts": {
                                "value": {
                                    "success": True,
                                    "count": 1,
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
}


def _tag_for_path(path):
    normalized_path = str(path or "").lower()
    if normalized_path.startswith("/api/health") or normalized_path.startswith("/api/system") or normalized_path.startswith("/api/container"):
        return "System"
    if normalized_path.startswith("/api/datasource") or normalized_path.startswith("/api/upload") or normalized_path.startswith("/api/files/extract") or normalized_path.startswith("/api/preflight"):
        return "Datasource"
    if normalized_path.startswith("/api/tile") or normalized_path.startswith("/api/terrain") or normalized_path.startswith("/api/tiles"):
        return "Tiles"
    if normalized_path.startswith("/api/task"):
        return "Tasks"
    if normalized_path.startswith("/api/publication") or normalized_path.startswith("/api/artifact"):
        return "Publication"
    if normalized_path.startswith("/api/workspace") or normalized_path.startswith("/api/results") or normalized_path.startswith("/api/filedetails"):
        return "Workspace"
    if normalized_path.startswith("/api/config") or normalized_path.startswith("/api/cache"):
        return "Config"
    if normalized_path.startswith("/api/docs") or normalized_path.startswith("/api/openapi") or normalized_path.startswith("/api/routes"):
        return "Docs"
    return "Misc"


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


def _build_paths():
    paths = {}

    for rule in current_app.url_map.iter_rules():
        route_path = str(rule.rule or "")
        if route_path.startswith("/static"):
            continue
        if route_path in {"/", "/console"}:
            continue
        if not (route_path.startswith("/api/") or route_path.startswith("/published")):
            continue

        openapi_path = _flask_path_to_openapi(route_path)
        methods = sorted(method.lower() for method in (rule.methods or set()) if method not in {"HEAD", "OPTIONS"})
        if not methods:
            continue

        path_item = paths.setdefault(openapi_path, {})
        for method in methods:
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

            override = _OPERATION_OVERRIDES.get((openapi_path, method))
            operation = _merge_operation(operation, override)
            path_item[method] = operation

    return dict(sorted(paths.items(), key=lambda item: item[0]))


def _openapi_spec():
    server_url = request.host_url.rstrip("/")
    return {
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
            {"name": "System", "description": "系统与健康状态"},
            {"name": "Datasource", "description": "数据源解析与预处理"},
            {"name": "Tiles", "description": "地图/地形切片任务"},
            {"name": "Tasks", "description": "任务管理"},
            {"name": "Publication", "description": "发布与产物管理"},
            {"name": "Workspace", "description": "工作空间与文件管理"},
            {"name": "Config", "description": "配置与缓存相关接口"},
            {"name": "Docs", "description": "接口文档相关接口"},
            {"name": "Misc", "description": "其他接口"},
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
                "IndexedTilesRequest": {
                    "type": "object",
                    "properties": {
                        "folderPaths": {"type": "array", "items": {"type": "string"}},
                        "filePatterns": {"type": "array", "items": {"type": "string"}},
                        "outputPath": {"type": "string"},
                        "minZoom": {"type": "integer"},
                        "maxZoom": {"type": "integer"},
                        "tileSize": {"type": "integer"},
                        "processes": {"type": "integer"},
                        "threads": {"type": "integer"},
                        "projection": {"type": "string"},
                        "dataFormat": {"type": "string"},
                        "imageFormat": {"type": "string"},
                        "tileScheme": {"type": "string"},
                        "redBand": {"type": "integer"},
                        "greenBand": {"type": "integer"},
                        "blueBand": {"type": "integer"},
                    },
                    "required": ["filePatterns", "outputPath"],
                },
                "TerrainTilesRequest": {
                    "type": "object",
                    "properties": {
                        "folderPaths": {"type": "array", "items": {"type": "string"}},
                        "filePatterns": {"type": "array", "items": {"type": "string"}},
                        "outputPath": {"type": "string"},
                        "startZoom": {"type": "integer"},
                        "endZoom": {"type": "integer"},
                        "threads": {"type": "integer"},
                        "maxMemory": {"type": "string"},
                        "compression": {"type": "boolean"},
                        "decompress": {"type": "boolean"},
                    },
                    "required": ["filePatterns", "outputPath"],
                },
            }
        },
    }


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

    html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AtlasWorks API Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  <style>
    body { margin: 0; background: #ffffff; color: #111827; font-family: "Segoe UI", "PingFang SC", sans-serif; }
    .doc-head { padding: 12px 18px; border-bottom: 1px solid #e5e7eb; background: #ffffff; color: #111827; }
    .doc-head a { color: #2563eb; text-decoration: none; margin-left: 12px; }
    .doc-head a:hover { text-decoration: underline; }
    .swagger-ui { background: #ffffff; }
    .swagger-ui .topbar { background: #ffffff; border-bottom: 1px solid #e5e7eb; }
    .swagger-ui .topbar .download-url-wrapper { display: none; }
  </style>
</head>
<body>
  <div class="doc-head">
    AtlasWorks 在线接口文档
    <a href="/api/openapi.json" target="_blank" rel="noreferrer">查看 OpenAPI JSON</a>
  </div>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = function () {
      window.ui = SwaggerUIBundle({
        url: '/api/openapi.json',
        dom_id: '#swagger-ui',
        deepLinking: true,
        displayRequestDuration: true,
        defaultModelsExpandDepth: 1
      });
    };
  </script>
</body>
</html>
"""
    return Response(html, mimetype="text/html; charset=utf-8")

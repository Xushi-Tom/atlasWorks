#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
from datetime import datetime

from flask import jsonify, request

from config import config, taskLock, taskStatus
from db import checkDatabaseHealth, countTableRows
from pagination import paginate_items, parse_pagination_args
from utils import logMessage
from version import APP_VERSION


def healthCheck():
    database_health = checkDatabaseHealth()
    service_status = "healthy"
    if database_health.get("enabled") and database_health.get("status") not in {"healthy", "disabled"}:
        service_status = "degraded"

    with taskLock:
        running_tasks = len([t for t in taskStatus.values() if t.get("status") == "running"])
        queued_tasks = len([t for t in taskStatus.values() if t.get("status") == "queued"])

    response = {
        "status": service_status,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": APP_VERSION,
        "database": database_health,
        "tasks": {
            "inMemoryTotal": len(taskStatus),
            "running": running_tasks,
            "queued": queued_tasks,
        },
        "catalog": {
            "artifacts": countTableRows("tf_artifacts") if database_health.get("enabled") else 0,
            "publications": countTableRows("tf_publications") if database_health.get("enabled") else 0,
            "taskEvents": countTableRows("tf_job_events") if database_health.get("enabled") else 0,
        },
    }
    return jsonify(response)


def systemInfo():
    try:
        logMessage("收到系统信息查询请求", "INFO")
        system_info = {
            "timestamp": datetime.now().isoformat(),
            "version": APP_VERSION,
            "config": {
                "dataSourceDir": config["dataSourceDir"],
                "dataSourceHostDir": config.get("dataSourceHostDir") or "",
                "tilesDir": config["tilesDir"],
                "tilesHostDir": config.get("tilesHostDir") or "",
                "publicBaseUrl": config.get("publicBaseUrl") or "",
                "publicBaseMode": config.get("publicBaseMode") or "auto",
                "publicBaseHost": config.get("publicBaseHost") or "",
                "publicBasePort": config.get("publicBasePort") or 0,
                "publicBaseScheme": config.get("publicBaseScheme") or "",
                "publicationRequireDb": bool(config.get("publicationRequireDb", True)),
                "maxThreads": config["maxThreads"],
                "supportedFormats": config["supportedFormats"],
            },
        }

        try:
            import psutil

            system_info["system"] = {
                "cpuCount": psutil.cpu_count(),
                "memoryTotal": psutil.virtual_memory().total,
                "memoryAvailable": psutil.virtual_memory().available,
                "diskUsage": psutil.disk_usage("/").percent,
            }
        except Exception:
            system_info["system"] = {
                "cpuCount": 4,
                "memoryTotal": 8589934592,
                "memoryAvailable": 4294967296,
                "diskUsage": 50,
            }

        with taskLock:
            system_info["tasks"] = {
                "total": len(taskStatus),
                "running": len([t for t in taskStatus.values() if t.get("status") == "running"]),
                "completed": len([t for t in taskStatus.values() if t.get("status") == "completed"]),
                "failed": len([t for t in taskStatus.values() if t.get("status") == "failed"]),
            }

        database_health = checkDatabaseHealth()
        system_info["database"] = database_health
        system_info["catalog"] = {
            "artifacts": countTableRows("tf_artifacts") if database_health.get("enabled") else 0,
            "publications": countTableRows("tf_publications") if database_health.get("enabled") else 0,
            "taskEvents": countTableRows("tf_job_events") if database_health.get("enabled") else 0,
        }
        return jsonify(system_info)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def listApiRoutes():
    try:
        page, page_size = parse_pagination_args(request.args, default_page_size=10, max_page_size=200)
        keyword = str(request.args.get("keyword", "")).strip().lower()
        routes = [
            {"path": "/api/health", "methods": ["GET"], "description": "健康检查", "category": "系统监控", "logic": "返回服务健康状态、时间戳和版本信息"},
            {"path": "/api/dataSources", "methods": ["GET"], "description": "获取数据源列表", "category": "数据源管理", "logic": "浏览根目录或指定子目录的TIF文件，支持地理范围筛选"},
            {"path": "/api/dataSources/<path:subpath>", "methods": ["GET"], "description": "获取子目录数据源", "category": "数据源管理", "logic": "浏览指定子目录的TIF文件，支持地理范围筛选"},
            {"path": "/api/dataSources/info/<filename>", "methods": ["GET"], "description": "获取数据源信息", "category": "数据源管理", "logic": "获取TIF文件的元数据、地理信息和智能切片配置推荐"},
            {"path": "/api/dataSources/workspace", "methods": ["GET"], "description": "获取数据源挂载信息", "category": "数据源管理", "logic": "返回数据源在容器内路径与宿主机挂载提示信息"},
            {"path": "/api/upload/file", "methods": ["POST"], "description": "上传单文件到数据源", "category": "数据源管理", "logic": "上传单个 tif/tiff/txt 等文件到 dataSource 目录"},
            {"path": "/api/upload/zip", "methods": ["POST"], "description": "上传 ZIP 并解压", "category": "数据源管理", "logic": "上传 zip 并解压到 dataSource 目录，带 zip-slip 防护和大小限制"},
            {"path": "/api/upload/folder", "methods": ["POST"], "description": "上传文件夹", "category": "数据源管理", "logic": "浏览器选择文件夹上传，保留相对目录结构写入 dataSource 目录"},
            {"path": "/api/files/extract", "methods": ["POST"], "description": "解压已上传压缩文件", "category": "数据源管理", "logic": "将数据源或工作空间中的 zip、tar、7z 压缩文件解压到其所在目录"},
            {"path": "/api/dataSources/split", "methods": ["POST"], "description": "拆分大文件", "category": "数据源管理", "logic": "将超大栅格按像素窗口拆分为多个较小的 TIF 文件，便于后续切片或重处理"},
            {"path": "/api/datasources/createFolder", "methods": ["POST"], "description": "创建数据源文件夹", "category": "数据源管理", "logic": "在数据源目录中创建新的目录节点"},
            {"path": "/api/datasources/folder/<path:folderPath>", "methods": ["DELETE"], "description": "删除数据源文件夹", "category": "数据源管理", "logic": "删除指定的数据源目录及其内容"},
            {"path": "/api/datasources/file/<path:filePath>", "methods": ["DELETE"], "description": "删除数据源文件", "category": "数据源管理", "logic": "删除指定的数据源文件"},
            {"path": "/api/preflight", "methods": ["POST"], "description": "执行构建预检查", "category": "数据源管理", "logic": "在正式构建前检查输入文件、工具链、波段与输出覆盖风险，并返回资源估算"},
            {"path": "/api/tile/terrain", "methods": ["POST"], "description": "创建地形瓦片（支持合并）", "category": "瓦片生成", "logic": "使用CTB生成地形瓦片，支持批量处理、智能缩放和地形合并。filePatterns 支持 http/https 网络地址；参数mergeTerrains=true可自动合并多个地形文件夹"},
            {"path": "/api/tile/indexedTiles", "methods": ["POST"], "description": "创建索引瓦片", "category": "瓦片生成", "logic": "基于空间索引的高性能瓦片生成，支持多进程并行处理，filePatterns 支持 http/https 网络地址"},
            {"path": "/api/tile/mvt", "methods": ["POST"], "description": "创建 MVT 矢量切片", "category": "瓦片生成", "logic": "将 GeoJSON、SHP、GPKG 等矢量源构建为静态 MVT（.pbf）目录，并复用现有任务与发布体系"},
            {"path": "/api/tile/3dtiles", "methods": ["POST"], "description": "创建 3D Tiles", "category": "瓦片生成", "logic": "按输入类型生成 3D Tiles 输出目录，支持 pointcloud/vector/model/osgb 并复用现有任务与发布体系"},
            {"path": "/api/tile/convert", "methods": ["POST"], "description": "瓦片格式转换", "category": "瓦片生成", "logic": "z/x_y.png ↔ z/x/y.png格式转换，支持批量处理"},
            {"path": "/api/fileDetails", "methods": ["GET"], "description": "获取文件详情", "category": "工作空间管理", "logic": "根据 type 和 path 查询数据源或结果目录中的单个文件详情"},
            {"path": "/api/tasks", "methods": ["GET"], "description": "获取任务列表", "category": "任务管理", "logic": "返回所有任务的状态、进度和基本信息"},
            {"path": "/api/tasks/<taskId>", "methods": ["GET"], "description": "获取任务状态", "category": "任务管理", "logic": "获取指定任务的详细状态、进度和结果信息"},
            {"path": "/api/tasks/<taskId>/events", "methods": ["GET"], "description": "获取任务事件流", "category": "任务管理", "logic": "读取任务状态变化和阶段切换事件，数据库不可用时回退内存 processLog"},
            {"path": "/api/tasks/cleanup", "methods": ["POST"], "description": "清理任务", "category": "任务管理", "logic": "清理已完成、失败或取消的任务记录"},
            {"path": "/api/tasks/<taskId>/stop", "methods": ["POST"], "description": "停止任务", "category": "任务管理", "logic": "停止正在运行的任务并释放资源"},
            {"path": "/api/tasks/<taskId>", "methods": ["DELETE"], "description": "删除任务", "category": "任务管理", "logic": "删除任务记录和相关数据"},
            {"path": "/api/artifacts", "methods": ["GET"], "description": "列出产物", "category": "产物管理", "logic": "返回数据库和 manifest 中可见的构建产物列表"},
            {"path": "/api/artifacts/<artifactId>", "methods": ["GET"], "description": "获取产物详情", "category": "产物管理", "logic": "读取指定产物的元数据、输出路径和 manifest 索引信息"},
            {"path": "/api/artifacts/<artifactId>/manifest", "methods": ["GET"], "description": "获取产物 manifest", "category": "产物管理", "logic": "读取指定产物目录中的 manifest.json 内容"},
            {"path": "/api/publications", "methods": ["GET", "POST"], "description": "管理发布记录", "category": "发布管理", "logic": "列出或创建产物发布记录，形成基础发布台账"},
            {"path": "/api/publications/<publicationId>", "methods": ["GET"], "description": "获取发布详情", "category": "发布管理", "logic": "查看指定发布记录的目标产物、别名和发布路径"},
            {"path": "/api/publications/<publicationId>", "methods": ["PUT"], "description": "更新发布记录", "category": "发布管理", "logic": "更新指定发布记录的发布方式、启用状态、别名和元数据"},
            {"path": "/api/publications/<publicationId>", "methods": ["DELETE"], "description": "删除发布记录", "category": "发布管理", "logic": "删除指定发布记录及其落盘描述文件"},
            {"path": "/publication-assets/<publicationId>/<path:relative_path>", "methods": ["GET"], "description": "访问指定发布记录资源", "category": "发布管理", "logic": "按 publicationId 访问发布资源，并在 XYZ/TMS 场景下自动换算瓦片行号"},
            {"path": "/published", "methods": ["GET"], "description": "浏览发布根目录", "category": "发布管理", "logic": "浏览已发布目录的根节点或入口资源"},
            {"path": "/published/<path:relative_path>", "methods": ["GET"], "description": "访问发布资源", "category": "发布管理", "logic": "读取已发布目录下的目录索引、静态文件或瓦片资源"},
            {"path": "/wmts", "methods": ["GET"], "description": "WMTS 服务", "category": "发布管理", "logic": "提供 WMTS GetCapabilities 与 GetTile 接口，用于访问已发布 WMTS 图层"},
            {"path": "/api/config/recommend", "methods": ["POST"], "description": "推荐配置", "category": "配置管理", "logic": "根据文件特征和系统资源推荐最优切片配置"},
            {"path": "/api/cache/info", "methods": ["GET"], "description": "获取缓存信息", "category": "配置管理", "logic": "扫描瓦片输出目录，返回元数据、索引文件和实际瓦片数量等缓存情况"},
            {"path": "/api/system/info", "methods": ["GET"], "description": "系统信息", "category": "系统监控", "logic": "返回系统资源使用情况、任务统计和性能指标"},
            {"path": "/api/container/update", "methods": ["POST"], "description": "更新Docker容器信息", "category": "系统监控", "logic": "更新容器时间同步、配置等系统信息"},
            {"path": "/api/workspace/createFolder", "methods": ["POST"], "description": "创建工作空间文件夹", "category": "工作空间管理", "logic": "在瓦片输出目录中创建新文件夹"},
            {"path": "/api/workspace/folder/<path:folderPath>", "methods": ["DELETE"], "description": "删除工作空间文件夹", "category": "工作空间管理", "logic": "删除指定的工作空间文件夹及其内容"},
            {"path": "/api/workspace/folder/<path:folderPath>/rename", "methods": ["PUT"], "description": "重命名工作空间文件夹", "category": "工作空间管理", "logic": "重命名指定的工作空间文件夹"},
            {"path": "/api/workspace/file/<path:filePath>", "methods": ["DELETE"], "description": "删除工作空间文件", "category": "工作空间管理", "logic": "删除指定的工作空间文件"},
            {"path": "/api/workspace/file/<path:filePath>/rename", "methods": ["PUT"], "description": "重命名工作空间文件", "category": "工作空间管理", "logic": "重命名指定的工作空间文件"},
            {"path": "/api/workspace/move", "methods": ["PUT"], "description": "移动工作空间项目", "category": "工作空间管理", "logic": "移动工作空间中的文件或文件夹到新位置"},
            {"path": "/api/workspace/info", "methods": ["GET"], "description": "获取工作空间信息", "category": "工作空间管理", "logic": "获取工作空间统计信息：总大小、文件数、目录数等"},
            {"path": "/api/workspace/raw/<path:filename>", "methods": ["GET"], "description": "预览工作空间图片", "category": "工作空间管理", "logic": "返回工作空间中的 PNG/JPG/JPEG 原图供前端弹窗直接预览"},
            {"path": "/api/tiles/nodata/scan", "methods": ["POST"], "description": "扫描包含透明（nodata）值的PNG瓦片", "category": "瓦片管理", "logic": "扫描指定目录中包含透明或nodata值的PNG瓦片"},
            {"path": "/api/tiles/nodata/delete", "methods": ["POST"], "description": "删除包含透明（nodata）值的PNG瓦片", "category": "瓦片管理", "logic": "删除扫描到的透明或nodata瓦片文件"},
            {"path": "/api/terrain/layer", "methods": ["POST"], "description": "更新地形瓦片的layer.json文件", "category": "地形处理", "logic": "修复和更新地形瓦片的layer.json元数据文件"},
            {"path": "/api/terrain/decompress", "methods": ["POST"], "description": "解压地形瓦片", "category": "地形处理", "logic": "解压缩地形瓦片文件（.terrain.gz → .terrain）"},
            {"path": "/api/routes", "methods": ["GET"], "description": "API路由列表", "category": "API文档", "logic": "返回所有可用API接口的详细信息和统计数据"},
            {"path": "/api/openapi.json", "methods": ["GET"], "description": "OpenAPI 文档", "category": "API文档", "logic": "返回 Swagger/OpenAPI 规范 JSON"},
            {"path": "/api/docs", "methods": ["GET"], "description": "在线接口文档", "category": "API文档", "logic": "Swagger 风格在线文档页面，可直接调试接口"},
        ]

        if keyword:
            routes = [
                route for route in routes
                if any(
                    keyword in str(field or "").lower()
                    for field in (
                        route.get("path"),
                        route.get("category"),
                        route.get("description"),
                        route.get("logic"),
                        ", ".join(route.get("methods", [])),
                    )
                )
            ]

        paged_routes, pagination = paginate_items(routes, page, page_size)
        categories = sorted(set(route["category"] for route in routes))
        return jsonify({
            "success": True,
            "routes": paged_routes,
            "categories": categories,
            **pagination,
            "stats": {
                "totalRoutes": len(routes),
                "byCategory": {category: len([r for r in routes if r["category"] == category]) for category in categories},
                "byMethod": {method: len([r for r in routes if method in r["methods"]]) for method in set(method for route in routes for method in route["methods"])},
            },
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def updateContainerInfo():
    """更新容器时间、环境、配置与基础系统状态。"""
    try:
        import socket
        import subprocess

        logMessage("收到 Docker 容器信息更新请求", "INFO")
        data = request.get_json(silent=True) if request.method == "POST" else {}
        update_type = data.get("updateType", "all")
        update_results = {
            "timestamp": datetime.now().isoformat(),
            "updateType": update_type,
            "version": APP_VERSION,
            "results": {},
        }

        if update_type in ["all", "time"]:
            try:
                time_results = {"actions": []}
                current_time = datetime.now()
                utc_time = datetime.utcnow()
                time_results["before"] = {
                    "localTime": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "utcTime": utc_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "timestamp": current_time.timestamp(),
                }

                try:
                    ntp_result = subprocess.run(["which", "ntpdate"], capture_output=True, text=True, timeout=5)
                    if ntp_result.returncode == 0:
                        sync_result = subprocess.run(["ntpdate", "-s", "time.nist.gov"], capture_output=True, text=True, timeout=30)
                        if sync_result.returncode == 0:
                            time_results["actions"].append("使用 ntpdate 同步网络时间成功")
                        else:
                            time_results["actions"].append(f"ntpdate 同步失败: {sync_result.stderr}")
                    else:
                        time_results["actions"].append("ntpdate 未安装，跳过网络时间同步")
                except Exception as exc:
                    time_results["actions"].append(f"时间同步异常: {str(exc)}")

                after_time = datetime.now()
                after_utc_time = datetime.utcnow()
                time_results["after"] = {
                    "localTime": after_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "utcTime": after_utc_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "timestamp": after_time.timestamp(),
                }
                time_results["timeDifferenceSeconds"] = after_time.timestamp() - current_time.timestamp()

                if "timezone" in data:
                    try:
                        timezone = data["timezone"]
                        os.environ["TZ"] = timezone
                        if hasattr(time, "tzset"):
                            time.tzset()
                            time_results["actions"].append("已调用 tzset 使时区配置立即生效")
                        time_results["actions"].append(f"设置时区为: {timezone}")
                    except Exception as exc:
                        time_results["actions"].append(f"设置时区失败: {str(exc)}")

                update_results["results"]["time"] = time_results
            except Exception as exc:
                update_results["results"]["time"] = {"error": str(exc)}

        if update_type in ["all", "environment"]:
            try:
                env_results = {"actions": [], "updated": {}}
                if "environment" in data:
                    for key, value in data["environment"].items():
                        try:
                            old_value = os.environ.get(key, "未设置")
                            os.environ[key] = str(value)
                            env_results["updated"][key] = {"old": old_value, "new": str(value)}
                            env_results["actions"].append(f"更新环境变量 {key}")
                        except Exception as exc:
                            env_results["actions"].append(f"更新环境变量 {key} 失败: {str(exc)}")

                gdal_env_vars = {
                    "GDAL_CACHEMAX": "512",
                    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
                    "GDAL_HTTP_TIMEOUT": "30",
                    "GDAL_HTTP_CONNECTTIMEOUT": "10",
                }
                for key, default_value in gdal_env_vars.items():
                    if key not in os.environ:
                        os.environ[key] = default_value
                        env_results["actions"].append(f"设置 GDAL 环境变量 {key} = {default_value}")

                update_results["results"]["environment"] = env_results
            except Exception as exc:
                update_results["results"]["environment"] = {"error": str(exc)}

        if update_type in ["all", "config"]:
            try:
                config_results = {"actions": [], "updated": {}}
                if "config" in data:
                    for key, value in data["config"].items():
                        if key in config:
                            old_value = config[key]
                            config[key] = value
                            config_results["updated"][key] = {"old": old_value, "new": value}
                            config_results["actions"].append(f"更新配置 {key}")
                        else:
                            config_results["actions"].append(f"配置项 {key} 不存在，跳过")

                for dir_key in ["dataSourceDir", "tilesDir", "logDir"]:
                    if dir_key in config and not os.path.exists(config[dir_key]):
                        os.makedirs(config[dir_key], exist_ok=True)
                        config_results["actions"].append(f"创建目录: {config[dir_key]}")

                update_results["results"]["config"] = config_results
            except Exception as exc:
                update_results["results"]["config"] = {"error": str(exc)}

        if update_type in ["all", "system"]:
            try:
                system_results = {"actions": []}
                try:
                    import tempfile

                    temp_dir = tempfile.gettempdir()
                    cutoff_time = datetime.now().timestamp() - 86400
                    cleaned_files = 0
                    for root, _, files in os.walk(temp_dir):
                        for filename in files:
                            file_path = os.path.join(root, filename)
                            try:
                                if os.path.getmtime(file_path) < cutoff_time:
                                    os.remove(file_path)
                                    cleaned_files += 1
                            except Exception:
                                pass
                    system_results["actions"].append(f"清理临时文件: {cleaned_files} 个")
                except Exception as exc:
                    system_results["actions"].append(f"清理临时文件失败: {str(exc)}")

                try:
                    if hasattr(os, "sync"):
                        os.sync()
                        system_results["actions"].append("同步文件系统缓存")
                except Exception:
                    pass

                update_results["results"]["system"] = system_results
            except Exception as exc:
                update_results["results"]["system"] = {"error": str(exc)}

        if update_type in ["all", "network"]:
            try:
                network_results = {"actions": []}
                try:
                    dns_result = subprocess.run(["nslookup", "google.com"], capture_output=True, text=True, timeout=10)
                    if dns_result.returncode == 0:
                        network_results["actions"].append("DNS 解析测试通过")
                    else:
                        network_results["actions"].append("DNS 解析测试失败")
                except Exception as exc:
                    network_results["actions"].append(f"DNS 测试异常: {str(exc)}")

                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.connect(("8.8.8.8", 80))
                    current_ip = sock.getsockname()[0]
                    sock.close()
                    network_results["actions"].append(f"当前 IP 地址: {current_ip}")
                except Exception as exc:
                    network_results["actions"].append(f"获取 IP 地址失败: {str(exc)}")

                update_results["results"]["network"] = network_results
            except Exception as exc:
                update_results["results"]["network"] = {"error": str(exc)}

        logMessage(f"容器信息更新完成: {update_type}", "INFO")
        return jsonify(
            {
                "success": True,
                "message": f"容器信息更新完成: {update_type}",
                "updateResults": update_results,
            }
        )
    except Exception as exc:
        logMessage(f"更新 Docker 容器信息失败: {str(exc)}", "ERROR")
        return jsonify({"error": f"更新容器信息失败: {str(exc)}"}), 500

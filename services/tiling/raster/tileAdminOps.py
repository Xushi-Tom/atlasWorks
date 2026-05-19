#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shutil
import subprocess
import threading
import time
from datetime import datetime

from flask import jsonify, request

from config import config, taskLock, taskStatus
from taskState import appendTaskLog, createTaskRecord
from utils import logMessage


def _normalize_tiles_relative_path(path_value):
    path = str(path_value or "").strip().replace("\\", "/").strip("/")
    return path


def _resolve_tiles_relative_path(path_value):
    relative_path = _normalize_tiles_relative_path(path_value)
    if not relative_path:
        raise ValueError("缺少缓存目录路径")
    tiles_root = os.path.abspath(config["tilesDir"])
    target_path = os.path.abspath(os.path.join(tiles_root, relative_path))
    if not target_path.startswith(tiles_root):
        raise ValueError("缓存目录超出 tiles 根目录")
    return relative_path, target_path


def _directory_size_bytes(path_value):
    total = 0
    for root, _, files in os.walk(path_value):
        for filename in files:
            try:
                total += os.path.getsize(os.path.join(root, filename))
            except OSError:
                continue
    return int(total)


def getCacheInfo():
    """获取瓦片缓存信息。"""
    try:
        tiles_dir = config["tilesDir"]
        cache_info = []
        if not os.path.exists(tiles_dir):
            return jsonify({"cacheDirectories": [], "totalDirectories": 0})

        for item in os.listdir(tiles_dir):
            item_path = os.path.join(tiles_dir, item)
            if not os.path.isdir(item_path):
                continue

            metadata_file = os.path.join(item_path, "tile_metadata.json")
            cache_item = {
                "directory": item,
                "path": item_path,
                "hasMetadata": False,
                "hasShpIndex": False,
                "hasGeoJsonIndex": False,
            }

            if os.path.exists(metadata_file):
                try:
                    import json

                    with open(metadata_file, "r", encoding="utf-8") as file_obj:
                        metadata = json.load(file_obj)
                    cache_item.update(
                        {
                            "hasMetadata": True,
                            "generatedAt": metadata.get("generatedAt", ""),
                            "completedAt": metadata.get("completedAt", ""),
                            "sourceFiles": metadata.get("sourceFiles", []),
                            "totalSourceFiles": metadata.get("totalSourceFiles", 0),
                            "zoomLevels": metadata.get("zoomLevels", ""),
                            "tileSize": metadata.get("tileSize", 256),
                            "totalTiles": metadata.get("totalTiles", 0),
                            "processedTiles": metadata.get("processedTiles", 0),
                            "failedTiles": metadata.get("failedTiles", 0),
                            "successRate": metadata.get("successRate", "0%"),
                            "method": metadata.get("method", ""),
                            "resampling": metadata.get("resampling", "near"),
                            "transparencyThreshold": metadata.get("transparencyThreshold", 0.1),
                        }
                    )
                except Exception as exc:
                    cache_item["metadataError"] = str(exc)

            cache_item["hasShpIndex"] = os.path.exists(os.path.join(item_path, "tile_index.shp"))
            cache_item["hasGeoJsonIndex"] = os.path.exists(os.path.join(item_path, "tile_index.geojson"))
            try:
                cache_item["sizeBytes"] = _directory_size_bytes(item_path)
            except Exception:
                cache_item["sizeBytes"] = 0

            try:
                tile_count = 0
                for root, _, files in os.walk(item_path):
                    tile_count += len([name for name in files if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))])
                cache_item["actualTileFiles"] = tile_count
            except Exception:
                cache_item["actualTileFiles"] = 0

            cache_info.append(cache_item)

        cache_info.sort(key=lambda item: item.get("generatedAt", ""), reverse=True)
        return jsonify(
            {
                "cacheDirectories": cache_info,
                "totalDirectories": len(cache_info),
                "tilesBaseDir": tiles_dir,
            }
        )
    except Exception as exc:
        logMessage(f"获取缓存信息失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def getCacheDetail():
    try:
        relative_path, target_path = _resolve_tiles_relative_path(request.args.get("path"))
        if not os.path.isdir(target_path):
            return jsonify({"error": f"缓存目录不存在: {relative_path}"}), 404

        metadata = {}
        metadata_file = os.path.join(target_path, "tile_metadata.json")
        if os.path.exists(metadata_file):
            try:
                import json
                with open(metadata_file, "r", encoding="utf-8") as file_obj:
                    metadata = json.load(file_obj)
            except Exception as exc:
                metadata = {"metadataError": str(exc)}

        zoom_levels = []
        for item in sorted(os.listdir(target_path)):
            item_path = os.path.join(target_path, item)
            if os.path.isdir(item_path) and str(item).isdigit():
                try:
                    tile_files = 0
                    for _, _, files in os.walk(item_path):
                        tile_files += len([name for name in files if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".pbf", ".json", ".terrain", ".b3dm", ".glb", ".gltf"))])
                    zoom_levels.append({
                        "zoom": int(item),
                        "tileFiles": tile_files,
                    })
                except Exception:
                    zoom_levels.append({
                        "zoom": int(item),
                        "tileFiles": 0,
                    })

        return jsonify({
            "success": True,
            "path": relative_path,
            "fullPath": target_path,
            "sizeBytes": _directory_size_bytes(target_path),
            "zoomLevels": zoom_levels,
            "metadata": metadata,
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logMessage(f"读取缓存详情失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def deleteCacheDirectory():
    try:
        data = request.get_json(silent=True) or {}
        relative_path, target_path = _resolve_tiles_relative_path(data.get("path") or request.args.get("path"))
        if not os.path.exists(target_path):
            return jsonify({"success": True, "path": relative_path, "deleted": False, "message": "缓存目录不存在"})
        if not os.path.isdir(target_path):
            return jsonify({"error": "目标不是目录"}), 400
        zoom_levels = data.get("zoomLevels")
        if isinstance(zoom_levels, list) and zoom_levels:
            deleted_levels = []
            missing_levels = []
            for zoom in zoom_levels:
                zoom_name = str(zoom).strip()
                if not zoom_name.isdigit():
                    continue
                zoom_path = os.path.join(target_path, zoom_name)
                if os.path.isdir(zoom_path):
                    shutil.rmtree(zoom_path)
                    deleted_levels.append(int(zoom_name))
                else:
                    missing_levels.append(int(zoom_name))
            return jsonify({
                "success": True,
                "path": relative_path,
                "deleted": bool(deleted_levels),
                "deletedZoomLevels": deleted_levels,
                "missingZoomLevels": missing_levels,
            })

        shutil.rmtree(target_path)
        return jsonify({"success": True, "path": relative_path, "deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logMessage(f"删除缓存目录失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def _buildTargetTilePath(relativePath, sourceFormat, targetFullPath):
    path_parts = relativePath.split(os.sep)
    if sourceFormat == "flat":
        if len(path_parts) < 2:
            raise ValueError(f"无效的路径格式: {relativePath}")
        z = path_parts[0]
        filename = path_parts[-1]
        stem, extension = os.path.splitext(filename)
        if "_" not in stem:
            raise ValueError(f"无效的文件名格式: {filename}")
        x, y = stem.split("_", 1)
        return os.path.join(targetFullPath, z, x, f"{y}{extension}")

    if len(path_parts) < 3:
        raise ValueError(f"无效的路径格式: {relativePath}")
    z = path_parts[0]
    x = path_parts[1]
    y_name = path_parts[-1]
    y_stem, extension = os.path.splitext(y_name)
    return os.path.join(targetFullPath, z, f"{x}_{y_stem}{extension}")


def convertTileFormat():
    """
    瓦片格式转换接口，支持 `z/x_y.ext` 和 `z/x/y.ext` 两种目录结构互转。
    """
    try:
        data = request.get_json(silent=True) or {}
        required_params = ["sourcePath", "targetPath", "sourceFormat", "targetFormat"]
        for param in required_params:
            if param not in data:
                return jsonify({"error": f"缺少参数: {param}"}), 400

        source_path = data["sourcePath"]
        target_path = data["targetPath"]
        source_format = data["sourceFormat"]
        target_format = data["targetFormat"]
        overwrite = bool(data.get("overwrite", False))

        valid_formats = ["flat", "nested"]
        if source_format not in valid_formats:
            return jsonify({"error": f"源格式无效: {source_format}，支持的格式: {valid_formats}"}), 400
        if target_format not in valid_formats:
            return jsonify({"error": f"目标格式无效: {target_format}，支持的格式: {valid_formats}"}), 400
        if source_format == target_format:
            return jsonify({"error": "源格式和目标格式不能相同"}), 400

        source_full_path = os.path.abspath(os.path.join(config["tilesDir"], source_path))
        target_full_path = os.path.abspath(os.path.join(config["tilesDir"], target_path))
        tiles_root = os.path.abspath(config["tilesDir"])
        if not source_full_path.startswith(tiles_root) or not target_full_path.startswith(tiles_root):
            return jsonify({"error": "路径不允许访问"}), 403
        if not os.path.exists(source_full_path):
            return jsonify({"error": f"源目录不存在: {source_full_path}"}), 404

        os.makedirs(target_full_path, exist_ok=True)
        task_id = f"tileConvert{int(time.time())}"
        with taskLock:
            taskStatus[task_id] = createTaskRecord(
                task_id=task_id,
                status="running",
                progress=0,
                message="开始瓦片格式转换",
                start_time=datetime.now().isoformat(),
                current_stage="初始化",
                result={
                    "sourcePath": source_path,
                    "targetPath": target_path,
                    "sourceFormat": source_format,
                    "targetFormat": target_format,
                },
                stats={"totalTiles": 0, "processedTiles": 0, "failedTiles": 0, "remainingTiles": 0, "averageSpeed": 0, "successRate": "0%"},
                extra={"errors": []},
            )

        def runConvertTask():
            try:
                tile_files = []
                logMessage(f"开始扫描源瓦片文件: {source_full_path}", "INFO")
                for root, _, files in os.walk(source_full_path):
                    for filename in files:
                        if filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                            tile_files.append(os.path.join(root, filename))

                total_tiles = len(tile_files)
                logMessage(f"找到 {total_tiles} 个瓦片文件", "INFO")
                if total_tiles == 0:
                    with taskLock:
                        taskStatus[task_id]["status"] = "failed"
                        taskStatus[task_id]["message"] = "未找到瓦片文件"
                        taskStatus[task_id]["endTime"] = datetime.now().isoformat()
                        taskStatus[task_id]["currentStage"] = "失败"
                    return

                with taskLock:
                    taskStatus[task_id]["stats"]["totalTiles"] = total_tiles
                    taskStatus[task_id]["message"] = f"开始转换 {total_tiles} 个瓦片文件"
                    taskStatus[task_id]["currentStage"] = "转换中"

                processed_tiles = 0
                skipped_tiles = 0
                error_tiles = 0
                for source_tile_file in tile_files:
                    try:
                        relative_path = os.path.relpath(source_tile_file, source_full_path)
                        target_tile_file = _buildTargetTilePath(relative_path, source_format, target_full_path)
                        os.makedirs(os.path.dirname(target_tile_file), exist_ok=True)
                        if os.path.exists(target_tile_file) and not overwrite:
                            skipped_tiles += 1
                        else:
                            shutil.copy2(source_tile_file, target_tile_file)
                            processed_tiles += 1

                        progress = int((processed_tiles + skipped_tiles + error_tiles) * 100 / max(1, total_tiles))
                        with taskLock:
                            taskStatus[task_id]["progress"] = progress
                            taskStatus[task_id]["stats"]["processedTiles"] = processed_tiles
                            taskStatus[task_id]["stats"]["failedTiles"] = error_tiles
                            taskStatus[task_id]["stats"]["remainingTiles"] = max(0, total_tiles - processed_tiles - skipped_tiles - error_tiles)
                            taskStatus[task_id]["message"] = (
                                f"已转换 {processed_tiles} 个瓦片，跳过 {skipped_tiles} 个，错误 {error_tiles} 个"
                            )
                    except Exception as exc:
                        error_tiles += 1
                        error_message = f"转换瓦片失败 {source_tile_file}: {str(exc)}"
                        logMessage(error_message, "WARNING")
                        with taskLock:
                            taskStatus[task_id]["errors"].append(error_message)

                with taskLock:
                    taskStatus[task_id]["status"] = "completed"
                    taskStatus[task_id]["progress"] = 100
                    taskStatus[task_id]["message"] = (
                        f"转换完成，处理 {processed_tiles} 个瓦片，跳过 {skipped_tiles} 个，错误 {error_tiles} 个"
                    )
                    taskStatus[task_id]["endTime"] = datetime.now().isoformat()
                    taskStatus[task_id]["currentStage"] = "完成"
                    taskStatus[task_id]["stats"] = {
                        "totalTiles": total_tiles,
                        "processedTiles": processed_tiles,
                        "failedTiles": error_tiles,
                        "remainingTiles": 0,
                        "averageSpeed": 0,
                        "successRate": f"{processed_tiles / total_tiles * 100:.1f}%" if total_tiles > 0 else "0%",
                    }
                    taskStatus[task_id]["result"] = {
                        "processedTiles": processed_tiles,
                        "skippedTiles": skipped_tiles,
                        "errorTiles": error_tiles,
                        "totalTiles": total_tiles,
                        "sourcePath": source_path,
                        "targetPath": target_path,
                        "sourceFormat": source_format,
                        "targetFormat": target_format,
                    }
                    appendTaskLog(taskStatus[task_id], "瓦片转换", "completed", taskStatus[task_id]["message"], 100)
                logMessage(f"瓦片格式转换完成: {task_id}", "INFO")
            except Exception as exc:
                logMessage(f"瓦片格式转换失败: {str(exc)}", "ERROR")
                with taskLock:
                    taskStatus[task_id]["status"] = "failed"
                    taskStatus[task_id]["message"] = f"转换失败: {str(exc)}"
                    taskStatus[task_id]["endTime"] = datetime.now().isoformat()
                    taskStatus[task_id]["currentStage"] = "失败"
                    appendTaskLog(taskStatus[task_id], "瓦片转换", "failed", str(exc), taskStatus[task_id].get("progress", 0))

        convert_thread = threading.Thread(target=runConvertTask, daemon=True)
        convert_thread.start()
        logMessage(f"瓦片格式转换任务已启动: {task_id}", "INFO")
        return jsonify(
            {
                "success": True,
                "message": "瓦片格式转换任务已启动",
                "taskId": task_id,
                "statusUrl": f"/api/tasks/{task_id}",
                "sourcePath": source_path,
                "targetPath": target_path,
                "sourceFormat": source_format,
                "targetFormat": target_format,
            }
        )
    except Exception as exc:
        logMessage(f"瓦片格式转换 API 异常: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def optimizeTiff(filePath, outputPath=None, compressionType="lzw"):
    """优化 TIFF 文件，包括压缩、分块和 BigTIFF 支持。"""
    try:
        if not outputPath:
            outputPath = filePath.replace(".tif", "_optimized.tif")

        cmd = [
            "gdalwarp",
            "-co",
            f"COMPRESS={compressionType}",
            "-co",
            "TILED=YES",
            "-co",
            "BIGTIFF=IF_SAFER",
            filePath,
            outputPath,
        ]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, stderr = process.communicate()
        if process.returncode == 0:
            logMessage(f"TIFF 优化完成: {outputPath}", "INFO")
            return outputPath

        logMessage(f"TIFF 优化失败: {stderr.decode()}", "ERROR")
        return None
    except Exception as exc:
        logMessage(f"TIFF 优化异常: {exc}", "ERROR")
        return None


def optimizedGdal2tilesByLevels(filePath, outputDir, minZoom=0, maxZoom=18, processes=4, tileFormat="png", quality=85):
    """分级生成瓦片，逐级处理以优化性能。"""
    try:
        os.makedirs(outputDir, exist_ok=True)
        for zoom in range(minZoom, maxZoom + 1):
            zoom_output_dir = os.path.join(outputDir, str(zoom))
            os.makedirs(zoom_output_dir, exist_ok=True)
            cmd = [
                "gdal2tiles.py",
                "-z",
                f"{zoom}-{zoom}",
                "-w",
                "none",
                "--processes",
                str(processes),
                filePath,
                zoom_output_dir,
            ]
            if tileFormat == "webp":
                cmd.extend(["--webp-quality", str(quality)])
            elif tileFormat == "jpeg":
                cmd.extend(["--jpeg-quality", str(quality)])

            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, stderr = process.communicate()
            if process.returncode != 0:
                logMessage(f"级别 {zoom} 生成失败: {stderr.decode()}", "ERROR")
                return False

            logMessage(f"级别 {zoom} 生成完成", "INFO")
        return True
    except Exception as exc:
        logMessage(f"分级生成瓦片失败: {exc}", "ERROR")
        return False

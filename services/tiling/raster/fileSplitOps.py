#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import subprocess
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime

from flask import jsonify, request

from config import config, taskLock, taskStatus
from taskState import appendTaskLog, createTaskRecord
from utils import logMessage


def _readRasterDimensions(sourcePath):
    result = subprocess.run(["gdalinfo", sourcePath], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"无法获取文件信息: {result.stderr}")

    size_match = re.search(r"Size is (\d+), (\d+)", result.stdout)
    if not size_match:
        raise RuntimeError("无法解析文件尺寸")

    return int(size_match.group(1)), int(size_match.group(2))


def _runUserSplitTask(task):
    try:
        translate_cmd = [
            "gdal_translate",
            "-srcwin",
            str(task["xOff"]),
            str(task["yOff"]),
            str(task["xSize"]),
            str(task["ySize"]),
            "-co",
            "COMPRESS=LZW",
            "-co",
            "TILED=YES",
            "-co",
            "BLOCKXSIZE=512",
            "-co",
            "BLOCKYSIZE=512",
            "-co",
            "NUM_THREADS=2",
            "-co",
            "BIGTIFF=IF_SAFER",
            "-q",
            task["sourcePath"],
            task["outputPath"],
        ]
        result = subprocess.run(translate_cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return {
                "success": True,
                "outputPath": task["outputPath"],
                "x": task["x"],
                "y": task["y"],
            }
        return {
            "success": False,
            "error": result.stderr,
            "x": task["x"],
            "y": task["y"],
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "x": task["x"],
            "y": task["y"],
        }


def _runInternalSplitTask(task):
    try:
        temp_split_file = task["outputPath"].replace(".tif", "_temp.tif")
        translate_cmd = [
            "gdal_translate",
            "-srcwin",
            str(task["xOff"]),
            str(task["yOff"]),
            str(task["xSize"]),
            str(task["ySize"]),
            "-co",
            "COMPRESS=LZW",
            "-co",
            "TILED=YES",
            "-co",
            "BLOCKXSIZE=512",
            "-co",
            "BLOCKYSIZE=512",
            "-co",
            "NUM_THREADS=1",
            "-co",
            "BIGTIFF=IF_SAFER",
            "-q",
            task["sourcePath"],
            temp_split_file,
        ]
        translate_result = subprocess.run(translate_cmd, capture_output=True, text=True, timeout=600)
        if translate_result.returncode != 0:
            return {
                "success": False,
                "error": f"裁剪失败: {translate_result.stderr}",
                "x": task["x"],
                "y": task["y"],
            }

        warp_cmd = [
            "gdalwarp",
            "-t_srs",
            "EPSG:4326",
            "-r",
            "near",
            "-co",
            "COMPRESS=LZW",
            "-co",
            "TILED=YES",
            "-co",
            "BLOCKXSIZE=512",
            "-co",
            "BLOCKYSIZE=512",
            "-co",
            "NUM_THREADS=1",
            "-co",
            "BIGTIFF=IF_SAFER",
            "-q",
            temp_split_file,
            task["outputPath"],
        ]
        warp_result = subprocess.run(warp_cmd, capture_output=True, text=True, timeout=600)
        try:
            if os.path.exists(temp_split_file):
                os.remove(temp_split_file)
        except Exception:
            pass

        if warp_result.returncode == 0:
            return {
                "success": True,
                "outputPath": task["outputPath"],
                "x": task["x"],
                "y": task["y"],
            }
        return {
            "success": False,
            "error": f"重投影失败: {warp_result.stderr}",
            "x": task["x"],
            "y": task["y"],
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "x": task["x"],
            "y": task["y"],
        }


def splitLargeFile():
    """拆分大文件为分幅的小 TIF 文件。"""
    try:
        data = request.get_json(silent=True) or {}
        logMessage("收到文件拆分请求", "INFO")

        required_params = ["sourceFile", "outputPath"]
        for param in required_params:
            if param not in data:
                return jsonify({"error": f"缺少参数: {param}"}), 400

        source_file = data["sourceFile"]
        output_path_array = data["outputPath"]
        tile_size = int(data.get("tileSize", 4096))
        overlap = int(data.get("overlap", 0))
        max_file_size = float(data.get("maxFileSize", 1.0))
        naming_pattern = data.get("namingPattern", "tile_{x}_{y}")

        source_path = os.path.join(config["dataSourceDir"], source_file)
        if isinstance(output_path_array, list):
            output_path = os.path.join(config["dataSourceDir"], *output_path_array)
        else:
            output_path = os.path.join(config["dataSourceDir"], output_path_array)

        if not os.path.exists(source_path):
            return jsonify({"error": "源文件不存在"}), 404

        file_size_gb = os.path.getsize(source_path) / (1024 ** 3)
        if file_size_gb < max_file_size:
            return jsonify(
                {
                    "message": "文件大小未超过阈值，无需拆分",
                    "fileSize": f"{file_size_gb:.2f}GB",
                    "threshold": f"{max_file_size}GB",
                    "skipSplit": True,
                }
            )

        os.makedirs(output_path, exist_ok=True)
        task_id = f"split{int(time.time())}"

        def runSplitTask():
            try:
                with taskLock:
                    taskStatus[task_id] = createTaskRecord(
                        task_id=task_id,
                        status="running",
                        progress=0,
                        message="正在分析文件信息...",
                        start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="初始化",
                        stats={"totalTiles": 0, "processedTiles": 0, "failedTiles": 0, "remainingTiles": 0, "averageSpeed": 0, "successRate": "0%"},
                    )

                logMessage(f"开始拆分文件: {source_path} -> {output_path}")
                width, height = _readRasterDimensions(source_path)
                tiles_x = (width + tile_size - 1) // tile_size
                tiles_y = (height + tile_size - 1) // tile_size
                total_tiles = tiles_x * tiles_y
                logMessage(f"文件尺寸: {width}x{height}")
                logMessage(f"计划拆分为 {tiles_x}x{tiles_y} = {total_tiles} 个分块")

                with taskLock:
                    taskStatus[task_id]["message"] = f"开始拆分为 {total_tiles} 个分块"
                    taskStatus[task_id]["progress"] = 10
                    taskStatus[task_id]["currentStage"] = "拆分中"
                    taskStatus[task_id]["stats"]["totalTiles"] = total_tiles

                split_tasks = []
                for y in range(tiles_y):
                    for x in range(tiles_x):
                        x_off = x * tile_size
                        y_off = y * tile_size
                        x_size = min(tile_size + overlap, width - x_off)
                        y_size = min(tile_size + overlap, height - y_off)
                        output_file_name = naming_pattern.format(x=x, y=y) + ".tif"
                        split_tasks.append(
                            {
                                "x": x,
                                "y": y,
                                "xOff": x_off,
                                "yOff": y_off,
                                "xSize": x_size,
                                "ySize": y_size,
                                "outputPath": os.path.join(output_path, output_file_name),
                                "sourcePath": source_path,
                            }
                        )

                logMessage(f"启动高速并行拆分: {len(split_tasks)} 个分块")
                split_files = []
                processed_tiles = 0
                failed_tiles = 0
                split_start_time = time.time()
                max_workers = min((os.cpu_count() or 4) * 2, 12, max(1, len(split_tasks)))

                with ProcessPoolExecutor(max_workers=max_workers) as executor:
                    future_to_task = {executor.submit(_runUserSplitTask, task): task for task in split_tasks}
                    for future in as_completed(future_to_task):
                        result = future.result()
                        if result["success"]:
                            split_files.append(os.path.relpath(result["outputPath"], config["dataSourceDir"]))
                            processed_tiles += 1
                        else:
                            failed_tiles += 1
                            logMessage(f"分块拆分失败 ({result['x']},{result['y']}): {result['error']}", "WARNING")

                        completed_tiles = processed_tiles + failed_tiles
                        progress = 10 + int((completed_tiles / max(1, total_tiles)) * 80)
                        with taskLock:
                            taskStatus[task_id]["progress"] = progress
                            taskStatus[task_id]["message"] = f"高速拆分进度: {completed_tiles}/{total_tiles}"
                            taskStatus[task_id]["stats"]["processedTiles"] = processed_tiles
                            taskStatus[task_id]["stats"]["failedTiles"] = failed_tiles
                            taskStatus[task_id]["stats"]["remainingTiles"] = max(0, total_tiles - completed_tiles)

                        if completed_tiles % 20 == 0:
                            elapsed = time.time() - split_start_time
                            speed = completed_tiles / elapsed if elapsed > 0 else 0
                            logMessage(f"拆分速度: {speed:.1f}块/秒, 已完成: {completed_tiles}/{total_tiles}")

                total_split_time = time.time() - split_start_time
                final_speed = (processed_tiles + failed_tiles) / total_split_time if total_split_time > 0 else 0
                logMessage(
                    f"并行拆分完成! 耗时: {total_split_time:.1f}秒, 平均速度: {final_speed:.1f}块/秒, "
                    f"成功: {processed_tiles}, 失败: {failed_tiles}"
                )
                if failed_tiles > 0:
                    logMessage(f"{failed_tiles} 个分块失败，继续保留成功结果", "WARNING")

                with taskLock:
                    taskStatus[task_id] = createTaskRecord(
                        task_id=task_id,
                        status="completed",
                        progress=100,
                        message=f"文件拆分完成，生成 {len(split_files)} 个分块",
                        start_time=taskStatus.get(task_id, {}).get("startTime"),
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="完成",
                        result={
                            "sourceFile": source_file,
                            "outputPath": output_path,
                            "splitFiles": split_files,
                            "totalFiles": len(split_files),
                            "tileSize": tile_size,
                            "overlap": overlap,
                            "originalSize": f"{file_size_gb:.2f}GB",
                            "tilesX": tiles_x,
                            "tilesY": tiles_y,
                            "failedTiles": failed_tiles,
                        },
                        stats={
                            "totalTiles": total_tiles,
                            "processedTiles": processed_tiles,
                            "failedTiles": failed_tiles,
                            "remainingTiles": 0,
                            "averageSpeed": round(final_speed, 1),
                            "successRate": f"{processed_tiles / total_tiles * 100:.1f}%" if total_tiles > 0 else "0%",
                        },
                    )
                    appendTaskLog(taskStatus[task_id], "文件拆分", "completed", f"拆分完成，成功 {processed_tiles}，失败 {failed_tiles}", 100)
                logMessage(f"文件拆分任务完成: {task_id}")
            except Exception as exc:
                with taskLock:
                    taskStatus[task_id] = createTaskRecord(
                        task_id=task_id,
                        status="failed",
                        progress=0,
                        message=f"文件拆分失败: {str(exc)}",
                        start_time=taskStatus.get(task_id, {}).get("startTime"),
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="失败",
                        error=str(exc),
                    )
                    appendTaskLog(taskStatus[task_id], "文件拆分", "failed", str(exc), taskStatus[task_id].get("progress", 0))
                logMessage(f"文件拆分失败: {task_id} - {exc}", "ERROR")

        task_thread = threading.Thread(target=runSplitTask, daemon=True)
        task_thread.start()
        return jsonify(
            {
                "message": "文件拆分任务已启动",
                "taskId": task_id,
                "statusUrl": f"/api/tasks/{task_id}",
                "sourceFile": source_file,
                "outputPath": output_path,
                "fileSize": f"{file_size_gb:.2f}GB",
                "splitConfig": {
                    "tileSize": tile_size,
                    "overlap": overlap,
                    "maxFileSize": max_file_size,
                    "namingPattern": naming_pattern,
                },
            }
        )
    except Exception as exc:
        logMessage(f"文件拆分 API 异常: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def performInternalFileSplit(sourcePath, splitTileSize, taskId):
    """内部文件拆分功能。"""
    try:
        width, height = _readRasterDimensions(sourcePath)
        tiles_x = (width + splitTileSize - 1) // splitTileSize
        tiles_y = (height + splitTileSize - 1) // splitTileSize
        total_tiles = tiles_x * tiles_y
        split_temp_dir = os.path.join(config["dataSourceDir"], f"split_{taskId}_{int(time.time())}")
        os.makedirs(split_temp_dir, exist_ok=True)

        logMessage(f"开始拆分文件: {width}x{height} -> {tiles_x}x{tiles_y} = {total_tiles} 个分块")
        split_files = []
        overlap = 50
        split_tasks = []
        for y in range(tiles_y):
            for x in range(tiles_x):
                x_off = max(0, x * splitTileSize - overlap)
                y_off = max(0, y * splitTileSize - overlap)
                x_size = min(splitTileSize + 2 * overlap, width - x_off)
                y_size = min(splitTileSize + 2 * overlap, height - y_off)
                split_tasks.append(
                    {
                        "x": x,
                        "y": y,
                        "xOff": x_off,
                        "yOff": y_off,
                        "xSize": x_size,
                        "ySize": y_size,
                        "outputPath": os.path.join(split_temp_dir, f"tile_{x}_{y}.tif"),
                        "sourcePath": sourcePath,
                    }
                )

        logMessage(f"启动并行拆分: {len(split_tasks)} 个分块, 预计提升 4-8 倍速度")
        processed_tiles = 0
        failed_tiles = 0
        start_time = time.time()
        max_workers = min((os.cpu_count() or 4) * 2, 16, max(1, len(split_tasks)))
        logMessage(f"启动 {max_workers} 个线程进行并行拆分...")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {executor.submit(_runInternalSplitTask, task): task for task in split_tasks}
            for future in as_completed(future_to_task):
                result = future.result()
                if result["success"]:
                    split_files.append(result["outputPath"])
                    processed_tiles += 1
                else:
                    failed_tiles += 1
                    logMessage(f"分块失败 ({result['x']},{result['y']}): {result['error']}", "WARNING")

                completed_tiles = processed_tiles + failed_tiles
                if completed_tiles % 20 == 0 or completed_tiles == len(split_tasks):
                    elapsed = time.time() - start_time
                    speed = completed_tiles / elapsed if elapsed > 0 else 0
                    progress_percent = int((completed_tiles / max(1, len(split_tasks))) * 100)
                    logMessage(
                        f"拆分进度: {completed_tiles}/{len(split_tasks)} ({progress_percent}%) | "
                        f"速度: {speed:.1f}块/秒 | 失败: {failed_tiles}"
                    )

        total_time = time.time() - start_time
        final_speed = (processed_tiles + failed_tiles) / total_time if total_time > 0 else 0
        logMessage(
            f"并行拆分完成! 总时间: {total_time:.1f}秒, 平均速度: {final_speed:.1f}块/秒, "
            f"成功: {processed_tiles}, 失败: {failed_tiles}"
        )
        if failed_tiles > 0:
            logMessage(f"{failed_tiles} 个分块拆分失败，但继续保留成功结果", "WARNING")

        return {
            "success": True,
            "splitFiles": split_files,
            "splitTempDir": split_temp_dir,
            "totalFiles": len(split_files),
            "tilesX": tiles_x,
            "tilesY": tiles_y,
            "failedTiles": failed_tiles,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import datetime

from flask import jsonify, request

from artifacts import finalizeTaskArtifact
from config import config, taskLock, taskProcesses, taskStatus
from dataSourceOps import findSourceFilesInFolders
from taskState import appendTaskLog, createTaskRecord
from utils import logMessage, normalizeInt, resolveTilesOutputPath, runCommandWithProcessTracking


SUPPORTED_VECTOR_EXTENSIONS = [".geojson", ".shp", ".gpkg"]


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _sanitize_layer_name(value, fallback="vector_layer"):
    text = str(value or "").strip()
    text = re.sub(r"[^0-9a-zA-Z_]+", "_", text).strip("_")
    if not text:
        text = fallback
    if text[0].isdigit():
        text = f"{fallback}_{text}"
    return text[:63]


def _dedupe_layer_name(value, used_names):
    base_name = _sanitize_layer_name(value)
    candidate = base_name
    suffix = 1
    while candidate.lower() in used_names:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    used_names.add(candidate.lower())
    return candidate


def _task_was_stopped(task_id):
    with taskLock:
        return str(taskStatus.get(task_id, {}).get("status", "")).lower() == "stopped"


def _ensure_task_not_stopped(task_id):
    if _task_was_stopped(task_id):
        raise RuntimeError("任务已停止")


def _count_vector_tiles(output_path):
    tile_count = 0
    for root, _, files in os.walk(output_path):
        tile_count += len([filename for filename in files if filename.endswith(".pbf")])
    return tile_count


def _find_sample_tile(output_path):
    for zoom_name in sorted(os.listdir(output_path), key=lambda value: (not str(value).isdigit(), str(value))):
        if not str(zoom_name).isdigit():
            continue
        zoom_dir = os.path.join(output_path, str(zoom_name))
        if not os.path.isdir(zoom_dir):
            continue
        for x_name in sorted(os.listdir(zoom_dir), key=lambda value: (not str(value).isdigit(), str(value))):
            if not str(x_name).isdigit():
                continue
            x_dir = os.path.join(zoom_dir, str(x_name))
            if not os.path.isdir(x_dir):
                continue
            for filename in sorted(os.listdir(x_dir)):
                if filename.endswith(".pbf"):
                    return {
                        "z": str(zoom_name),
                        "x": str(x_name),
                        "y": os.path.splitext(filename)[0],
                        "path": f"{zoom_name}/{x_name}/{filename}",
                    }
    return None


def _clear_directory(path):
    if not os.path.isdir(path):
        return
    for item in os.listdir(path):
        item_path = os.path.join(path, item)
        if os.path.isdir(item_path):
            shutil.rmtree(item_path, ignore_errors=True)
        else:
            try:
                os.remove(item_path)
            except FileNotFoundError:
                continue


def _write_tileset_metadata(output_path, dataset_name, layer_names, min_zoom, max_zoom, bounds=None):
    tileset_path = os.path.join(output_path, "tileset.json")
    payload = {
        "tilejson": "3.0.0",
        "name": dataset_name,
        "format": "pbf",
        "scheme": "xyz",
        "tiles": ["{z}/{x}/{y}.pbf"],
        "minzoom": min_zoom,
        "maxzoom": max_zoom,
        "vector_layers": [{"id": layer_name, "description": f"AtlasWorks layer {layer_name}"} for layer_name in layer_names],
    }
    if isinstance(bounds, list) and len(bounds) == 4:
        payload["bounds"] = bounds
    with open(tileset_path, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, indent=2, ensure_ascii=False)
    return tileset_path


def _build_failed_task(task_id, errors):
    timestamp = datetime.now()
    return createTaskRecord(
        task_id=task_id,
        status="failed",
        progress=0,
        message=f"MVT 任务创建失败: {'; '.join(errors)}",
        start_time=timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        end_time=timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        current_stage="参数校验失败",
        process_log=[
            {
                "stage": "参数校验",
                "status": "failed",
                "message": f"任务参数校验失败: {'; '.join(errors)}",
                "timestamp": timestamp.isoformat(),
                "progress": 0,
                "errors": errors,
            }
        ],
        files={"total": 0, "completed": 0, "failed": 0, "current": None},
        extra={"errors": errors},
    )


def createVectorTiles():
    try:
        logMessage("收到 MVT 切片创建请求", "INFO")
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({"error": "请求数据为空，无法解析JSON"}), 400

        task_id = f"mvt{int(time.time())}"
        folder_paths = data.get("folderPaths", [])
        file_patterns = data.get("filePatterns")
        output_path_value = data.get("outputPath", [])
        overwrite = _as_bool(data.get("overwrite"), False)
        min_zoom = normalizeInt(data.get("minZoom"), 0, 0, 22)
        max_zoom = normalizeInt(data.get("maxZoom"), 14, 0, 22)
        dataset_name = _sanitize_layer_name(data.get("datasetName") or data.get("layerName") or "atlasworks_mvt", "atlasworks_mvt")

        errors = []
        if not file_patterns:
            errors.append("缺少参数: filePatterns")
        if max_zoom < min_zoom:
            errors.append("maxZoom 不能小于 minZoom")

        relative_source_files = []
        if not errors:
            relative_source_files = findSourceFilesInFolders(
                folder_paths,
                filePatterns=file_patterns,
                allowedExtensions=SUPPORTED_VECTOR_EXTENSIONS,
            )
            if not relative_source_files:
                errors.append("未找到匹配的矢量文件（支持 .geojson/.shp/.gpkg）")

        output_path, output_path_array, output_auto_generated = resolveTilesOutputPath(output_path_value, "mvt")
        os.makedirs(output_path, exist_ok=True)
        if output_auto_generated:
            logMessage(f"未传 outputPath，已自动生成 MVT 输出目录: {output_path}")

        if os.path.abspath(output_path) == os.path.abspath(config["tilesDir"]):
            errors.append("禁止直接把 MVT 输出到 tiles 根目录")
        elif os.path.isdir(output_path) and os.listdir(output_path) and not overwrite:
            errors.append("outputPath 已存在且非空，如需覆盖请传 overwrite=true")

        if errors:
            with taskLock:
                taskStatus[task_id] = _build_failed_task(task_id, errors)
            return (
                jsonify(
                    {
                        "success": False,
                        "taskId": task_id,
                        "message": f"MVT 任务创建失败: {'; '.join(errors)}",
                        "statusUrl": f"/api/tasks/{task_id}",
                        "errors": errors,
                    }
                ),
                200,
            )

        source_files = [
            {
                "relativePath": relative_path,
                "fullPath": os.path.join(config["dataSourceDir"], relative_path),
                "filename": os.path.basename(relative_path),
            }
            for relative_path in relative_source_files
            if os.path.exists(os.path.join(config["dataSourceDir"], relative_path))
        ]
        if not source_files:
            with taskLock:
                taskStatus[task_id] = _build_failed_task(task_id, ["没有找到有效的矢量源文件"])
            return jsonify({"success": False, "taskId": task_id, "message": "没有找到有效的矢量源文件", "statusUrl": f"/api/tasks/{task_id}"}), 200

        def run_vector_tile_task():
            temp_dir = None
            try:
                with taskLock:
                    taskStatus[task_id] = createTaskRecord(
                        task_id=task_id,
                        status="running",
                        progress=0,
                        message=f"开始生成 MVT，共 {len(source_files)} 个源文件",
                        start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="准备数据",
                        process_log=[
                            {
                                "stage": "任务创建",
                                "status": "completed",
                                "message": f"任务初始化完成，识别到 {len(source_files)} 个矢量源文件",
                                "timestamp": datetime.now().isoformat(),
                                "progress": 0,
                            }
                        ],
                        files={"total": len(source_files), "completed": 0, "failed": 0, "current": None},
                    )

                _ensure_task_not_stopped(task_id)
                temp_dir = tempfile.mkdtemp(prefix=f"atlasworks-mvt-{task_id}-")
                staging_output_path = os.path.join(temp_dir, "mvt_output")
                merged_gpkg_path = os.path.join(temp_dir, "source_layers.gpkg")
                layer_names = []
                used_layer_names = set()

                for index, file_info in enumerate(source_files):
                    _ensure_task_not_stopped(task_id)
                    source_layer_name = _dedupe_layer_name(os.path.splitext(file_info["filename"])[0], used_layer_names)
                    layer_names.append(source_layer_name)

                    with taskLock:
                        current_task = taskStatus.get(task_id)
                        if not current_task:
                            return
                        current_task["files"]["current"] = file_info["filename"]
                        current_task["message"] = f"正在导入矢量源 {index + 1}/{len(source_files)}: {file_info['filename']}"
                        current_task["currentStage"] = "准备数据"

                    import_command = ["ogr2ogr", "-f", "GPKG"]
                    if index > 0:
                        import_command.append("-update")
                    import_command.extend(
                        [
                            merged_gpkg_path,
                            file_info["fullPath"],
                            "-nln",
                            source_layer_name,
                            "-skipfailures",
                        ]
                    )
                    import_result = runCommandWithProcessTracking(import_command, task_id)
                    if not import_result.get("success"):
                        if _task_was_stopped(task_id):
                            raise RuntimeError("任务已停止")
                        raise RuntimeError(import_result.get("stderr") or import_result.get("error") or "导入矢量源失败")

                    progress = 10 + int(((index + 1) / len(source_files)) * 35)
                    with taskLock:
                        current_task = taskStatus.get(task_id)
                        if not current_task:
                            return
                        current_task["files"]["completed"] = index + 1
                        current_task["progress"] = progress
                        appendTaskLog(
                            current_task,
                            "矢量导入",
                            "completed",
                            f"已导入矢量源: {file_info['filename']} -> {source_layer_name}",
                            progress,
                            sourceFile=file_info["relativePath"],
                            layerName=source_layer_name,
                        )

                _ensure_task_not_stopped(task_id)
                with taskLock:
                    current_task = taskStatus.get(task_id)
                    if not current_task:
                        return
                    current_task["progress"] = 55
                    current_task["message"] = "正在生成 MVT 目录切片"
                    current_task["currentStage"] = "生成 MVT"
                    appendTaskLog(current_task, "MVT 生成", "running", "开始执行 ogr2ogr MVT 输出", 55)

                build_command = [
                    "ogr2ogr",
                    "-f",
                    "MVT",
                    staging_output_path,
                    merged_gpkg_path,
                    "-dsco",
                    "FORMAT=DIRECTORY",
                    "-dsco",
                    f"MINZOOM={min_zoom}",
                    "-dsco",
                    f"MAXZOOM={max_zoom}",
                    "-dsco",
                    f"NAME={dataset_name}",
                ]
                build_result = runCommandWithProcessTracking(build_command, task_id)
                if not build_result.get("success"):
                    if _task_was_stopped(task_id):
                        raise RuntimeError("任务已停止")
                    raise RuntimeError(build_result.get("stderr") or build_result.get("error") or "生成 MVT 失败")

                _ensure_task_not_stopped(task_id)
                tile_count = _count_vector_tiles(staging_output_path)
                if tile_count <= 0:
                    raise RuntimeError("MVT 输出目录中未生成任何 .pbf 瓦片")

                if overwrite:
                    _clear_directory(output_path)
                shutil.copytree(staging_output_path, output_path, dirs_exist_ok=True)
                sample_tile = _find_sample_tile(output_path)
                tileset_metadata_path = _write_tileset_metadata(output_path, dataset_name, layer_names, min_zoom, max_zoom)

                with taskLock:
                    current_task = taskStatus.get(task_id, {})
                    existing_log = current_task.get("processLog", [])
                    start_time = current_task.get("startTime")
                    taskStatus[task_id] = createTaskRecord(
                        task_id=task_id,
                        status="completed",
                        progress=100,
                        message=f"MVT 切片完成，共生成 {tile_count} 个矢量瓦片",
                        start_time=start_time,
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="已完成",
                        process_log=existing_log,
                        result={
                            "outputPath": output_path,
                            "outputPathArray": output_path_array,
                            "totalTiles": tile_count,
                            "minZoom": min_zoom,
                            "maxZoom": max_zoom,
                            "layers": layer_names,
                            "sampleTile": sample_tile,
                            "sourceFiles": [item["relativePath"] for item in source_files],
                            "tilesetFile": tileset_metadata_path,
                            "method": "mvt-static",
                            "publishHints": {"publishType": "geo", "publishMethod": "mvt"},
                        },
                        stats={
                            "totalTiles": tile_count,
                            "processedTiles": tile_count,
                            "failedTiles": 0,
                            "remainingTiles": 0,
                            "averageSpeed": 0,
                            "successRate": "100%",
                        },
                        files={"total": len(source_files), "completed": len(source_files), "failed": 0, "current": None},
                    )
                    appendTaskLog(
                        taskStatus[task_id],
                        "任务完成",
                        "completed",
                        f"MVT 切片任务完成，生成 {tile_count} 个 .pbf 瓦片",
                        100,
                        outputPath=output_path,
                        layers=layer_names,
                    )

                finalizeTaskArtifact(
                    task_id,
                    source_files=[item["relativePath"] for item in source_files],
                    build_parameters={
                        "jobType": "mvt_tiles",
                        "outputPath": output_path_array,
                        "minZoom": min_zoom,
                        "maxZoom": max_zoom,
                        "datasetName": dataset_name,
                        "overwrite": overwrite,
                    },
                )
                logMessage(f"MVT 切片任务完成: {task_id}", "INFO")
            except Exception as exc:
                stopped = str(exc) == "任务已停止"
                with taskLock:
                    current_task = taskStatus.get(task_id, {})
                    taskStatus[task_id] = createTaskRecord(
                        task_id=task_id,
                        status="stopped" if stopped else "failed",
                        progress=current_task.get("progress", 0),
                        message="MVT 切片任务已停止" if stopped else f"MVT 切片失败: {exc}",
                        start_time=current_task.get("startTime", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="已停止" if stopped else "失败",
                        process_log=current_task.get("processLog", []),
                        result=current_task.get("result", {}),
                        files=current_task.get("files", {"total": len(source_files), "completed": 0, "failed": 0, "current": None}),
                        stats=current_task.get("stats"),
                        error=None if stopped else str(exc),
                    )
                    appendTaskLog(
                        taskStatus[task_id],
                        "任务停止" if stopped else "异常退出",
                        "stopped" if stopped else "failed",
                        "任务已停止" if stopped else str(exc),
                        current_task.get("progress", 0),
                    )
                logMessage(f"MVT 切片任务{'停止' if stopped else '失败'}: {task_id} - {exc}", "WARNING" if stopped else "ERROR")
            finally:
                if temp_dir and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                with taskLock:
                    taskProcesses.pop(task_id, None)

        task_thread = threading.Thread(target=run_vector_tile_task, daemon=True)
        with taskLock:
            taskProcesses[task_id] = task_thread
        task_thread.start()

        return jsonify(
            {
                "success": True,
                "taskId": task_id,
                "status": "running",
                "message": f"MVT 切片任务已启动，识别到 {len(source_files)} 个源文件",
                "statusUrl": f"/api/tasks/{task_id}",
                "parameters": {
                    "totalFiles": len(source_files),
                    "outputPath": output_path_array,
                    "zoomRange": f"{min_zoom}-{max_zoom}",
                    "datasetName": dataset_name,
                    "type": "mvt",
                    "overwrite": overwrite,
                },
            }
        )
    except Exception as exc:
        logMessage(f"创建 MVT 切片任务失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500

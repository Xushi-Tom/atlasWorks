#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
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


SUPPORTED_VECTOR_EXTENSIONS = [".geojson", ".json", ".shp", ".gpkg"]
VECTOR_TILE_FORMATS = {"mvt", "geojson"}
GEOJSON_TILE_METHOD = "geojson-tile"
WEB_MERCATOR_MAX_LAT = 85.0511287798066


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


def _normalize_vector_tile_format(value):
    normalized = str(value or "mvt").strip().lower()
    if normalized in {"json", "geojson", "geojson-tile", "geojson-tiles"}:
        return "geojson"
    return "mvt"


def _vector_tile_extension(tile_format):
    return ".geojson" if tile_format == "geojson" else ".pbf"


def _vector_publish_method(tile_format):
    return GEOJSON_TILE_METHOD if tile_format == "geojson" else "mvt"


def _count_vector_tiles(output_path, tile_extension=".pbf"):
    tile_count = 0
    for root, _, files in os.walk(output_path):
        tile_count += len([filename for filename in files if filename.endswith(tile_extension)])
    return tile_count


def _find_sample_tile(output_path, tile_extension=".pbf"):
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
                if filename.endswith(tile_extension):
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


def _write_tileset_metadata(output_path, dataset_name, layer_names, min_zoom, max_zoom, bounds=None, tile_format="mvt"):
    tile_extension = _vector_tile_extension(tile_format)
    tileset_path = os.path.join(output_path, "tileset.json")
    payload = {
        "tilejson": "3.0.0",
        "name": dataset_name,
        "format": "geojson" if tile_format == "geojson" else "pbf",
        "scheme": "xyz",
        "tiles": [f"{{z}}/{{x}}/{{y}}{tile_extension}"],
        "minzoom": min_zoom,
        "maxzoom": max_zoom,
        "vector_layers": [{"id": layer_name, "description": f"AtlasWorks layer {layer_name}"} for layer_name in layer_names],
    }
    if isinstance(bounds, list) and len(bounds) == 4:
        payload["bounds"] = bounds
    with open(tileset_path, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, indent=2, ensure_ascii=False)
    return tileset_path


def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def _lonlat_to_tile(lon, lat, zoom):
    lat = _clamp(float(lat), -WEB_MERCATOR_MAX_LAT, WEB_MERCATOR_MAX_LAT)
    lon = _clamp(float(lon), -180.0, 180.0)
    n = 2 ** int(zoom)
    x = int(math.floor((lon + 180.0) / 360.0 * n))
    lat_rad = math.radians(lat)
    y = int(math.floor((1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi) / 2.0 * n))
    return _clamp(x, 0, n - 1), _clamp(y, 0, n - 1)


def _tile_to_lonlat(x, y, zoom):
    n = 2.0 ** int(zoom)
    lon = float(x) / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * float(y) / n))))
    return lon, lat


def _tile_bounds(x, y, zoom):
    west, north = _tile_to_lonlat(x, y, zoom)
    east, south = _tile_to_lonlat(x + 1, y + 1, zoom)
    return [west, south, east, north]


def _tile_range_for_bounds(bounds, zoom):
    west, south, east, north = bounds
    west = _clamp(west, -180.0, 180.0)
    east = _clamp(east, -180.0, 180.0)
    south = _clamp(south, -WEB_MERCATOR_MAX_LAT, WEB_MERCATOR_MAX_LAT)
    north = _clamp(north, -WEB_MERCATOR_MAX_LAT, WEB_MERCATOR_MAX_LAT)
    if east < west:
        west, east = east, west
    if north < south:
        south, north = north, south
    x_min, y_max = _lonlat_to_tile(west, south, zoom)
    x_max, y_min = _lonlat_to_tile(east, north, zoom)
    return min(x_min, x_max), max(x_min, x_max), min(y_min, y_max), max(y_min, y_max)


def _envelope_intersects_bounds(envelope, bounds):
    min_x, max_x, min_y, max_y = envelope
    west, south, east, north = bounds
    return not (max_x < west or min_x > east or max_y < south or min_y > north)


def _build_bbox_polygon(bounds):
    from osgeo import ogr

    west, south, east, north = bounds
    ring = ogr.Geometry(ogr.wkbLinearRing)
    ring.AddPoint_2D(west, south)
    ring.AddPoint_2D(east, south)
    ring.AddPoint_2D(east, north)
    ring.AddPoint_2D(west, north)
    ring.AddPoint_2D(west, south)
    polygon = ogr.Geometry(ogr.wkbPolygon)
    polygon.AddGeometry(ring)
    return polygon


def _json_safe_property(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe_property(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe_property(item) for key, item in value.items()}
    return str(value)


def _normalize_level_rules(level_rules):
    if not isinstance(level_rules, list):
        return []

    normalized_rules = []
    for raw_rule in level_rules:
        if not isinstance(raw_rule, dict):
            continue

        raw_values = raw_rule.get("values")
        if raw_values is None:
            raw_values = raw_rule.get("levels")
        if raw_values is None:
            raw_values = raw_rule.get("value")
        if raw_values is None:
            raw_values = raw_rule.get("level")

        if isinstance(raw_values, (list, tuple, set)):
            values = {str(value).strip() for value in raw_values if str(value).strip()}
        else:
            values = {str(raw_values).strip()} if str(raw_values or "").strip() else set()
        if not values:
            continue

        min_zoom = normalizeInt(raw_rule.get("minZoom"), 0, 0, 22)
        max_zoom = normalizeInt(raw_rule.get("maxZoom"), 22, 0, 22)
        if max_zoom < min_zoom:
            min_zoom, max_zoom = max_zoom, min_zoom

        normalized_rules.append(
            {
                "values": values,
                "minZoom": min_zoom,
                "maxZoom": max_zoom,
            }
        )
    return normalized_rules


def _feature_allowed_at_zoom(properties, zoom, level_field, level_rules, unmatched_policy):
    if not level_field or not level_rules:
        return True

    value = str((properties or {}).get(level_field, "")).strip()
    for rule in level_rules:
        if value in rule["values"]:
            return rule["minZoom"] <= zoom <= rule["maxZoom"]
    return str(unmatched_policy or "include").strip().lower() != "exclude"


def _collect_geojson_features(merged_gpkg_path, layer_names):
    from osgeo import ogr, osr

    dataset = ogr.Open(merged_gpkg_path)
    if dataset is None:
        raise RuntimeError("无法打开中间 GPKG 数据")

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(4326)
    target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    features = []
    bounds = None
    for layer_name in layer_names:
        layer = dataset.GetLayerByName(layer_name)
        if layer is None:
            continue

        source_srs = layer.GetSpatialRef()
        transform = None
        if source_srs is not None:
            source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            if not source_srs.IsSame(target_srs):
                transform = osr.CoordinateTransformation(source_srs, target_srs)

        layer_defn = layer.GetLayerDefn()
        field_names = [layer_defn.GetFieldDefn(index).GetName() for index in range(layer_defn.GetFieldCount())]
        layer.ResetReading()
        for feature in layer:
            geometry = feature.GetGeometryRef()
            if geometry is None or geometry.IsEmpty():
                continue

            geometry_clone = geometry.Clone()
            if transform is not None:
                geometry_clone.Transform(transform)
            geometry_clone.FlattenTo2D()
            envelope = geometry_clone.GetEnvelope()

            feature_bounds = [envelope[0], envelope[2], envelope[1], envelope[3]]
            if bounds is None:
                bounds = list(feature_bounds)
            else:
                bounds = [
                    min(bounds[0], feature_bounds[0]),
                    min(bounds[1], feature_bounds[1]),
                    max(bounds[2], feature_bounds[2]),
                    max(bounds[3], feature_bounds[3]),
                ]

            properties = {}
            for field_name in field_names:
                value = feature.GetField(field_name)
                if value is not None:
                    properties[field_name] = _json_safe_property(value)
            properties.setdefault("_layer", layer_name)

            features.append(
                {
                    "layer": layer_name,
                    "properties": properties,
                    "geometry": geometry_clone,
                    "envelope": envelope,
                }
            )

    if not features:
        raise RuntimeError("未读取到有效矢量要素")
    return features, bounds


def _write_geojson_feature_collection(path, features):
    payload = {
        "type": "FeatureCollection",
        "features": features,
    }
    with open(path, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, ensure_ascii=False, separators=(",", ":"))


def _build_geojson_tiles(merged_gpkg_path, output_path, layer_names, min_zoom, max_zoom, task_id, level_field="", level_rules=None, unmatched_policy="include"):
    features, bounds = _collect_geojson_features(merged_gpkg_path, layer_names)
    level_rules = _normalize_level_rules(level_rules)
    os.makedirs(output_path, exist_ok=True)
    tile_count = 0

    for zoom in range(min_zoom, max_zoom + 1):
        _ensure_task_not_stopped(task_id)
        zoom_features = [
            feature for feature in features
            if _feature_allowed_at_zoom(feature.get("properties"), zoom, level_field, level_rules, unmatched_policy)
        ]
        if not zoom_features:
            continue

        x_min, x_max, y_min, y_max = _tile_range_for_bounds(bounds, zoom)
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                tile_bounds = _tile_bounds(x, y, zoom)
                tile_polygon = _build_bbox_polygon(tile_bounds)
                tile_features = []

                for source_feature in zoom_features:
                    if not _envelope_intersects_bounds(source_feature["envelope"], tile_bounds):
                        continue
                    try:
                        clipped_geometry = source_feature["geometry"].Intersection(tile_polygon)
                    except Exception:
                        clipped_geometry = None
                    if clipped_geometry is None or clipped_geometry.IsEmpty():
                        continue

                    tile_features.append(
                        {
                            "type": "Feature",
                            "properties": dict(source_feature["properties"]),
                            "geometry": json.loads(clipped_geometry.ExportToJson()),
                        }
                    )

                if not tile_features:
                    continue

                tile_dir = os.path.join(output_path, str(zoom), str(x))
                os.makedirs(tile_dir, exist_ok=True)
                _write_geojson_feature_collection(os.path.join(tile_dir, f"{y}.geojson"), tile_features)
                tile_count += 1

        with taskLock:
            current_task = taskStatus.get(task_id)
            if current_task:
                progress = 55 + int(((zoom - min_zoom + 1) / max(1, max_zoom - min_zoom + 1)) * 35)
                current_task["progress"] = min(90, progress)
                current_task["message"] = f"正在生成 GeoJSON 瓦片: z{zoom}"

    return {"tileCount": tile_count, "bounds": bounds}


def _build_failed_task(task_id, errors):
    timestamp = datetime.now()
    return createTaskRecord(
        task_id=task_id,
        status="failed",
        progress=0,
        message=f"二维矢量切片任务创建失败: {'; '.join(errors)}",
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
        logMessage("收到二维矢量切片创建请求", "INFO")
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({"error": "请求数据为空，无法解析JSON"}), 400

        tile_format = _normalize_vector_tile_format(data.get("tileFormat") or data.get("outputFormat") or data.get("format"))
        tile_extension = _vector_tile_extension(tile_format)
        publish_method = _vector_publish_method(tile_format)
        task_id = f"{tile_format}{int(time.time())}"
        folder_paths = data.get("folderPaths", [])
        file_patterns = data.get("filePatterns")
        output_path_value = data.get("outputPath", [])
        overwrite = _as_bool(data.get("overwrite"), False)
        min_zoom = normalizeInt(data.get("minZoom"), 0, 0, 22)
        max_zoom = normalizeInt(data.get("maxZoom"), 14, 0, 22)
        dataset_name = _sanitize_layer_name(data.get("datasetName") or data.get("layerName") or f"atlasworks_{tile_format}", f"atlasworks_{tile_format}")
        level_field = str(data.get("levelField") or "").strip()
        level_rules = _normalize_level_rules(data.get("levelRules"))
        unmatched_policy = str(data.get("unmatchedPolicy") or "include").strip().lower()
        if unmatched_policy not in {"include", "exclude"}:
            unmatched_policy = "include"

        errors = []
        if not file_patterns:
            errors.append("缺少参数: filePatterns")
        if tile_format not in VECTOR_TILE_FORMATS:
            errors.append("tileFormat 仅支持 mvt 或 geojson")
        if tile_format != "geojson" and (level_field or level_rules):
            errors.append("levelField/levelRules 目前仅支持 GeoJSON 瓦片输出")
        if level_rules and not level_field:
            errors.append("传入 levelRules 时必须指定 levelField")
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
                errors.append("未找到匹配的矢量文件（支持 .geojson/.json/.shp/.gpkg）")

        output_path, output_path_array, output_auto_generated = resolveTilesOutputPath(output_path_value, tile_format)
        os.makedirs(output_path, exist_ok=True)
        if output_auto_generated:
            logMessage(f"未传 outputPath，已自动生成二维矢量输出目录: {output_path}")

        if os.path.abspath(output_path) == os.path.abspath(config["tilesDir"]):
            errors.append("禁止直接把二维矢量切片输出到 tiles 根目录")
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
                        "message": f"二维矢量切片任务创建失败: {'; '.join(errors)}",
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
                format_label = "GeoJSON" if tile_format == "geojson" else "MVT"
                with taskLock:
                    taskStatus[task_id] = createTaskRecord(
                        task_id=task_id,
                        status="running",
                        progress=0,
                        message=f"开始生成 {format_label} 矢量瓦片，共 {len(source_files)} 个源文件",
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
                temp_dir = tempfile.mkdtemp(prefix=f"atlasworks-vector-{task_id}-")
                staging_output_path = os.path.join(temp_dir, f"{tile_format}_output")
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
                    current_task["message"] = f"正在生成 {format_label} 目录切片"
                    current_task["currentStage"] = f"生成 {format_label}"
                    appendTaskLog(current_task, f"{format_label} 生成", "running", f"开始生成 {format_label} 输出", 55)

                generated_bounds = None
                if tile_format == "mvt":
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
                else:
                    geojson_result = _build_geojson_tiles(
                        merged_gpkg_path,
                        staging_output_path,
                        layer_names,
                        min_zoom,
                        max_zoom,
                        task_id,
                        level_field=level_field,
                        level_rules=level_rules,
                        unmatched_policy=unmatched_policy,
                    )
                    generated_bounds = geojson_result.get("bounds")

                _ensure_task_not_stopped(task_id)
                tile_count = _count_vector_tiles(staging_output_path, tile_extension)
                if tile_count <= 0:
                    raise RuntimeError(f"{format_label} 输出目录中未生成任何 {tile_extension} 瓦片")

                if overwrite:
                    _clear_directory(output_path)
                shutil.copytree(staging_output_path, output_path, dirs_exist_ok=True)
                sample_tile = _find_sample_tile(output_path, tile_extension)
                tileset_metadata_path = _write_tileset_metadata(output_path, dataset_name, layer_names, min_zoom, max_zoom, bounds=generated_bounds, tile_format=tile_format)

                with taskLock:
                    current_task = taskStatus.get(task_id, {})
                    existing_log = current_task.get("processLog", [])
                    start_time = current_task.get("startTime")
                    taskStatus[task_id] = createTaskRecord(
                        task_id=task_id,
                        status="completed",
                        progress=100,
                        message=f"{format_label} 切片完成，共生成 {tile_count} 个矢量瓦片",
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
                            "format": tile_format,
                            "tileExtension": tile_extension,
                            "bounds": generated_bounds,
                            "levelField": level_field or None,
                            "levelRules": [
                                {"values": sorted(rule["values"]), "minZoom": rule["minZoom"], "maxZoom": rule["maxZoom"]}
                                for rule in level_rules
                            ],
                            "unmatchedPolicy": unmatched_policy,
                            "method": f"{tile_format}-static",
                            "publishHints": {"publishType": "vector", "publishMethod": publish_method},
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
                        f"{format_label} 切片任务完成，生成 {tile_count} 个 {tile_extension} 瓦片",
                        100,
                        outputPath=output_path,
                        layers=layer_names,
                    )

                finalizeTaskArtifact(
                    task_id,
                    source_files=[item["relativePath"] for item in source_files],
                    build_parameters={
                        "jobType": "geojson_tiles" if tile_format == "geojson" else "mvt_tiles",
                        "outputPath": output_path_array,
                        "minZoom": min_zoom,
                        "maxZoom": max_zoom,
                        "datasetName": dataset_name,
                        "tileFormat": tile_format,
                        "levelField": level_field or None,
                        "levelRules": [
                            {"values": sorted(rule["values"]), "minZoom": rule["minZoom"], "maxZoom": rule["maxZoom"]}
                            for rule in level_rules
                        ],
                        "unmatchedPolicy": unmatched_policy,
                        "overwrite": overwrite,
                    },
                )
                logMessage(f"{format_label} 切片任务完成: {task_id}", "INFO")
            except Exception as exc:
                stopped = str(exc) == "任务已停止"
                failure_label = "GeoJSON" if tile_format == "geojson" else "MVT"
                with taskLock:
                    current_task = taskStatus.get(task_id, {})
                    taskStatus[task_id] = createTaskRecord(
                        task_id=task_id,
                        status="stopped" if stopped else "failed",
                        progress=current_task.get("progress", 0),
                        message=f"{failure_label} 切片任务已停止" if stopped else f"{failure_label} 切片失败: {exc}",
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
                logMessage(f"{failure_label} 切片任务{'停止' if stopped else '失败'}: {task_id} - {exc}", "WARNING" if stopped else "ERROR")
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
                "message": f"二维矢量切片任务已启动，识别到 {len(source_files)} 个源文件",
                "statusUrl": f"/api/tasks/{task_id}",
                "parameters": {
                    "totalFiles": len(source_files),
                    "outputPath": output_path_array,
                    "zoomRange": f"{min_zoom}-{max_zoom}",
                    "datasetName": dataset_name,
                    "type": tile_format,
                    "publishMethod": publish_method,
                    "levelField": level_field or None,
                    "levelRules": [
                        {"values": sorted(rule["values"]), "minZoom": rule["minZoom"], "maxZoom": rule["maxZoom"]}
                        for rule in level_rules
                    ],
                    "overwrite": overwrite,
                },
            }
        )
    except Exception as exc:
        logMessage(f"创建二维矢量切片任务失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500

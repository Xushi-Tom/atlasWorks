#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import os
import re
import glob
import gc
import shutil
import struct
import tempfile
import threading
import time
from datetime import datetime

from flask import jsonify, request

from artifacts import finalizeTaskArtifact
from config import config, taskLock, taskProcesses, taskStatus, taskStopFlags
from dataSourceOps import findSourceFilesInFolders
from taskState import appendTaskLog, createTaskRecord
from utils import (
    logMessage,
    normalizeFloat,
    normalizeInt,
    resolveTilesOutputPath,
    runCommand,
    runCommandWithProcessTracking,
    validateDataSourcePath,
)


SUPPORTED_3DTILES_TYPES = {"pointcloud", "vector", "model", "osgb"}
SOURCE_EXTENSIONS = {
    "pointcloud": [".las", ".laz"],
    "vector": [".geojson", ".shp"],
    "model": [".obj"],
    "osgb": [".osgb"],
}
WGS84_A = 6378137.0
WGS84_E2 = 6.69437999014e-3
SUPPORTED_CONTENT_FORMATS = {"b3dm", "glb"}
SUPPORTED_VECTOR_HEIGHT_MODES = {"meters", "floors"}
DEFAULT_FLOOR_HEIGHT_METERS = 3.0
MIN_VECTOR_EXTRUSION_HEIGHT = 0.01
MAX_VECTOR_CHUNK_LON_SPAN_DEG = 2.0
MAX_VECTOR_CHUNK_LAT_SPAN_DEG = 2.0
MIN_VECTOR_SPLIT_RECORDS = 24
TARGET_MODEL_CHUNK_RECORDS = 128
MAX_MODEL_CHUNK_FACE_COUNT = 20000


def _pad_bytes(data, alignment=8, pad_byte=b" "):
    raw = bytes(data or b"")
    if alignment <= 1:
        return raw
    padding = (-len(raw)) % int(alignment)
    if padding == 0:
        return raw
    return raw + (pad_byte * padding)


def _write_b3dm_from_glb(glb_path, b3dm_path):
    with open(glb_path, "rb") as file_obj:
        glb_data = file_obj.read()
    if len(glb_data) < 12 or glb_data[:4] != b"glTF":
        raise RuntimeError(f"GLB 文件无效: {glb_path}")

    feature_table_json = _pad_bytes(b'{"BATCH_LENGTH":0}', alignment=8, pad_byte=b" ")
    header_length = 28
    byte_length = header_length + len(feature_table_json) + len(glb_data)
    header = b"".join(
        [
            b"b3dm",
            struct.pack("<I", 1),
            struct.pack("<I", byte_length),
            struct.pack("<I", len(feature_table_json)),
            struct.pack("<I", 0),
            struct.pack("<I", 0),
            struct.pack("<I", 0),
        ]
    )

    with open(b3dm_path, "wb") as file_obj:
        file_obj.write(header)
        file_obj.write(feature_table_json)
        file_obj.write(glb_data)


def _build_error_task(task_id, errors):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return createTaskRecord(
        task_id=task_id,
        status="failed",
        progress=0,
        message=f"3D Tiles 任务创建失败: {'; '.join(errors)}",
        start_time=now,
        end_time=now,
        current_stage="初始化失败",
        process_log=[
            {
                "stage": "初始化",
                "status": "failed",
                "message": f"任务创建失败: {'; '.join(errors)}",
                "timestamp": datetime.now().isoformat(),
                "progress": 0,
                "errors": list(errors),
            }
        ],
        result={
            "totalFiles": 0,
            "completedFiles": 0,
            "failedFiles": 0,
            "errors": list(errors),
        },
        files={"total": 0, "completed": 0, "failed": 0, "current": None},
        extra={"errors": list(errors)},
    )


def _is_task_stopped(task_id):
    with taskLock:
        if taskStatus.get(task_id, {}).get("status") == "stopped":
            return True
    return bool(taskStopFlags.get(task_id))


def _ensure_not_stopped(stop_checker):
    if callable(stop_checker) and stop_checker():
        raise RuntimeError("任务已停止")


def _update_task(task_id, progress=None, message=None, stage=None, log_stage=None, log_status="info", **details):
    with taskLock:
        record = taskStatus.get(task_id)
        if not isinstance(record, dict):
            return
        if progress is not None:
            record["progress"] = max(0, min(int(progress), 100))
        if message is not None:
            record["message"] = str(message)
        if stage is not None:
            record["currentStage"] = str(stage)
        if log_stage:
            appendTaskLog(
                record,
                log_stage,
                log_status,
                message or record.get("message", ""),
                progress=record.get("progress", 0),
                **details,
            )


def _normalize_source_relpath(path_value):
    value = str(path_value or "").strip().replace("\\", "/").strip("/")
    if not value:
        return ""
    if ".." in value.split("/"):
        raise ValueError("sourcePath 包含非法路径")
    if "?" in value or "[" in value or "]" in value:
        raise ValueError("sourcePath 仅支持 * 通配符，不支持 ? 或 []")
    return value


def _has_glob_pattern(path_value):
    value = str(path_value or "")
    return "*" in value


def _normalize_source_input(source_path):
    if isinstance(source_path, (list, tuple, set)):
        return [item for item in source_path if str(item or "").strip()]
    return source_path


def _source_for_log(source_rel_path):
    if isinstance(source_rel_path, (list, tuple)):
        if not source_rel_path:
            return ""
        if len(source_rel_path) == 1:
            return str(source_rel_path[0])
        return f"{source_rel_path[0]} (+{len(source_rel_path) - 1})"
    return str(source_rel_path or "")


def _source_for_result(source_rel_path):
    if isinstance(source_rel_path, (list, tuple)):
        return list(source_rel_path)
    return source_rel_path


def _resolve_relative_files(relative_paths):
    normalized_items = []
    full_items = []
    for rel_path in relative_paths:
        ok, full_path = validateDataSourcePath(rel_path)
        if not ok:
            raise ValueError(full_path)
        if not os.path.isfile(full_path):
            raise ValueError("匹配结果不是文件")
        normalized_items.append(rel_path)
        full_items.append(full_path)
    return normalized_items, full_items


def _resolve_single_source(folder_paths, file_patterns, source_path, data_type):
    source_path = _normalize_source_input(source_path)
    if source_path:
        if isinstance(source_path, list):
            normalized_items = []
            full_items = []
            for item in source_path:
                normalized = _normalize_source_relpath(item)
                ok, full_path = validateDataSourcePath(normalized)
                if not ok:
                    raise ValueError(full_path)
                if data_type == "osgb":
                    normalized_items.append(normalized)
                    full_items.append(full_path)
                    continue
                if data_type == "pointcloud" and os.path.isdir(full_path):
                    matched = findSourceFilesInFolders(
                        [normalized],
                        filePatterns=[f"*{ext}" for ext in SOURCE_EXTENSIONS.get("pointcloud", [])],
                        allowedExtensions=SOURCE_EXTENSIONS.get("pointcloud", []),
                    )
                    if not matched:
                        raise ValueError("sourcePath 数组目录中未找到点云文件")
                    matched_rel, matched_full = _resolve_relative_files(matched)
                    normalized_items.extend(matched_rel)
                    full_items.extend(matched_full)
                    continue
                if _has_glob_pattern(normalized):
                    matched_files = findSourceFilesInFolders(
                        [],
                        filePatterns=[normalized],
                        allowedExtensions=SOURCE_EXTENSIONS.get(data_type, []),
                    )
                    if data_type == "pointcloud":
                        if not matched_files:
                            continue
                        matched_rel, matched_full = _resolve_relative_files(matched_files)
                        normalized_items.extend(matched_rel)
                        full_items.extend(matched_full)
                        continue
                    if len(matched_files) != 1:
                        raise ValueError("sourcePath 数组中非 OSGB 项必须精确匹配单个文件")
                    matched_rel = matched_files[0]
                    ok, matched_full = validateDataSourcePath(matched_rel)
                    if not ok or not os.path.isfile(matched_full):
                        raise ValueError("sourcePath 数组通配符匹配结果无效")
                    normalized_items.append(matched_rel)
                    full_items.append(matched_full)
                else:
                    if not os.path.isfile(full_path):
                        raise ValueError("sourcePath 数组中存在非文件项")
                    normalized_items.append(normalized)
                    full_items.append(full_path)
            if data_type not in {"osgb", "pointcloud"} and len(full_items) != 1:
                raise ValueError("当前版本每次仅支持处理单个输入文件")
            if data_type == "osgb":
                return normalized_items, full_items
            if data_type == "pointcloud":
                if not full_items:
                    raise ValueError("未找到点云输入文件")
                if len(full_items) == 1:
                    return normalized_items[0], full_items[0]
                dedup = {}
                for rel_path, full_path in zip(normalized_items, full_items):
                    dedup[full_path] = rel_path
                full_dedup = list(dedup.keys())
                rel_dedup = [dedup[item] for item in full_dedup]
                return rel_dedup, full_dedup
            return normalized_items[0], full_items[0]

        normalized = _normalize_source_relpath(source_path)
        ok, full_path = validateDataSourcePath(normalized)
        if not ok:
            raise ValueError(full_path)

        if _has_glob_pattern(normalized):
            matched_files = findSourceFilesInFolders(
                [],
                filePatterns=[normalized],
                allowedExtensions=SOURCE_EXTENSIONS.get(data_type, []),
            )
            if not matched_files:
                raise ValueError("sourcePath 通配符未匹配到输入文件")
            if data_type == "osgb":
                return normalized, full_path
            if data_type == "pointcloud":
                matched_rel, matched_full = _resolve_relative_files(matched_files)
                if len(matched_full) == 1:
                    return matched_rel[0], matched_full[0]
                return matched_rel, matched_full
            if len(matched_files) > 1:
                raise ValueError("sourcePath 通配符匹配到多个文件，请缩小匹配范围")
            matched_rel = matched_files[0]
            ok, matched_full = validateDataSourcePath(matched_rel)
            if not ok or not os.path.isfile(matched_full):
                raise ValueError("sourcePath 通配符匹配结果无效")
            return matched_rel, matched_full

        if data_type == "pointcloud" and os.path.isdir(full_path):
            matched_files = findSourceFilesInFolders(
                [normalized],
                filePatterns=[f"*{ext}" for ext in SOURCE_EXTENSIONS.get("pointcloud", [])],
                allowedExtensions=SOURCE_EXTENSIONS.get("pointcloud", []),
            )
            if not matched_files:
                raise ValueError("sourcePath 目录中未找到点云文件")
            matched_rel, matched_full = _resolve_relative_files(matched_files)
            if len(matched_full) == 1:
                return matched_rel[0], matched_full[0]
            return matched_rel, matched_full

        if data_type == "osgb" and os.path.isdir(full_path):
            return normalized, full_path
        if not os.path.isfile(full_path):
            raise ValueError("sourcePath 不是文件")
        return normalized, full_path

    matched_files = findSourceFilesInFolders(
        folder_paths,
        filePatterns=file_patterns,
        allowedExtensions=SOURCE_EXTENSIONS.get(data_type, []),
    )
    if not matched_files:
        raise ValueError("未找到匹配的输入文件")
    if len(matched_files) > 1:
        if data_type == "osgb":
            raise ValueError("匹配到多个 .osgb，请改用 sourcePath 指向上级目录以启用批量 OSGB 转换")
        if data_type == "pointcloud":
            matched_rel, matched_full = _resolve_relative_files(matched_files)
            return matched_rel, matched_full
        raise ValueError("当前版本每次仅支持处理单个输入文件，请缩小 filePatterns 或直接传 sourcePath")

    normalized = matched_files[0]
    ok, full_path = validateDataSourcePath(normalized)
    if not ok:
        raise ValueError(full_path)
    if not os.path.isfile(full_path):
        raise ValueError("匹配结果不是文件")
    return normalized, full_path


def _resolve_height_value(raw_value, default_value):
    value = normalizeFloat(raw_value, None)
    if value is None:
        return default_value
    return float(value)


def _normalize_vector_height_mode(value, default="meters"):
    text = str(value or "").strip().lower()
    if text in SUPPORTED_VECTOR_HEIGHT_MODES:
        return text
    return default


def _normalize_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _ecef_from_geodetic(longitude_deg, latitude_deg, height_m):
    lon = math.radians(float(longitude_deg))
    lat = math.radians(float(latitude_deg))
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + height_m) * cos_lat * cos_lon
    y = (n + height_m) * cos_lat * sin_lon
    z = (n * (1.0 - WGS84_E2) + height_m) * sin_lat
    return x, y, z


def _enu_transform(longitude_deg, latitude_deg, height_m):
    lon = math.radians(float(longitude_deg))
    lat = math.radians(float(latitude_deg))
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    x, y, z = _ecef_from_geodetic(longitude_deg, latitude_deg, height_m)
    east = (-sin_lon, cos_lon, 0.0)
    north = (-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat)
    up = (cos_lat * cos_lon, cos_lat * sin_lon, sin_lat)
    return [
        east[0], east[1], east[2], 0.0,
        north[0], north[1], north[2], 0.0,
        up[0], up[1], up[2], 0.0,
        x, y, z, 1.0,
    ]


def _multiply_matrix4(left, right):
    result = [0.0] * 16
    left_values = [float(value) for value in (left or [])[:16]]
    right_values = [float(value) for value in (right or [])[:16]]
    if len(left_values) != 16 or len(right_values) != 16:
        raise RuntimeError("4x4 变换矩阵格式无效")

    for column in range(4):
        for row in range(4):
            value = 0.0
            for inner in range(4):
                value += left_values[inner * 4 + row] * right_values[column * 4 + inner]
            result[column * 4 + row] = value
    return result


def _build_local_scene_transform(scale, rotation_z_degrees):
    scale_value = float(scale if scale is not None else 1.0)
    rotation_radians = math.radians(float(rotation_z_degrees or 0.0))
    cos_theta = math.cos(rotation_radians)
    sin_theta = math.sin(rotation_radians)
    scaled_cos = scale_value * cos_theta
    scaled_sin = scale_value * sin_theta
    return [
        scaled_cos, scaled_sin, 0.0, 0.0,
        -scaled_sin, scaled_cos, 0.0, 0.0,
        0.0, 0.0, scale_value, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _compose_tileset_transform(longitude, latitude, height, scale=1.0, rotation_z_degrees=0.0):
    root_transform = _enu_transform(float(longitude), float(latitude), float(height or 0.0))
    scale_value = float(scale if scale is not None else 1.0)
    rotation_value = float(rotation_z_degrees or 0.0)
    if abs(scale_value - 1.0) < 1e-12 and abs(rotation_value) < 1e-12:
        return root_transform
    local_transform = _build_local_scene_transform(scale_value, rotation_value)
    return _multiply_matrix4(root_transform, local_transform)


def _meters_per_degree(longitude_deg, latitude_deg):
    lat_rad = math.radians(float(latitude_deg))
    meters_per_degree_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad) + 1.175 * math.cos(4 * lat_rad)
    meters_per_degree_lon = 111412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad)
    return meters_per_degree_lon, meters_per_degree_lat


def _traditional_gis_order_srs(spatial_ref):
    if spatial_ref is None:
        return None
    try:
        from osgeo import osr
    except Exception:
        return spatial_ref

    cloned = spatial_ref.Clone()
    try:
        cloned.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    except Exception:
        pass
    return cloned


def _region_bounds(west, south, east, north, min_height, max_height):
    return [
        math.radians(float(west)),
        math.radians(float(south)),
        math.radians(float(east)),
        math.radians(float(north)),
        float(min_height),
        float(max_height),
    ]


def _write_tileset(
    output_dir,
    west,
    south,
    east,
    north,
    min_height,
    max_height,
    transform=None,
    content_uri=None,
    children=None,
    asset_version="1.1",
    gltf_up_axis=None,
    root_geometric_error=None,
):
    import json

    default_error = max(1.0, float(max_height or 1.0) - float(min_height or 0.0))
    root_error = float(root_geometric_error) if root_geometric_error is not None else default_error
    tileset = {
        "asset": {"version": str(asset_version or "1.1")},
        "geometricError": max(1.0, root_error),
        "root": {
            "boundingVolume": {"region": _region_bounds(west, south, east, north, min_height, max_height)},
            "geometricError": max(1.0, root_error),
            "refine": "ADD",
        },
    }
    axis = str(gltf_up_axis or "").strip().upper()
    if axis in {"X", "Y", "Z"}:
        tileset["asset"]["gltfUpAxis"] = axis
    if content_uri:
        tileset["root"]["content"] = {"uri": str(content_uri)}
    if children:
        tileset["root"]["children"] = list(children)
    if transform:
        tileset["root"]["transform"] = list(transform)

    tileset_path = os.path.join(output_dir, "tileset.json")
    with open(tileset_path, "w", encoding="utf-8") as file_obj:
        json.dump(tileset, file_obj, ensure_ascii=False, indent=2)
    return tileset_path


def _normalize_content_format(content_format):
    format_name = str(content_format or "b3dm").strip().lower()
    if format_name not in SUPPORTED_CONTENT_FORMATS:
        raise RuntimeError(f"不支持的 contentFormat: {content_format}")
    return format_name


def _looks_like_url(value):
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _join_uri_prefix(prefix, uri):
    raw_uri = str(uri or "")
    if not raw_uri or _looks_like_url(raw_uri) or raw_uri.startswith("/"):
        return raw_uri
    normalized_prefix = str(prefix or "").replace("\\", "/").strip("/")
    if not normalized_prefix:
        return raw_uri
    return f"{normalized_prefix}/{raw_uri}".replace("\\", "/")


def _prefix_tileset_uris(node, prefix):
    if isinstance(node, dict):
        content = node.get("content")
        if isinstance(content, dict) and "uri" in content:
            content["uri"] = _join_uri_prefix(prefix, content.get("uri"))

        contents = node.get("contents")
        if isinstance(contents, list):
            for item in contents:
                if isinstance(item, dict) and "uri" in item:
                    item["uri"] = _join_uri_prefix(prefix, item.get("uri"))

        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                _prefix_tileset_uris(child, prefix)


def _discover_generated_tileset(output_dir):
    root_tileset = os.path.join(output_dir, "tileset.json")
    if os.path.isfile(root_tileset):
        return root_tileset

    candidates = []
    for root, _, files in os.walk(output_dir):
        for filename in files:
            if str(filename).lower() != "tileset.json":
                continue
            full_path = os.path.join(root, filename)
            try:
                relative = os.path.relpath(full_path, output_dir)
            except Exception:
                relative = full_path
            depth = str(relative).replace("\\", "/").count("/")
            candidates.append((depth, len(str(relative)), full_path))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def _probe_pointcloud_crs_groups(sources, sample_limit=3):
    try:
        import laspy
    except Exception:
        return None

    groups = {}
    for source in sources:
        source_path = str(source or "")
        if not source_path:
            continue
        try:
            with laspy.open(source_path) as reader:
                parsed = reader.header.parse_crs()
                crs_name = parsed.to_string() if parsed else "UNKNOWN"
                point_count = int(getattr(reader.header, "point_count", 0) or 0)
        except Exception:
            crs_name = "UNREADABLE"
            point_count = 0

        entry = groups.setdefault(
            crs_name,
            {"count": 0, "points": 0, "samples": []},
        )
        entry["count"] += 1
        entry["points"] += max(0, point_count)
        if len(entry["samples"]) < int(sample_limit):
            entry["samples"].append(os.path.basename(source_path))
    return groups or None


def _format_pointcloud_convert_error(error, sources, crs):
    raw_message = str(error or "").strip()
    if not raw_message:
        raw_message = "py3dtiles 转换失败"

    lowered = raw_message.lower()
    if "same srs in" in lowered or "srsinmixinexception" in lowered:
        groups = _probe_pointcloud_crs_groups(sources)
        if groups:
            parts = []
            for crs_name, info in groups.items():
                samples = ", ".join(info.get("samples", []))
                parts.append(
                    f"{crs_name}: {info.get('count', 0)} 个文件, {info.get('points', 0)} 点"
                    + (f" (示例: {samples})" if samples else "")
                )
            merged = "；".join(parts)
            if crs:
                return (
                    f"点云输入包含混合坐标系，且 py3dtiles 无法自动合并：{merged}。"
                    f"你当前传入 crs={crs}，请确认所有文件坐标值本身属于同一坐标系后再强制转换。"
                )
            return (
                f"点云输入包含混合坐标系，py3dtiles 拒绝合并：{merged}。"
                "请按同一 CRS 分批转换，或显式传入 crs 强制统一（仅当坐标值本就同一坐标系时）。"
            )
    return raw_message


def _promote_nested_tileset_to_root(output_dir, discovered_tileset_path):
    if not discovered_tileset_path:
        return None

    root_tileset = os.path.join(output_dir, "tileset.json")
    discovered_abs = os.path.abspath(discovered_tileset_path)
    root_abs = os.path.abspath(root_tileset)
    if discovered_abs == root_abs:
        return root_tileset

    try:
        import json

        with open(discovered_abs, "r", encoding="utf-8") as file_obj:
            tileset_json = json.load(file_obj)

        nested_dir = os.path.dirname(discovered_abs)
        prefix = os.path.relpath(nested_dir, output_dir).replace("\\", "/").strip("/")
        if prefix and prefix != ".":
            _prefix_tileset_uris(tileset_json.get("root"), prefix)

        with open(root_tileset, "w", encoding="utf-8") as file_obj:
            json.dump(tileset_json, file_obj, ensure_ascii=False, indent=2)
        return root_tileset
    except Exception:
        return discovered_tileset_path


def _normalize_anchor_mode(value, default_mode="manual"):
    mode = str(value or default_mode).strip().lower()
    return mode if mode in {"manual", "auto"} else str(default_mode).strip().lower()


def _region_center(region):
    return (
        (float(region[0]) + float(region[2])) * 0.5,
        (float(region[1]) + float(region[3])) * 0.5,
    )


def _merge_regions(regions):
    if not regions:
        return None
    west = min(float(region[0]) for region in regions)
    south = min(float(region[1]) for region in regions)
    east = max(float(region[2]) for region in regions)
    north = max(float(region[3]) for region in regions)
    min_height = min(float(region[4]) for region in regions)
    max_height = max(float(region[5]) for region in regions)
    return [west, south, east, north, min_height, max_height]


def _estimate_geometric_error_for_region(region):
    center_lon = math.degrees((float(region[0]) + float(region[2])) * 0.5)
    center_lat = math.degrees((float(region[1]) + float(region[3])) * 0.5)
    lon_span = abs(math.degrees(float(region[2]) - float(region[0])))
    lat_span = abs(math.degrees(float(region[3]) - float(region[1])))
    meters_lon, meters_lat = _meters_per_degree(center_lon, center_lat)
    span_x = lon_span * max(meters_lon, 1.0)
    span_y = lat_span * max(meters_lat, 1.0)
    span_h = abs(float(region[5]) - float(region[4]))
    return max(1.0, max(span_x, span_y, span_h) * 0.25)


def _child_region(child):
    return ((child or {}).get("boundingVolume") or {}).get("region")


def _split_tiles_for_pyramid(children):
    if len(children) <= 1:
        return [list(children)]

    entries = []
    for index, child in enumerate(children):
        region = _child_region(child)
        if not region or len(region) < 6:
            return [list(children)]
        center_x, center_y = _region_center(region)
        entries.append((child, center_x, center_y, index))

    min_x = min(item[1] for item in entries)
    max_x = max(item[1] for item in entries)
    min_y = min(item[2] for item in entries)
    max_y = max(item[2] for item in entries)

    if abs(max_x - min_x) < 1e-12 and abs(max_y - min_y) < 1e-12:
        ordered = sorted(entries, key=lambda item: str((((item[0] or {}).get("content") or {}).get("uri") or item[3])))
        middle = max(1, len(ordered) // 2)
        first = [item[0] for item in ordered[:middle]]
        second = [item[0] for item in ordered[middle:]]
        return [group for group in [first, second] if group]

    mid_x = (min_x + max_x) * 0.5
    mid_y = (min_y + max_y) * 0.5
    buckets = [[], [], [], []]
    for child, center_x, center_y, _ in entries:
        bucket_index = 0
        if center_x >= mid_x:
            bucket_index += 1
        if center_y >= mid_y:
            bucket_index += 2
        buckets[bucket_index].append(child)

    groups = [group for group in buckets if group]
    if len(groups) > 1:
        return groups

    ordered = sorted(entries, key=lambda item: (item[1], item[2], item[3]))
    middle = max(1, len(ordered) // 2)
    first = [item[0] for item in ordered[:middle]]
    second = [item[0] for item in ordered[middle:]]
    return [group for group in [first, second] if group]


def _make_internal_pyramid_node(children):
    regions = []
    max_child_error = 0.0
    for child in children:
        region = _child_region(child)
        if region and len(region) >= 6:
            regions.append(region)
        max_child_error = max(max_child_error, float((child or {}).get("geometricError") or 0.0))

    node = {
        "geometricError": max(1.0, max_child_error),
        "refine": "ADD",
        "children": list(children),
    }
    merged_region = _merge_regions(regions)
    if merged_region:
        node["boundingVolume"] = {"region": merged_region}
        node["geometricError"] = max(float(node["geometricError"]), _estimate_geometric_error_for_region(merged_region))
    return node


def _build_pyramid_node(children, leaf_size, max_depth, depth):
    if not children:
        return None
    if len(children) == 1:
        return children[0]
    if depth >= max_depth or len(children) <= leaf_size:
        return _make_internal_pyramid_node(children)

    groups = _split_tiles_for_pyramid(children)
    if len(groups) <= 1:
        return _make_internal_pyramid_node(children)

    descendants = []
    for group in groups:
        child_node = _build_pyramid_node(group, leaf_size, max_depth, depth + 1)
        if child_node:
            descendants.append(child_node)
    if not descendants:
        return None
    if len(descendants) == 1:
        return descendants[0]
    return _make_internal_pyramid_node(descendants)


def _apply_optional_pyramid(children, enable_pyramid=False, pyramid_leaf_size=8, pyramid_max_depth=4):
    if not children:
        return [], None
    leaf_size = max(1, int(pyramid_leaf_size or 1))
    max_depth = max(1, int(pyramid_max_depth or 1))
    if not enable_pyramid or len(children) <= leaf_size:
        return list(children), None

    root_node = _build_pyramid_node(list(children), leaf_size, max_depth, 0)
    if not root_node:
        return list(children), None

    root_error = max(1.0, float((root_node or {}).get("geometricError") or 0.0))
    if isinstance(root_node, dict) and root_node.get("children"):
        return list(root_node["children"]), root_error
    return [root_node], root_error


def _collect_osgb_files(source_path, max_scan=200000):
    if isinstance(source_path, (list, tuple, set)):
        merged = []
        for item in source_path:
            merged.extend(_collect_osgb_files(item, max_scan=max_scan))
        merged = sorted(set(merged))
        if not merged:
            raise RuntimeError("OSGB 输入列表中未找到 .osgb 文件")
        return merged

    if _has_glob_pattern(source_path):
        matches = []
        for candidate in glob.glob(str(source_path), recursive=True):
            if os.path.isfile(candidate) and str(candidate).lower().endswith(".osgb"):
                matches.append(candidate)
        matches = sorted(set(matches))
        if not matches:
            raise RuntimeError("OSGB 通配符未匹配到 .osgb 文件")
        return matches

    if os.path.isfile(source_path):
        if str(source_path).lower().endswith(".osgb"):
            return [source_path]
        raise RuntimeError("OSGB 任务输入文件必须是 .osgb")
    if not os.path.isdir(source_path):
        raise RuntimeError("OSGB 输入路径不存在")

    matches = []
    scanned = 0
    for root, _, files in os.walk(source_path):
        for filename in files:
            scanned += 1
            if scanned > max_scan:
                raise RuntimeError("OSGB 目录文件过多，超过扫描上限")
            if str(filename).lower().endswith(".osgb"):
                matches.append(os.path.join(root, filename))

    if not matches:
        raise RuntimeError("OSGB 目录中未找到 .osgb 文件")
    matches.sort()
    return matches


def _parse_anchor_from_proj4_text(text):
    content = str(text or "")
    if not content:
        return None
    lon_match = re.search(r"(?:\+lon_0=)([-+]?[0-9]*\.?[0-9]+)", content)
    lat_match = re.search(r"(?:\+lat_0=)([-+]?[0-9]*\.?[0-9]+)", content)
    if not lon_match or not lat_match:
        return None
    try:
        longitude = float(lon_match.group(1))
        latitude = float(lat_match.group(1))
    except Exception:
        return None
    if abs(longitude) > 180 or abs(latitude) > 90:
        return None
    return longitude, latitude


def _extract_anchor_from_xodr(xodr_path):
    try:
        with open(xodr_path, "r", encoding="utf-8", errors="ignore") as file_obj:
            content = file_obj.read()
    except Exception:
        return None

    cdata_match = re.search(r"<geoReference[^>]*>\s*<!\[CDATA\[(.*?)\]\]>\s*</geoReference>", content, flags=re.IGNORECASE | re.DOTALL)
    if cdata_match:
        anchor = _parse_anchor_from_proj4_text(cdata_match.group(1))
        if anchor:
            return anchor

    tag_match = re.search(r"<geoReference[^>]*>(.*?)</geoReference>", content, flags=re.IGNORECASE | re.DOTALL)
    if tag_match:
        return _parse_anchor_from_proj4_text(tag_match.group(1))
    return None


def _iter_candidate_xodr_paths(source_path, max_scan_per_dir=40000):
    roots = []
    source_items = list(source_path) if isinstance(source_path, (list, tuple, set)) else [source_path]
    for item in source_items:
        item_path = str(item or "").strip()
        if not item_path:
            continue
        if _has_glob_pattern(item_path):
            base_dir = os.path.dirname(item_path)
        elif os.path.isfile(item_path):
            base_dir = os.path.dirname(item_path)
        elif os.path.isdir(item_path):
            base_dir = item_path
        else:
            base_dir = os.path.dirname(item_path)
        if not base_dir:
            continue
        current = os.path.abspath(base_dir)
        for _ in range(4):
            if current in roots:
                break
            roots.append(current)
            parent = os.path.dirname(current)
            if not parent or parent == current:
                break
            current = parent

    if not roots:
        return []

    candidates = []
    seen = set()
    for root in roots:
        scanned = 0
        for walk_root, _, files in os.walk(root):
            for filename in files:
                scanned += 1
                if scanned > max_scan_per_dir:
                    break
                if str(filename).lower().endswith(".xodr"):
                    full_path = os.path.join(walk_root, filename)
                    if full_path not in seen:
                        seen.add(full_path)
                        candidates.append(full_path)
            if scanned > max_scan_per_dir:
                break
    return candidates


def _guess_osgb_anchor_from_related_xodr(source_path, osgb_files):
    osgb_stems = {os.path.splitext(os.path.basename(path))[0].lower() for path in (osgb_files or [])}
    candidates = _iter_candidate_xodr_paths(source_path)
    if not candidates:
        return None

    weighted = []
    for xodr_path in candidates:
        anchor = _extract_anchor_from_xodr(xodr_path)
        if not anchor:
            continue
        stem = os.path.splitext(os.path.basename(xodr_path))[0].lower()
        score = 1
        if stem in osgb_stems:
            score += 10
        weighted.append((score, anchor[0], anchor[1], xodr_path))

    if not weighted:
        return None

    weighted.sort(key=lambda item: item[0], reverse=True)
    best_score = weighted[0][0]
    best_group = [item for item in weighted if item[0] == best_score]
    counts = {}
    for _, lon, lat, xodr_path in best_group:
        key = (round(float(lon), 7), round(float(lat), 7))
        entry = counts.get(key)
        if entry is None:
            counts[key] = {"count": 1, "path": xodr_path}
        else:
            entry["count"] += 1

    selected_key = None
    selected_count = -1
    selected_path = ""
    for key, entry in counts.items():
        if entry["count"] > selected_count:
            selected_key = key
            selected_count = entry["count"]
            selected_path = entry["path"]

    if selected_key is None:
        return None
    return {
        "longitude": float(selected_key[0]),
        "latitude": float(selected_key[1]),
        "source": selected_path,
        "confidence": "high" if best_score >= 11 else "medium",
    }


def _apply_scene_transform(scene, scale, rotation_z_degrees):
    try:
        import trimesh
    except Exception as exc:
        raise RuntimeError(f"模型处理依赖不可用: {exc}")

    if scale and scale != 1.0:
        scene.apply_scale(float(scale))
    if rotation_z_degrees:
        rotation = trimesh.transformations.rotation_matrix(
            math.radians(float(rotation_z_degrees)),
            [0, 0, 1],
        )
        scene.apply_transform(rotation)
    return scene


def _is_identity_transform(transform, tolerance=1e-9):
    if transform is None:
        return True
    try:
        import numpy as np
    except Exception:
        return False
    return bool(np.allclose(transform, np.eye(4), atol=float(tolerance)))


def _export_scene_content(scene, output_dir, content_stem, content_format):
    format_name = _normalize_content_format(content_format)
    glb_path = os.path.join(output_dir, f"{content_stem}.glb")
    scene.export(glb_path)
    return _finalize_glb_content(glb_path, output_dir, content_stem, format_name)


def _finalize_glb_content(glb_path, output_dir, content_stem, content_format):
    format_name = _normalize_content_format(content_format)
    target_glb_path = os.path.join(output_dir, f"{content_stem}.glb")
    source_glb_abs = os.path.abspath(glb_path)
    target_glb_abs = os.path.abspath(target_glb_path)

    if source_glb_abs != target_glb_abs:
        shutil.move(source_glb_abs, target_glb_abs)

    if format_name == "b3dm":
        b3dm_name = f"{content_stem}.b3dm"
        b3dm_path = os.path.join(output_dir, b3dm_name)
        _write_b3dm_from_glb(target_glb_path, b3dm_path)
        try:
            os.remove(target_glb_path)
        except Exception:
            pass
        return b3dm_name
    return f"{content_stem}.glb"


def _write_exported_obj_bundle(obj_text, assets, target_dir, chunk_stem):
    os.makedirs(target_dir, exist_ok=True)
    obj_path = os.path.join(target_dir, f"{chunk_stem}.obj")
    if isinstance(obj_text, bytes):
        obj_payload = obj_text.decode("utf-8", errors="ignore")
    else:
        obj_payload = str(obj_text or "")
    with open(obj_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(obj_payload)

    for asset_name, asset_content in dict(assets or {}).items():
        if not asset_name:
            continue
        asset_path = os.path.join(target_dir, str(asset_name))
        parent_dir = os.path.dirname(asset_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        if isinstance(asset_content, bytes):
            with open(asset_path, "wb") as file_obj:
                file_obj.write(asset_content)
        else:
            with open(asset_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(str(asset_content or ""))
    return obj_path


def _split_face_groups(face_centers, max_face_count):
    try:
        import numpy as np
    except Exception as exc:
        raise RuntimeError(f"OBJ 分块依赖不可用: {exc}")

    indices = np.arange(len(face_centers), dtype=int)
    if len(indices) <= int(max_face_count):
        return [indices.tolist()]

    pending = [indices]
    output = []
    while pending:
        current = pending.pop()
        if len(current) <= int(max_face_count):
            output.append(current.tolist())
            continue

        centers = face_centers[current]
        spans = centers.max(axis=0) - centers.min(axis=0)
        axis = int(0 if spans[0] >= spans[1] else 1)
        ordered = current[np.argsort(centers[:, axis], kind="mergesort")]
        pivot = len(ordered) // 2
        if pivot <= 0 or pivot >= len(ordered):
            output.append(current.tolist())
            continue
        pending.append(ordered[pivot:])
        pending.append(ordered[:pivot])
    return output


def _build_model_mesh_record(mesh, name, geometry_name=None, transform=None, face_indices=None):
    bounds = getattr(mesh, "bounds", None)
    if bounds is None:
        return None
    faces = getattr(mesh, "faces", None)
    face_count = 0 if faces is None else int(len(faces))
    min_corner = [float(value) for value in bounds[0]]
    max_corner = [float(value) for value in bounds[1]]
    if any(math.isnan(value) for value in min_corner + max_corner):
        return None
    return {
        "name": str(name or "mesh"),
        "geometryName": str(geometry_name or name or "mesh"),
        "transform": list(transform) if transform is not None else None,
        "faceIndices": list(face_indices) if face_indices else None,
        "minCorner": min_corner,
        "maxCorner": max_corner,
        "centroidX": float((min_corner[0] + max_corner[0]) * 0.5),
        "centroidY": float((min_corner[1] + max_corner[1]) * 0.5),
        "centroidZ": float((min_corner[2] + max_corner[2]) * 0.5),
        "faceCount": face_count,
    }


def _split_model_mesh_records(mesh, base_name, geometry_name, transform=None, max_face_count=MAX_MODEL_CHUNK_FACE_COUNT):
    faces = getattr(mesh, "faces", None)
    face_count = 0 if faces is None else int(len(faces))
    if face_count <= 0 or face_count <= int(max_face_count):
        record = _build_model_mesh_record(mesh, base_name, geometry_name=geometry_name, transform=transform)
        return [record] if record else []

    try:
        face_centers = mesh.triangles_center
    except Exception:
        record = _build_model_mesh_record(mesh, base_name, geometry_name=geometry_name, transform=transform)
        return [record] if record else []

    records = []
    for chunk_index, face_indices in enumerate(_split_face_groups(face_centers, max_face_count)):
        if not face_indices:
            continue
        submesh = mesh.submesh([face_indices], append=True, repair=False)
        record = _build_model_mesh_record(
            submesh,
            f"{base_name}_{chunk_index:04d}",
            geometry_name=geometry_name,
            transform=transform,
            face_indices=face_indices,
        )
        if record:
            records.append(record)
    return records


def _materialize_model_record_mesh(scene, record):
    try:
        import numpy as np
        import trimesh
    except Exception as exc:
        raise RuntimeError(f"OBJ 分块依赖不可用: {exc}")

    geometry_name = str(record.get("geometryName") or "")
    geometry = scene.geometry.get(geometry_name)
    if geometry is None or not isinstance(geometry, trimesh.Trimesh):
        raise RuntimeError(f"OBJ 分块缺少几何对象: {geometry_name}")

    mesh = geometry.copy()
    transform = record.get("transform")
    if transform is not None and not _is_identity_transform(transform):
        mesh.apply_transform(np.asarray(transform, dtype=float))

    face_indices = record.get("faceIndices")
    if face_indices:
        mesh = mesh.submesh([face_indices], append=True, repair=False)
    return mesh


def _collect_model_mesh_records(scene, max_face_count=MAX_MODEL_CHUNK_FACE_COUNT, stop_checker=None):
    try:
        import numpy as np
        import trimesh
    except Exception as exc:
        raise RuntimeError(f"OBJ 分块依赖不可用: {exc}")

    records = []
    geometry_nodes = list(scene.graph.nodes_geometry)
    for node_name in geometry_nodes:
        _ensure_not_stopped(stop_checker)
        transform, geom_name = scene.graph[node_name]
        geometry = scene.geometry.get(geom_name)
        if geometry is None or not isinstance(geometry, trimesh.Trimesh):
            continue
        mesh = geometry.copy()
        transform_matrix = None
        if transform is not None and not _is_identity_transform(transform):
            transform_matrix = np.asarray(transform, dtype=float)
            mesh.apply_transform(transform_matrix)
        records.extend(
            _split_model_mesh_records(
                mesh,
                str(node_name or geom_name),
                str(geom_name),
                transform=transform_matrix.reshape(-1).tolist() if transform_matrix is not None else None,
                max_face_count=max_face_count,
            )
        )
    return records


def _split_model_chunk_records(records, target_records=TARGET_MODEL_CHUNK_RECORDS):
    if not records:
        return []

    max_records = max(1, int(target_records or 1))
    pending = [list(records)]
    output = []
    while pending:
        current = pending.pop()
        if len(current) <= max_records:
            output.append(current)
            continue

        span_x = max(item["centroidX"] for item in current) - min(item["centroidX"] for item in current)
        span_y = max(item["centroidY"] for item in current) - min(item["centroidY"] for item in current)
        key_name = "centroidX" if span_x >= span_y else "centroidY"
        ordered = sorted(current, key=lambda item: float(item[key_name]))
        pivot = len(ordered) // 2
        if pivot <= 0 or pivot >= len(ordered):
            output.append(current)
            continue
        pending.append(ordered[pivot:])
        pending.append(ordered[:pivot])
    return output


def _export_model_chunk_records(
    scene,
    records,
    output_dir,
    chunk_stem,
    content_format,
    task_id=None,
    stop_checker=None,
):
    try:
        import trimesh
    except Exception as exc:
        raise RuntimeError(f"OBJ 分块依赖不可用: {exc}")

    if not records:
        raise RuntimeError("OBJ 分块为空")

    min_x = min(float(item["minCorner"][0]) for item in records)
    min_y = min(float(item["minCorner"][1]) for item in records)
    min_z = min(float(item["minCorner"][2]) for item in records)
    max_x = max(float(item["maxCorner"][0]) for item in records)
    max_y = max(float(item["maxCorner"][1]) for item in records)
    max_z = max(float(item["maxCorner"][2]) for item in records)
    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5
    center_z = (min_z + max_z) * 0.5

    chunk_scene = trimesh.Scene()
    for record_index, record in enumerate(records):
        _ensure_not_stopped(stop_checker)
        mesh = _materialize_model_record_mesh(scene, record)
        mesh.apply_translation([-center_x, -center_y, -center_z])
        chunk_name = f"{chunk_stem}_{record_index:04d}"
        chunk_scene.add_geometry(mesh, node_name=chunk_name, geom_name=chunk_name)

    exported = chunk_scene.export(file_type="obj", include_texture=True, return_texture=True)
    if isinstance(exported, tuple):
        obj_text, assets = exported
    else:
        obj_text, assets = exported, {}

    temp_dir = tempfile.mkdtemp(prefix=f"atlasworks-{chunk_stem}-")
    try:
        _ensure_not_stopped(stop_checker)
        obj_path = _write_exported_obj_bundle(obj_text, assets, temp_dir, chunk_stem)
        glb_path = os.path.join(output_dir, f"{chunk_stem}.glb")
        _convert_obj_to_glb(obj_path, glb_path, task_id=task_id)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    content_file = _finalize_glb_content(glb_path, output_dir, chunk_stem, content_format)
    del chunk_scene
    gc.collect()
    return {
        "contentFile": content_file,
        "minCorner": [min_x, min_y, min_z],
        "maxCorner": [max_x, max_y, max_z],
        "center": [center_x, center_y, center_z],
        "recordCount": len(records),
    }


def _convert_obj_to_glb(source_path, glb_path, task_id=None):
    command = ["obj2gltf", "-i", source_path, "-o", glb_path, "-b"]
    if task_id:
        result = runCommandWithProcessTracking(command, task_id)
    else:
        result = runCommand(command)
    if not result.get("success"):
        raise RuntimeError(result.get("stderr") or result.get("error") or "obj2gltf 执行失败")
    if not os.path.exists(glb_path):
        raise RuntimeError("obj2gltf 未生成 GLB 输出")
    return glb_path


def _convert_osgb_to_obj(source_path, obj_path, task_id=None):
    if task_id:
        result = runCommandWithProcessTracking(["osgconv", source_path, obj_path], task_id)
    else:
        result = runCommand(["osgconv", source_path, obj_path])
    if not result.get("success"):
        raise RuntimeError(result.get("stderr") or result.get("error") or "osgconv 执行失败")
    if not os.path.exists(obj_path):
        raise RuntimeError("osgconv 未生成 OBJ 输出")


def _polygon_area(points):
    area = 0.0
    for index in range(len(points)):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return area * 0.5


def _is_point_in_triangle(point, a, b, c):
    px, py = point
    ax, ay = a
    bx, by = b
    cx, cy = c

    v0x = cx - ax
    v0y = cy - ay
    v1x = bx - ax
    v1y = by - ay
    v2x = px - ax
    v2y = py - ay

    dot00 = v0x * v0x + v0y * v0y
    dot01 = v0x * v1x + v0y * v1y
    dot02 = v0x * v2x + v0y * v2y
    dot11 = v1x * v1x + v1y * v1y
    dot12 = v1x * v2x + v1y * v2y

    denominator = dot00 * dot11 - dot01 * dot01
    if abs(denominator) < 1e-12:
        return False
    inverse = 1.0 / denominator
    u = (dot11 * dot02 - dot01 * dot12) * inverse
    v = (dot00 * dot12 - dot01 * dot02) * inverse
    return u >= 0 and v >= 0 and (u + v) <= 1


def _triangulate_polygon(points):
    if len(points) < 3:
        return []

    working = list(range(len(points)))
    triangles = []
    if _polygon_area(points) < 0:
        working.reverse()

    guard = 0
    while len(working) > 3 and guard < len(points) * len(points):
        ear_found = False
        for index in range(len(working)):
            prev_index = working[index - 1]
            current_index = working[index]
            next_index = working[(index + 1) % len(working)]
            a = points[prev_index]
            b = points[current_index]
            c = points[next_index]
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if cross <= 0:
                continue
            contains_point = False
            for candidate in working:
                if candidate in {prev_index, current_index, next_index}:
                    continue
                if _is_point_in_triangle(points[candidate], a, b, c):
                    contains_point = True
                    break
            if contains_point:
                continue
            triangles.append((prev_index, current_index, next_index))
            del working[index]
            ear_found = True
            break
        if not ear_found:
            break
        guard += 1

    if len(working) == 3:
        triangles.append((working[0], working[1], working[2]))
    return triangles


def _extrude_polygon(points_xy, base_height, top_height):
    if len(points_xy) < 3 or top_height <= base_height:
        return [], []

    triangles = _triangulate_polygon(points_xy)
    if not triangles:
        return [], []

    vertices = []
    faces = []
    top_offset = len(points_xy)

    for x, y in points_xy:
        vertices.append([x, y, float(base_height)])
    for x, y in points_xy:
        vertices.append([x, y, float(top_height)])

    for a, b, c in triangles:
        faces.append([top_offset + a, top_offset + b, top_offset + c])
        faces.append([c, b, a])

    for index in range(len(points_xy)):
        next_index = (index + 1) % len(points_xy)
        faces.append([index, next_index, top_offset + next_index])
        faces.append([index, top_offset + next_index, top_offset + index])

    return vertices, faces


def _split_vector_chunk_records(
    records,
    max_lon_span=MAX_VECTOR_CHUNK_LON_SPAN_DEG,
    max_lat_span=MAX_VECTOR_CHUNK_LAT_SPAN_DEG,
    min_records=MIN_VECTOR_SPLIT_RECORDS,
):
    pending = [list(records or [])]
    output = []

    while pending:
        subset = pending.pop()
        if not subset:
            continue
        if len(subset) <= max(2, int(min_records or 1)):
            output.append(subset)
            continue

        subset_west = min(item["west"] for item in subset)
        subset_south = min(item["south"] for item in subset)
        subset_east = max(item["east"] for item in subset)
        subset_north = max(item["north"] for item in subset)
        lon_span = float(subset_east - subset_west)
        lat_span = float(subset_north - subset_south)

        if lon_span <= float(max_lon_span) and lat_span <= float(max_lat_span):
            output.append(subset)
            continue

        split_by_lon = lon_span >= lat_span
        if split_by_lon:
            sorted_subset = sorted(subset, key=lambda item: float(item["centroidLon"]))
        else:
            sorted_subset = sorted(subset, key=lambda item: float(item["centroidLat"]))

        pivot_index = max(1, len(sorted_subset) // 2)
        left_subset = sorted_subset[:pivot_index]
        right_subset = sorted_subset[pivot_index:]
        if not left_subset or not right_subset:
            output.append(subset)
            continue
        pending.append(right_subset)
        pending.append(left_subset)

    return output


def _export_vector_tiles(
    source_path,
    output_dir,
    height_field,
    default_height,
    content_format,
    vector_height_mode="meters",
    floor_height_meters=DEFAULT_FLOOR_HEIGHT_METERS,
    enable_pyramid=False,
    pyramid_leaf_size=8,
    pyramid_max_depth=4,
    stop_checker=None,
):
    try:
        import numpy as np
        import trimesh
        from osgeo import ogr, osr
    except Exception as exc:
        raise RuntimeError(f"矢量 3D Tiles 依赖不可用: {exc}")

    format_name = _normalize_content_format(content_format)

    dataset = ogr.Open(source_path)
    if dataset is None:
        raise RuntimeError("无法打开矢量数据源")

    layer = dataset.GetLayer(0)
    if layer is None:
        raise RuntimeError("矢量图层不存在")

    source_srs = _traditional_gis_order_srs(layer.GetSpatialRef())
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(4326)
    target_srs = _traditional_gis_order_srs(target_srs)
    transform_to_wgs84 = None
    if source_srs and not source_srs.IsSame(target_srs):
        transform_to_wgs84 = osr.CoordinateTransformation(source_srs, target_srs)

    vector_height_mode = _normalize_vector_height_mode(vector_height_mode, "meters")
    floor_height_meters = max(0.1, _resolve_height_value(floor_height_meters, DEFAULT_FLOOR_HEIGHT_METERS))
    default_height_meters = float(default_height) * floor_height_meters if vector_height_mode == "floors" else float(default_height)

    feature_records = []
    west = 180.0
    south = 90.0
    east = -180.0
    north = -90.0
    min_height = 0.0
    max_height = float(default_height_meters)
    layer.ResetReading()
    for feature in layer:
        _ensure_not_stopped(stop_checker)
        geometry = feature.GetGeometryRef()
        if geometry is None:
            continue
        geometry = geometry.Clone()
        if transform_to_wgs84:
            geometry.Transform(transform_to_wgs84)

        raw_height_value = _resolve_height_value(
            feature.GetField(height_field) if height_field and feature.GetFieldIndex(height_field) >= 0 else None,
            default_height,
        )
        height_value = float(raw_height_value) * floor_height_meters if vector_height_mode == "floors" else float(raw_height_value)
        if height_value < 0:
            continue
        if abs(float(height_value)) < 1e-9:
            # Allow "贴地" usage when fallback height is 0 while keeping mesh export valid.
            height_value = MIN_VECTOR_EXTRUSION_HEIGHT

        geometry_type = geometry.GetGeometryType()
        polygons = []
        if geometry_type in (ogr.wkbPolygon, ogr.wkbPolygon25D):
            polygons = [geometry]
        elif geometry_type in (ogr.wkbMultiPolygon, ogr.wkbMultiPolygon25D):
            polygons = [geometry.GetGeometryRef(index) for index in range(geometry.GetGeometryCount())]
        else:
            continue

        for polygon in polygons:
            _ensure_not_stopped(stop_checker)
            ring = polygon.GetGeometryRef(0)
            if ring is None:
                continue
            points = []
            for index in range(ring.GetPointCount()):
                lon, lat, *_ = ring.GetPoint(index)
                points.append((lon, lat))
            if len(points) > 1 and points[0] == points[-1]:
                points = points[:-1]
            if len(points) < 3:
                continue

            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            poly_west = min(xs)
            poly_south = min(ys)
            poly_east = max(xs)
            poly_north = max(ys)
            west = min(west, poly_west)
            south = min(south, poly_south)
            east = max(east, poly_east)
            north = max(north, poly_north)
            max_height = max(max_height, height_value)
            feature_records.append(
                {
                    "points": points,
                    "height": float(height_value),
                    "west": float(poly_west),
                    "south": float(poly_south),
                    "east": float(poly_east),
                    "north": float(poly_north),
                    "centroidLon": float((poly_west + poly_east) * 0.5),
                    "centroidLat": float((poly_south + poly_north) * 0.5),
                }
            )

    if not feature_records:
        raise RuntimeError("未生成任何有效建筑几何，当前仅支持简单 Polygon/MultiPolygon")

    target_features_per_chunk = 400
    target_chunks = max(1, int(math.ceil(float(len(feature_records)) / float(target_features_per_chunk))))
    lon_span = max(float(east - west), 1e-6)
    lat_span = max(float(north - south), 1e-6)
    span_ratio = max(0.2, min(5.0, lon_span / lat_span))
    grid_x = max(1, int(math.ceil(math.sqrt(target_chunks * span_ratio))))
    grid_y = max(1, int(math.ceil(float(target_chunks) / float(grid_x))))

    chunk_groups = {}
    for record in feature_records:
        chunk_x = int((record["centroidLon"] - west) / lon_span * grid_x) if lon_span > 1e-9 else 0
        chunk_y = int((record["centroidLat"] - south) / lat_span * grid_y) if lat_span > 1e-9 else 0
        chunk_x = min(max(chunk_x, 0), grid_x - 1)
        chunk_y = min(max(chunk_y, 0), grid_y - 1)
        chunk_groups.setdefault((chunk_x, chunk_y), []).append(record)

    refined_chunk_groups = []
    for _, grouped_records in sorted(chunk_groups.items(), key=lambda item: item[0]):
        if not grouped_records:
            continue
        refined_chunk_groups.extend(_split_vector_chunk_records(grouped_records))

    children = []
    content_files = []
    total_chunk_features = 0
    chunk_index = 0
    for records in refined_chunk_groups:
        _ensure_not_stopped(stop_checker)
        if not records:
            continue

        chunk_west = min(item["west"] for item in records)
        chunk_south = min(item["south"] for item in records)
        chunk_east = max(item["east"] for item in records)
        chunk_north = max(item["north"] for item in records)
        chunk_center_lon = (chunk_west + chunk_east) * 0.5
        chunk_center_lat = (chunk_south + chunk_north) * 0.5
        meters_lon, meters_lat = _meters_per_degree(chunk_center_lon, chunk_center_lat)

        all_vertices = []
        all_faces = []
        offset = 0
        chunk_max_height = 0.0
        chunk_feature_count = 0
        for record in records:
            _ensure_not_stopped(stop_checker)
            local_points = [
                ((lon - chunk_center_lon) * meters_lon, (lat - chunk_center_lat) * meters_lat)
                for lon, lat in record["points"]
            ]
            vertices, faces = _extrude_polygon(local_points, 0.0, record["height"])
            if not vertices or not faces:
                continue
            all_vertices.extend(vertices)
            all_faces.extend([[a + offset, b + offset, c + offset] for a, b, c in faces])
            offset += len(vertices)
            chunk_max_height = max(chunk_max_height, float(record["height"]))
            chunk_feature_count += 1

        if not all_vertices or not all_faces:
            continue

        mesh = trimesh.Trimesh(
            vertices=np.asarray(all_vertices, dtype=float),
            faces=np.asarray(all_faces, dtype=int),
            process=False,
        )
        chunk_file_stem = f"chunk_{chunk_index:04d}"
        chunk_glb_path = os.path.join(output_dir, f"{chunk_file_stem}.glb")
        mesh.export(chunk_glb_path)
        if format_name == "b3dm":
            chunk_b3dm_path = os.path.join(output_dir, f"{chunk_file_stem}.b3dm")
            _write_b3dm_from_glb(chunk_glb_path, chunk_b3dm_path)
            try:
                os.remove(chunk_glb_path)
            except Exception:
                pass
            chunk_file = f"{chunk_file_stem}.b3dm"
        else:
            chunk_file = f"{chunk_file_stem}.glb"
        content_files.append(chunk_file)
        children.append(
            {
                "boundingVolume": {
                    "region": _region_bounds(chunk_west, chunk_south, chunk_east, chunk_north, min_height, chunk_max_height)
                },
                "geometricError": 0,
                "refine": "ADD",
                "transform": _enu_transform(chunk_center_lon, chunk_center_lat, min_height),
                "content": {"uri": chunk_file},
            }
        )
        chunk_index += 1
        total_chunk_features += chunk_feature_count

    if not children:
        raise RuntimeError("未生成有效分块模型，无法输出 3D Tiles")

    final_children, root_geometric_error = _apply_optional_pyramid(
        children,
        enable_pyramid=enable_pyramid,
        pyramid_leaf_size=pyramid_leaf_size,
        pyramid_max_depth=pyramid_max_depth,
    )
    tileset_path = _write_tileset(
        output_dir,
        west,
        south,
        east,
        north,
        min_height,
        max_height,
        children=final_children,
        asset_version="1.0" if format_name == "b3dm" else "1.1",
        gltf_up_axis="Z",
        root_geometric_error=root_geometric_error,
    )
    return {
        "tilesetPath": tileset_path,
        "entryFile": tileset_path,
        "contentFiles": content_files,
        "bounds": [west, south, east, north],
        "featureCount": total_chunk_features,
        "chunkCount": len(children),
        "rootChildren": len(final_children),
    }


def _load_scene(source_path):
    try:
        import trimesh
    except Exception as exc:
        raise RuntimeError(f"模型处理依赖不可用: {exc}")

    scene = trimesh.load(source_path, force="scene")
    if scene is None:
        raise RuntimeError("无法读取模型")
    return scene


def _estimate_region_from_anchor(longitude, latitude, bounds):
    min_corner, max_corner = bounds
    extent_x = max(abs(float(min_corner[0])), abs(float(max_corner[0])))
    extent_y = max(abs(float(min_corner[1])), abs(float(max_corner[1])))
    meters_lon, meters_lat = _meters_per_degree(longitude, latitude)
    delta_lon = extent_x / max(meters_lon, 1.0)
    delta_lat = extent_y / max(meters_lat, 1.0)
    return (
        longitude - delta_lon,
        latitude - delta_lat,
        longitude + delta_lon,
        latitude + delta_lat,
    )


def _export_scene_tiles(
    scene,
    output_dir,
    longitude,
    latitude,
    height,
    scale,
    rotation_z_degrees,
    content_format,
    stop_checker=None,
):
    if longitude is None or latitude is None:
        raise RuntimeError("OBJ/OSGB 需要提供 longitude 与 latitude 作为锚点")

    _ensure_not_stopped(stop_checker)
    _apply_scene_transform(scene, scale, rotation_z_degrees)
    format_name = _normalize_content_format(content_format)
    _ensure_not_stopped(stop_checker)
    content_file = _export_scene_content(scene, output_dir, "scene", format_name)

    bounds = scene.bounds
    min_height = float(height or 0.0) + float(bounds[0][2])
    max_height = float(height or 0.0) + float(bounds[1][2])
    west, south, east, north = _estimate_region_from_anchor(float(longitude), float(latitude), bounds)
    tileset_path = _write_tileset(
        output_dir,
        west,
        south,
        east,
        north,
        min_height,
        max_height,
        transform=_enu_transform(float(longitude), float(latitude), float(height or 0.0)),
        content_uri=content_file,
        asset_version="1.0" if format_name == "b3dm" else "1.1",
        gltf_up_axis="Z",
    )
    return {
        "tilesetPath": tileset_path,
        "entryFile": tileset_path,
        "contentFiles": [content_file],
        "bounds": [west, south, east, north],
        "sceneBounds": bounds.tolist(),
    }


def _export_obj_tiles(
    source_path,
    output_dir,
    longitude,
    latitude,
    height,
    scale,
    rotation_z_degrees,
    content_format,
    enable_pyramid=False,
    pyramid_leaf_size=8,
    pyramid_max_depth=4,
    task_id=None,
    stop_checker=None,
):
    if longitude is None or latitude is None:
        raise RuntimeError("OBJ/OSGB 需要提供 longitude 与 latitude 作为锚点")

    _ensure_not_stopped(stop_checker)
    scene = _load_scene(source_path)
    _apply_scene_transform(scene, scale, rotation_z_degrees)
    _ensure_not_stopped(stop_checker)
    format_name = _normalize_content_format(content_format)
    bounds = scene.bounds
    min_height = float(height or 0.0) + float(bounds[0][2])
    max_height = float(height or 0.0) + float(bounds[1][2])
    west, south, east, north = _estimate_region_from_anchor(float(longitude), float(latitude), bounds)

    content_files = []
    export_mode = "trimesh-single"
    texture_error = None
    try:
        _ensure_not_stopped(stop_checker)
        model_records = _collect_model_mesh_records(scene, stop_checker=stop_checker)
        if not model_records:
            raise RuntimeError("OBJ 中未发现可用几何，无法执行分块导出")

        meters_lon_ref, meters_lat_ref = _meters_per_degree(float(longitude), float(latitude))
        chunk_groups = _split_model_chunk_records(model_records, target_records=TARGET_MODEL_CHUNK_RECORDS)
        children = []
        total_features = 0
        for chunk_index, chunk_records in enumerate(chunk_groups):
            _ensure_not_stopped(stop_checker)
            if not chunk_records:
                continue

            chunk_stem = f"chunk_{chunk_index:04d}"
            chunk_result = _export_model_chunk_records(
                scene,
                chunk_records,
                output_dir,
                chunk_stem,
                format_name,
                task_id=task_id,
                stop_checker=stop_checker,
            )
            content_file = chunk_result["contentFile"]
            content_files.append(content_file)

            min_corner = chunk_result["minCorner"]
            max_corner = chunk_result["maxCorner"]
            center = chunk_result["center"]
            center_x, center_y, center_z = center
            half_x = max((max_corner[0] - min_corner[0]) * 0.5, 0.01)
            half_y = max((max_corner[1] - min_corner[1]) * 0.5, 0.01)
            chunk_lon = float(longitude) + (center_x / max(meters_lon_ref, 1.0))
            chunk_lat = float(latitude) + (center_y / max(meters_lat_ref, 1.0))
            meters_lon, meters_lat = _meters_per_degree(chunk_lon, chunk_lat)
            delta_lon = half_x / max(meters_lon, 1.0)
            delta_lat = half_y / max(meters_lat, 1.0)
            chunk_min_height = float(height or 0.0) + min_corner[2]
            chunk_max_height = float(height or 0.0) + max_corner[2]
            chunk_height = float(height or 0.0) + center_z

            children.append(
                {
                    "boundingVolume": {
                        "region": _region_bounds(
                            chunk_lon - delta_lon,
                            chunk_lat - delta_lat,
                            chunk_lon + delta_lon,
                            chunk_lat + delta_lat,
                            chunk_min_height,
                            chunk_max_height,
                        )
                    },
                    "geometricError": 0,
                    "refine": "ADD",
                    "transform": _enu_transform(chunk_lon, chunk_lat, chunk_height),
                    "content": {"uri": content_file},
                }
            )
            total_features += int(chunk_result.get("recordCount") or 0)
            gc.collect()

        if not children:
            raise RuntimeError("OBJ 分块导出失败：未生成有效内容")

        final_children, root_geometric_error = _apply_optional_pyramid(
            children,
            enable_pyramid=enable_pyramid,
            pyramid_leaf_size=pyramid_leaf_size,
            pyramid_max_depth=pyramid_max_depth,
        )
        tileset_path = _write_tileset(
            output_dir,
            west,
            south,
            east,
            north,
            min_height,
            max_height,
            children=final_children,
            asset_version="1.0" if format_name == "b3dm" else "1.1",
            gltf_up_axis="Z",
            root_geometric_error=root_geometric_error,
        )
        return {
            "tilesetPath": tileset_path,
            "entryFile": tileset_path,
            "contentFiles": content_files,
            "bounds": [west, south, east, north],
            "sceneBounds": bounds.tolist(),
            "featureCount": total_features,
            "chunkCount": len(children),
            "rootChildren": len(final_children),
            "exportMode": "obj2gltf-chunked",
        }
    except Exception as exc:
        texture_error = str(exc)
        logMessage(f"OBJ 分块纹理导出链路不可用，回退单体导出: {texture_error}", "WARNING")
        _ensure_not_stopped(stop_checker)
        content_file = None
        transform = _enu_transform(float(longitude), float(latitude), float(height or 0.0))
        try:
            glb_path = os.path.join(output_dir, "scene.glb")
            _convert_obj_to_glb(source_path, glb_path, task_id=task_id)
            content_file = _finalize_glb_content(glb_path, output_dir, "scene", format_name)
            transform = _compose_tileset_transform(
                float(longitude),
                float(latitude),
                float(height or 0.0),
                scale=scale,
                rotation_z_degrees=rotation_z_degrees,
            )
            export_mode = "obj2gltf-single"
        except Exception as single_exc:
            texture_error = f"{texture_error}; single={single_exc}"
            logMessage(f"OBJ 纹理单体导出链路不可用，回退 trimesh 导出: {single_exc}", "WARNING")
            _ensure_not_stopped(stop_checker)
            content_file = _export_scene_content(scene, output_dir, "scene", format_name)

        tileset_path = _write_tileset(
            output_dir,
            west,
            south,
            east,
            north,
            min_height,
            max_height,
            transform=transform,
            content_uri=content_file,
            asset_version="1.0" if format_name == "b3dm" else "1.1",
            gltf_up_axis="Z",
        )
        content_files = [content_file]

    result = {
        "tilesetPath": tileset_path,
        "entryFile": tileset_path,
        "contentFiles": content_files,
        "bounds": [west, south, east, north],
        "sceneBounds": bounds.tolist(),
        "exportMode": export_mode,
    }
    if texture_error:
        result["texturePipelineWarning"] = texture_error
    return result


def _export_osgb_tiles(
    source_path,
    output_dir,
    longitude,
    latitude,
    height,
    scale,
    rotation_z_degrees,
    content_format,
    enable_pyramid=False,
    pyramid_leaf_size=8,
    pyramid_max_depth=4,
    task_id=None,
    stop_checker=None,
):
    if longitude is None or latitude is None:
        raise RuntimeError("OSGB 转换必须提供 longitude 与 latitude 作为锚点")
    format_name = _normalize_content_format(content_format)
    osgb_files = _collect_osgb_files(source_path)
    if len(osgb_files) == 1:
        source_path = osgb_files[0]
        temp_dir = tempfile.mkdtemp(prefix="atlasworks-osgb-")
        try:
            obj_path = os.path.join(temp_dir, "osgb_converted.obj")
            _ensure_not_stopped(stop_checker)
            _convert_osgb_to_obj(source_path, obj_path, task_id=task_id)
            _ensure_not_stopped(stop_checker)
            return _export_obj_tiles(
                obj_path,
                output_dir,
                longitude,
                latitude,
                height,
                scale,
                rotation_z_degrees,
                format_name,
                enable_pyramid=enable_pyramid,
                pyramid_leaf_size=pyramid_leaf_size,
                pyramid_max_depth=pyramid_max_depth,
                task_id=task_id,
                stop_checker=stop_checker,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    meters_lon_ref, meters_lat_ref = _meters_per_degree(float(longitude), float(latitude))
    children = []
    content_files = []
    skipped_files = []
    global_min_x = float("inf")
    global_min_y = float("inf")
    global_max_x = float("-inf")
    global_max_y = float("-inf")
    global_min_z = float("inf")
    global_max_z = float("-inf")
    temp_dir = tempfile.mkdtemp(prefix="atlasworks-osgb-")
    try:
        chunk_index = 0
        obj_path = os.path.join(temp_dir, "osgb_current.obj")
        for osgb_file in osgb_files:
            try:
                _ensure_not_stopped(stop_checker)
                _convert_osgb_to_obj(osgb_file, obj_path, task_id=task_id)
                _ensure_not_stopped(stop_checker)
                scene = _load_scene(obj_path)
                _apply_scene_transform(scene, scale, rotation_z_degrees)
                bounds = scene.bounds
                if bounds is None:
                    skipped_files.append(osgb_file)
                    continue

                min_corner = [float(value) for value in bounds[0]]
                max_corner = [float(value) for value in bounds[1]]
                if any(math.isnan(value) for value in min_corner + max_corner):
                    skipped_files.append(osgb_file)
                    continue

                center_x = (min_corner[0] + max_corner[0]) * 0.5
                center_y = (min_corner[1] + max_corner[1]) * 0.5
                center_z = (min_corner[2] + max_corner[2]) * 0.5
                half_x = max((max_corner[0] - min_corner[0]) * 0.5, 0.01)
                half_y = max((max_corner[1] - min_corner[1]) * 0.5, 0.01)

                chunk_lon = float(longitude) + (center_x / max(meters_lon_ref, 1.0))
                chunk_lat = float(latitude) + (center_y / max(meters_lat_ref, 1.0))
                meters_lon, meters_lat = _meters_per_degree(chunk_lon, chunk_lat)
                delta_lon = half_x / max(meters_lon, 1.0)
                delta_lat = half_y / max(meters_lat, 1.0)

                min_height = float(height or 0.0) + min_corner[2]
                max_height = float(height or 0.0) + max_corner[2]
                chunk_height = float(height or 0.0) + center_z

                chunk_scene = scene.copy()
                chunk_scene.apply_translation([-center_x, -center_y, -center_z])
                chunk_stem = f"chunk_{chunk_index:04d}"
                _ensure_not_stopped(stop_checker)
                chunk_file = _export_scene_content(chunk_scene, output_dir, chunk_stem, format_name)
                content_files.append(chunk_file)

                children.append(
                    {
                        "boundingVolume": {
                            "region": _region_bounds(
                                chunk_lon - delta_lon,
                                chunk_lat - delta_lat,
                                chunk_lon + delta_lon,
                                chunk_lat + delta_lat,
                                min_height,
                                max_height,
                            )
                        },
                        "geometricError": 0,
                        "refine": "ADD",
                        "transform": _enu_transform(chunk_lon, chunk_lat, chunk_height),
                        "content": {"uri": chunk_file},
                    }
                )

                global_min_x = min(global_min_x, min_corner[0])
                global_min_y = min(global_min_y, min_corner[1])
                global_max_x = max(global_max_x, max_corner[0])
                global_max_y = max(global_max_y, max_corner[1])
                global_min_z = min(global_min_z, min_corner[2])
                global_max_z = max(global_max_z, max_corner[2])
                chunk_index += 1
            except Exception:
                skipped_files.append(osgb_file)
                continue

        if not children:
            raise RuntimeError("OSGB 批量转换失败：未生成有效分块内容")

        west = float(longitude) + (global_min_x / max(meters_lon_ref, 1.0))
        south = float(latitude) + (global_min_y / max(meters_lat_ref, 1.0))
        east = float(longitude) + (global_max_x / max(meters_lon_ref, 1.0))
        north = float(latitude) + (global_max_y / max(meters_lat_ref, 1.0))
        min_height = float(height or 0.0) + global_min_z
        max_height = float(height or 0.0) + global_max_z

        final_children, root_geometric_error = _apply_optional_pyramid(
            children,
            enable_pyramid=enable_pyramid,
            pyramid_leaf_size=pyramid_leaf_size,
            pyramid_max_depth=pyramid_max_depth,
        )
        tileset_path = _write_tileset(
            output_dir,
            west,
            south,
            east,
            north,
            min_height,
            max_height,
            children=final_children,
            asset_version="1.0" if format_name == "b3dm" else "1.1",
            gltf_up_axis="Z",
            root_geometric_error=root_geometric_error,
        )
        return {
            "tilesetPath": tileset_path,
            "entryFile": tileset_path,
            "contentFiles": content_files,
            "bounds": [west, south, east, north],
            "chunkCount": len(children),
            "rootChildren": len(final_children),
            "skippedFiles": len(skipped_files),
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _export_pointcloud_tiles(source_path, output_dir, jobs, crs, task_id=None, stop_checker=None):
    try:
        from py3dtiles.convert import convert as py3dtiles_convert
        from pyproj import CRS
    except Exception as exc:
        raise RuntimeError(f"点云 3D Tiles 依赖不可用: {exc}")

    sources = list(source_path) if isinstance(source_path, (list, tuple, set)) else [source_path]
    sources = [str(item) for item in sources if str(item or "").strip()]
    if not sources:
        raise RuntimeError("点云输入为空")
    primary_source = sources if len(sources) > 1 else sources[0]

    crs_in = CRS.from_user_input(crs) if crs else None
    crs_out = CRS.from_epsg(4978)
    convert_attempts = [
        lambda: py3dtiles_convert(
            primary_source,
            outfolder=output_dir,
            jobs=jobs,
            crs_in=crs_in,
            crs_out=crs_out,
            force_crs_in=bool(crs_in),
            pyproj_always_xy=True,
            use_process_pool=False,
        ),
        lambda: py3dtiles_convert(
            sources,
            outfolder=output_dir,
            jobs=jobs,
            crs_in=crs_in,
            crs_out=crs_out,
            force_crs_in=bool(crs_in),
            pyproj_always_xy=True,
            use_process_pool=False,
        ),
        lambda: py3dtiles_convert(primary_source, output_dir),
    ]
    last_error = None
    tileset_path = None
    for attempt in convert_attempts:
        _ensure_not_stopped(stop_checker)
        try:
            attempt()
            _ensure_not_stopped(stop_checker)
            detected_tileset = _discover_generated_tileset(output_dir)
            if detected_tileset and os.path.exists(detected_tileset):
                promoted = _promote_nested_tileset_to_root(output_dir, detected_tileset)
                if promoted and os.path.exists(promoted):
                    tileset_path = promoted
                    break
                tileset_path = detected_tileset
                break
            last_error = RuntimeError("点云转换执行成功，但未发现可用的 tileset.json")
            continue
        except TypeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            break
    if not tileset_path:
        if last_error is not None:
            raise RuntimeError(_format_pointcloud_convert_error(last_error, sources, crs))

        fallback_tileset = os.path.join(output_dir, "tileset.json")
        if not os.path.exists(fallback_tileset):
            entries = []
            try:
                entries = sorted(os.listdir(output_dir))
            except Exception:
                entries = []
            preview = ", ".join(entries[:10]) if entries else "空目录"
            raise RuntimeError(
                f"点云转换未生成 tileset.json，输出目录内容: {preview}"
            )
        tileset_path = fallback_tileset

    if not os.path.exists(tileset_path):
        raise RuntimeError(f"点云转换完成，但未生成 {tileset_path}")
    return {
        "tilesetPath": tileset_path,
        "entryFile": tileset_path,
        "contentFiles": [],
    }


def _process_tiles3d_task(task_id, source_rel_path, source_full_path, output_path, request_data):
    data_type = str(request_data.get("dataType") or "pointcloud").strip().lower()
    jobs = normalizeInt(request_data.get("jobs"), min(4, max(1, config.get("maxThreads", 4))), 1, max(1, config.get("maxThreads", 4)))
    crs = str(request_data.get("crs") or "").strip()
    height_field = str(request_data.get("heightField") or "").strip()
    default_height = _resolve_height_value(request_data.get("defaultHeight"), 30.0)
    vector_height_mode = _normalize_vector_height_mode(request_data.get("vectorHeightMode"), "meters")
    floor_height_meters = _resolve_height_value(request_data.get("floorHeightMeters"), DEFAULT_FLOOR_HEIGHT_METERS)
    if floor_height_meters <= 0:
        floor_height_meters = DEFAULT_FLOOR_HEIGHT_METERS
    longitude = normalizeFloat(request_data.get("longitude"), None)
    latitude = normalizeFloat(request_data.get("latitude"), None)
    anchor_mode = _normalize_anchor_mode(request_data.get("anchorMode"), "manual")
    height = _resolve_height_value(request_data.get("height"), 0.0)
    scale = _resolve_height_value(request_data.get("scale"), 1.0)
    rotation_z_degrees = _resolve_height_value(request_data.get("rotationZ"), 0.0)
    content_format = str(request_data.get("contentFormat") or "b3dm").strip().lower()
    enable_pyramid = _normalize_bool(request_data.get("enablePyramid"), False)
    pyramid_leaf_size = normalizeInt(request_data.get("pyramidLeafSize"), 8, 1, 2000)
    pyramid_max_depth = normalizeInt(request_data.get("pyramidMaxDepth"), 4, 1, 12)
    output_content_format = "pnts"
    resolved_anchor = None
    stop_checker = lambda: _is_task_stopped(task_id)

    _update_task(
        task_id,
        progress=10,
        message="开始处理 3D Tiles 数据",
        stage="数据转换",
        log_stage="初始化",
        log_status="completed",
        sourceFile=_source_for_result(source_rel_path),
        sourceLabel=_source_for_log(source_rel_path),
        dataType=data_type,
    )

    os.makedirs(output_path, exist_ok=True)
    if _is_task_stopped(task_id):
        raise RuntimeError("任务已停止")

    if data_type == "osgb" and (longitude is None or latitude is None) and anchor_mode == "auto":
        osgb_files = _collect_osgb_files(source_full_path)
        guessed_anchor = _guess_osgb_anchor_from_related_xodr(source_full_path, osgb_files)
        if not guessed_anchor:
            raise RuntimeError("OSGB 自动定位失败：未找到可用的 xodr geoReference。请将 .xodr 放在 OSGB 同级/上级目录，或改为手动填写经纬度锚点")
        longitude = float(guessed_anchor["longitude"])
        latitude = float(guessed_anchor["latitude"])
        resolved_anchor = guessed_anchor
        _update_task(
            task_id,
            progress=20,
            message=f"已自动识别 OSGB 锚点: {longitude:.7f}, {latitude:.7f}",
            stage="锚点定位",
            log_stage="锚点定位",
            log_status="completed",
            anchorMode=anchor_mode,
            anchorSource=guessed_anchor.get("source"),
            confidence=guessed_anchor.get("confidence"),
        )

    if data_type == "pointcloud":
        _update_task(task_id, progress=25, message="正在执行点云转换", stage="点云转换")
        result = _export_pointcloud_tiles(
            source_full_path,
            output_path,
            jobs,
            crs,
            task_id=task_id,
            stop_checker=stop_checker,
        )
        method = "3dtiles-pointcloud"
    elif data_type == "vector":
        _update_task(task_id, progress=25, message="正在生成建筑三维模型", stage="矢量转换")
        result = _export_vector_tiles(
            source_full_path,
            output_path,
            height_field,
            default_height,
            content_format,
            vector_height_mode=vector_height_mode,
            floor_height_meters=floor_height_meters,
            enable_pyramid=enable_pyramid,
            pyramid_leaf_size=pyramid_leaf_size,
            pyramid_max_depth=pyramid_max_depth,
            stop_checker=stop_checker,
        )
        method = "3dtiles-vector"
        output_content_format = content_format
    elif data_type == "model":
        _update_task(task_id, progress=25, message="正在转换 OBJ 模型", stage="模型转换")
        result = _export_obj_tiles(
            source_full_path,
            output_path,
            longitude,
            latitude,
            height,
            scale,
            rotation_z_degrees,
            content_format,
            enable_pyramid=enable_pyramid,
            pyramid_leaf_size=pyramid_leaf_size,
            pyramid_max_depth=pyramid_max_depth,
            task_id=task_id,
            stop_checker=stop_checker,
        )
        method = "3dtiles-model"
        output_content_format = content_format
    else:
        _update_task(task_id, progress=25, message="正在转换 OSGB 模型", stage="OSGB 转换")
        result = _export_osgb_tiles(
            source_full_path,
            output_path,
            longitude,
            latitude,
            height,
            scale,
            rotation_z_degrees,
            content_format,
            enable_pyramid=enable_pyramid,
            pyramid_leaf_size=pyramid_leaf_size,
            pyramid_max_depth=pyramid_max_depth,
            task_id=task_id,
            stop_checker=stop_checker,
        )
        method = "3dtiles-osgb"
        output_content_format = content_format

    if _is_task_stopped(task_id):
        raise RuntimeError("任务已停止")

    with taskLock:
        record = taskStatus.get(task_id)
        if not isinstance(record, dict):
            return
        record["status"] = "completed"
        record["progress"] = 100
        record["endTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record["currentStage"] = "完成"
        record["message"] = "3D Tiles 任务完成"
        record["files"] = {"total": 1, "completed": 1, "failed": 0, "current": None}
        record["result"] = {
            "totalFiles": 1,
            "completedFiles": 1,
            "failedFiles": 0,
            "outputPath": output_path,
            "entryFile": result.get("entryFile"),
            "tilesetPath": result.get("tilesetPath"),
            "sourceFile": _source_for_result(source_rel_path),
            "method": method,
            "dataType": data_type,
            "contentFormat": output_content_format,
            "bounds": result.get("bounds"),
            "contentFiles": result.get("contentFiles", []),
            "enablePyramid": enable_pyramid if data_type in {"vector", "model", "osgb"} else False,
            "anchorMode": anchor_mode if data_type in {"model", "osgb"} else None,
        }
        if data_type == "vector":
            record["result"]["vectorHeightMode"] = vector_height_mode
            record["result"]["floorHeightMeters"] = float(floor_height_meters)
        if longitude is not None and latitude is not None and data_type in {"model", "osgb"}:
            record["result"]["resolvedAnchor"] = {
                "longitude": float(longitude),
                "latitude": float(latitude),
                "mode": anchor_mode,
            }
            if resolved_anchor:
                record["result"]["resolvedAnchor"]["source"] = resolved_anchor.get("source")
                record["result"]["resolvedAnchor"]["confidence"] = resolved_anchor.get("confidence")
        if result.get("featureCount") is not None:
            record["result"]["featureCount"] = result.get("featureCount")
        if result.get("chunkCount") is not None:
            record["result"]["chunkCount"] = result.get("chunkCount")
        if result.get("rootChildren") is not None:
            record["result"]["rootChildren"] = result.get("rootChildren")
        if result.get("skippedFiles") is not None:
            record["result"]["skippedFiles"] = result.get("skippedFiles")
        if result.get("sceneBounds") is not None:
            record["result"]["sceneBounds"] = result.get("sceneBounds")
        appendTaskLog(record, "完成", "completed", "3D Tiles 输出已生成", progress=100, outputPath=output_path, entryFile=result.get("entryFile"))

    finalizeTaskArtifact(
        task_id,
        source_files=list(source_rel_path) if isinstance(source_rel_path, (list, tuple)) else [source_rel_path],
        build_parameters={
            "jobType": "3dtiles",
            "dataType": data_type,
            "sourceFile": _source_for_result(source_rel_path),
            "entryFile": result.get("entryFile"),
            "contentFormat": output_content_format,
            "anchorMode": anchor_mode if data_type in {"model", "osgb"} else None,
            "vectorHeightMode": vector_height_mode if data_type == "vector" else None,
            "floorHeightMeters": float(floor_height_meters) if data_type == "vector" else None,
        },
    )


def create3DTiles():
    try:
        logMessage("收到 3D Tiles 任务创建请求", "INFO")
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({"error": "请求数据为空，无法解析JSON"}), 400

        data_type = str(data.get("dataType") or "").strip().lower()
        anchor_mode = _normalize_anchor_mode(data.get("anchorMode"), "manual")
        task_id = f"tiles3d{int(time.time())}"
        errors = []

        if data_type not in SUPPORTED_3DTILES_TYPES:
            errors.append("dataType 必须是 pointcloud、vector、model、osgb 之一")

        folder_paths = data.get("folderPaths", [])
        file_patterns = data.get("filePatterns", [])
        source_path = data.get("sourcePath", "")

        if not source_path and not file_patterns:
            errors.append("缺少 sourcePath 或 filePatterns")

        if data_type in {"vector", "model", "osgb"}:
            content_format = str(data.get("contentFormat") or "b3dm").strip().lower()
            if content_format not in SUPPORTED_CONTENT_FORMATS:
                errors.append("contentFormat 仅支持 b3dm 或 glb")
        if data_type == "vector":
            raw_mode = str(data.get("vectorHeightMode") or "").strip().lower()
            if raw_mode and raw_mode not in SUPPORTED_VECTOR_HEIGHT_MODES:
                errors.append("vectorHeightMode 仅支持 meters 或 floors")
            floor_height_meters = normalizeFloat(data.get("floorHeightMeters"), DEFAULT_FLOOR_HEIGHT_METERS)
            if floor_height_meters is not None and float(floor_height_meters) <= 0:
                errors.append("floorHeightMeters 必须大于 0")
        if data_type == "model":
            if normalizeFloat(data.get("longitude"), None) is None or normalizeFloat(data.get("latitude"), None) is None:
                errors.append("OBJ 任务必须提供 longitude 与 latitude")
        if data_type == "osgb":
            if anchor_mode == "manual":
                if normalizeFloat(data.get("longitude"), None) is None or normalizeFloat(data.get("latitude"), None) is None:
                    errors.append("OSGB 手动锚点模式必须提供 longitude 与 latitude")

        if errors:
            with taskLock:
                taskStatus[task_id] = _build_error_task(task_id, errors)
            return jsonify({
                "success": False,
                "taskId": task_id,
                "message": f"3D Tiles 任务创建失败: {'; '.join(errors)}",
                "statusUrl": f"/api/tasks/{task_id}",
                "errors": errors,
            }), 200

        try:
            source_rel_path, source_full_path = _resolve_single_source(folder_paths, file_patterns, source_path, data_type)
        except Exception as exc:
            with taskLock:
                taskStatus[task_id] = _build_error_task(task_id, [str(exc)])
            return jsonify({
                "success": False,
                "taskId": task_id,
                "message": f"3D Tiles 任务创建失败: {exc}",
                "statusUrl": f"/api/tasks/{task_id}",
                "errors": [str(exc)],
            }), 200

        if data_type == "osgb":
            if isinstance(source_full_path, str) and os.path.isfile(source_full_path) and not str(source_full_path).lower().endswith(".osgb"):
                message = "OSGB 任务输入文件必须为 .osgb"
                with taskLock:
                    taskStatus[task_id] = _build_error_task(task_id, [message])
                return jsonify({
                    "success": False,
                    "taskId": task_id,
                    "message": f"3D Tiles 任务创建失败: {message}",
                    "statusUrl": f"/api/tasks/{task_id}",
                    "errors": [message],
                }), 200

        output_path, _, _ = resolveTilesOutputPath(data.get("outputPath"), "3dtiles")
        os.makedirs(output_path, exist_ok=True)

        def run_task():
            try:
                with taskLock:
                    taskStatus[task_id] = createTaskRecord(
                        task_id=task_id,
                        status="running",
                        progress=0,
                        message="准备开始 3D Tiles 转换",
                        start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="初始化",
                        process_log=[],
                        files={
                            "total": 1,
                            "completed": 0,
                            "failed": 0,
                            "current": os.path.basename(source_rel_path[0]) if isinstance(source_rel_path, (list, tuple)) and source_rel_path else os.path.basename(str(source_rel_path)),
                        },
                        result={},
                        extra={"jobType": "3dtiles", "dataType": data_type},
                    )

                _process_tiles3d_task(task_id, source_rel_path, source_full_path, output_path, data)
            except Exception as exc:
                stopped = _is_task_stopped(task_id) or str(exc) == "任务已停止"
                if stopped:
                    logMessage(f"3D Tiles 任务已停止 {task_id}", "INFO")
                else:
                    logMessage(f"3D Tiles 任务失败 {task_id}: {exc}", "ERROR")
                with taskLock:
                    record = taskStatus.get(task_id)
                    if not isinstance(record, dict):
                        record = createTaskRecord(task_id=task_id)
                        taskStatus[task_id] = record
                    record["endTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if stopped:
                        record["status"] = "stopped"
                        record["progress"] = min(int(record.get("progress", 0) or 0), 99)
                        record["message"] = "任务已停止"
                        record["currentStage"] = "已停止"
                        record["files"] = {"total": 1, "completed": 0, "failed": 0, "current": None}
                        appendTaskLog(record, "停止", "stopped", "任务已停止", progress=record["progress"])
                    else:
                        record["status"] = "failed"
                        record["progress"] = min(int(record.get("progress", 0) or 0), 99)
                        record["message"] = f"3D Tiles 任务失败: {exc}"
                        record["currentStage"] = "失败"
                        record["files"] = {"total": 1, "completed": 0, "failed": 1, "current": None}
                        appendTaskLog(record, "失败", "failed", str(exc), progress=record["progress"])
            finally:
                with taskLock:
                    taskProcesses.pop(task_id, None)
                    taskStopFlags.pop(task_id, None)

        task_thread = threading.Thread(target=run_task, daemon=True)
        with taskLock:
            taskProcesses[task_id] = task_thread
        task_thread.start()

        return jsonify({
            "success": True,
            "taskId": task_id,
            "message": "3D Tiles 任务已启动",
            "statusUrl": f"/api/tasks/{task_id}",
            "dataType": data_type,
            "outputPath": output_path,
            "sourceFile": _source_for_result(source_rel_path),
        })
    except Exception as exc:
        logMessage(f"创建 3D Tiles 任务异常: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500

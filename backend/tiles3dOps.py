#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import os
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
    return value


def _resolve_single_source(folder_paths, file_patterns, source_path, data_type):
    if source_path:
        normalized = _normalize_source_relpath(source_path)
        ok, full_path = validateDataSourcePath(normalized)
        if not ok:
            raise ValueError(full_path)
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
):
    import json

    tileset = {
        "asset": {"version": str(asset_version or "1.1")},
        "geometricError": max(1.0, float(max_height or 1.0) - float(min_height or 0.0)),
        "root": {
            "boundingVolume": {"region": _region_bounds(west, south, east, north, min_height, max_height)},
            "geometricError": max(1.0, float(max_height or 1.0) - float(min_height or 0.0)),
            "refine": "ADD",
        },
    }
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


def _export_vector_tiles(source_path, output_dir, height_field, default_height, content_format):
    try:
        import numpy as np
        import trimesh
        from osgeo import ogr, osr
    except Exception as exc:
        raise RuntimeError(f"矢量 3D Tiles 依赖不可用: {exc}")

    format_name = str(content_format or "b3dm").strip().lower()
    if format_name not in SUPPORTED_CONTENT_FORMATS:
        raise RuntimeError(f"不支持的 contentFormat: {content_format}")

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

    feature_records = []
    west = 180.0
    south = 90.0
    east = -180.0
    north = -90.0
    min_height = 0.0
    max_height = float(default_height)
    layer.ResetReading()
    for feature in layer:
        geometry = feature.GetGeometryRef()
        if geometry is None:
            continue
        geometry = geometry.Clone()
        if transform_to_wgs84:
            geometry.Transform(transform_to_wgs84)

        height_value = _resolve_height_value(
            feature.GetField(height_field) if height_field and feature.GetFieldIndex(height_field) >= 0 else None,
            default_height,
        )
        if height_value <= 0:
            continue

        geometry_type = geometry.GetGeometryType()
        polygons = []
        if geometry_type in (ogr.wkbPolygon, ogr.wkbPolygon25D):
            polygons = [geometry]
        elif geometry_type in (ogr.wkbMultiPolygon, ogr.wkbMultiPolygon25D):
            polygons = [geometry.GetGeometryRef(index) for index in range(geometry.GetGeometryCount())]
        else:
            continue

        for polygon in polygons:
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

    children = []
    content_files = []
    total_chunk_features = 0
    chunk_index = 0
    for chunk_key in sorted(chunk_groups):
        records = chunk_groups.get(chunk_key) or []
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

    tileset_path = _write_tileset(
        output_dir,
        west,
        south,
        east,
        north,
        min_height,
        max_height,
        children=children,
        asset_version="1.0" if format_name == "b3dm" else "1.1",
    )
    return {
        "tilesetPath": tileset_path,
        "entryFile": tileset_path,
        "contentFiles": content_files,
        "bounds": [west, south, east, north],
        "featureCount": total_chunk_features,
        "chunkCount": len(children),
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


def _export_scene_tiles(scene, output_dir, longitude, latitude, height, scale, rotation_z_degrees, content_format):
    try:
        import trimesh
    except Exception as exc:
        raise RuntimeError(f"模型导出依赖不可用: {exc}")

    if longitude is None or latitude is None:
        raise RuntimeError("OBJ/OSGB 需要提供 longitude 与 latitude 作为锚点")

    if scale and scale != 1.0:
        scene.apply_scale(float(scale))
    if rotation_z_degrees:
        rotation = trimesh.transformations.rotation_matrix(
            math.radians(float(rotation_z_degrees)),
            [0, 0, 1],
        )
        scene.apply_transform(rotation)

    format_name = str(content_format or "b3dm").strip().lower()
    if format_name not in SUPPORTED_CONTENT_FORMATS:
        raise RuntimeError(f"不支持的 contentFormat: {content_format}")

    glb_path = os.path.join(output_dir, "scene.glb")
    if format_name == "b3dm":
        content_file = "scene.b3dm"
        content_path = os.path.join(output_dir, content_file)
        scene.export(glb_path)
        _write_b3dm_from_glb(glb_path, content_path)
        try:
            os.remove(glb_path)
        except Exception:
            pass
    else:
        content_file = "scene.glb"
        scene.export(glb_path)

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
    )
    return {
        "tilesetPath": tileset_path,
        "entryFile": tileset_path,
        "contentFiles": [content_file],
        "bounds": [west, south, east, north],
        "sceneBounds": bounds.tolist(),
    }


def _export_obj_tiles(source_path, output_dir, longitude, latitude, height, scale, rotation_z_degrees, content_format):
    scene = _load_scene(source_path)
    return _export_scene_tiles(scene, output_dir, longitude, latitude, height, scale, rotation_z_degrees, content_format)


def _export_osgb_tiles(source_path, output_dir, longitude, latitude, height, scale, rotation_z_degrees, content_format):
    temp_dir = tempfile.mkdtemp(prefix="atlasworks-osgb-")
    try:
        obj_path = os.path.join(temp_dir, "osgb_converted.obj")
        result = runCommand(["osgconv", source_path, obj_path])
        if not result.get("success"):
            raise RuntimeError(result.get("stderr") or result.get("error") or "osgconv 执行失败")
        if not os.path.exists(obj_path):
            raise RuntimeError("osgconv 未生成 OBJ 输出")
        return _export_obj_tiles(obj_path, output_dir, longitude, latitude, height, scale, rotation_z_degrees, content_format)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _export_pointcloud_tiles(source_path, output_dir, jobs, crs):
    try:
        from py3dtiles.convert import convert as py3dtiles_convert
        from pyproj import CRS
    except Exception as exc:
        raise RuntimeError(f"点云 3D Tiles 依赖不可用: {exc}")

    crs_in = CRS.from_user_input(crs) if crs else None
    crs_out = CRS.from_epsg(4978)
    convert_attempts = [
        lambda: py3dtiles_convert(
            source_path,
            outfolder=output_dir,
            jobs=jobs,
            crs_in=crs_in,
            crs_out=crs_out,
            force_crs_in=bool(crs_in),
            pyproj_always_xy=True,
        ),
        lambda: py3dtiles_convert(
            [source_path],
            outfolder=output_dir,
            jobs=jobs,
            crs_in=crs_in,
            crs_out=crs_out,
            force_crs_in=bool(crs_in),
            pyproj_always_xy=True,
        ),
        lambda: py3dtiles_convert(source_path, output_dir),
    ]
    last_error = None
    for attempt in convert_attempts:
        try:
            attempt()
            break
        except TypeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            break
    else:
        raise RuntimeError(str(last_error or "py3dtiles 转换失败"))

    tileset_path = os.path.join(output_dir, "tileset.json")
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
    longitude = normalizeFloat(request_data.get("longitude"), None)
    latitude = normalizeFloat(request_data.get("latitude"), None)
    height = _resolve_height_value(request_data.get("height"), 0.0)
    scale = _resolve_height_value(request_data.get("scale"), 1.0)
    rotation_z_degrees = _resolve_height_value(request_data.get("rotationZ"), 0.0)
    content_format = str(request_data.get("contentFormat") or "b3dm").strip().lower()
    output_content_format = "pnts"

    _update_task(task_id, progress=10, message="开始处理 3D Tiles 数据", stage="数据转换", log_stage="初始化", log_status="completed", sourceFile=source_rel_path, dataType=data_type)

    os.makedirs(output_path, exist_ok=True)
    if _is_task_stopped(task_id):
        raise RuntimeError("任务已停止")

    if data_type == "pointcloud":
        _update_task(task_id, progress=25, message="正在执行点云转换", stage="点云转换")
        result = _export_pointcloud_tiles(source_full_path, output_path, jobs, crs)
        method = "3dtiles-pointcloud"
    elif data_type == "vector":
        _update_task(task_id, progress=25, message="正在生成建筑三维模型", stage="矢量转换")
        result = _export_vector_tiles(source_full_path, output_path, height_field, default_height, content_format)
        method = "3dtiles-vector"
        output_content_format = content_format
    elif data_type == "model":
        _update_task(task_id, progress=25, message="正在转换 OBJ 模型", stage="模型转换")
        result = _export_obj_tiles(source_full_path, output_path, longitude, latitude, height, scale, rotation_z_degrees, content_format)
        method = "3dtiles-model"
        output_content_format = content_format
    else:
        _update_task(task_id, progress=25, message="正在转换 OSGB 模型", stage="OSGB 转换")
        result = _export_osgb_tiles(source_full_path, output_path, longitude, latitude, height, scale, rotation_z_degrees, content_format)
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
            "sourceFile": source_rel_path,
            "method": method,
            "dataType": data_type,
            "contentFormat": output_content_format,
            "bounds": result.get("bounds"),
            "contentFiles": result.get("contentFiles", []),
        }
        if result.get("featureCount") is not None:
            record["result"]["featureCount"] = result.get("featureCount")
        if result.get("chunkCount") is not None:
            record["result"]["chunkCount"] = result.get("chunkCount")
        if result.get("sceneBounds") is not None:
            record["result"]["sceneBounds"] = result.get("sceneBounds")
        appendTaskLog(record, "完成", "completed", "3D Tiles 输出已生成", progress=100, outputPath=output_path, entryFile=result.get("entryFile"))

    finalizeTaskArtifact(
        task_id,
        source_files=[source_rel_path],
        build_parameters={
            "jobType": "3dtiles",
            "dataType": data_type,
            "sourceFile": source_rel_path,
            "entryFile": result.get("entryFile"),
            "contentFormat": output_content_format,
        },
    )


def create3DTiles():
    try:
        logMessage("收到 3D Tiles 任务创建请求", "INFO")
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({"error": "请求数据为空，无法解析JSON"}), 400

        data_type = str(data.get("dataType") or "").strip().lower()
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
        if data_type in {"model", "osgb"}:
            if normalizeFloat(data.get("longitude"), None) is None or normalizeFloat(data.get("latitude"), None) is None:
                errors.append("OBJ/OSGB 任务必须提供 longitude 与 latitude")

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
                        files={"total": 1, "completed": 0, "failed": 0, "current": os.path.basename(source_rel_path)},
                        result={},
                        extra={"jobType": "3dtiles", "dataType": data_type},
                    )

                _process_tiles3d_task(task_id, source_rel_path, source_full_path, output_path, data)
            except Exception as exc:
                logMessage(f"3D Tiles 任务失败 {task_id}: {exc}", "ERROR")
                with taskLock:
                    record = taskStatus.get(task_id)
                    if not isinstance(record, dict):
                        record = createTaskRecord(task_id=task_id)
                        taskStatus[task_id] = record
                    record["status"] = "failed"
                    record["progress"] = min(int(record.get("progress", 0) or 0), 99)
                    record["message"] = f"3D Tiles 任务失败: {exc}"
                    record["currentStage"] = "失败"
                    record["endTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            "sourceFile": source_rel_path,
        })
    except Exception as exc:
        logMessage(f"创建 3D Tiles 任务异常: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500

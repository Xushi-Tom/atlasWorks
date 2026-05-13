#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import os
import re
import requests
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from flask import jsonify, request

from artifacts import finalizeTaskArtifact
from config import config, taskLock, taskProcesses, taskStatus
from dataSourceOps import findTifFilesInFolders, getSourceBandInfoCached
from db import enqueueBuildJob, isDatabaseEnabled, syncTaskSnapshot
from geoserverOps import createRasterStyle, deleteStore, deleteStyle, publishGeoserverPayload, setLayerDefaultStyle
from taskState import appendTaskLog, createTaskRecord
from utils import (
    logMessage,
    normalizeFloat,
    normalizeImageFormat,
    normalizeInt,
    normalizeProjection,
    normalizeTileScheme,
    resolveTilesOutputPath,
    runCommand,
)


_cpu_for_slots = os.cpu_count() or 4
MAX_INDEXED_TASK_SLOTS = max(1, min(3, _cpu_for_slots // 8 + 1))
indexedTaskSemaphore = threading.Semaphore(MAX_INDEXED_TASK_SLOTS)
GEOSERVER_WMS_RETRIES = 3
GEOSERVER_WMS_RETRY_DELAY = 0.8


def deg2tile(latDeg, lonDeg, zoom):
    latRad = math.radians(latDeg)
    n = 2.0 ** zoom
    x = int((lonDeg + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(latRad)) / math.pi) / 2.0 * n)
    return (x, y)


def tile2deg(x, y, zoom):
    n = 2.0 ** zoom
    lonDeg = x / n * 360.0 - 180.0
    latRad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    latDeg = math.degrees(latRad)
    return (lonDeg, latDeg)


def tile2mercator_bounds(x, y, zoom):
    half_world = 20037508.342789244
    n = 2.0 ** zoom
    tile_span = (half_world * 2.0) / n
    min_x = -half_world + x * tile_span
    max_x = -half_world + (x + 1) * tile_span
    max_y = half_world - y * tile_span
    min_y = half_world - (y + 1) * tile_span
    return min_x, min_y, max_x, max_y


def getTileOutputPath(tilesDir, zoom, tileX, tileY, renderOptions):
    tileScheme = normalizeTileScheme((renderOptions or {}).get("tileScheme", "tms"))
    imageFormat = normalizeImageFormat((renderOptions or {}).get("imageFormat", "png"))
    outputY = tileY if tileScheme == "google" else (1 << int(zoom)) - int(tileY) - 1
    extension = "jpg" if imageFormat == "jpeg" else "png"
    tileDir = os.path.join(tilesDir, str(zoom), str(tileX))
    os.makedirs(tileDir, exist_ok=True)
    tileFile = os.path.join(tileDir, f"{outputY}.{extension}")
    return tileFile, outputY, extension


def checkTileHasNodata(tileFile, transparencyThreshold=0.1):
    try:
        from PIL import Image
        import numpy as np

        threshold = normalizeFloat(transparencyThreshold, 0.1)
        if threshold > 1:
            threshold = threshold / 100.0
        threshold = max(0.0, min(1.0, threshold))
        with Image.open(tileFile) as img:
            if img.size != (256, 256):
                return True
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            alphaChannel = np.array(img)[:, :, 3]
            transparentMask = alphaChannel < 255
            transparentCount = int(np.count_nonzero(transparentMask))
            transparentRatio = transparentCount / float(transparentMask.size)
            if threshold <= 0:
                return transparentCount > 0
            return transparentRatio >= threshold
    except Exception:
        try:
            result = subprocess.run(["gdalinfo", "-stats", tileFile], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return True
            output = result.stdout
            hasNodata = "NoData Value=" in output
            hasAlphaTransparency = "ColorInterp=Alpha" in output and ("Min=0" in output or "Minimum=0" in output)
            return hasNodata or hasAlphaTransparency
        except Exception:
            return True


def deleteNodataTilesInternal(tilesPath, includeDetails=True, transparencyThreshold=0.1):
    try:
        fullTilesPath = os.path.join(config["tilesDir"], tilesPath)
        if not os.path.exists(fullTilesPath):
            return {"success": False, "error": f"瓦片目录不存在: {fullTilesPath}"}

        threshold = normalizeFloat(transparencyThreshold, 0.1)
        if threshold > 1:
            threshold = threshold / 100.0
        threshold = max(0.0, min(1.0, threshold))

        totalChecked = 0
        deletedCount = 0
        errorCount = 0
        deletedFiles = []
        for root, _, files in os.walk(fullTilesPath):
            for file in files:
                if not file.lower().endswith(".png"):
                    continue
                filePath = os.path.join(root, file)
                totalChecked += 1
                try:
                    if checkTileHasNodata(filePath, threshold):
                        os.remove(filePath)
                        deletedCount += 1
                        if includeDetails:
                            deletedFiles.append(os.path.relpath(filePath, fullTilesPath))
                except Exception:
                    errorCount += 1

        cleanedDirs = 0
        for root, dirs, _ in os.walk(fullTilesPath, topdown=False):
            for dirName in dirs:
                dirPath = os.path.join(root, dirName)
                try:
                    os.rmdir(dirPath)
                    cleanedDirs += 1
                except OSError:
                    pass

        result = {
            "success": True,
            "summary": {
                "total_checked": totalChecked,
                "deleted_count": deletedCount,
                "error_count": errorCount,
                "cleaned_dirs": cleanedDirs,
                "transparency_threshold": threshold,
            },
            "message": f"删除完成！检查了 {totalChecked} 个瓦片，删除了 {deletedCount} 个达到透明阈值的瓦片，清理了 {cleanedDirs} 个空目录",
        }
        if includeDetails:
            result["deleted_files"] = deletedFiles
        return result
    except Exception as exc:
        return {"success": False, "error": f"删除透明瓦片时发生错误: {exc}"}


def deleteNodataTiles():
    try:
        data = request.get_json(silent=True) or {}
        if not data:
            return jsonify({"error": "缺少请求参数"}), 400
        tilesPath = data.get("tilesPath")
        if not tilesPath:
            return jsonify({"error": "缺少瓦片目录路径参数 tilesPath"}), 400
        includeDetails = data.get("includeDetails", True)
        transparencyThreshold = data.get("transparencyThreshold", 0.1)
        result = deleteNodataTilesInternal(tilesPath, includeDetails, transparencyThreshold)
        if result["success"]:
            return jsonify(result)
        return jsonify(result), 400
    except Exception as exc:
        errorMessage = f"删除透明瓦片请求处理失败: {exc}"
        logMessage(errorMessage, "ERROR")
        return jsonify({"error": errorMessage}), 500


def scanNodataTiles():
    try:
        data = request.get_json(silent=True) or {}
        if not data:
            return jsonify({"error": "缺少请求参数"}), 400
        tilesPath = data.get("tilesPath")
        if not tilesPath:
            return jsonify({"error": "缺少瓦片目录路径参数 tilesPath"}), 400

        fullTilesPath = os.path.join(config["tilesDir"], tilesPath)
        if not os.path.exists(fullTilesPath):
            return jsonify({"error": f"瓦片目录不存在: {fullTilesPath}"}), 404

        threshold = normalizeFloat(data.get("transparencyThreshold", 0.1), 0.1)
        if threshold > 1:
            threshold = threshold / 100.0
        threshold = max(0.0, min(1.0, threshold))

        totalChecked = 0
        nodataCount = 0
        validCount = 0
        errorCount = 0
        nodataFiles = []
        zoomStats = {}

        for root, _, files in os.walk(fullTilesPath):
            for file in files:
                if not file.lower().endswith(".png"):
                    continue
                filePath = os.path.join(root, file)
                totalChecked += 1
                relPath = os.path.relpath(filePath, fullTilesPath)
                pathParts = relPath.split(os.sep)
                zoomLevel = pathParts[0] if pathParts and pathParts[0].isdigit() else "unknown"
                try:
                    if checkTileHasNodata(filePath, threshold):
                        nodataCount += 1
                        nodataFiles.append(relPath)
                        zoomStats.setdefault(zoomLevel, {"total": 0, "nodata": 0})
                        zoomStats[zoomLevel]["nodata"] += 1
                    else:
                        validCount += 1
                    zoomStats.setdefault(zoomLevel, {"total": 0, "nodata": 0})
                    zoomStats[zoomLevel]["total"] += 1
                except Exception:
                    errorCount += 1

        result = {
            "success": True,
            "summary": {
                "totalChecked": totalChecked,
                "nodataTiles": nodataCount,
                "validTiles": validCount,
                "errors": errorCount,
                "nodataPercentage": round((nodataCount / totalChecked * 100), 2) if totalChecked > 0 else 0,
                "transparencyThreshold": threshold,
            },
            "zoomLevelStats": zoomStats,
            "message": f"扫描完成！检查了 {totalChecked} 个瓦片，发现 {nodataCount} 个达到透明阈值的瓦片",
        }
        if data.get("includeDetails", False) and nodataFiles:
            result["nodataFiles"] = nodataFiles[:100]
            if len(nodataFiles) > 100:
                result["note"] = f"透明文件过多，仅显示前100个，总共发现 {len(nodataFiles)} 个透明文件"
        return jsonify(result)
    except Exception as exc:
        errorMessage = f"扫描透明瓦片失败: {exc}"
        logMessage(errorMessage, "ERROR")
        return jsonify({"error": errorMessage}), 500


def extractGeographicBounds(gdalinfoOutput: str) -> dict:
    try:
        lines = gdalinfoOutput.split("\n")
        bounds = {}
        coordinateSystemType = None
        for line in lines:
            line = line.strip()
            if line.startswith("PROJCS["):
                coordinateSystemType = "projected"
                break
            if line.startswith("GEOGCS[") or line.startswith("GEOGCRS["):
                coordinateSystemType = "geographic"
                break
        if coordinateSystemType is None:
            return None

        def parseDmsCoordinate(coordStr):
            match = re.search(r"(\d+)d\s*(\d+)'(\d+\.?\d*)\"([EWNS])", coordStr)
            if not match:
                return None
            degrees = float(match.group(1))
            minutes = float(match.group(2))
            seconds = float(match.group(3))
            direction = match.group(4)
            decimalDegrees = degrees + minutes / 60 + seconds / 3600
            if direction in ["W", "S"]:
                decimalDegrees = -decimalDegrees
            return decimalDegrees

        def parseDecimalCoordinate(coordStr):
            numbers = re.findall(r"(-?\d+\.?\d*)", coordStr)
            if len(numbers) >= 2:
                return float(numbers[0]), float(numbers[1])
            return None, None

        cornerSection = False
        for line in lines:
            line = line.strip()
            if line.startswith("Corner Coordinates:"):
                cornerSection = True
                continue
            if cornerSection and line.startswith("Upper Left"):
                parts = line.split(")")
                if coordinateSystemType == "projected" and len(parts) >= 2:
                    coordSection = parts[1].strip().replace("(", "").replace(")", "")
                    if "," in coordSection:
                        lonStr, latStr = coordSection.split(",", 1)
                        lon = parseDmsCoordinate(lonStr.strip())
                        lat = parseDmsCoordinate(latStr.strip())
                        if lon is not None and lat is not None:
                            bounds["upperLeftLon"] = lon
                            bounds["upperLeftLat"] = lat
                elif coordinateSystemType == "geographic" and len(parts) >= 1:
                    coordSection = parts[0].split("(")[1].strip() if "(" in parts[0] else parts[0].strip()
                    lon, lat = parseDecimalCoordinate(coordSection)
                    if lon is not None and lat is not None:
                        bounds["upperLeftLon"] = lon
                        bounds["upperLeftLat"] = lat
            elif cornerSection and line.startswith("Lower Right"):
                parts = line.split(")")
                if coordinateSystemType == "projected" and len(parts) >= 2:
                    coordSection = parts[1].strip().replace("(", "").replace(")", "")
                    if "," in coordSection:
                        lonStr, latStr = coordSection.split(",", 1)
                        lon = parseDmsCoordinate(lonStr.strip())
                        lat = parseDmsCoordinate(latStr.strip())
                        if lon is not None and lat is not None:
                            bounds["lowerRightLon"] = lon
                            bounds["lowerRightLat"] = lat
                elif coordinateSystemType == "geographic" and len(parts) >= 1:
                    coordSection = parts[0].split("(")[1].strip() if "(" in parts[0] else parts[0].strip()
                    lon, lat = parseDecimalCoordinate(coordSection)
                    if lon is not None and lat is not None:
                        bounds["lowerRightLon"] = lon
                        bounds["lowerRightLat"] = lat
        if "upperLeftLon" in bounds and "lowerRightLon" in bounds:
            west = bounds["upperLeftLon"]
            east = bounds["lowerRightLon"]
            north = bounds["upperLeftLat"]
            south = bounds["lowerRightLat"]
            widthDegrees = east - west
            heightDegrees = north - south
            if widthDegrees < 0:
                widthDegrees += 360
            if heightDegrees < 0:
                heightDegrees = abs(heightDegrees)
            bounds.update({"west": west, "east": east, "north": north, "south": south, "widthDegrees": widthDegrees, "heightDegrees": heightDegrees})
        return bounds if bounds else None
    except Exception as exc:
        logMessage(f"提取地理边界失败: {exc}", "ERROR")
        return None


def getFileGeographicBounds(filePath: str) -> dict:
    try:
        result = runCommand(["gdalinfo", filePath])
        if not result["success"]:
            return None
        return extractGeographicBounds(result["stdout"])
    except Exception as exc:
        logMessage(f"获取文件地理边界失败: {filePath}, 错误: {exc}", "ERROR")
        return None


def _safe_geoserver_tile_name(value, default_value):
    text = str(value or "").strip()
    if not text:
        text = default_value
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")
    if not normalized:
        normalized = default_value
    if not re.match(r"^[A-Za-z_]", normalized):
        normalized = f"map_{normalized}"
    return normalized


def _output_name_from_path(output_path_array, task_id):
    if isinstance(output_path_array, list):
        candidates = [str(part or "").strip() for part in output_path_array if str(part or "").strip()]
        if candidates:
            return candidates[-1]
    text = str(output_path_array or "").replace("\\", "/").strip("/")
    if text:
        return text.split("/")[-1]
    return task_id


def _geoserver_wms_base_url():
    return str(config.get("geoserverBaseUrl") or "http://atlasworks-geoserver:8080/geoserver").rstrip("/") + "/wms"


def _geoserver_auth_tuple():
    return (
        str(config.get("geoserverUsername") or "admin"),
        str(config.get("geoserverPassword") or "geoserver"),
    )


def _sync_indexed_task(task_id):
    with taskLock:
        snapshot = taskStatus.get(task_id)
    if snapshot:
        syncTaskSnapshot(task_id, snapshot)


def _is_task_stopped(task_id):
    if not task_id:
        return False
    with taskLock:
        current = taskStatus.get(task_id)
    return bool(current and current.get("status") == "stopped")


def _geoserver_tile_output_path(tile_info, output_path, image_format, tile_scheme):
    return getTileOutputPath(
        output_path,
        int(tile_info["z"]),
        int(tile_info["x"]),
        int(tile_info["y"]),
        {"imageFormat": image_format, "tileScheme": tile_scheme},
    )


def _read_bbox_axis_value(payload, *names):
    if not isinstance(payload, dict):
        return None
    for name in names:
        if name in payload and payload.get(name) is not None:
            return float(payload.get(name))
    return None


def _extract_geoserver_wgs84_bounds(publish_result):
    coverage = ((publish_result or {}).get("layerInfo") or {}).get("coverage") or {}
    lat_lon_bbox = coverage.get("latLonBoundingBox") or coverage.get("latlonBoundingBox") or {}
    west = _read_bbox_axis_value(lat_lon_bbox, "minx", "minX")
    south = _read_bbox_axis_value(lat_lon_bbox, "miny", "minY")
    east = _read_bbox_axis_value(lat_lon_bbox, "maxx", "maxX")
    north = _read_bbox_axis_value(lat_lon_bbox, "maxy", "maxY")

    if None not in (west, south, east, north):
        return [
            max(-180.0, min(180.0, west)),
            max(-85.05112878, min(85.05112878, south)),
            max(-180.0, min(180.0, east)),
            max(-85.05112878, min(85.05112878, north)),
        ]

    raise ValueError("GeoServer 未返回有效 WGS84 图层范围，无法生成瓦片计划")


def _build_tile_index_from_bounds(bounds, min_zoom, max_zoom, tile_size):
    west, south, east, north = bounds
    tile_index = []
    for zoom in range(int(min_zoom), int(max_zoom) + 1):
        min_tile_x, min_tile_y = deg2tile(north, west, zoom)
        max_tile_x, max_tile_y = deg2tile(south, east, zoom)
        min_tile_x = max(0, min(min_tile_x, max_tile_x))
        max_tile_x = min((1 << zoom) - 1, max(min_tile_x, max_tile_x))
        min_tile_y = max(0, min(min_tile_y, max_tile_y))
        max_tile_y = min((1 << zoom) - 1, max(min_tile_y, max_tile_y))
        for tile_x in range(min_tile_x, max_tile_x + 1):
            for tile_y in range(min_tile_y, max_tile_y + 1):
                tile_west, tile_north = tile2deg(tile_x, tile_y, zoom)
                tile_east, tile_south = tile2deg(tile_x + 1, tile_y + 1, zoom)
                tile_index.append({
                    "z": zoom,
                    "x": tile_x,
                    "y": tile_y,
                    "bounds": [tile_west, tile_south, tile_east, tile_north],
                    "tileSize": tile_size,
                })
    return tile_index


def _write_geoserver_tile(tile_info, output_path, workspace, layer_names, image_format, tile_scheme, tile_size, transparent_background=True, retry_count=GEOSERVER_WMS_RETRIES):
    zoom = int(tile_info["z"])
    tile_x = int(tile_info["x"])
    tile_y = int(tile_info["y"])
    tile_file, _, _ = _geoserver_tile_output_path(tile_info, output_path, image_format, tile_scheme)
    if os.path.exists(tile_file) and os.path.getsize(tile_file) > 0:
        return {"success": True, "skipped": True, "tileFile": tile_file}

    min_x, min_y, max_x, max_y = tile2mercator_bounds(tile_x, tile_y, zoom)
    mime_type = "image/jpeg" if image_format == "jpeg" else "image/png"
    temp_file = f"{tile_file}.tmp"
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": ",".join(f"{workspace}:{name}" for name in layer_names),
        "STYLES": "",
        "SRS": "EPSG:3857",
        "BBOX": f"{min_x},{min_y},{max_x},{max_y}",
        "WIDTH": int(tile_size),
        "HEIGHT": int(tile_size),
        "FORMAT": mime_type,
        "TRANSPARENT": "true" if transparent_background and image_format == "png" else "false",
    }
    attempts = max(1, int(retry_count or 1))
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                _geoserver_wms_base_url(),
                params=params,
                auth=_geoserver_auth_tuple(),
                timeout=90,
            )
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if response.status_code != 200 or not content_type.startswith("image/"):
                detail = response.text[:500] if hasattr(response, "text") else f"HTTP {response.status_code}"
                raise RuntimeError(detail)
            if not response.content:
                raise RuntimeError("GeoServer 返回空图片内容")
            with open(temp_file, "wb") as file_obj:
                file_obj.write(response.content)
            os.replace(temp_file, tile_file)
            return {"success": True, "tileFile": tile_file, "attempts": attempt}
        except Exception as exc:
            last_error = str(exc)
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass
            if attempt < attempts:
                time.sleep(GEOSERVER_WMS_RETRY_DELAY * attempt)
    raise RuntimeError(f"GeoServer WMS 出图失败 z={zoom} x={tile_x} y={tile_y}，已重试 {attempts} 次: {last_error}")


def _union_bounds(bounds_list):
    valid_bounds = [bounds for bounds in bounds_list if isinstance(bounds, list) and len(bounds) == 4]
    if not valid_bounds:
        raise ValueError("GeoServer 未返回有效图层范围，无法生成瓦片计划")
    bounds = [
        min(bounds[0] for bounds in valid_bounds),
        min(bounds[1] for bounds in valid_bounds),
        max(bounds[2] for bounds in valid_bounds),
        max(bounds[3] for bounds in valid_bounds),
    ]
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise ValueError(f"GeoServer 返回非法图层范围: {bounds}")
    return bounds


def _validate_geoserver_render_options(tif_files, render_options):
    errors = []
    warnings = []
    render_mode = str(render_options.get("renderMode") or "auto").strip().lower()
    if render_mode not in {"auto", "gray", "rgb"}:
        errors.append(f"渲染模式不支持: {render_mode}")
        return errors, warnings
    if render_mode == "auto":
        return errors, warnings

    requested_bands = [normalizeInt(render_options.get("redBand"), 1, 1)]
    if render_mode == "rgb":
        requested_bands.extend([
            normalizeInt(render_options.get("greenBand"), 2, 1),
            normalizeInt(render_options.get("blueBand"), 3, 1),
        ])
    max_requested = max(requested_bands)
    for tif_file in tif_files:
        try:
            band_info = getSourceBandInfoCached(tif_file)
            band_count = int(band_info.get("bandCount") or 0)
        except Exception as exc:
            warnings.append(f"{os.path.basename(tif_file)} 波段读取失败: {exc}")
            continue
        if band_count <= 0:
            warnings.append(f"{os.path.basename(tif_file)} 未读取到有效波段数")
            continue
        if max_requested > band_count:
            errors.append(f"{os.path.basename(tif_file)} 只有 {band_count} 个波段，当前请求波段 {requested_bands}")
    return errors, warnings


def _publish_geoserver_tile_layers(tif_files, layer_name, render_options, image_format):
    publish_results = []
    style_result = None
    for index, tif_file in enumerate(tif_files, start=1):
        source_path = os.path.relpath(tif_file, config["dataSourceDir"]).replace("\\", "/")
        source_stem = os.path.splitext(os.path.basename(tif_file))[0]
        per_file_layer_name = _safe_geoserver_tile_name(f"{layer_name}_{index:03d}_{source_stem}", f"{layer_name}_{index:03d}")
        publish_result = publishGeoserverPayload({
            "sourcePath": source_path,
            "alias": per_file_layer_name,
            "layerName": per_file_layer_name,
            "storeName": per_file_layer_name,
            "targetCrs": render_options.get("projection") or "EPSG:3857",
            "tileFormat": "image/jpeg" if image_format == "jpeg" else "image/png",
            "styleName": "raster",
            "nodataValue": render_options.get("nodataValue"),
            "seedEnabled": False,
            "overwrite": True,
        })
        render_mode = str(render_options.get("renderMode") or "auto").strip().lower()
        if render_mode in {"rgb", "gray"}:
            if style_result is None:
                style_result = createRasterStyle(
                    publish_result.get("workspace"),
                    f"{layer_name}_{render_mode}_style",
                    render_mode,
                    render_options.get("redBand", 1),
                    render_options.get("greenBand", 2),
                    render_options.get("blueBand", 3),
                    render_options.get("nodataValue"),
                    overwrite=True,
                )
            setLayerDefaultStyle(publish_result.get("workspace"), publish_result.get("layerName"), style_result.get("styleName"))
        publish_results.append(publish_result)
    return publish_results, style_result


def processIndexedTilesWithGeoserver(tif_files, output_path, output_path_array, task_id, render_options, min_zoom, max_zoom, tile_size, image_format, tile_scheme, enable_incremental_update=False, skip_nodata_tiles=False, transparency_threshold=0.1):
    layer_name = _safe_geoserver_tile_name(_output_name_from_path(output_path_array, task_id), f"map_tiles_{task_id}")
    publish_results = []
    style_result = None
    cleanup_results = []
    try:
        publish_results, style_result = _publish_geoserver_tile_layers(tif_files, layer_name, render_options, image_format)
        workspace = publish_results[0].get("workspace")
        actual_layer_names = [item.get("layerName") for item in publish_results if item.get("layerName")]
        bounds = _union_bounds([_extract_geoserver_wgs84_bounds(item) for item in publish_results])
        tile_index = _build_tile_index_from_bounds(bounds, min_zoom, max_zoom, tile_size)
        total_tiles = len(tile_index)
        processed_tiles = 0
        skipped_tiles = 0
        failed_tiles = 0
        error_samples = []
        failed_tile_records = []
        deleted_nodata_tiles = 0
        start_time = time.time()
        wms_concurrency = normalizeInt(render_options.get("wmsConcurrency"), 4, 1, 16)
        transparent_background = bool(render_options.get("transparentBackground", True))
        retry_count = normalizeInt(render_options.get("wmsRetryCount"), GEOSERVER_WMS_RETRIES, 1, 8)
        pending_tile_index = tile_index

        if enable_incremental_update:
            pending_tile_index = []
            for tile_info in tile_index:
                tile_file, _, _ = _geoserver_tile_output_path(tile_info, output_path, image_format, tile_scheme)
                if os.path.exists(tile_file) and os.path.getsize(tile_file) > 0:
                    skipped_tiles += 1
                    processed_tiles += 1
                else:
                    pending_tile_index.append(tile_info)

        with taskLock:
            current = taskStatus.get(task_id)
            if current:
                current["currentStage"] = "GeoServer 出图切片"
                current["message"] = f"GeoServer 图层已准备，开始写出瓦片 0/{total_tiles}"
                current["progress"] = 8
                current.setdefault("stats", {})["totalTiles"] = total_tiles
                current["stats"]["skippedTiles"] = skipped_tiles
                current["stats"]["pendingTiles"] = len(pending_tile_index)
                appendTaskLog(current, "GeoServer 图层", "completed", f"临时图层已准备: {len(actual_layer_names)} 个", 8)
                if skipped_tiles:
                    appendTaskLog(current, "增量续切", "completed", f"已复用现有瓦片 {skipped_tiles} 个，待写出 {len(pending_tile_index)} 个", 9)
        _sync_indexed_task(task_id)

        def process_tile(tile_info):
            if _is_task_stopped(task_id):
                return {"success": False, "stopped": True, "tile": tile_info, "error": "任务已停止"}
            try:
                result = _write_geoserver_tile(
                    tile_info,
                    output_path,
                    workspace,
                    actual_layer_names,
                    image_format,
                    tile_scheme,
                    tile_size,
                    transparent_background,
                    retry_count,
                )
                return {"success": True, "tile": tile_info, "skipped": bool(result.get("skipped")), "attempts": result.get("attempts", 1)}
            except Exception as exc:
                return {"success": False, "tile": tile_info, "error": str(exc)}

        with ThreadPoolExecutor(max_workers=wms_concurrency) as executor:
            future_map = {executor.submit(process_tile, tile_info): tile_info for tile_info in pending_tile_index}
            for index, future in enumerate(as_completed(future_map), start=1):
                tile_result = future.result()
                if tile_result.get("stopped"):
                    for pending_future in future_map:
                        if not pending_future.done():
                            pending_future.cancel()
                    return {
                        "success": False,
                        "stopped": True,
                        "error": "任务已停止",
                        "outputPath": output_path,
                        "totalTiles": total_tiles,
                        "processedTiles": processed_tiles,
                        "skippedTiles": skipped_tiles,
                        "failedTiles": failed_tiles,
                        "bounds": bounds,
                        "renderOptions": render_options,
                        "method": "geoserver-wms-file-tiles",
                    }
                if tile_result.get("success"):
                    processed_tiles += 1
                    if tile_result.get("skipped"):
                        skipped_tiles += 1
                else:
                    failed_tiles += 1
                    tile_info = tile_result.get("tile") or {}
                    exc_message = tile_result.get("error") or "未知错误"
                    failed_tile_records.append({
                        "z": tile_info.get("z"),
                        "x": tile_info.get("x"),
                        "y": tile_info.get("y"),
                        "bounds": tile_info.get("bounds"),
                        "error": exc_message,
                    })
                    if len(error_samples) < 20:
                        error_samples.append({
                            "z": tile_info.get("z"),
                            "x": tile_info.get("x"),
                            "y": tile_info.get("y"),
                            "error": exc_message,
                        })

                completed_count = skipped_tiles + index
                if index == len(pending_tile_index) or index % 20 == 0:
                    progress = 10 + int((completed_count / max(1, total_tiles)) * 85)
                    elapsed = max(0.001, time.time() - start_time)
                    speed = round(max(0, index - failed_tiles) / elapsed, 2)
                    with taskLock:
                        current = taskStatus.get(task_id)
                        if current:
                            current["progress"] = min(99, progress)
                            current["currentStage"] = "GeoServer 出图切片"
                            current["message"] = f"GeoServer 切片处理中 {completed_count}/{total_tiles}，复用 {skipped_tiles}，失败 {failed_tiles}"
                            current["stats"] = {
                                "totalTiles": total_tiles,
                                "processedTiles": processed_tiles,
                                "skippedTiles": skipped_tiles,
                                "failedTiles": failed_tiles,
                                "remainingTiles": max(0, total_tiles - completed_count),
                                "averageSpeed": speed,
                                "successRate": f"{processed_tiles / max(1, total_tiles) * 100:.1f}%",
                            }
                    _sync_indexed_task(task_id)

        failed_tiles_file = None
        if failed_tile_records:
            failed_tiles_file = os.path.join(output_path, "failed_tiles.json")
            with open(failed_tiles_file, "w", encoding="utf-8") as file_obj:
                json.dump(failed_tile_records, file_obj, indent=2, ensure_ascii=False)

        if skip_nodata_tiles and image_format == "png" and failed_tiles == 0:
            cleanup_result = deleteNodataTilesInternal(
                os.path.relpath(output_path, config["tilesDir"]).replace("\\", "/"),
                includeDetails=False,
                transparencyThreshold=transparency_threshold,
            )
            deleted_nodata_tiles = int((cleanup_result.get("summary") or {}).get("deleted_count") or cleanup_result.get("deleted_count") or 0)

        metadata_file = os.path.join(output_path, "tile_metadata.json")
        metadata = {
            "taskId": task_id,
            "method": "geoserver-wms-file-tiles",
            "outputPath": output_path,
            "outputPathArray": output_path_array,
            "sourceFiles": [os.path.relpath(path, config["dataSourceDir"]).replace("\\", "/") for path in tif_files],
            "totalSourceFiles": len(tif_files),
            "zoomLevels": f"{min_zoom}-{max_zoom}",
            "tileSize": tile_size,
            "imageFormat": image_format,
            "tileScheme": tile_scheme,
            "totalTiles": total_tiles,
            "processedTiles": processed_tiles,
            "skippedTiles": skipped_tiles,
            "failedTiles": failed_tiles,
            "deletedNodataTiles": deleted_nodata_tiles,
            "successRate": f"{processed_tiles / max(1, total_tiles) * 100:.1f}%",
            "bounds": bounds,
            "renderOptions": render_options,
            "wmsRetryCount": retry_count,
            "geoserverWorkspace": workspace,
            "geoserverLayerNames": actual_layer_names,
            "geoserverStoreNames": [item.get("storeName") for item in publish_results],
            "geoserverMode": "single-layer-stack",
            "geoserverStyle": style_result.get("styleName") if style_result else "raster",
            "temporaryGeoserverLayer": True,
            "errorSamples": error_samples,
            "failedTilesFile": failed_tiles_file,
            "createdAt": datetime.now().isoformat(),
        }
        with open(metadata_file, "w", encoding="utf-8") as file_obj:
            json.dump(metadata, file_obj, indent=2, ensure_ascii=False)

        return {
            "success": failed_tiles == 0,
            "error": f"GeoServer 切片完成但存在失败瓦片 {failed_tiles} 个" if failed_tiles else "",
            "outputPath": output_path,
            "metadataFile": metadata_file,
            "sourceFiles": metadata["sourceFiles"],
            "totalTiles": total_tiles,
            "processedTiles": processed_tiles,
            "skippedTiles": skipped_tiles,
            "failedTiles": failed_tiles,
            "deletedNodataTiles": deleted_nodata_tiles,
            "successRate": metadata["successRate"],
            "bounds": bounds,
            "renderOptions": render_options,
            "method": "geoserver-wms-file-tiles",
            "geoserverWorkspace": workspace,
            "geoserverLayerNames": actual_layer_names,
            "geoserverStoreNames": [item.get("storeName") for item in publish_results],
            "geoserverMode": "single-layer-stack",
            "geoserverStyle": style_result.get("styleName") if style_result else "raster",
            "errorSamples": error_samples,
            "failedTilesFile": failed_tiles_file,
        }
    finally:
        for publish_result in publish_results:
            try:
                cleanup_results.append({
                    **deleteStore(publish_result.get("workspace"), publish_result.get("storeName") or publish_result.get("layerName") or layer_name),
                    "type": "store",
                    "success": True,
                })
            except Exception as exc:
                cleanup_results.append({
                    "type": "store",
                    "workspace": publish_result.get("workspace"),
                    "storeName": publish_result.get("storeName") or publish_result.get("layerName") or layer_name,
                    "success": False,
                    "error": str(exc),
                })
                logMessage(f"GeoServer 临时图层清理失败: {exc}", "WARNING")
        if style_result:
            try:
                cleanup_results.append({
                    **deleteStyle(style_result.get("workspace"), style_result.get("styleName"), purge=True, quiet=True),
                    "type": "style",
                    "success": True,
                })
            except Exception as exc:
                cleanup_results.append({
                    "type": "style",
                    "workspace": style_result.get("workspace"),
                    "styleName": style_result.get("styleName"),
                    "success": False,
                    "error": str(exc),
                })
                logMessage(f"GeoServer 临时样式清理失败: {exc}", "WARNING")
        if cleanup_results:
            try:
                cleanup_file = os.path.join(output_path, "geoserver_cleanup.json")
                with open(cleanup_file, "w", encoding="utf-8") as file_obj:
                    json.dump(cleanup_results, file_obj, indent=2, ensure_ascii=False)
            except Exception as exc:
                logMessage(f"GeoServer 清理记录写入失败: {exc}", "WARNING")


def createIndexedTiles():
    try:
        data = request.get_json(silent=True) or {}
        task_id = str(data.get("taskId") or f"indexedTiles{int(time.time())}")
        worker_run = bool(data.get("_workerRun"))
        run_synchronously = bool(data.get("_runSynchronously"))
        folder_paths = data.get("folderPaths", [])
        file_patterns = data.get("filePatterns", [])
        output_path_array = data.get("outputPath", [])
        min_zoom = normalizeInt(data.get("minZoom"), 0, 0)
        max_zoom = normalizeInt(data.get("maxZoom"), 12, min_zoom)
        tile_size = normalizeInt(data.get("tileSize"), 256, 64)
        projection = normalizeProjection(data.get("projection", "EPSG:3857"))
        data_format = data.get("dataFormat", "xyz")
        image_format = normalizeImageFormat(data.get("imageFormat", "png"))
        tile_scheme = normalizeTileScheme(data.get("tileScheme", "tms"))
        wms_concurrency = normalizeInt(data.get("wmsConcurrency", data.get("threads")), 4, 1, 16)
        transparent_background = bool(data.get("transparentBackground", True))
        use_source_nodata = False if data.get("useSourceNodata") is False else True
        render_mode = str(data.get("renderMode") or "auto").strip().lower()
        if render_mode not in {"auto", "gray", "rgb"}:
            render_mode = "auto"
        red_band = normalizeInt(data.get("redBand"), 1, 1)
        green_band = normalizeInt(data.get("greenBand"), 2, 1)
        blue_band = normalizeInt(data.get("blueBand"), 3, 1)
        nodata_value = data.get("nodataValue")
        enable_incremental_update = bool(data.get("enableIncrementalUpdate", False))
        skip_nodata_tiles = bool(data.get("skipNodataTiles", False))
        transparency_threshold = normalizeFloat(data.get("transparencyThreshold"), 0.1)
        if skip_nodata_tiles and image_format != "png":
            logMessage("skipNodataTiles 仅在 PNG 输出下生效，已自动禁用", "WARNING")
            skip_nodata_tiles = False

        render_options = {
            "projection": projection,
            "dataFormat": data_format,
            "imageFormat": image_format,
            "tileScheme": tile_scheme,
            "wmsConcurrency": wms_concurrency,
            "transparentBackground": transparent_background,
            "useSourceNodata": use_source_nodata,
            "renderMode": render_mode,
            "redBand": red_band,
            "greenBand": green_band,
            "blueBand": blue_band,
            "nodataValue": nodata_value,
            "transparencyThreshold": transparency_threshold,
            "renderer": "geoserver-wms",
        }

        errors = []
        tif_files = []
        relative_tif_files = findTifFilesInFolders(folder_paths, file_patterns)
        if not relative_tif_files:
            errors.append("未找到匹配的 TIF 文件")
        else:
            for relative_path in relative_tif_files:
                full_path = os.path.join(config["dataSourceDir"], relative_path)
                if os.path.exists(full_path):
                    tif_files.append(full_path)
            if not tif_files:
                errors.append("匹配结果存在，但源文件都不可用")
        if tif_files:
            render_errors, render_warnings = _validate_geoserver_render_options(tif_files, render_options)
            errors.extend(render_errors)
            if render_warnings:
                logMessage(f"GeoServer 地图切片渲染配置提示: {'; '.join(render_warnings[:5])}", "WARNING")

        if errors:
            failed_record = createTaskRecord(
                task_id=task_id,
                status="failed",
                progress=0,
                message=f"任务参数校验失败: {'; '.join(errors)}",
                start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                current_stage="参数校验失败",
                process_log=[{
                    "stage": "参数校验",
                    "status": "failed",
                    "message": f"任务参数校验失败: {'; '.join(errors)}",
                    "timestamp": datetime.now().isoformat(),
                    "progress": 0,
                    "errors": errors,
                }],
                stats={"totalTiles": 0, "processedTiles": 0, "failedTiles": 0, "remainingTiles": 0, "successRate": "0%"},
                extra={"errors": errors},
            )
            with taskLock:
                taskStatus[task_id] = failed_record
            _sync_indexed_task(task_id)
            return jsonify({"success": False, "taskId": task_id, "message": failed_record["message"], "statusUrl": f"/api/tasks/{task_id}", "errors": errors}), 200

        output_path, output_path_array, output_path_auto_generated = resolveTilesOutputPath(output_path_array, "map")
        os.makedirs(output_path, exist_ok=True)
        if output_path_auto_generated:
            logMessage(f"未传 outputPath，已自动生成地图输出目录: {output_path}")
        preview_resource_plan = {
            "renderer": "geoserver-wms",
            "wmsConcurrency": wms_concurrency,
            "transparentBackground": transparent_background,
            "renderMode": render_mode,
        }

        def run_geoserver_tile_task():
            slot_acquired = False
            try:
                queued_record = createTaskRecord(
                    task_id=task_id,
                    status="queued",
                    progress=0,
                    message=f"任务已进入排队，当前重任务并发槽位上限为 {MAX_INDEXED_TASK_SLOTS}",
                    start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    current_stage="排队中",
                    process_log=[{
                        "stage": "任务创建",
                        "status": "completed",
                        "message": f"任务创建完成，已解析到 {len(tif_files)} 个源文件，渲染器 GeoServer",
                        "timestamp": datetime.now().isoformat(),
                        "progress": 0,
                        "fileCount": len(tif_files),
                    }],
                    stats={
                        "totalTiles": 0,
                        "processedTiles": 0,
                        "failedTiles": 0,
                        "remainingTiles": 0,
                        "averageSpeed": 0,
                        "successRate": "0%",
                    },
                    processing_info={"previewResourcePlan": preview_resource_plan, "renderer": "geoserver-wms"},
                )
                with taskLock:
                    taskStatus[task_id] = queued_record
                _sync_indexed_task(task_id)

                while not slot_acquired:
                    with taskLock:
                        current_task = taskStatus.get(task_id)
                        if not current_task or current_task.get("status") == "stopped":
                            return
                    slot_acquired = indexedTaskSemaphore.acquire(timeout=1)

                with taskLock:
                    current_task = taskStatus.get(task_id)
                    if not current_task or current_task.get("status") == "stopped":
                        return
                    current_task["status"] = "running"
                    current_task["progress"] = 3
                    current_task["message"] = "开始使用 GeoServer 渲染瓦片文件"
                    current_task["currentStage"] = "GeoServer 初始化"
                    appendTaskLog(current_task, "任务调度", "completed", "任务已获得执行槽位，开始 GeoServer 切片", 3)
                _sync_indexed_task(task_id)

                result = processIndexedTilesWithGeoserver(
                    tif_files,
                    output_path,
                    output_path_array,
                    task_id,
                    render_options,
                    min_zoom,
                    max_zoom,
                    tile_size,
                    image_format,
                    tile_scheme,
                    enable_incremental_update,
                    skip_nodata_tiles,
                    transparency_threshold,
                )

                with taskLock:
                    current_task = taskStatus.get(task_id)
                if not current_task:
                    return

                start_time_str = current_task.get("startTime")
                if result.get("stopped"):
                    stopped_record = createTaskRecord(
                        task_id=task_id,
                        status="stopped",
                        progress=current_task.get("progress", 0),
                        message="GeoServer 地图切片任务已停止",
                        start_time=start_time_str,
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="已停止",
                        process_log=current_task.get("processLog", []),
                        result=result,
                        processing_info=current_task.get("processingInfo", {}),
                    )
                    appendTaskLog(stopped_record, "任务停止", "stopped", "已收到停止信号，临时 GeoServer 图层已清理", stopped_record.get("progress", 0))
                    with taskLock:
                        taskStatus[task_id] = stopped_record
                elif result.get("success"):
                    completed_record = createTaskRecord(
                        task_id=task_id,
                        status="completed",
                        progress=100,
                        message=f"切片完成 {result.get('processedTiles', 0)}/{result.get('totalTiles', 0)}",
                        start_time=start_time_str,
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="完成",
                        process_log=current_task.get("processLog", []),
                        result={
                            "outputPath": result.get("outputPath"),
                            "outputPathArray": output_path_array,
                            "metadataFile": result.get("metadataFile"),
                            "sourceFiles": result.get("sourceFiles", []),
                            "totalSourceFiles": len(result.get("sourceFiles", [])),
                            "totalTiles": result.get("totalTiles", 0),
                            "processedTiles": result.get("processedTiles", 0),
                            "failedTiles": result.get("failedTiles", 0),
                            "deletedNodataTiles": result.get("deletedNodataTiles", 0),
                            "successRate": result.get("successRate"),
                            "zoomLevels": f"{min_zoom}-{max_zoom}",
                            "tileSize": tile_size,
                            "method": "geoserver-wms-file-tiles",
                            "renderOptions": render_options,
                            "bounds": result.get("bounds"),
                        },
                        stats={
                            "totalTiles": result.get("totalTiles", 0),
                            "processedTiles": result.get("processedTiles", 0),
                            "failedTiles": result.get("failedTiles", 0),
                            "deletedNodataTiles": result.get("deletedNodataTiles", 0),
                            "remainingTiles": 0,
                            "successRate": result.get("successRate"),
                            "estimatedTimeRemaining": "已完成",
                        },
                        processing_info={"renderer": "geoserver-wms", "previewResourcePlan": preview_resource_plan},
                    )
                    appendTaskLog(completed_record, "切片完成", "completed", "GeoServer 已输出实际瓦片文件", 100)
                    with taskLock:
                        taskStatus[task_id] = completed_record
                    finalizeTaskArtifact(task_id, source_files=result.get("sourceFiles", []), build_parameters={"jobType": "indexed_tiles", "method": "geoserver-wms-file-tiles", "minZoom": min_zoom, "maxZoom": max_zoom, "tileSize": tile_size, "outputPath": output_path_array})
                else:
                    failed_record = createTaskRecord(
                        task_id=task_id,
                        status="failed",
                        progress=current_task.get("progress", 0),
                        message=f"切片失败: {result.get('error', '未知错误')}",
                        start_time=start_time_str,
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="失败",
                        process_log=current_task.get("processLog", []),
                        error=result.get("error", "未知错误"),
                        result=result,
                        processing_info=current_task.get("processingInfo", {}),
                    )
                    appendTaskLog(failed_record, "切片失败", "failed", result.get("error", "未知错误"), failed_record.get("progress", 0))
                    with taskLock:
                        taskStatus[task_id] = failed_record
                _sync_indexed_task(task_id)
            except Exception as exc:
                with taskLock:
                    current_task = taskStatus.get(task_id, {})
                    failed_record = createTaskRecord(
                        task_id=task_id,
                        status="failed",
                        progress=current_task.get("progress", 0),
                        message=f"切片任务异常: {exc}",
                        start_time=current_task.get("startTime"),
                        end_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        current_stage="异常退出",
                        process_log=current_task.get("processLog", []),
                        error=str(exc),
                        processing_info=current_task.get("processingInfo", {}),
                    )
                    appendTaskLog(failed_record, "异常退出", "failed", str(exc), failed_record.get("progress", 0))
                    taskStatus[task_id] = failed_record
                _sync_indexed_task(task_id)
                logMessage(f"GeoServer indexedTiles 任务异常: {task_id} - {exc}", "ERROR")
            finally:
                if slot_acquired:
                    indexedTaskSemaphore.release()
                with taskLock:
                    taskProcesses.pop(task_id, None)

        should_queue = (
            not worker_run
            and str(config.get("taskDispatch") or "").strip().lower() in {"db", "queue", "worker"}
            and isDatabaseEnabled()
        )
        if should_queue:
            worker_payload = dict(data)
            worker_payload.update({
                "taskId": task_id,
                "outputPath": output_path_array,
                "minZoom": min_zoom,
                "maxZoom": max_zoom,
                "tileSize": tile_size,
                "projection": projection,
                "dataFormat": data_format,
                "imageFormat": image_format,
                "tileScheme": tile_scheme,
                "wmsConcurrency": wms_concurrency,
                "transparentBackground": transparent_background,
                "useSourceNodata": use_source_nodata,
                "renderMode": render_mode,
                "redBand": red_band,
                "greenBand": green_band,
                "blueBand": blue_band,
                "nodataValue": nodata_value,
                "skipNodataTiles": skip_nodata_tiles,
                "transparencyThreshold": transparency_threshold,
            })
            queued_record = createTaskRecord(
                task_id=task_id,
                status="queued",
                progress=0,
                message=f"GeoServer 地图切片任务已入队，识别到 {len(tif_files)} 个源文件",
                start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                current_stage="排队中",
                process_log=[{
                    "stage": "任务创建",
                    "status": "queued",
                    "message": f"任务已入队，已解析到 {len(tif_files)} 个源文件，渲染器 GeoServer",
                    "timestamp": datetime.now().isoformat(),
                    "progress": 0,
                    "fileCount": len(tif_files),
                }],
                stats={
                    "totalTiles": 0,
                    "processedTiles": 0,
                    "failedTiles": 0,
                    "remainingTiles": 0,
                    "averageSpeed": 0,
                    "successRate": "0%",
                },
                processing_info={"previewResourcePlan": preview_resource_plan, "renderer": "geoserver-wms"},
                extra={"jobType": "indexed_tiles", "workerPayload": worker_payload},
            )
            if enqueueBuildJob(task_id, "indexed_tiles", queued_record):
                return jsonify({
                    "success": True,
                    "taskId": task_id,
                    "status": "queued",
                    "message": f"GeoServer 地图切片任务已入队，识别到 {len(tif_files)} 个源文件",
                    "statusUrl": f"/api/tasks/{task_id}",
                    "method": "geoserver-wms-file-tiles",
                })

        if run_synchronously:
            run_geoserver_tile_task()
        else:
            task_thread = threading.Thread(target=run_geoserver_tile_task, daemon=True)
            with taskLock:
                taskProcesses[task_id] = task_thread
            task_thread.start()

        return jsonify({
            "success": True,
            "taskId": task_id,
            "status": "running" if worker_run else "queued",
            "message": f"GeoServer 地图切片任务已{'启动' if worker_run else '创建'}，识别到 {len(tif_files)} 个源文件",
            "statusUrl": f"/api/tasks/{task_id}",
            "method": "geoserver-wms-file-tiles",
            "indexInfo": {
                "totalFiles": len(tif_files),
                "zoomLevels": f"{min_zoom}-{max_zoom}",
                "tileSize": tile_size,
                "projection": projection,
                "dataFormat": data_format,
                "imageFormat": image_format,
                "tileScheme": tile_scheme,
                "bands": {"red": red_band, "green": green_band, "blue": blue_band},
                "enableIncrementalUpdate": enable_incremental_update,
                "wmsConcurrency": wms_concurrency,
                "transparentBackground": transparent_background,
                "useSourceNodata": use_source_nodata,
                "renderMode": render_mode,
                "nodataValue": nodata_value,
                "skipNodataTiles": skip_nodata_tiles,
                "transparencyThreshold": transparency_threshold,
            },
            "processingInfo": {
                "renderer": "geoserver-wms",
                "previewResourcePlan": preview_resource_plan,
                "outputPathArray": output_path_array,
            },
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

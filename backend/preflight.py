#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import os
import shutil
import subprocess

from flask import jsonify, request

from config import config
from dataSourceOps import findTifFilesInFolders
from utils import logMessage, normalizeInt


def _run_command(command, timeout=20):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except Exception as exc:
        return {"success": False, "stdout": "", "stderr": str(exc)}


def _normalize_output_path(output_path):
    if not output_path:
        return None
    if isinstance(output_path, list):
        return os.path.join(config["tilesDir"], *[str(item) for item in output_path])
    return os.path.join(config["tilesDir"], str(output_path))


def _extract_bounds(info):
    extent = info.get("wgs84Extent", {})
    coordinates = extent.get("coordinates") or []
    if not coordinates:
        return None
    ring = coordinates[0]
    if not ring:
        return None
    xs = [point[0] for point in ring if isinstance(point, (list, tuple)) and len(point) >= 2]
    ys = [point[1] for point in ring if isinstance(point, (list, tuple)) and len(point) >= 2]
    if not xs or not ys:
        return None
    return {
        "west": min(xs),
        "south": min(ys),
        "east": max(xs),
        "north": max(ys),
    }


def _inspect_raster(relative_path):
    full_path = os.path.join(config["dataSourceDir"], relative_path)
    info_result = _run_command(["gdalinfo", "-json", full_path], timeout=30)
    if not info_result["success"]:
        return {
            "path": relative_path,
            "exists": os.path.exists(full_path),
            "error": info_result["stderr"] or "gdalinfo 执行失败",
        }

    info = json.loads(info_result["stdout"])
    bands = info.get("bands", [])
    size = info.get("size", [0, 0])
    coordinate_system = info.get("coordinateSystem", {})
    stats = os.stat(full_path)

    projection = coordinate_system.get("wkt") or coordinate_system.get("proj4") or ""
    projection_name = projection.split(",")[0][:120] if projection else ""
    geo_transform = info.get("geoTransform", [])

    return {
        "path": relative_path,
        "exists": True,
        "sizeBytes": stats.st_size,
        "lastModified": int(stats.st_mtime),
        "width": size[0] if len(size) > 0 else 0,
        "height": size[1] if len(size) > 1 else 0,
        "bandCount": len(bands),
        "hasAlpha": any(band.get("colorInterpretation") == "Alpha" for band in bands),
        "dataTypes": sorted({band.get("type", "unknown") for band in bands}),
        "bounds": _extract_bounds(info),
        "projection": projection_name,
        "pixelSize": {
            "x": abs(geo_transform[1]) if len(geo_transform) >= 2 else None,
            "y": abs(geo_transform[5]) if len(geo_transform) >= 6 else None,
        },
    }


def _estimate_pyramid_tiles(width, height, min_zoom, max_zoom):
    if width <= 0 or height <= 0:
        return 0

    current_tiles = max(1, math.ceil(width / 256) * math.ceil(height / 256))
    levels = max(1, max_zoom - min_zoom + 1)
    total_tiles = 0

    for _ in range(levels):
        total_tiles += current_tiles
        if current_tiles <= 1:
            continue
        current_tiles = max(1, math.ceil(current_tiles / 4))

    return total_tiles


def _merge_bounds(all_bounds):
    valid_bounds = [bounds for bounds in all_bounds if isinstance(bounds, dict)]
    if not valid_bounds:
        return None
    return {
        "west": min(bounds["west"] for bounds in valid_bounds),
        "south": min(bounds["south"] for bounds in valid_bounds),
        "east": max(bounds["east"] for bounds in valid_bounds),
        "north": max(bounds["north"] for bounds in valid_bounds),
    }


def _detect_toolchain():
    gdal = _run_command(["gdalinfo", "--version"])
    ctb = _run_command(["ctb-tile", "--version"])
    return {
        "gdalinfo": {
            "available": gdal["success"],
            "version": gdal["stdout"] or gdal["stderr"],
        },
        "ctbTile": {
            "available": ctb["success"],
            "version": ctb["stdout"] or ctb["stderr"],
        },
    }


def runPreflightCheck():
    try:
        data = request.get_json(silent=True) or {}
        job_type = str(data.get("jobType", "map_tiles")).strip() or "map_tiles"
        folder_paths = data.get("folderPaths", [])
        file_patterns = data.get("filePatterns", [])
        output_path_input = data.get("outputPath")
        max_files = normalizeInt(data.get("maxFiles"), 50, 1, 500)
        min_zoom = normalizeInt(data.get("minZoom"), 0, 0, 30)
        max_zoom = normalizeInt(data.get("maxZoom"), 18, 0, 30)
        height_band = data.get("heightBand")

        matched_files = findTifFilesInFolders(folder_paths, file_patterns)
        files_for_scan = matched_files[:max_files]
        scanned_files = [_inspect_raster(relative_path) for relative_path in files_for_scan]

        warnings = []
        errors = []
        total_size = 0
        total_estimated_tiles = 0
        projections = set()
        band_counts = set()
        bounds_list = []
        multi_band_files = 0
        failed_scans = 0

        for file_info in scanned_files:
            if file_info.get("error"):
                failed_scans += 1
                errors.append(f"{file_info['path']}: {file_info['error']}")
                continue

            total_size += file_info.get("sizeBytes", 0)
            total_estimated_tiles += _estimate_pyramid_tiles(
                file_info.get("width", 0),
                file_info.get("height", 0),
                min_zoom,
                max_zoom,
            )

            projection = file_info.get("projection")
            if projection:
                projections.add(projection)

            band_count = file_info.get("bandCount")
            if isinstance(band_count, int) and band_count > 0:
                band_counts.add(band_count)
                if band_count > 1:
                    multi_band_files += 1

            if file_info.get("bounds"):
                bounds_list.append(file_info["bounds"])

        output_path = _normalize_output_path(output_path_input)
        output_exists = bool(output_path and os.path.exists(output_path))
        output_non_empty = False
        if output_exists and os.path.isdir(output_path):
            output_non_empty = any(True for _ in os.scandir(output_path))

        if len(projections) > 1:
            warnings.append("输入文件存在多个坐标系，正式构建前建议统一投影。")
        if len(band_counts) > 1:
            warnings.append("输入文件波段数不一致，可能触发波段兼容或渲染策略分支。")
        if job_type in ("terrain", "terrain_tiles") and multi_band_files > 0 and height_band in (None, ""):
            warnings.append("检测到多波段 DEM，但未显式提供 heightBand，后续建议补齐高程波段选择。")
        if output_non_empty:
            warnings.append("输出目录已存在且非空，继续构建可能覆盖旧结果。")
        if not matched_files:
            errors.append("未匹配到任何输入文件。")

        disk_usage = shutil.disk_usage(config["tilesDir"])
        estimated_disk_bytes = int(total_estimated_tiles * (45 * 1024 if job_type in ("terrain", "terrain_tiles") else 25 * 1024))
        estimated_duration_seconds = int(total_estimated_tiles / (25 if job_type in ("terrain", "terrain_tiles") else 80)) if total_estimated_tiles > 0 else 0
        toolchain = _detect_toolchain()

        if not toolchain["gdalinfo"]["available"]:
            errors.append("gdalinfo 不可用，无法执行正式构建。")
        if job_type in ("terrain", "terrain_tiles") and not toolchain["ctbTile"]["available"]:
            errors.append("ctb-tile 不可用，无法执行地形切片。")

        response = {
            "success": len(errors) == 0,
            "jobType": job_type,
            "folderPaths": folder_paths,
            "filePatterns": file_patterns,
            "matchedFileCount": len(matched_files),
            "scannedFileCount": len(scanned_files),
            "truncated": len(matched_files) > max_files,
            "warnings": warnings,
            "errors": errors,
            "checks": {
                "inputsReady": len(matched_files) > 0,
                "toolchainReady": len(errors) == 0 or all("不可用" not in error for error in errors),
                "projectionConsistent": len(projections) <= 1,
                "outputOverwriteRisk": output_non_empty,
            },
            "inputSummary": {
                "totalSizeBytes": total_size,
                "mergedBounds": _merge_bounds(bounds_list),
                "projectionCount": len(projections),
                "projections": sorted(projections)[:5],
                "bandCounts": sorted(band_counts),
                "multiBandFileCount": multi_band_files,
                "failedScanCount": failed_scans,
            },
            "outputSummary": {
                "outputPath": output_path,
                "exists": output_exists,
                "nonEmpty": output_non_empty,
            },
            "estimate": {
                "tileCount": total_estimated_tiles,
                "diskBytes": estimated_disk_bytes,
                "durationSeconds": estimated_duration_seconds,
            },
            "resourceState": {
                "tilesDirFreeBytes": disk_usage.free,
                "tilesDirTotalBytes": disk_usage.total,
            },
            "toolchain": toolchain,
            "files": scanned_files,
        }

        logMessage(
            f"预检查完成: jobType={job_type}, matched={len(matched_files)}, warnings={len(warnings)}, errors={len(errors)}",
            "INFO",
        )
        return jsonify(response)
    except Exception as exc:
        logMessage(f"预检查失败: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500

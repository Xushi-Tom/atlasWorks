#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import os
import subprocess
import hashlib
import ipaddress
import tempfile
from datetime import datetime
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from flask import jsonify, request, send_file

from config import config
from pagination import paginate_items, parse_pagination_args
from utils import formatFileSize, logMessage


_bandInfoCache = {}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for item in value]
    return [value]


def isHttpSource(value):
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def hasHttpSourcesInPatterns(file_patterns):
    for pattern in _as_list(file_patterns):
        if isHttpSource(pattern):
            return True
    return False


def _sanitize_download_name(name):
    invalid_chars = '<>:"/\\|?*'
    cleaned = "".join("_" if ch in invalid_chars or ord(ch) < 32 else ch for ch in str(name or "").strip())
    return cleaned.strip().strip(".") or "remote_source"


def _parse_host_aliases(raw_text):
    alias_mapping = {}
    for segment in str(raw_text or "").split(","):
        item = segment.strip()
        if not item or "=" not in item:
            continue
        source_host, target_host = item.split("=", 1)
        source = source_host.strip().lower()
        target = target_host.strip()
        if source and target:
            alias_mapping[source] = target
    return alias_mapping


def _replace_url_host(url, new_host):
    parsed = urlparse(url)
    if not parsed.netloc:
        return None
    host_text = str(new_host or "").strip()
    if not host_text:
        return None
    host_part = host_text
    if ":" in host_part and not host_part.startswith("["):
        host_part = f"[{host_part}]"
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo = f"{userinfo}:{parsed.password}"
        userinfo = f"{userinfo}@"
    netloc = f"{userinfo}{host_part}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return parsed._replace(netloc=netloc).geturl()


def _is_private_or_loopback_host(host_value):
    try:
        ip_obj = ipaddress.ip_address(str(host_value or "").strip())
        return ip_obj.is_private or ip_obj.is_loopback
    except ValueError:
        return False


def _build_download_url_candidates(url):
    parsed = urlparse(url)
    host = str(parsed.hostname or "").strip()
    if not host:
        return [url]

    candidates = [url]
    host_key = host.lower()

    alias_mapping = _parse_host_aliases(config.get("remoteSourceHostAliases"))
    alias_target = alias_mapping.get(host_key)
    if alias_target:
        aliased_url = _replace_url_host(url, alias_target)
        if aliased_url and aliased_url not in candidates:
            candidates.append(aliased_url)

    docker_fallback_enabled = bool(config.get("remoteSourceDockerHostFallback", True))
    docker_fallback_host = str(config.get("remoteSourceDockerHostFallbackHost") or "host.docker.internal").strip()
    should_try_docker_fallback = host_key in {"localhost", "127.0.0.1", "::1"} or _is_private_or_loopback_host(host)
    if docker_fallback_enabled and docker_fallback_host and should_try_docker_fallback:
        docker_fallback_url = _replace_url_host(url, docker_fallback_host)
        if docker_fallback_url and docker_fallback_url not in candidates:
            candidates.append(docker_fallback_url)

    return candidates


def _download_remote_source(url, data_source_dir):
    url = str(url or "").strip()
    if not isHttpSource(url):
        return None

    date_folder_name = datetime.now().strftime("%Y%m%d")
    date_folder_path = os.path.join(data_source_dir, date_folder_name)
    os.makedirs(date_folder_path, exist_ok=True)

    parsed_url = urlparse(url)
    raw_name = unquote(os.path.basename(parsed_url.path or ""))
    safe_name = _sanitize_download_name(raw_name or "remote_source")
    stem, ext = os.path.splitext(safe_name)
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    final_name = f"{stem}_{url_hash}{ext}" if ext else f"{stem}_{url_hash}"
    target_path = os.path.join(date_folder_path, final_name)

    if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
        relative_path = os.path.relpath(target_path, data_source_dir)
        return relative_path.replace("\\", "/")

    timeout_seconds = normalizeInt(config.get("remoteSourceTimeoutSeconds"), 45, 5, 900)
    retry_count = normalizeInt(config.get("remoteSourceRetryCount"), 1, 0, 10)
    candidate_urls = _build_download_url_candidates(url)
    attempt_errors = []

    for candidate_url in candidate_urls:
        for attempt_index in range(retry_count + 1):
            request_obj = Request(candidate_url, headers={"User-Agent": "AtlasWorks/2.0"})
            try:
                with urlopen(request_obj, timeout=timeout_seconds) as response:
                    with open(target_path, "wb") as target_file:
                        while True:
                            chunk = response.read(1024 * 256)
                            if not chunk:
                                break
                            target_file.write(chunk)
                if os.path.getsize(target_path) <= 0:
                    raise RuntimeError("远程文件下载后为空")

                relative_path = os.path.relpath(target_path, data_source_dir)
                normalized_relative_path = relative_path.replace("\\", "/")
                if candidate_url != url:
                    logMessage(f"远程数据源地址回退成功: {url} -> {candidate_url}", "INFO")
                logMessage(f"远程数据源下载成功: {candidate_url} -> {normalized_relative_path}", "INFO")
                return normalized_relative_path
            except Exception as exc:
                attempt_errors.append(f"{candidate_url} [第{attempt_index + 1}次]: {exc}")
                try:
                    if os.path.exists(target_path):
                        os.remove(target_path)
                except OSError:
                    pass

    details = "; ".join(attempt_errors) if attempt_errors else "未知错误"
    logMessage(f"远程数据源下载失败: {url} - {details}", "WARNING")
    return None


def _download_remote_source_to_temp(url):
    url = str(url or "").strip()
    if not isHttpSource(url):
        return None

    parsed_url = urlparse(url)
    raw_name = unquote(os.path.basename(parsed_url.path or ""))
    safe_name = _sanitize_download_name(raw_name or "remote_source")
    stem, ext = os.path.splitext(safe_name)
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    final_name = f"{stem}_{url_hash}{ext}" if ext else f"{stem}_{url_hash}"

    temp_dir = tempfile.mkdtemp(prefix="atlasworks-remote-info-")
    temp_path = os.path.join(temp_dir, final_name)

    timeout_seconds = normalizeInt(config.get("remoteSourceTimeoutSeconds"), 45, 5, 900)
    retry_count = normalizeInt(config.get("remoteSourceRetryCount"), 1, 0, 10)
    candidate_urls = _build_download_url_candidates(url)
    attempt_errors = []

    for candidate_url in candidate_urls:
        for attempt_index in range(retry_count + 1):
            request_obj = Request(candidate_url, headers={"User-Agent": "AtlasWorks/2.0"})
            try:
                with urlopen(request_obj, timeout=timeout_seconds) as response:
                    with open(temp_path, "wb") as target_file:
                        while True:
                            chunk = response.read(1024 * 256)
                            if not chunk:
                                break
                            target_file.write(chunk)
                if os.path.getsize(temp_path) <= 0:
                    raise RuntimeError("远程文件下载后为空")
                if candidate_url != url:
                    logMessage(f"远程详情地址回退成功: {url} -> {candidate_url}", "INFO")
                return temp_path
            except Exception as exc:
                attempt_errors.append(f"{candidate_url} [第{attempt_index + 1}次]: {exc}")
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except OSError:
                    pass

    details = "; ".join(attempt_errors) if attempt_errors else "未知错误"
    logMessage(f"远程详情下载失败: {url} - {details}", "WARNING")
    try:
        os.rmdir(temp_dir)
    except OSError:
        pass
    return None


def normalizeInt(value, defaultValue, minValue=None, maxValue=None):
    try:
        result = int(value)
    except Exception:
        result = defaultValue
    if minValue is not None:
        result = max(minValue, result)
    if maxValue is not None:
        result = min(maxValue, result)
    return result


def _run_command(command, timeout=30):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {"success": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}
    except Exception as exc:
        return {"success": False, "stdout": "", "stderr": str(exc)}


def _extract_bounds_from_json(info):
    extent = info.get("wgs84Extent", {})
    coordinates = extent.get("coordinates") or []
    if not coordinates:
        return None
    ring = coordinates[0]
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


def _extract_projection_summary(info):
    coordinate_system = info.get("coordinateSystem", {})
    wkt = coordinate_system.get("wkt") or ""
    if not wkt:
        return ""
    return wkt.split(",")[0][:100]


def _extract_data_name_from_source(source_path, fallback_name):
    source_text = str(source_path or "").strip()
    if source_text:
        parsed = urlparse(source_text)
        if parsed.scheme in {"http", "https"}:
            remote_name = unquote(os.path.basename(parsed.path or ""))
            if remote_name:
                stem, _ = os.path.splitext(remote_name)
                return stem or remote_name
    fallback_text = str(fallback_name or "").strip()
    if not fallback_text:
        return ""
    stem, _ = os.path.splitext(fallback_text)
    return stem or fallback_text


def _extract_epsg_code(info):
    coordinate_system = info.get("coordinateSystem", {})
    if not isinstance(coordinate_system, dict):
        return None
    cs_id = coordinate_system.get("id", {})
    if isinstance(cs_id, dict):
        authority = str(cs_id.get("authority") or "").strip().upper()
        code = cs_id.get("code")
        if authority == "EPSG" and code is not None:
            return code

    wkt = coordinate_system.get("wkt") or ""
    if not wkt:
        return None
    marker = 'ID["EPSG",'
    marker_index = wkt.find(marker)
    if marker_index < 0:
        return None
    start_index = marker_index + len(marker)
    end_index = wkt.find("]", start_index)
    if end_index < 0:
        return None
    raw_code = wkt[start_index:end_index].replace('"', "").strip()
    try:
        return int(raw_code)
    except Exception:
        return raw_code or None


def _build_corner_coordinates(bounds):
    if not isinstance(bounds, dict):
        return None
    west = bounds.get("west")
    east = bounds.get("east")
    south = bounds.get("south")
    north = bounds.get("north")
    if None in (west, east, south, north):
        return None
    return {
        "leftTop": {"longitude": west, "latitude": north},
        "rightTop": {"longitude": east, "latitude": north},
        "leftBottom": {"longitude": west, "latitude": south},
        "rightBottom": {"longitude": east, "latitude": south},
    }


def _build_center_coordinate(bounds):
    if not isinstance(bounds, dict):
        return None
    west = bounds.get("west")
    east = bounds.get("east")
    south = bounds.get("south")
    north = bounds.get("north")
    if None in (west, east, south, north):
        return None
    return {
        "longitude": (west + east) / 2.0,
        "latitude": (south + north) / 2.0,
    }


def _build_geometry_wkt(bounds):
    if not isinstance(bounds, dict):
        return None
    west = bounds.get("west")
    east = bounds.get("east")
    south = bounds.get("south")
    north = bounds.get("north")
    if None in (west, east, south, north):
        return None
    return (
        f"POLYGON(({west} {north}, {east} {north}, {east} {south}, "
        f"{west} {south}, {west} {north}))"
    )


def generateSmartRecommendations(fileSizeGb, tileType="map", userMinZoom=None, userMaxZoom=None, cpuCount=4, memoryTotalGb=8):
    try:
        recommendations = {}
        if tileType == "terrain":
            if fileSizeGb < 0.5:
                recommendations["maxZoom"] = 16
                recommendations["minZoom"] = 0
                recommendations["processes"] = min(cpuCount // 2, 4)
                recommendations["maxMemory"] = "4g"
            elif fileSizeGb < 2:
                recommendations["maxZoom"] = 15
                recommendations["minZoom"] = 0
                recommendations["processes"] = min(cpuCount // 2, 6)
                recommendations["maxMemory"] = "6g"
            elif fileSizeGb < 8:
                recommendations["maxZoom"] = 14
                recommendations["minZoom"] = 0
                recommendations["processes"] = min(cpuCount // 2, 8)
                recommendations["maxMemory"] = "8g"
            else:
                recommendations["maxZoom"] = 13
                recommendations["minZoom"] = 0
                recommendations["processes"] = min(cpuCount // 2, 10)
                recommendations["maxMemory"] = "12g"

            recommendations["tileFormat"] = "terrain"
            recommendations["quality"] = 100
            recommendations["compression"] = True
            recommendations["decompress"] = True
            recommendations["autoZoom"] = True
            recommendations["zoomStrategy"] = "conservative"

            if memoryTotalGb < 8:
                recommendations["maxMemory"] = "4g"
                recommendations["processes"] = min(recommendations["processes"], 2)
            elif memoryTotalGb < 16:
                recommendations["maxMemory"] = "6g"
                recommendations["processes"] = min(recommendations["processes"], 4)
            elif memoryTotalGb >= 32:
                recommendations["maxMemory"] = "16g"
                recommendations["processes"] = min(recommendations["processes"], 12)
        else:
            if fileSizeGb < 1:
                recommendations["maxZoom"] = 18
                recommendations["minZoom"] = 0
                recommendations["tileFormat"] = "png"
                recommendations["quality"] = 90
                recommendations["processes"] = min(cpuCount - 1, 6)
                recommendations["maxMemory"] = max(2048, int(memoryTotalGb * 1024 * 0.3))
            elif fileSizeGb < 5:
                recommendations["maxZoom"] = 16
                recommendations["minZoom"] = 0
                recommendations["tileFormat"] = "webp"
                recommendations["quality"] = 85
                recommendations["processes"] = min(cpuCount - 1, 8)
                recommendations["maxMemory"] = max(4096, int(memoryTotalGb * 1024 * 0.4))
            elif fileSizeGb < 20:
                recommendations["maxZoom"] = 15
                recommendations["minZoom"] = 0
                recommendations["tileFormat"] = "webp"
                recommendations["quality"] = 80
                recommendations["processes"] = min(cpuCount - 1, 10)
                recommendations["maxMemory"] = max(6144, int(memoryTotalGb * 1024 * 0.5))
            else:
                recommendations["maxZoom"] = 14
                recommendations["minZoom"] = 0
                recommendations["tileFormat"] = "webp"
                recommendations["quality"] = 75
                recommendations["processes"] = min(cpuCount - 1, 12)
                recommendations["maxMemory"] = max(8192, int(memoryTotalGb * 1024 * 0.6))

            recommendations["resampling"] = "bilinear"
            recommendations["autoZoom"] = True
            recommendations["zoomStrategy"] = "conservative"
            recommendations["optimizeFile"] = True
            recommendations["createOverview"] = fileSizeGb > 2
            recommendations["useOptimizedMode"] = True

            if memoryTotalGb < 8:
                recommendations["processes"] = min(recommendations["processes"], 4)
                recommendations["maxMemory"] = min(recommendations["maxMemory"], 2048)
            elif memoryTotalGb < 16:
                recommendations["processes"] = min(recommendations["processes"], 6)
                recommendations["maxMemory"] = min(recommendations["maxMemory"], 4096)

        if userMinZoom is not None:
            recommendations["minZoom"] = userMinZoom
        if userMaxZoom is not None:
            recommendations["maxZoom"] = userMaxZoom
        recommendations["processes"] = max(1, min(recommendations["processes"], cpuCount))
        return recommendations
    except Exception as exc:
        logMessage(f"生成推荐配置失败: {exc}", "ERROR")
        return None


def getSourceBandInfo(filePath):
    try:
        result = _run_command(["gdalinfo", "-json", filePath], timeout=15)
        if result["success"]:
            info = json.loads(result["stdout"])
            bands = info.get("bands", [])
            return {
                "bandCount": len(bands),
                "hasAlpha": any(band.get("colorInterpretation") == "Alpha" for band in bands),
            }
    except Exception:
        pass
    return {"bandCount": 3, "hasAlpha": False}


def getSourceBandInfoCached(filePath):
    if filePath not in _bandInfoCache:
        _bandInfoCache[filePath] = getSourceBandInfo(filePath)
    return _bandInfoCache[filePath]


def getFileInfo(filePath, relativePath=None, sourcePath=None, displayName=None, dataSourceType="local"):
    try:
        file_info = {}
        if os.path.exists(filePath):
            stat = os.stat(filePath)
            source_path_text = str(sourcePath or relativePath or "").replace("\\", "/").strip("/")
            normalized_relative_path = source_path_text or os.path.basename(filePath)
            file_name = str(displayName or "").strip() or os.path.basename(filePath)
            file_ext = os.path.splitext(filePath)[1].lower()
            data_name = _extract_data_name_from_source(sourcePath or relativePath, file_name)
            file_info.update({
                "name": file_name,
                "path": normalized_relative_path or file_name,
                "fullPath": filePath,
                "size": stat.st_size,
                "sizeFormatted": formatFileSize(stat.st_size),
                "lastModified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "modifiedTime": stat.st_mtime,
                "type": "file",
                "extension": file_ext,
            })
            file_info["format"] = file_ext.lstrip(".") or "file"
            file_info["data_name"] = data_name
            file_info["data_path"] = file_info["path"]
            file_info["data_size"] = file_info["size"]
            file_info["data_format"] = file_info["format"]
            file_info["data_source"] = dataSourceType
            file_info["id"] = None
            file_info["satelite_no"] = None
            file_info["gather_time"] = None
            file_info["thumb_url"] = None
            file_info["processing_level"] = None
            file_info["product_no"] = None
            if file_ext in [".tif", ".tiff", ".geotiff"]:
                result = _run_command(["gdalinfo", "-json", filePath], timeout=30)
                if result["success"]:
                    info = json.loads(result["stdout"])
                    size = info.get("size", [0, 0])
                    geo_transform = info.get("geoTransform", [])
                    bands = info.get("bands", [])
                    bounds = _extract_bounds_from_json(info)
                    root_metadata = info.get("metadata", {}) if isinstance(info.get("metadata", {}), dict) else {}
                    image_structure = root_metadata.get("IMAGE_STRUCTURE", {}) if isinstance(root_metadata.get("IMAGE_STRUCTURE", {}), dict) else {}
                    nodata_values = sorted({
                        band.get("noDataValue")
                        for band in bands
                        if isinstance(band, dict) and band.get("noDataValue") is not None
                    })
                    data_types = sorted({
                        band.get("type", "unknown")
                        for band in bands
                        if isinstance(band, dict)
                    })
                    metadata = {
                        "driver": info.get("driverShortName") or "",
                        "driverLongName": info.get("driverLongName") or "",
                        "description": info.get("description") or "",
                        "files": info.get("files", []),
                        "rasterSize": {
                            "width": size[0] if len(size) > 0 else 0,
                            "height": size[1] if len(size) > 1 else 0,
                        },
                        "pixelSize": {
                            "x": abs(geo_transform[1]) if len(geo_transform) >= 2 else None,
                            "y": abs(geo_transform[5]) if len(geo_transform) >= 6 else None,
                        },
                        "bandCount": len(bands),
                        "srs": _extract_projection_summary(info),
                        "coordinateSystem": info.get("coordinateSystem", {}) if isinstance(info.get("coordinateSystem"), dict) else {},
                        "epsg": _extract_epsg_code(info),
                        "geoTransform": geo_transform,
                        "cornerCoordinates": info.get("cornerCoordinates", {}),
                        "wgs84Extent": info.get("wgs84Extent", {}),
                        "stac": info.get("stac", {}),
                        "metadataDomains": root_metadata,
                        "bands": bands,
                    }
                    if data_types:
                        metadata["dataType"] = ",".join(data_types)
                        metadata["bandDataTypes"] = data_types
                        file_info["data_type"] = metadata["dataType"]
                    else:
                        file_info["data_type"] = "raster"
                    if nodata_values:
                        metadata["nodata"] = nodata_values[0] if len(nodata_values) == 1 else nodata_values
                    if image_structure.get("COMPRESSION"):
                        metadata["compression"] = image_structure.get("COMPRESSION")

                    pixel_size = metadata.get("pixelSize", {})
                    file_info["resolution"] = pixel_size.get("x") or pixel_size.get("y")
                    file_info["coordinate_system"] = metadata.get("srs") or ""
                    if bounds:
                        metadata["bounds"] = bounds
                        file_info["geoBounds"] = bounds
                        corners = _build_corner_coordinates(bounds)
                        center = _build_center_coordinate(bounds)
                        file_info["center_longitude"] = center.get("longitude") if center else None
                        file_info["center_latitude"] = center.get("latitude") if center else None
                        file_info["geometry"] = _build_geometry_wkt(bounds)
                        if corners:
                            file_info["left_top_longitude"] = corners["leftTop"]["longitude"]
                            file_info["left_top_latitude"] = corners["leftTop"]["latitude"]
                            file_info["right_top_longitude"] = corners["rightTop"]["longitude"]
                            file_info["right_top_latitude"] = corners["rightTop"]["latitude"]
                            file_info["left_bottom_longitude"] = corners["leftBottom"]["longitude"]
                            file_info["left_bottom_latitude"] = corners["leftBottom"]["latitude"]
                            file_info["right_bottom_longitude"] = corners["rightBottom"]["longitude"]
                            file_info["right_bottom_latitude"] = corners["rightBottom"]["latitude"]
                            metadata["corners"] = corners
                        if center:
                            metadata["center"] = center
                    file_info["metadata"] = metadata
                else:
                    file_info["data_type"] = "raster"
            else:
                file_info["data_type"] = file_info["format"]
        return file_info
    except Exception as exc:
        logMessage(f"获取文件信息失败 {filePath}: {exc}", "ERROR")
        return {"error": str(exc)}


def detectOptimalZoomLevels(filePath):
    """检测基于文件分辨率的最佳缩放级别。"""
    try:
        info = getFileInfo(filePath)
        if "error" in info:
            return None

        metadata = info.get("metadata", {})
        raster_size = metadata.get("rasterSize", {}) if isinstance(metadata, dict) else {}
        width = raster_size.get("width", 0)
        height = raster_size.get("height", 0)
        if width <= 0 or height <= 0:
            return None

        max_dim = max(width, height)
        optimal_max_zoom = min(18, int(math.log2(max_dim / 256)) + 1)
        return {
            "minZoom": 0,
            "maxZoom": optimal_max_zoom,
            "reason": f"基于图像分辨率 {width}x{height} 计算",
        }
    except Exception as exc:
        logMessage(f"检测最佳级别失败: {exc}", "ERROR")
        return None


def listDataSources(subpath=""):
    try:
        logMessage(f"收到数据源列表请求，子路径: '{subpath}'", "INFO")
        datasource_dir = config["dataSourceDir"]
        full_path = os.path.join(datasource_dir, subpath) if subpath else datasource_dir
        full_path = os.path.abspath(full_path)
        datasource_dir = os.path.abspath(datasource_dir)
        if not full_path.startswith(datasource_dir):
            return jsonify({"error": "路径不允许访问"}), 403
        if not os.path.exists(full_path):
            return jsonify({"error": "路径不存在"}), 404
        if not os.path.isdir(full_path):
            return jsonify({"error": "路径不是目录"}), 400

        search_bounds = None
        page, page_size = parse_pagination_args(request.args, default_page_size=100, max_page_size=500)
        bounds_param = request.args.get("bounds")
        if bounds_param:
            try:
                bounds_data = json.loads(bounds_param)
                search_bounds = bounds_data if isinstance(bounds_data, list) else [bounds_data]
            except Exception:
                return jsonify({"error": "地理范围参数格式错误"}), 400

        directories = []
        datasources = []
        archive_extensions = {".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z", ".tar.gz", ".tar.bz2", ".tar.xz", ".tbz2", ".txz"}
        try:
            with os.scandir(full_path) as entries:
                for entry in entries:
                    item = entry.name
                    item_path = entry.path
                    if entry.is_dir(follow_symlinks=False):
                        directories.append({
                            "name": item,
                            "type": "directory",
                            "path": os.path.join(subpath, item) if subpath else item,
                        })
                        continue

                    if not entry.is_file(follow_symlinks=False):
                        continue

                    item_lower = item.lower()
                    file_ext = os.path.splitext(item)[1].lower()
                    is_archive = any(item_lower.endswith(ext) for ext in archive_extensions)
                    if file_ext not in config["supportedFormats"] and not is_archive:
                        continue

                    stat_info = entry.stat(follow_symlinks=False)
                    file_info = {
                        "name": item,
                        "type": "file",
                        "size": stat_info.st_size,
                        "sizeFormatted": formatFileSize(stat_info.st_size),
                        "extension": file_ext,
                        "isArchive": is_archive,
                        "path": os.path.join(subpath, item) if subpath else item,
                        "modifiedTime": stat_info.st_mtime,
                    }
                    if search_bounds and file_ext in config["supportedFormats"]:
                        detailed_info = getFileInfo(item_path)
                        if "geoBounds" in detailed_info:
                            file_info["geoBounds"] = detailed_info["geoBounds"]
                    datasources.append(file_info)
        except PermissionError:
            return jsonify({"error": "权限不足"}), 403

        if search_bounds:
            filtered = []
            for item in datasources:
                bounds = item.get("geoBounds")
                if not bounds:
                    continue
                for area in search_bounds:
                    west = area.get("west", -180)
                    south = area.get("south", -90)
                    east = area.get("east", 180)
                    north = area.get("north", 90)
                    if bounds["east"] >= west and bounds["west"] <= east and bounds["north"] >= south and bounds["south"] <= north:
                        filtered.append(item)
                        break
            datasources = filtered

        directories.sort(key=lambda item: str(item.get("name", "")).lower())
        datasources.sort(key=lambda item: str(item.get("name", "")).lower())

        parent_path = None
        if subpath:
            parts = subpath.split("/")
            parent_path = "/".join(parts[:-1]) if len(parts) > 1 else ""

        combined_entries = [{"kind": "directory", "payload": item} for item in directories]
        combined_entries.extend({"kind": "file", "payload": item} for item in datasources)
        paged_entries, pagination = paginate_items(combined_entries, page, page_size)
        paged_directories = [item["payload"] for item in paged_entries if item["kind"] == "directory"]
        paged_datasources = [item["payload"] for item in paged_entries if item["kind"] == "file"]

        response = {
            "currentPath": subpath,
            "parentPath": parent_path,
            "directories": paged_directories,
            "datasources": paged_datasources,
            "totalDirectories": len(directories),
            "totalFiles": len(datasources),
            "totalEntries": len(combined_entries),
            "count": pagination["count"],
            "page": pagination["page"],
            "pageSize": pagination["pageSize"],
            "totalPages": pagination["totalPages"],
            "hasPrev": pagination["hasPrev"],
            "hasNext": pagination["hasNext"],
        }
        if search_bounds:
            response["filterInfo"] = {
                "boundsFilter": search_bounds,
                "filteredCount": len(datasources),
                "message": f"已根据地理范围筛选，找到 {len(datasources)} 个匹配文件",
            }
        return jsonify(response)
    except Exception as exc:
        logMessage(f"数据源列表请求处理失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def getDataSourceWorkspaceInfo():
    try:
        return jsonify({
            "success": True,
            "workspace": {
                "containerPath": config["dataSourceDir"],
                "hostPathHint": config.get("dataSourceHostDir") or "",
                "supportedFormats": config.get("supportedFormats", []),
                "mountNote": "hostPathHint 为 dockerCompose 中配置的宿主机相对路径提示",
            },
        })
    except Exception as exc:
        logMessage(f"获取数据源工作区信息失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def getDataSourceInfo(filename):
    remote_temp_file = None
    try:
        logMessage(f"收到文件信息请求: {filename}", "INFO")
        source_text = str(filename or "").strip()
        is_remote_http = isHttpSource(source_text)
        normalized_filename = source_text.replace("\\", "/").strip("/")
        data_source_dir = os.path.abspath(config["dataSourceDir"])
        source_path_for_response = normalized_filename
        display_name = os.path.basename(normalized_filename) if normalized_filename else ""
        data_source_type = "remote-http" if is_remote_http else "local"

        if is_remote_http:
            remote_temp_file = _download_remote_source_to_temp(source_text)
            if not remote_temp_file:
                return jsonify({"error": "远程文件下载失败"}), 404
            file_path = remote_temp_file
            normalized_filename = source_text
        else:
            file_path = os.path.abspath(os.path.join(data_source_dir, normalized_filename))
            if os.path.commonpath([data_source_dir, file_path]) != data_source_dir:
                return jsonify({"error": "路径不允许访问"}), 403
            if not os.path.exists(file_path):
                return jsonify({"error": "文件不存在"}), 404

        extension = os.path.splitext(file_path)[1].lower()
        if extension in {".png", ".jpg", ".jpeg"}:
            stat_info = os.stat(file_path)
            image_payload = {
                "name": os.path.basename(file_path),
                "path": normalized_filename,
                "fullPath": file_path,
                "format": extension.lstrip(".") or "file",
                "size": stat_info.st_size,
                "sizeFormatted": formatFileSize(stat_info.st_size),
                "lastModified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                "modifiedTime": stat_info.st_mtime,
                "extension": extension,
                "metadata": {
                    "previewType": "image" if not is_remote_http else "remote-image",
                },
            }
            if not is_remote_http:
                image_payload["previewUrl"] = f"/api/datasources/raw/{normalized_filename}"
            return jsonify(image_payload)
        if extension not in config.get("supportedFormats", []):
            stat_info = os.stat(file_path)
            return jsonify({
                "name": os.path.basename(file_path),
                "path": normalized_filename,
                "fullPath": file_path,
                "format": extension.lstrip(".") or "file",
                "size": stat_info.st_size,
                "sizeFormatted": formatFileSize(stat_info.st_size),
                "lastModified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                "modifiedTime": stat_info.st_mtime,
                "metadata": {},
            })

        file_info = getFileInfo(file_path, normalized_filename)
        if "error" not in file_info:
            file_size_gb = file_info["size"] / (1024**3)
            tile_type = request.args.get("tileType")
            user_min_zoom = request.args.get("minZoom")
            user_max_zoom = request.args.get("maxZoom")
            user_min_zoom = int(user_min_zoom) if user_min_zoom else None
            user_max_zoom = int(user_max_zoom) if user_max_zoom else None
            try:
                import psutil

                cpu_count = psutil.cpu_count() or 4
                memory_total_gb = psutil.virtual_memory().total / (1024**3)
            except Exception:
                cpu_count = 4
                memory_total_gb = 8

            recommendations = generateSmartRecommendations(
                file_size_gb,
                tile_type or "map",
                user_min_zoom,
                user_max_zoom,
                cpu_count,
                memory_total_gb,
            )
            if recommendations:
                file_info["recommendations"] = recommendations
        return jsonify(file_info)
    except Exception as exc:
        logMessage(f"文件信息请求处理失败: {filename}, 错误: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500
    finally:
        if remote_temp_file:
            try:
                if os.path.exists(remote_temp_file):
                    os.remove(remote_temp_file)
                temp_dir = os.path.dirname(remote_temp_file)
                if temp_dir and os.path.isdir(temp_dir):
                    os.rmdir(temp_dir)
            except OSError:
                pass


def serveDataSourceFile(filename):
    try:
        normalized_filename = str(filename or "").replace("\\", "/").strip("/")
        data_source_dir = os.path.abspath(config["dataSourceDir"])
        file_path = os.path.abspath(os.path.join(data_source_dir, normalized_filename))
        if os.path.commonpath([data_source_dir, file_path]) != data_source_dir:
            return jsonify({"error": "路径不允许访问"}), 403
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            return jsonify({"error": "文件不存在"}), 404

        extension = os.path.splitext(file_path)[1].lower()
        if extension not in {".png", ".jpg", ".jpeg"}:
            return jsonify({"error": "仅支持图片预览"}), 400
        return send_file(file_path, conditional=True)
    except Exception as exc:
        logMessage(f"数据源文件预览失败: {filename}, 错误: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def recommendConfig():
    try:
        data = request.get_json(silent=True) or {}
        source_file = data.get("sourceFile")
        if not source_file:
            return jsonify({"error": "缺少参数: sourceFile"}), 400

        file_path = os.path.join(config["dataSourceDir"], source_file)
        if not os.path.exists(file_path):
            return jsonify({"error": "源文件不存在"}), 404

        file_size_gb = os.path.getsize(file_path) / (1024 ** 3)
        try:
            import psutil

            cpu_count = psutil.cpu_count() or 4
            memory_total_gb = psutil.virtual_memory().total / (1024 ** 3)
        except Exception:
            cpu_count = 4
            memory_total_gb = 8

        tile_type = data.get("tileType", "map")
        user_min_zoom = data.get("minZoom")
        user_max_zoom = data.get("maxZoom")
        recommendations = generateSmartRecommendations(
            file_size_gb,
            tile_type,
            user_min_zoom,
            user_max_zoom,
            cpu_count,
            memory_total_gb,
        )

        return jsonify(
            {
                "success": True,
                "fileSize": file_size_gb,
                "systemInfo": {
                    "cpuCount": cpu_count,
                    "memoryTotalGb": memory_total_gb,
                },
                "recommendations": recommendations,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def resolveDataSourceFiles():
    try:
        data = request.get_json(silent=True) or {}
        folder_paths = data.get("folderPaths", [])
        file_patterns = data.get("filePatterns", [])
        max_files = normalizeInt(data.get("maxFiles"), 200, 1, 2000)

        matched_files = findTifFilesInFolders(folder_paths, file_patterns)
        total_matched = len(matched_files)
        files_for_summary = matched_files[:max_files]
        band_details = []
        valid_band_counts = []
        for relative_path in files_for_summary:
            full_path = os.path.join(config["dataSourceDir"], relative_path)
            band_info = getSourceBandInfoCached(full_path)
            band_count = band_info.get("bandCount")
            has_alpha = bool(band_info.get("hasAlpha", False))
            band_details.append({"path": relative_path, "bandCount": band_count, "hasAlpha": has_alpha})
            if isinstance(band_count, int) and band_count > 0:
                valid_band_counts.append(band_count)

        band_summary = None
        if valid_band_counts:
            min_band_count = min(valid_band_counts)
            max_band_count = max(valid_band_counts)
            band_summary = {
                "minBandCount": min_band_count,
                "maxBandCount": max_band_count,
                "commonBandCount": min_band_count,
                "allSame": min_band_count == max_band_count,
                "validFileCount": len(valid_band_counts),
            }

        return jsonify({
            "success": True,
            "folderPaths": folder_paths,
            "filePatterns": file_patterns,
            "totalMatched": total_matched,
            "returnedCount": len(files_for_summary),
            "truncated": total_matched > max_files,
            "files": files_for_summary,
            "bandDetails": band_details,
            "bandSummary": band_summary,
            "message": f"已解析 {total_matched} 个匹配文件",
        })
    except Exception as exc:
        logMessage(f"解析数据源文件失败: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def findSourceFilesInFolders(folderPaths, filePatterns=None, allowedExtensions=None):
    try:
        found_files = []
        found_set = set()
        data_source_dir = config["dataSourceDir"]
        folderPaths = [str(item).strip() for item in _as_list(folderPaths) if str(item).strip()]
        normalized_extensions = {
            str(item or "").strip().lower()
            for item in _as_list(allowedExtensions or [])
            if str(item or "").strip()
        }

        def is_allowed_path(path_value):
            lower_path = str(path_value or "").lower()
            if not normalized_extensions:
                return True
            return any(lower_path.endswith(extension) for extension in normalized_extensions)

        if not folderPaths:
            search_paths = [data_source_dir]
            relative_bases = [""]
        else:
            search_paths = []
            relative_bases = []
            for folder_path in folderPaths:
                full_path = os.path.join(data_source_dir, folder_path) if folder_path else data_source_dir
                if os.path.exists(full_path):
                    search_paths.append(full_path)
                    relative_bases.append(folder_path or "")
                else:
                    logMessage(f"输入目录不存在，已跳过: {folder_path}", "WARNING")

        if not filePatterns:
            if normalized_extensions:
                filePatterns = [f"*{extension}" for extension in sorted(normalized_extensions)]
            else:
                filePatterns = ["*"]
        filePatterns = [str(pattern).strip() for pattern in _as_list(filePatterns) if str(pattern).strip()]
        remote_patterns = [pattern for pattern in filePatterns if isHttpSource(pattern)]
        local_patterns = [pattern for pattern in filePatterns if not isHttpSource(pattern)]

        txt_files = [pattern for pattern in local_patterns if str(pattern).lower().endswith(".txt")]
        glob_patterns = [pattern for pattern in local_patterns if not str(pattern).lower().endswith(".txt")]

        def add_relative_path(relative_path):
            normalized = os.path.normpath(relative_path).replace("\\", "/")
            if normalized not in found_set:
                found_set.add(normalized)
                found_files.append(normalized)

        def resolve_candidate_relative_paths(relative_line, txt_file_path=None):
            candidates = [os.path.normpath(relative_line)]
            if txt_file_path:
                txt_parent_rel = os.path.relpath(os.path.dirname(txt_file_path), data_source_dir)
                if txt_parent_rel != ".":
                    candidates.append(os.path.normpath(os.path.join(txt_parent_rel, relative_line)))
            for relative_base in relative_bases:
                if relative_base:
                    candidates.append(os.path.normpath(os.path.join(relative_base, relative_line)))
            deduped = []
            seen = set()
            for candidate in candidates:
                if candidate not in seen:
                    seen.add(candidate)
                    deduped.append(candidate)
            return deduped

        for remote_url in remote_patterns:
            downloaded_relative_path = _download_remote_source(remote_url, data_source_dir)
            if not downloaded_relative_path:
                continue
            lower_downloaded = downloaded_relative_path.lower()
            if lower_downloaded.endswith(".txt"):
                txt_files.append(downloaded_relative_path)
            elif is_allowed_path(downloaded_relative_path):
                add_relative_path(downloaded_relative_path)
            else:
                logMessage(f"远程来源扩展名不在允许列表内，已忽略: {remote_url}", "WARNING")

        for txt_file in txt_files:
            txt_path_candidates = []
            if os.path.isabs(txt_file):
                txt_path_candidates.append(txt_file)
            else:
                txt_path_candidates.append(os.path.join(data_source_dir, txt_file))
                for relative_base in relative_bases:
                    if relative_base:
                        txt_path_candidates.append(os.path.join(data_source_dir, relative_base, txt_file))
            txt_file_path = next((candidate for candidate in txt_path_candidates if os.path.exists(candidate)), None)
            if txt_file_path is None:
                logMessage(f"未找到 txt 文件: {txt_file}，已尝试路径: {txt_path_candidates}", "WARNING")
                continue

            try:
                with open(txt_file_path, "r", encoding="utf-8") as file_handle:
                    lines = file_handle.readlines()
                for line_num, line in enumerate(lines, 1):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if isHttpSource(line):
                        downloaded_relative_path = _download_remote_source(line, data_source_dir)
                        if downloaded_relative_path and is_allowed_path(downloaded_relative_path):
                            add_relative_path(downloaded_relative_path)
                        elif downloaded_relative_path:
                            logMessage(f"txt 远程行下载后扩展名不在允许列表内，已忽略: {line}", "WARNING")
                        continue
                    if os.path.isabs(line):
                        if os.path.exists(line) and is_allowed_path(line):
                            relative_path = os.path.relpath(line, data_source_dir)
                            if not relative_path.startswith(".."):
                                add_relative_path(relative_path)
                        continue
                    file_found = False
                    for candidate_relative_path in resolve_candidate_relative_paths(line, txt_file_path):
                        full_path = os.path.join(data_source_dir, candidate_relative_path)
                        if os.path.exists(full_path) and is_allowed_path(full_path):
                            add_relative_path(candidate_relative_path)
                            file_found = True
                    if not file_found:
                        logMessage(f"txt 行未匹配到允许类型文件: {txt_file}:{line_num} -> {line}", "WARNING")
            except Exception as exc:
                logMessage(f"读取 txt 文件失败 {txt_file_path}: {exc}", "WARNING")

        for search_path in search_paths:
            for pattern in glob_patterns:
                normalized_pattern = str(pattern).strip() or "*.tif"
                recursive = "**" in normalized_pattern or "/" in normalized_pattern or "\\" in normalized_pattern
                pattern_path = os.path.join(search_path, normalized_pattern)
                try:
                    import glob

                    matches = glob.glob(pattern_path, recursive=recursive)
                    for match in matches:
                        if os.path.isfile(match) and is_allowed_path(match):
                            relative_path = os.path.relpath(match, data_source_dir)
                            add_relative_path(relative_path)
                except Exception as exc:
                    logMessage(f"模式匹配失败: {pattern_path} - {exc}", "WARNING")

        found_files.sort()
        return found_files
    except Exception as exc:
        logMessage(f"查找数据源文件失败: {exc}", "ERROR")
        return []


def findTifFilesInFolders(folderPaths, filePatterns=None):
    return findSourceFilesInFolders(
        folderPaths,
        filePatterns=filePatterns,
        allowedExtensions=[".tif", ".tiff"],
    )

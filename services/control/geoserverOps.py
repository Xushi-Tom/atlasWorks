#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import time
from urllib.parse import quote
from xml.sax.saxutils import escape
from xml.etree import ElementTree as ET

import requests
from flask import jsonify, request

from config import config
from utils import normalizeProjection, validateDataSourcePath, logMessage


GEOSERVER_TIMEOUT = 45
GEOSERVER_WAIT_TIMEOUT = 30
GEOSERVER_WAIT_INTERVAL = 1.0
GEOSERVER_METHODS = {"geoserver-wms", "geoserver-wmts"}
GEOSERVER_RASTER_EXTENSIONS = {".tif", ".tiff"}
GEOSERVER_WMTS_GRIDSET = "EPSG:900913"
GEOSERVER_CRS_ALIASES = {
    "EPSG:3857": "EPSG:3857",
    "3857": "EPSG:3857",
    "EPSG:4326": "EPSG:4326",
    "4326": "EPSG:4326",
    "EPSG:4490": "EPSG:4490",
    "4490": "EPSG:4490",
}


def _json_error(message, status_code=400):
    return jsonify({"success": False, "error": message}), status_code


def _safe_name(value, default_value="layer"):
    text = str(value or "").strip()
    if not text:
        text = default_value
    normalized = []
    for ch in text:
        if ch.isalnum() or ch in {"-", "_", "."}:
            normalized.append(ch)
        else:
            normalized.append("_")
    result = "".join(normalized).strip("._-")
    return result or default_value


def _normalize_crs(value, default_value="EPSG:3857"):
    normalized = normalizeProjection(value or default_value)
    return GEOSERVER_CRS_ALIASES.get(str(normalized).strip().upper(), normalized)


def _geoserver_public_base_url():
    explicit = str(config.get("geoserverPublicBaseUrl") or "").strip()
    if explicit:
        return explicit.rstrip("/")

    host = str(config.get("publicBaseHost") or config.get("publicBaseUrl") or "localhost").strip()
    if "://" in host:
        return host.rstrip("/")
    scheme = str(config.get("publicBaseScheme") or "http").strip() or "http"
    port = int(config.get("geoserverPublicBasePort") or 18083)
    return f"{scheme}://{host}:{port}/geoserver"


def _geoserver_rest_base_url():
    return str(config.get("geoserverBaseUrl") or "http://atlasworks-geoserver:8080/geoserver").rstrip("/")


def _geoserver_auth():
    return (
        str(config.get("geoserverUsername") or "admin"),
        str(config.get("geoserverPassword") or "geoserver"),
    )


def _geoserver_data_source_path(resolved_path):
    api_data_dir = os.path.abspath(str(config.get("dataSourceDir") or "/app/dataSource"))
    geoserver_data_dir = str(config.get("geoserverDataSourceDir") or "/opt/geoserver/data_dir/dataSource").rstrip("/\\")
    resolved_abs = os.path.abspath(str(resolved_path or ""))
    relative = os.path.relpath(resolved_abs, api_data_dir).replace("\\", "/")
    if relative.startswith("../"):
        raise ValueError("GeoServer 数据源路径超出数据源目录")
    if relative == ".":
        return geoserver_data_dir
    return f"{geoserver_data_dir}/{relative}"


def _geoserver_request(method, path, *, params=None, json_body=None, data=None, headers=None, expected_statuses=None):
    url = f"{_geoserver_rest_base_url()}{path}"
    request_headers = {"Accept": "application/json", **(headers or {})}
    response = requests.request(
        method=method.upper(),
        url=url,
        params=params,
        json=json_body,
        data=data,
        headers=request_headers,
        auth=_geoserver_auth(),
        timeout=GEOSERVER_TIMEOUT,
    )
    if expected_statuses and response.status_code not in expected_statuses:
        detail = response.text.strip() or f"HTTP {response.status_code}"
        raise RuntimeError(f"GeoServer 请求失败 {method.upper()} {path}: {detail}")
    return response


def _wait_until(checker, *, timeout=GEOSERVER_WAIT_TIMEOUT, interval=GEOSERVER_WAIT_INTERVAL, description="GeoServer resource"):
    deadline = time.time() + max(1, float(timeout))
    last_error = None
    while time.time() < deadline:
        try:
            result = checker()
            if result:
                return result
        except Exception as exc:
            last_error = exc
        time.sleep(max(0.1, float(interval)))
    if last_error:
        raise RuntimeError(f"{description} 等待超时: {last_error}")
    raise RuntimeError(f"{description} 等待超时")


def _coverage_exists(workspace, store_name, layer_name):
    response = _geoserver_request(
        "GET",
        f"/rest/workspaces/{quote(workspace)}/coveragestores/{quote(store_name)}/coverages/{quote(layer_name)}.json",
        expected_statuses={200, 404},
    )
    return response.status_code == 200


def _list_store_coverages(workspace, store_name):
    response = _geoserver_request(
        "GET",
        f"/rest/workspaces/{quote(workspace)}/coveragestores/{quote(store_name)}/coverages.json",
        expected_statuses={200, 404},
    )
    if response.status_code == 404:
        return []
    payload = response.json()
    if isinstance(payload, str):
        coverage_payload = [payload]
    elif isinstance(payload, list):
        coverage_payload = payload
    elif isinstance(payload, dict):
        coverages = payload.get("coverages", {})
        if isinstance(coverages, str):
            coverage_payload = [coverages]
        elif isinstance(coverages, list):
            coverage_payload = coverages
        elif isinstance(coverages, dict):
            coverage_payload = coverages.get("coverage", [])
        else:
            coverage_payload = []
    else:
        coverage_payload = []
    if isinstance(coverage_payload, (str, dict)):
        coverage_payload = [coverage_payload]
    coverage_names = []
    for item in coverage_payload:
        if isinstance(item, dict) and item.get("name"):
            coverage_names.append(_safe_name(item.get("name")))
        elif isinstance(item, str) and item.strip():
            coverage_names.append(_safe_name(item))
    return coverage_names


def _store_exists(workspace, store_name):
    response = _geoserver_request(
        "GET",
        f"/rest/workspaces/{quote(workspace)}/coveragestores/{quote(store_name)}.json",
        expected_statuses={200, 404},
    )
    return response.status_code == 200


def ensureWorkspace(name):
    workspace_name = _safe_name(name, "atlasworks")
    response = _geoserver_request(
        "GET",
        f"/rest/workspaces/{quote(workspace_name)}.json",
        expected_statuses={200, 404},
    )
    if response.status_code == 200:
        return {"created": False, "name": workspace_name}

    _geoserver_request(
        "POST",
        "/rest/workspaces",
        json_body={"workspace": {"name": workspace_name}},
        expected_statuses={201},
    )
    return {"created": True, "name": workspace_name}


def _create_coveragestore_payload(workspace_name, store_name, source_url, coverage_type):
    return {
        "coverageStore": {
            "name": store_name,
            "workspace": {"name": _safe_name(workspace_name, "atlasworks")},
            "enabled": True,
            "type": coverage_type,
            "url": source_url,
        }
    }


def createCoverageStore(workspace, storeName, filePath):
    store_name = _safe_name(storeName)
    source_url = f"file:{_geoserver_data_source_path(filePath)}"
    payload = _create_coveragestore_payload(workspace, store_name, source_url, "GeoTIFF")
    _geoserver_request(
        "POST",
        f"/rest/workspaces/{quote(workspace)}/coveragestores",
        json_body=payload,
        expected_statuses={201},
    )
    _wait_until(
        lambda: _store_exists(workspace, store_name),
        description=f"coverage store {workspace}:{store_name}",
    )
    return {"workspace": workspace, "storeName": store_name, "type": "GeoTIFF"}


def createImageMosaic(workspace, storeName, dirPath):
    store_name = _safe_name(storeName)
    source_url = f"file:{_geoserver_data_source_path(dirPath)}"
    payload = _create_coveragestore_payload(workspace, store_name, source_url, "ImageMosaic")
    _geoserver_request(
        "POST",
        f"/rest/workspaces/{quote(workspace)}/coveragestores",
        json_body=payload,
        expected_statuses={201},
    )
    _wait_until(
        lambda: _store_exists(workspace, store_name),
        description=f"ImageMosaic store {workspace}:{store_name}",
    )
    return {"workspace": workspace, "storeName": store_name, "type": "ImageMosaic"}


def _publish_coverage(workspace, store_name, layer_name, srs):
    payload = {
        "coverage": {
            "name": layer_name,
            "title": layer_name,
            "nativeName": layer_name,
            "srs": srs,
            "enabled": True,
        }
    }
    if _coverage_exists(workspace, store_name, layer_name):
        return layer_name

    last_error = None
    for _ in range(5):
        try:
            response = _geoserver_request(
                "POST",
                f"/rest/workspaces/{quote(workspace)}/coveragestores/{quote(store_name)}/coverages",
                json_body=payload,
                expected_statuses={201, 403, 500},
            )
            if response.status_code == 201:
                break
            detail = response.text.strip() or f"HTTP {response.status_code}"
            last_error = RuntimeError(f"GeoServer coverage 创建失败: {detail}")
        except Exception as exc:
            last_error = exc
        time.sleep(1.0)
    else:
        available_coverages = _list_store_coverages(workspace, store_name)
        if available_coverages:
            return available_coverages[0]
        raise last_error or RuntimeError(f"GeoServer coverage 创建失败: {workspace}:{layer_name}")

    _wait_until(
        lambda: _coverage_exists(workspace, store_name, layer_name),
        description=f"coverage {workspace}:{layer_name}",
    )
    return layer_name


def _normalise_nodata_value(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if number.is_integer():
        return str(int(number))
    return str(number)


def _coverage_parameter_entries(nodata_value=None):
    entries = []
    normalised_nodata = _normalise_nodata_value(nodata_value)
    if normalised_nodata is not None:
        entries.append({"string": ["InputTransparentColor", normalised_nodata]})
    return entries


def _configure_layer(workspace, store_name, layer_name, srs, style_name="raster", nodata_value=None):
    parameter_entries = _coverage_parameter_entries(nodata_value)
    payload = {
        "coverage": {
            "title": layer_name,
            "srs": srs,
            "projectionPolicy": "REPROJECT_TO_DECLARED",
            "enabled": True,
        }
    }
    if parameter_entries:
        payload["coverage"]["parameters"] = {"entry": parameter_entries}
    _geoserver_request(
        "PUT",
        f"/rest/workspaces/{quote(workspace)}/coveragestores/{quote(store_name)}/coverages/{quote(layer_name)}",
        json_body=payload,
        expected_statuses={200, 201, 404},
    )
    _geoserver_request(
        "PUT",
        f"/rest/layers/{quote(workspace)}:{quote(layer_name)}",
        json_body={"layer": {"defaultStyle": {"name": style_name}, "enabled": True}},
        expected_statuses={200, 201, 404},
    )


def setLayerDefaultStyle(workspace, layerName, styleName):
    layer_name = _safe_name(layerName)
    style_name = _safe_name(styleName)
    _geoserver_request(
        "PUT",
        f"/rest/layers/{quote(workspace)}:{quote(layer_name)}",
        json_body={"layer": {"defaultStyle": {"name": style_name}, "enabled": True}},
        expected_statuses={200, 201},
    )
    return {"workspace": workspace, "layerName": layer_name, "styleName": style_name}


def _build_raster_sld(style_name, render_mode="auto", red_band=1, green_band=2, blue_band=3, nodata_value=None):
    style_name = _safe_name(style_name, "raster_style")
    render_mode = str(render_mode or "auto").strip().lower()
    normalised_nodata = _normalise_nodata_value(nodata_value)
    if render_mode == "rgb":
        channel_selection = (
            "<ChannelSelection>"
            f"<RedChannel><SourceChannelName>{int(red_band)}</SourceChannelName></RedChannel>"
            f"<GreenChannel><SourceChannelName>{int(green_band)}</SourceChannelName></GreenChannel>"
            f"<BlueChannel><SourceChannelName>{int(blue_band)}</SourceChannelName></BlueChannel>"
            "</ChannelSelection>"
        )
    elif render_mode == "gray":
        channel_selection = (
            "<ChannelSelection>"
            f"<GrayChannel><SourceChannelName>{int(red_band)}</SourceChannelName></GrayChannel>"
            "</ChannelSelection>"
        )
    else:
        channel_selection = ""

    color_map = ""
    if normalised_nodata is not None and render_mode == "gray":
        color_map = (
            "<ColorMap>"
            f'<ColorMapEntry color="#000000" quantity="{escape(normalised_nodata)}" opacity="0"/>'
            "</ColorMap>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<StyledLayerDescriptor version="1.0.0" '
        'xmlns="http://www.opengis.net/sld" '
        'xmlns:ogc="http://www.opengis.net/ogc" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://www.opengis.net/sld StyledLayerDescriptor.xsd">'
        "<NamedLayer>"
        f"<Name>{escape(style_name)}</Name>"
        "<UserStyle>"
        f"<Name>{escape(style_name)}</Name>"
        "<FeatureTypeStyle><Rule><RasterSymbolizer>"
        f"{channel_selection}"
        f"{color_map}"
        "</RasterSymbolizer></Rule></FeatureTypeStyle>"
        "</UserStyle>"
        "</NamedLayer>"
        "</StyledLayerDescriptor>"
    )


def createRasterStyle(workspace, styleName, renderMode="auto", redBand=1, greenBand=2, blueBand=3, nodataValue=None, overwrite=True):
    workspace_name = _safe_name(workspace, "atlasworks")
    style_name = _safe_name(styleName, "raster_style")
    if overwrite:
        deleteStyle(workspace_name, style_name, purge=True, quiet=True)
    sld_body = _build_raster_sld(style_name, renderMode, redBand, greenBand, blueBand, nodataValue)
    _geoserver_request(
        "POST",
        f"/rest/workspaces/{quote(workspace_name)}/styles",
        params={"name": style_name},
        data=sld_body,
        headers={"Content-Type": "application/vnd.ogc.sld+xml"},
        expected_statuses={201},
    )
    return {"workspace": workspace_name, "styleName": style_name, "renderMode": renderMode}


def deleteStyle(workspace, styleName, purge=True, quiet=False):
    workspace_name = _safe_name(workspace, "atlasworks")
    style_name = _safe_name(styleName, "raster_style")
    try:
        _geoserver_request(
            "DELETE",
            f"/rest/workspaces/{quote(workspace_name)}/styles/{quote(style_name)}",
            params={"purge": "true" if purge else "false"},
            expected_statuses={200, 202, 404},
        )
        return {"workspace": workspace_name, "styleName": style_name}
    except Exception:
        if quiet:
            return {"workspace": workspace_name, "styleName": style_name, "deleted": False}
        raise


def getLayerInfo(workspace, layerName, storeName=None):
    layer_name = _safe_name(layerName)
    store_name = _safe_name(storeName or layer_name)
    layer_response = _geoserver_request(
        "GET",
        f"/rest/layers/{quote(workspace)}:{quote(layer_name)}.json",
        expected_statuses={200},
    )
    coverage_response = _geoserver_request(
        "GET",
        f"/rest/workspaces/{quote(workspace)}/coveragestores/{quote(store_name)}/coverages/{quote(layer_name)}.json",
        expected_statuses={200, 404},
    )
    payload = {
        "layer": layer_response.json().get("layer", {}),
        "coverage": coverage_response.json().get("coverage", {}) if coverage_response.status_code == 200 else {},
    }
    return payload


def deleteStore(workspace, storeName):
    store_name = _safe_name(storeName)
    _geoserver_request(
        "DELETE",
        f"/rest/workspaces/{quote(workspace)}/coveragestores/{quote(store_name)}",
        params={"recurse": "true", "purge": "metadata"},
        expected_statuses={200, 202, 404},
    )
    _wait_until(
        lambda: not _store_exists(workspace, store_name),
        description=f"delete store {workspace}:{store_name}",
    )
    return {"workspace": workspace, "storeName": store_name}


def _seed_request_payload(workspace, layerName, seed_type="seed", zoomStart=0, zoomStop=16, format_name="image/png", thread_count=1):
    layer_id = f"{workspace}:{_safe_name(layerName)}"
    seed_type = str(seed_type or "seed").strip().lower()
    payload = (
        "<seedRequest>"
        f"<name>{escape(layer_id)}</name>"
        f"<type>{escape(seed_type)}</type>"
    )
    if seed_type not in {"kill_all", "kill_thread"}:
        payload += (
            # ARM 版 GeoServer/GWC 可能同时存在多套 EPSG:3857 GridSubset，必须显式指定网格集。
            "<gridSetId>EPSG:900913</gridSetId>"
            "<srs><number>3857</number></srs>"
            f"<zoomStart>{int(zoomStart)}</zoomStart>"
            f"<zoomStop>{int(zoomStop)}</zoomStop>"
            f"<format>{escape(str(format_name or 'image/png'))}</format>"
            f"<threadCount>{max(1, int(thread_count or 1))}</threadCount>"
        )
    payload += "</seedRequest>"
    return layer_id, payload


def seedLayer(workspace, layerName, zoomStart, zoomStop, format_name, thread_count=1):
    layer_id, payload = _seed_request_payload(workspace, layerName, "seed", zoomStart, zoomStop, format_name, thread_count)
    response = _geoserver_request(
        "POST",
        f"/gwc/rest/seed/{quote(layer_id, safe=':')}.xml",
        data=payload,
        headers={"Content-Type": "text/xml"},
        expected_statuses={200, 201},
    )
    try:
        return response.json()
    except Exception:
        return {"success": True, "message": response.text.strip() or "seed accepted"}


def getSeedStatus(workspace, layerName):
    layer_id = f"{workspace}:{_safe_name(layerName)}"
    response = _geoserver_request(
        "GET",
        f"/gwc/rest/seed/{quote(layer_id, safe=':')}.xml",
        expected_statuses={200, 404},
    )
    text = response.text.strip() if response.status_code == 200 else ""
    status_text = "当前没有运行中的预热任务"
    task_count = 0
    raw_arrays = []
    running = False
    if text:
        try:
            root = ET.fromstring(text)
            array_nodes = root.findall(".//long-array")
            for array_node in array_nodes:
                values = []
                for long_node in array_node.findall("./long"):
                    try:
                        values.append(int((long_node.text or "").strip()))
                    except Exception:
                        continue
                if values:
                    raw_arrays.append(values)
            task_count = len(raw_arrays)
            if task_count > 0:
                running = True
                status_text = f"预热执行中，GeoServer 返回 {task_count} 组运行队列"
            else:
                plain_text = "".join(root.itertext()).strip()
                if plain_text:
                    status_text = plain_text
        except Exception:
            if "<long-array" in text:
                task_count = max(1, text.count("<long-array>"))
                running = True
                status_text = f"预热执行中，GeoServer 返回 {task_count} 组运行队列"
            else:
                status_text = text
    return {
        "success": True,
        "workspace": workspace,
        "layerName": _safe_name(layerName),
        "running": running,
        "status": text,
        "statusText": status_text,
        "taskCount": task_count,
        "taskQueues": raw_arrays,
    }


def cancelSeed(workspace, layerName):
    layer_id = f"{workspace}:{_safe_name(layerName)}"
    response = _geoserver_request(
        "POST",
        f"/gwc/rest/seed/{quote(layer_id, safe=':')}",
        params={"kill_all": "all"},
        expected_statuses={200, 201, 202},
    )
    return {"success": True, "workspace": workspace, "layerName": _safe_name(layerName), "message": response.text.strip() or "seed cancel accepted"}


def getLayerPreviewUrl(workspace, layerName):
    public_base = _geoserver_public_base_url()
    layer_id = f"{workspace}:{_safe_name(layerName)}"
    encoded_layer = quote(layer_id, safe=":")
    wms_url = f"{public_base}/wms?service=WMS&version=1.1.0&request=GetMap&layers={encoded_layer}&styles=&bbox={{bbox-epsg-3857}}&width=256&height=256&srs=EPSG:3857&format=image/png"
    wmts_capabilities = f"{public_base}/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetCapabilities"
    wmts_template = f"{public_base}/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER={encoded_layer}&STYLE=raster&TILEMATRIXSET={GEOSERVER_WMTS_GRIDSET}&TILEMATRIX={GEOSERVER_WMTS_GRIDSET}:{{z}}&TILEROW={{y}}&TILECOL={{x}}&FORMAT=image/png"
    return {
        "wmsUrl": wms_url,
        "wmtsCapabilitiesUrl": wmts_capabilities,
        "wmtsTileUrl": wmts_template,
        "wmtsTileMatrixSet": GEOSERVER_WMTS_GRIDSET,
        "layerId": layer_id,
    }


def _resolve_publish_source(path_value):
    valid, resolved = validateDataSourcePath(path_value)
    if not valid:
        raise ValueError(resolved)
    if not os.path.exists(resolved):
        raise ValueError("数据源路径不存在")
    return resolved


def _infer_publish_mode(resolved_path):
    if os.path.isdir(resolved_path):
        tif_files = [
            name for name in os.listdir(resolved_path)
            if os.path.splitext(name)[1].lower() in GEOSERVER_RASTER_EXTENSIONS
        ]
        if not tif_files:
            raise ValueError("目录中未找到 tif/tiff 文件，无法创建 ImageMosaic")
        if len(tif_files) == 1:
            return "single-dir"
        return "multi-geotiff"
    ext = os.path.splitext(resolved_path)[1].lower()
    if ext not in GEOSERVER_RASTER_EXTENSIONS:
        raise ValueError("GeoServer 目前仅支持 tif/tiff 影像发布")
    return "single"


def _default_publish_name_from_path(resolved_path, mode):
    normalized_path = str(resolved_path or "").rstrip("/\\")
    if mode == "mosaic":
        return _safe_name(os.path.basename(normalized_path) or "imagery", "imagery")
    return _safe_name(os.path.splitext(os.path.basename(normalized_path))[0] or "imagery", "imagery")


def _list_directory_tiffs(resolved_path):
    tif_files = []
    for filename in sorted(os.listdir(resolved_path)):
        if os.path.splitext(filename)[1].lower() in GEOSERVER_RASTER_EXTENSIONS:
            tif_files.append(os.path.join(resolved_path, filename))
    return tif_files


def _publish_single_geotiff(payload, publish_name, publish_source_path):
    createCoverageStore(payload["workspace"], publish_name, publish_source_path)
    actual_layer_name = _publish_coverage(payload["workspace"], publish_name, publish_name, payload["targetCrs"])
    store_name = publish_name
    if not _store_exists(payload["workspace"], store_name):
        store_name = actual_layer_name
    _configure_layer(payload["workspace"], store_name, actual_layer_name, payload["targetCrs"], payload["styleName"], payload.get("nodataValue"))
    layer_info = {}
    try:
        layer_info = getLayerInfo(payload["workspace"], actual_layer_name, store_name)
    except Exception as exc:
        logMessage(f"GeoServer 图层详情读取失败: {exc}", "WARNING")
    return {
        "workspace": payload["workspace"],
        "storeName": store_name,
        "layerName": actual_layer_name,
        "resolvedPath": publish_source_path.replace("\\", "/"),
        "targetCrs": payload["targetCrs"],
        "layerInfo": layer_info,
    }


def _normalize_geoserver_payload(data):
    workspace = _safe_name(
        data.get("workspace")
        or config.get("geoserverWorkspace")
        or "atlasworks",
        "atlasworks",
    )
    publish_name = _safe_name(
        data.get("alias")
        or data.get("layerName")
        or data.get("storeName")
        or "imagery",
        "imagery",
    )
    source_path = str(data.get("sourcePath") or data.get("path") or "").strip()
    if not source_path:
        raise ValueError("缺少参数: sourcePath")
    target_crs = _normalize_crs(data.get("targetCrs") or data.get("projection") or "EPSG:3857")
    style_name = str(data.get("styleName") or "raster").strip() or "raster"
    tile_format = str(data.get("tileFormat") or "image/png").strip() or "image/png"
    min_zoom = int(data.get("minZoom", 0))
    max_zoom = int(data.get("maxZoom", 16))
    nodata_value = _normalise_nodata_value(data.get("nodataValue"))
    return {
        "workspace": workspace,
        "publishName": publish_name,
        "sourcePath": source_path,
        "targetCrs": target_crs,
        "styleName": style_name,
        "tileFormat": tile_format,
        "minZoom": min_zoom,
        "maxZoom": max_zoom,
        "seedEnabled": bool(data.get("seedEnabled") or data.get("seed")),
        "overwrite": False if data.get("overwrite") is False else True,
        "nodataValue": nodata_value,
    }


def publishGeoserverPayload(data):
    payload = _normalize_geoserver_payload(data)
    resolved_path = _resolve_publish_source(payload["sourcePath"])
    mode = _infer_publish_mode(resolved_path)
    publish_source_path = resolved_path
    if mode == "single-dir":
        tif_files = sorted(
            name for name in os.listdir(resolved_path)
            if os.path.splitext(name)[1].lower() in GEOSERVER_RASTER_EXTENSIONS
        )
        publish_source_path = os.path.join(resolved_path, tif_files[0])
        mode = "single"
    actual_publish_name = payload["publishName"]
    fallback_publish_name = _default_publish_name_from_path(publish_source_path, mode)

    ensureWorkspace(payload["workspace"])
    if mode == "multi-geotiff":
        tif_files = _list_directory_tiffs(resolved_path)
        publish_results = []
        if payload["overwrite"]:
            deleteStore(payload["workspace"], actual_publish_name)
            for index, tif_file in enumerate(tif_files, start=1):
                source_stem = os.path.splitext(os.path.basename(tif_file))[0]
                per_file_name = _safe_name(f"{actual_publish_name}_{index:03d}_{source_stem}", f"{actual_publish_name}_{index:03d}")
                deleteStore(payload["workspace"], per_file_name)
        for index, tif_file in enumerate(tif_files, start=1):
            source_stem = os.path.splitext(os.path.basename(tif_file))[0]
            per_file_name = _safe_name(f"{actual_publish_name}_{index:03d}_{source_stem}", f"{actual_publish_name}_{index:03d}")
            try:
                publish_results.append(_publish_single_geotiff(payload, per_file_name, tif_file))
            except Exception as exc:
                fallback_name = _default_publish_name_from_path(tif_file, "single")
                logMessage(
                    f"GeoServer 目录文件发布名称 {per_file_name} 不可用，回退为源文件名 {fallback_name}: {exc}",
                    "WARNING",
                )
                deleteStore(payload["workspace"], per_file_name)
                publish_results.append(_publish_single_geotiff(payload, fallback_name, tif_file))
        layer_names = [item.get("layerName") for item in publish_results if item.get("layerName")]
        store_names = [item.get("storeName") for item in publish_results if item.get("storeName")]
        primary_layer = layer_names[0] if layer_names else actual_publish_name
        preview_urls = getLayerPreviewUrl(payload["workspace"], primary_layer)
        layer_ids = ",".join(f"{payload['workspace']}:{name}" for name in layer_names)
        preview_urls["wmsLayerNames"] = layer_names
        preview_urls["wmsUrl"] = (
            f"{_geoserver_public_base_url()}/wms?service=WMS&version=1.1.1&request=GetMap"
            f"&layers={quote(layer_ids, safe=':,')}"
            "&styles=&bbox={bbox-epsg-3857}&width=256&height=256&srs=EPSG:3857&format=image/png&transparent=true"
        )
        return {
            "success": True,
            "workspace": payload["workspace"],
            "storeName": store_names[0] if store_names else None,
            "storeNames": store_names,
            "layerName": primary_layer,
            "layerNames": layer_names,
            "requestedName": payload["publishName"],
            "sourcePath": payload["sourcePath"],
            "resolvedPath": resolved_path.replace("\\", "/"),
            "mode": mode,
            "targetCrs": payload["targetCrs"],
            "preview": preview_urls,
            "seed": None,
            "seedError": None,
            "layerInfo": publish_results[0].get("layerInfo") if publish_results else {},
        }

    if payload["overwrite"]:
        deleteStore(payload["workspace"], actual_publish_name)
        if fallback_publish_name != actual_publish_name:
            deleteStore(payload["workspace"], fallback_publish_name)

    created_store_name = None

    def _create_and_publish(publish_name):
        nonlocal created_store_name
        if mode == "mosaic":
            createImageMosaic(payload["workspace"], publish_name, publish_source_path)
        else:
            createCoverageStore(payload["workspace"], publish_name, publish_source_path)
        created_store_name = publish_name
        return _publish_coverage(payload["workspace"], publish_name, publish_name, payload["targetCrs"])

    try:
        actual_publish_name = _create_and_publish(actual_publish_name)
    except Exception as exc:
        if mode == "single" and fallback_publish_name != actual_publish_name:
            logMessage(
                f"GeoServer 单文件发布名称 {actual_publish_name} 不可用，回退为源文件名 {fallback_publish_name}: {exc}",
                "WARNING",
            )
            deleteStore(payload["workspace"], actual_publish_name)
            actual_publish_name = _create_and_publish(fallback_publish_name)
        else:
            raise

    store_name = created_store_name or payload["publishName"]
    if not _store_exists(payload["workspace"], store_name):
        store_name = actual_publish_name
    _configure_layer(payload["workspace"], store_name, actual_publish_name, payload["targetCrs"], payload["styleName"], payload.get("nodataValue"))
    preview_urls = getLayerPreviewUrl(payload["workspace"], actual_publish_name)

    seed_result = None
    seed_error = None
    if payload["seedEnabled"]:
        try:
            seed_result = seedLayer(
                payload["workspace"],
                actual_publish_name,
                payload["minZoom"],
                payload["maxZoom"],
                payload["tileFormat"],
            )
        except Exception as exc:
            seed_error = str(exc)
            logMessage(f"GeoServer 预切片失败，图层已发布: {seed_error}", "WARNING")

    layer_info = {}
    try:
        layer_info = getLayerInfo(payload["workspace"], actual_publish_name, store_name)
    except Exception as exc:
        logMessage(f"GeoServer 图层详情读取失败: {exc}", "WARNING")

    return {
        "success": True,
        "workspace": payload["workspace"],
        "storeName": store_name,
        "layerName": actual_publish_name,
        "requestedName": payload["publishName"],
        "sourcePath": payload["sourcePath"],
        "resolvedPath": publish_source_path.replace("\\", "/"),
        "mode": mode,
        "targetCrs": payload["targetCrs"],
        "preview": preview_urls,
        "seed": seed_result,
        "seedError": seed_error,
        "layerInfo": layer_info,
    }


def geoserverHealth():
    try:
        response = _geoserver_request("GET", "/rest/about/version.json", expected_statuses={200})
        payload = response.json()
        return jsonify({
            "success": True,
            "baseUrl": _geoserver_rest_base_url(),
            "publicBaseUrl": _geoserver_public_base_url(),
            "version": payload,
        })
    except Exception as exc:
        logMessage(f"GeoServer 健康检查失败: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 502


def geoserverPublish():
    try:
        data = request.get_json(silent=True) or {}
        return jsonify(publishGeoserverPayload(data))
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception as exc:
        logMessage(f"GeoServer 发布失败: {exc}", "ERROR")
        return _json_error(str(exc), 500)


def geoserverListLayers():
    workspace = _safe_name(request.args.get("workspace") or config.get("geoserverWorkspace") or "atlasworks", "atlasworks")
    try:
        response = _geoserver_request(
            "GET",
            f"/rest/workspaces/{quote(workspace)}/layers.json",
            expected_statuses={200, 404},
        )
        if response.status_code == 404:
            return jsonify({"success": True, "workspace": workspace, "layers": []})
        payload = response.json()
        return jsonify({
            "success": True,
            "workspace": workspace,
            "layers": payload.get("layers", {}).get("layer", []),
        })
    except Exception as exc:
        logMessage(f"GeoServer 图层列表查询失败: {exc}", "ERROR")
        return _json_error(str(exc), 500)


def geoserverLayerDetail(name):
    workspace = _safe_name(request.args.get("workspace") or config.get("geoserverWorkspace") or "atlasworks", "atlasworks")
    try:
        payload = getLayerInfo(workspace, name)
        payload["preview"] = getLayerPreviewUrl(workspace, name)
        return jsonify({
            "success": True,
            "workspace": workspace,
            "layerName": _safe_name(name),
            **payload,
        })
    except Exception as exc:
        logMessage(f"GeoServer 图层详情读取失败: {exc}", "ERROR")
        return _json_error(str(exc), 500)


def geoserverDeleteLayer(name):
    workspace = _safe_name(request.args.get("workspace") or config.get("geoserverWorkspace") or "atlasworks", "atlasworks")
    try:
        result = deleteStore(workspace, name)
        return jsonify({"success": True, **result})
    except Exception as exc:
        logMessage(f"GeoServer 图层删除失败: {exc}", "ERROR")
        return _json_error(str(exc), 500)


def geoserverSeed(name):
    workspace = _safe_name(request.args.get("workspace") or config.get("geoserverWorkspace") or "atlasworks", "atlasworks")
    data = request.get_json(silent=True) or {}
    try:
        result = seedLayer(
            workspace,
            name,
            int(data.get("minZoom", 0)),
            int(data.get("maxZoom", 16)),
            str(data.get("format") or "image/png"),
            int(data.get("threadCount", 1)),
        )
        return jsonify({"success": True, "workspace": workspace, "layerName": _safe_name(name), "seed": result})
    except Exception as exc:
        logMessage(f"GeoServer seed 失败: {exc}", "ERROR")
        return _json_error(str(exc), 500)


def geoserverSeedStatus(name):
    workspace = _safe_name(request.args.get("workspace") or config.get("geoserverWorkspace") or "atlasworks", "atlasworks")
    try:
        return jsonify(getSeedStatus(workspace, name))
    except Exception as exc:
        logMessage(f"GeoServer seed 状态读取失败: {exc}", "ERROR")
        return _json_error(str(exc), 500)


def geoserverCancelSeed(name):
    workspace = _safe_name(request.args.get("workspace") or config.get("geoserverWorkspace") or "atlasworks", "atlasworks")
    try:
        return jsonify(cancelSeed(workspace, name))
    except Exception as exc:
        logMessage(f"GeoServer seed 取消失败: {exc}", "ERROR")
        return _json_error(str(exc), 500)

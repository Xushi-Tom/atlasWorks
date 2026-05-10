#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import shutil
import socket
import subprocess
import threading
import uuid
import hashlib
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlsplit
from urllib.request import urlopen
import xml.etree.ElementTree as ET

from flask import Response, jsonify, redirect, request, send_from_directory

from config import config, taskLock, taskStatus
from db import (
    appendJobEvent,
    countTableRows,
    deletePublicationRecord,
    fetchArtifactRecord,
    fetchPublicationRecord,
    fetchTaskSnapshot,
    isDatabaseEnabled,
    listArtifactRecords,
    listPublicationRecords,
    upsertPublicationRecord,
)
from pagination import paginate_items, parse_pagination_args
from utils import logMessage, validateDataSourcePath, validateWorkspacePath


PUBLICATIONS_DIRNAME = "_publications"
WMTS_DEFAULT_MATRIX_SET = "GoogleMapsCompatible"
WMTS_SUPPORTED_MATRIX_SET = {"googlemapscompatible", "epsg:3857", "epsg3857", "webmercatorquad"}
WMTS_TOP_LEFT_CORNER = "-20037508.342789244 20037508.342789244"
WMTS_INITIAL_SCALE_DENOMINATOR = 559082264.0287178
WMTS_MIN_ZOOM = 0
WMTS_MAX_ZOOM = 22
TITILER_PUBLISH_METHODS = {"titiler-cog", "titiler", "cog"}
DATASOURCE_PUBLISH_TYPE = "imagery"
DATASOURCE_PUBLISH_METHOD = "titiler-cog"
_TITILER_HEALTH_CACHE = {"checkedAt": None, "status": "unknown", "ok": None, "detail": ""}
_PUBLICATION_BUILD_THREADS = {}
_PUBLICATION_BUILD_LOCK = threading.Lock()


def _mime_from_extension(extension):
    ext = str(extension or "").strip().lower()
    mapping = {
        ".json": "application/json",
        ".geojson": "application/geo+json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".pbf": "application/vnd.mapbox-vector-tile",
        ".mvt": "application/vnd.mapbox-vector-tile",
        ".glb": "model/gltf-binary",
        ".b3dm": "application/octet-stream",
        ".pnts": "application/octet-stream",
        ".i3dm": "application/octet-stream",
        ".cmpt": "application/octet-stream",
    }
    return mapping.get(ext)


def _extension_from_mime(mime_type):
    mime = str(mime_type or "").strip().lower().split(";")[0]
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "model/gltf-binary": ".glb",
        "application/json": ".json",
        "application/geo+json": ".geojson",
    }
    return mapping.get(mime)


def _wmts_parameters():
    normalized = {}
    for key, value in request.args.items():
        normalized[str(key).strip().lower()] = str(value or "").strip()
    return normalized


def _wmts_param(name, default=""):
    params = _wmts_parameters()
    return params.get(str(name or "").strip().lower(), default)


def _wmts_error(message, exception_code="InvalidParameterValue", locator="", status_code=400):
    ns = "http://www.opengis.net/ows/1.1"
    ET.register_namespace("", ns)

    report = ET.Element(f"{{{ns}}}ExceptionReport", attrib={"version": "1.0.0"})
    exception = ET.SubElement(report, f"{{{ns}}}Exception", attrib={"exceptionCode": str(exception_code)})
    if locator:
        exception.set("locator", str(locator))
    text = ET.SubElement(exception, f"{{{ns}}}ExceptionText")
    text.text = str(message)

    payload = ET.tostring(report, encoding="utf-8", xml_declaration=True)
    return Response(payload, status=status_code, content_type="application/xml; charset=utf-8")


def _safe_json(value, fallback=None):
    if value is None:
        return fallback
    return value


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _first_defined(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _first_non_blank(*values):
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_list_input(value):
    if value is None:
        return []

    items = []
    if isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        raw_text = str(value or "").strip()
        if not raw_text:
            return []
        if raw_text.startswith("[") and raw_text.endswith("]"):
            try:
                parsed = json.loads(raw_text)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                items = parsed
            else:
                items = [segment for segment in raw_text.replace("\r", "\n").replace(",", "\n").split("\n")]
        else:
            items = [segment for segment in raw_text.replace("\r", "\n").replace(",", "\n").split("\n")]

    normalized = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _load_manifest(manifest_path):
    with open(manifest_path, "r", encoding="utf-8") as manifest_file:
        return json.load(manifest_file)


def _normalize_tile_scheme(tile_scheme, default="tms"):
    raw = str(tile_scheme or "").strip().lower()
    if raw in {"google", "googlexyz", "xyz", "wmts"}:
        return "google"
    if raw in {"tms"}:
        return "tms"
    return default


def _target_tile_scheme_for_publish_method(publish_method):
    normalized = str(publish_method or "").strip().lower()
    if normalized in {"xyz", "wmts"}:
        return "google"
    if normalized == "tms":
        return "tms"
    return ""


def _transform_tile_y(zoom, tile_y, from_scheme, to_scheme):
    try:
        zoom_int = int(zoom)
        tile_y_int = int(tile_y)
    except (TypeError, ValueError):
        return None

    if zoom_int < 0 or tile_y_int < 0:
        return None

    matrix_height = 1 << zoom_int
    if tile_y_int >= matrix_height:
        return None

    normalized_from = _normalize_tile_scheme(from_scheme)
    normalized_to = _normalize_tile_scheme(to_scheme)
    if normalized_from == normalized_to:
        return tile_y_int
    return matrix_height - tile_y_int - 1


def _parse_tile_request_path(relative_path):
    normalized = _normalize_relative_path(relative_path)
    parts = [segment for segment in normalized.split("/") if segment]
    if len(parts) != 3:
        return None

    zoom_value, x_value, y_filename = parts
    stem, extension = os.path.splitext(y_filename)
    if not zoom_value.isdigit() or not x_value.isdigit() or not stem.isdigit() or not extension:
        return None

    return {
        "zoom": int(zoom_value),
        "x": int(x_value),
        "y": int(stem),
        "extension": extension,
    }


def _build_publication_asset_url(publication_id, relative_path=""):
    publication_token = quote(str(publication_id or "").strip(), safe="")
    suffix = _normalize_relative_path(relative_path)
    if suffix:
        return f"{_public_base_url()}/publication-assets/{publication_token}/{suffix}"
    return f"{_public_base_url()}/publication-assets/{publication_token}"


def _extract_tile_profile_from_manifest(manifest):
    if not isinstance(manifest, dict):
        return {}

    build_parameters = _safe_dict(manifest.get("buildParameters"))
    result_summary = _safe_dict(manifest.get("resultSummary"))
    render_options = _safe_dict(result_summary.get("renderOptions"))
    image_format = str(
        _first_non_blank(
            render_options.get("imageFormat"),
            result_summary.get("imageFormat"),
            build_parameters.get("imageFormat"),
        )
    ).strip().lower()

    profile = {}
    tile_scheme = _first_non_blank(
        render_options.get("tileScheme"),
        result_summary.get("tileScheme"),
        build_parameters.get("tileScheme"),
    )
    if tile_scheme:
        profile["sourceTileScheme"] = _normalize_tile_scheme(tile_scheme)
    if image_format:
        profile["tileExtension"] = ".jpg" if image_format in {"jpg", "jpeg"} else f".{image_format}"
    return profile


def _resolve_tile_publish_profile(full_path, metadata=None, artifact=None):
    metadata = _safe_dict(metadata)
    artifact = artifact if isinstance(artifact, dict) else {}
    custom_metadata = _safe_dict(metadata.get("customMetadata"))
    artifact_metadata = _safe_dict(artifact.get("metadata"))
    artifact_result = _safe_dict(artifact_metadata.get("resultSummary"))
    artifact_render_options = _safe_dict(artifact_result.get("renderOptions"))
    artifact_build_parameters = _safe_dict(artifact_metadata.get("buildParameters"))

    profile = {}
    stored_scheme = _first_non_blank(
        metadata.get("sourceTileScheme"),
        custom_metadata.get("sourceTileScheme"),
        artifact_render_options.get("tileScheme"),
        artifact_result.get("tileScheme"),
        artifact_build_parameters.get("tileScheme"),
    )
    if stored_scheme:
        profile["sourceTileScheme"] = _normalize_tile_scheme(stored_scheme)

    stored_extension = _first_non_blank(
        metadata.get("tileExtension"),
        custom_metadata.get("tileExtension"),
    )
    if stored_extension:
        normalized_extension = str(stored_extension).strip().lower()
        if normalized_extension and not normalized_extension.startswith("."):
            normalized_extension = f".{normalized_extension}"
        profile["tileExtension"] = normalized_extension

    metadata_path = os.path.join(full_path, "tile_metadata.json")
    if os.path.isfile(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8") as file_obj:
                tile_metadata = json.load(file_obj)
            render_options = _safe_dict(tile_metadata.get("renderOptions"))
            if not profile.get("sourceTileScheme") and render_options.get("tileScheme"):
                profile["sourceTileScheme"] = _normalize_tile_scheme(render_options.get("tileScheme"))
            if not profile.get("tileExtension"):
                image_format = str(render_options.get("imageFormat") or "").strip().lower()
                if image_format:
                    profile["tileExtension"] = ".jpg" if image_format in {"jpg", "jpeg"} else f".{image_format}"
        except Exception as exc:
            logMessage(f"读取 tile_metadata 失败: {metadata_path} - {exc}", "WARNING")

    manifest_path = _first_non_blank(metadata.get("manifestPath"), artifact.get("manifestPath"))
    if manifest_path and os.path.isfile(manifest_path):
        try:
            manifest_profile = _extract_tile_profile_from_manifest(_load_manifest(manifest_path))
            for key, value in manifest_profile.items():
                profile.setdefault(key, value)
        except Exception as exc:
            logMessage(f"读取 manifest 失败: {manifest_path} - {exc}", "WARNING")

    local_manifest_path = os.path.join(full_path, "manifest.json")
    if os.path.isfile(local_manifest_path):
        try:
            manifest_profile = _extract_tile_profile_from_manifest(_load_manifest(local_manifest_path))
            for key, value in manifest_profile.items():
                profile.setdefault(key, value)
        except Exception as exc:
            logMessage(f"读取 manifest 失败: {local_manifest_path} - {exc}", "WARNING")

    tile_info = _find_tile_template_info(full_path)
    if tile_info:
        profile.setdefault("tileExtension", str(tile_info.get("extension") or "").strip().lower())

    profile["sourceTileScheme"] = _normalize_tile_scheme(profile.get("sourceTileScheme"))
    profile["tileExtension"] = str(profile.get("tileExtension") or "").strip().lower()
    if profile["tileExtension"] and not profile["tileExtension"].startswith("."):
        profile["tileExtension"] = f".{profile['tileExtension']}"
    return profile


def _normalize_relative_path(path_value):
    raw_path = unquote(str(path_value or "").strip())
    if not raw_path:
        return ""

    unix_style_path = raw_path.replace("\\", "/")
    tiles_dir_unix = str(config.get("tilesDir") or "").strip().replace("\\", "/").rstrip("/")
    default_tiles_prefix = "/app/tiles"

    for prefix in (tiles_dir_unix, default_tiles_prefix):
        normalized_prefix = str(prefix or "").strip().replace("\\", "/").rstrip("/")
        if not normalized_prefix:
            continue
        lower_path = unix_style_path.lower()
        lower_prefix = normalized_prefix.lower()
        if lower_path == lower_prefix:
            return ""
        if lower_path.startswith(f"{lower_prefix}/"):
            unix_style_path = unix_style_path[len(normalized_prefix) + 1:]
            break

    if os.path.isabs(raw_path):
        tiles_root = os.path.abspath(config["tilesDir"])
        abs_input = os.path.abspath(raw_path)
        if abs_input == tiles_root:
            return ""
        if abs_input.startswith(f"{tiles_root}{os.sep}"):
            unix_style_path = os.path.relpath(abs_input, tiles_root).replace("\\", "/")

    return unix_style_path.strip("/")


def _resolve_tiles_path(path_value=""):
    normalized_path = _normalize_relative_path(path_value)
    tiles_root = os.path.abspath(config["tilesDir"])
    full_path = os.path.abspath(os.path.join(tiles_root, normalized_path))
    if full_path != tiles_root and not full_path.startswith(f"{tiles_root}{os.sep}"):
        raise ValueError("目标路径非法")
    return normalized_path, full_path


def _build_access_url(path_value):
    normalized_path = _normalize_relative_path(path_value)
    if not normalized_path:
        return None
    return f"{_public_base_url()}/published/{normalized_path}"


def _build_nginx_published_url(path_value):
    normalized_path = _normalize_relative_path(path_value)
    base_url = _nginx_public_base_url()
    if normalized_path:
        return f"{base_url}/published/{normalized_path}"
    return f"{base_url}/published/"


def _is_loopback_host(host):
    host = str(host or "").strip().lower().strip("[]")
    if host in {"", "localhost"}:
        return True
    return host.startswith("127.") or host == "::1"


def _detect_container_ip():
    configured_host = str(config.get("publicBaseHost") or "").strip()
    if configured_host:
        return configured_host

    candidates = []
    try:
        hostname = socket.gethostname()
        candidates.extend(socket.gethostbyname_ex(hostname)[2] or [])
    except Exception:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            candidates.append(sock.getsockname()[0])
    except Exception:
        pass

    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized and not _is_loopback_host(normalized):
            return normalized
    return ""


def _build_host_url(scheme, host, port=None):
    host = str(host or "").strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    normalized_scheme = str(scheme or "http").strip().lower() or "http"

    port_value = 0
    try:
        port_value = int(port or 0)
    except (TypeError, ValueError):
        port_value = 0

    hide_default_port = (normalized_scheme == "http" and port_value == 80) or (normalized_scheme == "https" and port_value == 443)
    port_part = "" if (port_value <= 0 or hide_default_port) else f":{port_value}"
    return f"{normalized_scheme}://{host}{port_part}"


def _external_backend_base_url(configured_url_key, public_port_key):
    configured_url = str(config.get(configured_url_key) or "").strip().rstrip("/")
    if configured_url:
        return configured_url

    configured_host = str(config.get("publicBaseHost") or "").strip()
    if configured_host:
        scheme = str(config.get("publicBaseScheme") or "http").strip() or "http"
        return _build_host_url(scheme, configured_host, config.get(public_port_key))

    try:
        shared_base = _public_base_url()
    except RuntimeError:
        shared_base = "http://127.0.0.1"

    parsed = urlsplit(shared_base)
    host = parsed.hostname or parsed.netloc.split(":")[0] or "127.0.0.1"
    scheme = parsed.scheme or "http"
    return _build_host_url(scheme, host, config.get(public_port_key))


def _nginx_public_base_url():
    return _external_backend_base_url("nginxPublicBaseUrl", "nginxPublicBasePort")

def _titiler_public_base_url():
    return _external_backend_base_url("titilerPublicBaseUrl", "titilerPublicBasePort")


def _titiler_health_state(force_refresh=False):
    cache = _TITILER_HEALTH_CACHE
    now = datetime.now(timezone.utc)
    checked_at = cache.get("checkedAt")
    if (
        not force_refresh
        and isinstance(checked_at, datetime)
        and (now - checked_at).total_seconds() < 15
    ):
        return {
            "ok": cache.get("ok"),
            "status": cache.get("status") or "unknown",
            "detail": cache.get("detail") or "",
            "checkedAt": checked_at.isoformat(),
        }

    health_url = f"{_titiler_public_base_url().rstrip('/')}/healthz"
    ok = False
    status = "unhealthy"
    detail = ""
    try:
        with urlopen(health_url, timeout=5) as response:
            ok = int(getattr(response, "status", 0) or 0) == 200
            status = "healthy" if ok else "unhealthy"
            detail = f"HTTP {getattr(response, 'status', 0)}"
    except Exception as exc:
        ok = False
        status = "unhealthy"
        detail = str(exc)

    cache["checkedAt"] = now
    cache["ok"] = ok
    cache["status"] = status
    cache["detail"] = detail
    return {
        "ok": ok,
        "status": status,
        "detail": detail,
        "checkedAt": now.isoformat(),
    }


def _public_base_url():
    configured_base_url = str(config.get("publicBaseUrl") or "").strip().rstrip("/")
    if configured_base_url:
        return configured_base_url

    request_parts = urlsplit(request.host_url)
    request_host = request_parts.hostname or ""
    request_port = request_parts.port
    request_scheme = request_parts.scheme or request.scheme or "http"

    mode = str(config.get("publicBaseMode") or "auto").strip().lower()
    custom_scheme = str(config.get("publicBaseScheme") or "").strip().lower()
    explicit_port = config.get("publicBasePort")
    target_scheme = custom_scheme or request_scheme

    try:
        explicit_port = int(explicit_port or 0)
    except (TypeError, ValueError):
        explicit_port = 0

    configured_base_host = str(config.get("publicBaseHost") or "").strip()
    if configured_base_host:
        target_port = explicit_port or int(config.get("port") or 18000)
        return _build_host_url(target_scheme, configured_base_host, target_port)

    if mode in {"container_ip", "container", "ip"}:
        target_host = _detect_container_ip() or request_host
        target_port = explicit_port or int(config.get("port") or 18000)
        return _build_host_url(target_scheme, target_host, target_port)

    if mode == "auto" and _is_loopback_host(request_host):
        target_host = _detect_container_ip()
        if target_host:
            target_port = explicit_port or int(config.get("port") or 18000)
            return _build_host_url(target_scheme, target_host, target_port)

    if explicit_port:
        return _build_host_url(target_scheme, request_host, explicit_port)
    return request.host_url.rstrip("/")


def _find_tile_template_info(full_path):
    if not os.path.isdir(full_path):
        return None

    for zoom_name in sorted(os.listdir(full_path), key=lambda value: (not str(value).isdigit(), str(value))):
        if not str(zoom_name).isdigit():
            continue
        zoom_dir = os.path.join(full_path, str(zoom_name))
        if not os.path.isdir(zoom_dir):
            continue

        for x_name in sorted(os.listdir(zoom_dir), key=lambda value: (not str(value).isdigit(), str(value))):
            if not str(x_name).isdigit():
                continue
            x_dir = os.path.join(zoom_dir, str(x_name))
            if not os.path.isdir(x_dir):
                continue

            for filename in sorted(os.listdir(x_dir)):
                if filename.endswith(".aux.xml"):
                    continue
                stem, extension = os.path.splitext(filename)
                if not stem.isdigit() or not extension:
                    continue
                return {
                    "extension": extension,
                    "zoom": str(zoom_name),
                    "x": str(x_name),
                    "y": stem,
                }
    return None


def _find_tileset_entry(full_path):
    if not os.path.isdir(full_path):
        return None
    for candidate in ("tileset.json", "Tileset.json"):
        candidate_path = os.path.join(full_path, candidate)
        if os.path.isfile(candidate_path):
            return candidate
    return None


def _load_vector_tileset_metadata(full_path):
    tileset_entry = _find_tileset_entry(full_path)
    if not tileset_entry:
        return {}

    tileset_path = os.path.join(full_path, tileset_entry)
    try:
        with open(tileset_path, "r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
    except Exception as exc:
        logMessage(f"读取矢量 tileset 失败: {tileset_path} - {exc}", "WARNING")
        return {}

    if not isinstance(payload, dict):
        return {}

    vector_layers = payload.get("vector_layers")
    if not isinstance(vector_layers, list):
        vector_layers = []

    bounds = payload.get("bounds")
    if not (isinstance(bounds, list) and len(bounds) == 4):
        bounds = None

    return {
        "tilesetPath": tileset_path,
        "tilejson": payload.get("tilejson"),
        "name": payload.get("name"),
        "format": payload.get("format"),
        "scheme": payload.get("scheme"),
        "tiles": payload.get("tiles") if isinstance(payload.get("tiles"), list) else [],
        "minzoom": payload.get("minzoom"),
        "maxzoom": payload.get("maxzoom"),
        "bounds": bounds,
        "vectorLayers": vector_layers,
    }


def _normalize_data_source_path(path_value):
    raw_path = unquote(str(path_value or "").strip())
    if not raw_path:
        return ""

    unix_style_path = raw_path.replace("\\", "/")
    data_dir_unix = str(config.get("dataSourceDir") or "").strip().replace("\\", "/").rstrip("/")
    default_data_prefix = "/app/dataSource"

    for prefix in (data_dir_unix, default_data_prefix):
        normalized_prefix = str(prefix or "").strip().replace("\\", "/").rstrip("/")
        if not normalized_prefix:
            continue
        lower_path = unix_style_path.lower()
        lower_prefix = normalized_prefix.lower()
        if lower_path == lower_prefix:
            return ""
        if lower_path.startswith(f"{lower_prefix}/"):
            unix_style_path = unix_style_path[len(normalized_prefix) + 1:]
            break

    if os.path.isabs(raw_path):
        data_root = os.path.abspath(config["dataSourceDir"])
        abs_input = os.path.abspath(raw_path)
        if abs_input == data_root:
            return ""
        if abs_input.startswith(f"{data_root}{os.sep}"):
            unix_style_path = os.path.relpath(abs_input, data_root).replace("\\", "/")

    return unix_style_path.strip("/")


def _resolve_data_source_path(path_value=""):
    normalized_path = _normalize_data_source_path(path_value)
    data_root = os.path.abspath(config["dataSourceDir"])
    full_path = os.path.abspath(os.path.join(data_root, normalized_path))
    if full_path != data_root and not full_path.startswith(f"{data_root}{os.sep}"):
        raise ValueError("目标数据源路径非法")
    return normalized_path, full_path


def _normalize_data_source_paths(source_paths):
    normalized = []
    seen = set()
    for item in _normalize_list_input(source_paths):
        path_value = _normalize_data_source_path(item)
        if not path_value or path_value in seen:
            continue
        normalized.append(path_value)
        seen.add(path_value)
    return normalized


def _is_titiler_tiff_path(path_value):
    return os.path.splitext(str(path_value or ""))[1].lower() in {".tif", ".tiff"}


def _iter_titiler_directory_sources(path_value, full_path):
    data_root = os.path.abspath(config["dataSourceDir"])
    resolved = []
    for root, _, filenames in os.walk(full_path):
        for filename in sorted(filenames):
            if not _is_titiler_tiff_path(filename):
                continue
            file_full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_full_path, data_root).replace("\\", "/")
            resolved.append({
                "path": rel_path,
                "fullPath": file_full_path,
                "sourceEntry": path_value,
            })
    return resolved


def _validate_titiler_source_paths(source_paths):
    source_entries = _normalize_data_source_paths(source_paths)
    if not source_entries:
        raise ValueError("TiTiler 发布至少需要选择一个 GeoTIFF/COG 文件或目录")

    resolved = []
    seen = set()
    for path_value in source_entries:
        is_valid, full_path = validateDataSourcePath(path_value)
        if not is_valid:
            raise ValueError(str(full_path))
        if os.path.isdir(full_path):
            directory_sources = _iter_titiler_directory_sources(path_value, full_path)
            if not directory_sources:
                raise ValueError(f"目录中未找到 .tif/.tiff 文件: {path_value}")
            for source in directory_sources:
                normalized_file_path = source["path"]
                if normalized_file_path in seen:
                    continue
                resolved.append(source)
                seen.add(normalized_file_path)
            continue
        if not os.path.isfile(full_path):
            raise ValueError(f"发布文件不存在: {path_value}")
        if not _is_titiler_tiff_path(full_path):
            raise ValueError("TiTiler 发布仅支持 .tif/.tiff 文件")
        normalized_file_path = _normalize_data_source_path(path_value)
        if normalized_file_path in seen:
            continue
        resolved.append({
            "path": normalized_file_path,
            "fullPath": full_path,
            "sourceEntry": path_value,
        })
        seen.add(normalized_file_path)
    if not resolved:
        raise ValueError("TiTiler 发布至少需要一个有效的 GeoTIFF/COG 文件")
    return {"sourceEntries": source_entries, "resolvedSources": resolved}


def _titiler_cog_relative_path(publication_id, source_path):
    digest = hashlib.sha1(str(source_path or "").encode("utf-8")).hexdigest()[:12]
    stem = os.path.splitext(os.path.basename(str(source_path or "").strip()))[0] or "source"
    return _publication_runtime_relative_path(publication_id, os.path.join("cogs", f"{stem}-{digest}.tif"))


def _titiler_source_is_cog(full_path):
    command = ["gdalinfo", full_path]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except OSError as exc:
        raise RuntimeError(f"GeoTIFF 检查失败: {exc}") from exc
    if result.returncode != 0:
        error_text = str(result.stderr or result.stdout or "").strip() or "未知错误"
        raise RuntimeError(f"GeoTIFF 检查失败: {error_text}")
    info_text = str(result.stdout or "")
    return "LAYOUT=COG" in info_text


def _ensure_titiler_cog_source(publication_id, source):
    source_path = source.get("path")
    full_path = source.get("fullPath")
    if _titiler_source_is_cog(full_path):
        return {
            **source,
            "publishPath": source_path,
            "publishFullPath": full_path,
            "optimized": False,
        }

    relative_target_path = _titiler_cog_relative_path(publication_id, source_path)
    _, target_full_path = _resolve_tiles_path(relative_target_path)
    os.makedirs(os.path.dirname(target_full_path), exist_ok=True)

    if os.path.isfile(target_full_path):
        source_stat = os.stat(full_path)
        target_stat = os.stat(target_full_path)
        if target_stat.st_size > 0 and target_stat.st_mtime >= source_stat.st_mtime:
            return {
                **source,
                "publishPath": relative_target_path,
                "publishFullPath": target_full_path,
                "optimized": True,
            }

    command = [
        "gdal_translate",
        "-of",
        "COG",
        "-co",
        "COMPRESS=LZW",
        "-co",
        "BIGTIFF=IF_SAFER",
        "-co",
        "BLOCKSIZE=512",
        "-co",
        "RESAMPLING=AVERAGE",
        "-co",
        "NUM_THREADS=ALL_CPUS",
        full_path,
        target_full_path,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except OSError as exc:
        raise RuntimeError(f"COG 转换失败: {exc}") from exc
    if result.returncode != 0:
        error_text = str(result.stderr or result.stdout or "").strip() or "未知错误"
        raise RuntimeError(f"COG 转换失败: {source_path}: {error_text}")

    return {
        **source,
        "publishPath": relative_target_path,
        "publishFullPath": target_full_path,
        "optimized": True,
    }


def _prepare_titiler_sources(publication_id, resolved_sources):
    prepared_sources = []
    for source in resolved_sources:
        prepared_sources.append(_ensure_titiler_cog_source(publication_id, source))
    return prepared_sources


def _build_mosaic_json(publication_id, resolved_sources):
    publication_id = str(publication_id or "").strip() or "publication"
    runtime_dir = _publication_runtime_dir(publication_id)
    os.makedirs(runtime_dir, exist_ok=True)

    sources_list_path = os.path.join(runtime_dir, "sources.txt")
    mosaic_json_path = os.path.join(runtime_dir, "mosaic.json")
    with open(sources_list_path, "w", encoding="utf-8") as file_obj:
        for source in resolved_sources:
            file_obj.write(f"{source.get('publishFullPath') or source['fullPath']}\n")

    command = [
        "cogeo-mosaic",
        "create",
        sources_list_path,
        "-o",
        mosaic_json_path,
        "-q",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except OSError as exc:
        raise RuntimeError(f"MosaicJSON 生成失败: {exc}") from exc
    if result.returncode != 0:
        error_text = str(result.stderr or result.stdout or "").strip() or "未知错误"
        raise RuntimeError(f"MosaicJSON 生成失败: {error_text}")
    if not os.path.isfile(mosaic_json_path):
        raise RuntimeError("MosaicJSON 生成失败: 未找到输出文件")

    return {
        "relativePath": _publication_runtime_relative_path(publication_id, "mosaic.json"),
        "fullPath": mosaic_json_path,
        "sourcesListPath": _publication_runtime_relative_path(publication_id, "sources.txt"),
        "sourceCount": len(resolved_sources),
    }


def _is_titiler_publish_method(publish_method):
    return str(publish_method or "").strip().lower() in TITILER_PUBLISH_METHODS


def _is_supported_publication_record(publication):
    if not isinstance(publication, dict):
        return False
    metadata = _safe_dict(publication.get("metadata"))
    source_mode = str(metadata.get("sourceMode") or "").strip().lower()
    publish_method = str(
        publication.get("publishMethod")
        or metadata.get("publishMethod")
        or ""
    ).strip().lower()
    if source_mode == "datasource":
        return _is_titiler_publish_method(publish_method)
    return True


def _publication_runtime_cache_state(publication_id, metadata=None):
    publication_token = str(publication_id or "").strip()
    runtime_dir = _publication_runtime_dir(publication_token) if publication_token else ""
    metadata = _safe_dict(metadata)
    mosaic_relative_path = metadata.get("mosaicJsonPath")
    build_state = _safe_dict(metadata.get("buildState"))
    mosaic_exists = False
    if mosaic_relative_path:
        try:
            _, mosaic_full_path = _resolve_tiles_path(mosaic_relative_path)
            mosaic_exists = os.path.isfile(mosaic_full_path)
        except Exception:
            mosaic_exists = False
    return {
        "runtimeDir": runtime_dir,
        "runtimeDirExists": bool(runtime_dir and os.path.isdir(runtime_dir)),
        "mosaicJsonPath": mosaic_relative_path,
        "mosaicReady": mosaic_exists,
        "buildState": build_state,
        "titiler": _titiler_health_state() if _is_titiler_publish_method(metadata.get("publishMethod")) else None,
    }


def _build_titiler_urls(source_path="", mosaic_json_path=""):
    encoded_url = ""
    source_mode = "cog"
    normalized_path = ""
    full_path = ""
    if mosaic_json_path:
        try:
            normalized_path, full_path = _resolve_tiles_path(mosaic_json_path)
            if os.path.isfile(full_path):
                encoded_url = quote(full_path.replace("\\", "/"), safe="")
                source_mode = "mosaicjson"
            else:
                normalized_path = ""
                full_path = ""
        except Exception:
            normalized_path = ""
            full_path = ""

    if source_mode != "mosaicjson":
        normalized_path, full_path = _resolve_data_source_path(source_path)
        encoded_url = quote(full_path.replace("\\", "/"), safe="")

    base_url = _titiler_public_base_url()
    tile_matrix_set = str(config.get("titilerTileMatrixSet") or "WebMercatorQuad").strip() or "WebMercatorQuad"
    route_prefix = "mosaicjson" if source_mode == "mosaicjson" else "cog"
    map_url = f"{base_url}/{route_prefix}/{quote(tile_matrix_set, safe='')}/map.html?url={encoded_url}"
    tilejson_url = f"{base_url}/{route_prefix}/{quote(tile_matrix_set, safe='')}/tilejson.json?url={encoded_url}"
    tile_template_url = f"{base_url}/{route_prefix}/tiles/{quote(tile_matrix_set, safe='')}/{{z}}/{{x}}/{{y}}.png?url={encoded_url}"
    preview_url = map_url if source_mode == "mosaicjson" else f"{base_url}/{route_prefix}/preview.png?url={encoded_url}"
    return {
        "normalizedPath": normalized_path,
        "fullPath": full_path,
        "sourceMode": source_mode,
        "mapUrl": map_url,
        "tileJsonUrl": tilejson_url,
        "tileTemplateUrl": tile_template_url,
        "previewUrl": preview_url,
    }


def _build_publication_access_payload(publish_path, publish_method=None, publish_type=None, publication_id=None, metadata=None):
    public_base = _public_base_url()
    browser_url = _build_access_url(publish_path)
    access_url = browser_url
    launch_url = browser_url
    sample_url = None
    metadata = _safe_dict(metadata)

    normalized_path = _normalize_relative_path(publish_path)
    if not normalized_path:
        return {
            "browserUrl": browser_url,
            "accessUrl": access_url,
            "launchUrl": launch_url,
            "sampleUrl": sample_url,
            "publicBaseUrl": public_base,
        }

    publish_method = str(publish_method or "").strip().lower()
    publish_type = str(publish_type or "").strip().lower()

    if publish_method in TITILER_PUBLISH_METHODS:
        titiler_urls = _build_titiler_urls(
            source_path=_first_non_blank(
                metadata.get("sourcePath"),
                metadata.get("workspacePath"),
                publish_path,
            ),
            mosaic_json_path=metadata.get("mosaicJsonPath"),
        )
        return {
            "browserUrl": titiler_urls["mapUrl"],
            "accessUrl": titiler_urls["tileTemplateUrl"],
            "launchUrl": titiler_urls["tileJsonUrl"],
            "sampleUrl": titiler_urls["previewUrl"],
            "publicBaseUrl": public_base,
            "backendBaseUrl": _titiler_public_base_url(),
            "dynamicSourceMode": titiler_urls.get("sourceMode"),
        }

    _, full_path = _resolve_tiles_path(normalized_path)
    tile_profile = _resolve_tile_publish_profile(full_path, metadata=metadata)
    source_tile_scheme = tile_profile.get("sourceTileScheme") or "tms"
    target_tile_scheme = _target_tile_scheme_for_publish_method(publish_method)
    is_vector_tile_publish = publish_method in {"mvt", "vector-tile", "vector-tiles", "geojson-tile", "geojson-tiles"}
    tileset_entry = _find_tileset_entry(full_path) if publish_method == "3d-tiles" or publish_type == "3dtiles" else None
    enable_tile_template = (
        publish_method in {"wmts", "tms", "xyz", "quantized-mesh", "cesium-terrain", "terrain", "mvt", "vector-tile", "vector-tiles", "geojson-tile", "geojson-tiles"}
        or publish_type == "terrain"
    )
    tile_info = _find_tile_template_info(full_path) if enable_tile_template else None

    if tileset_entry:
        static_base = _nginx_public_base_url() if publish_method == "nginx-static" else public_base
        tileset_url = f"{static_base}/published/{normalized_path}/{tileset_entry}"
        access_url = tileset_url
        launch_url = tileset_url
        sample_url = tileset_url

    if publish_method == "wmts":
        layer_identifier = str(publication_id or normalized_path).strip()
        tile_extension = tile_profile.get("tileExtension") or (tile_info or {}).get("extension") or ".png"
        tile_mime = _mime_from_extension(tile_extension) or "image/png"

        capabilities_url = (
            f"{public_base}/wmts?SERVICE=WMTS&REQUEST=GetCapabilities"
            "&VERSION=1.0.0"
        )
        if layer_identifier:
            encoded_layer = quote(layer_identifier, safe="")
            access_url = (
                f"{public_base}/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                f"&LAYER={encoded_layer}&STYLE=default&TILEMATRIXSET={WMTS_DEFAULT_MATRIX_SET}"
                f"&TILEMATRIX={{z}}&TILEROW={{y}}&TILECOL={{x}}&FORMAT={tile_mime}"
            )
            sample_zoom = (tile_info or {}).get("zoom", "0")
            sample_x = (tile_info or {}).get("x", "0")
            sample_y = str(
                _transform_tile_y(sample_zoom, (tile_info or {}).get("y", "0"), source_tile_scheme, "google")
                if tile_info
                else 0
            )
            sample_url = (
                f"{public_base}/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                f"&LAYER={encoded_layer}&STYLE=default&TILEMATRIXSET={WMTS_DEFAULT_MATRIX_SET}"
                f"&TILEMATRIX={sample_zoom}&TILEROW={sample_y}&TILECOL={sample_x}&FORMAT={tile_mime}"
            )
        launch_url = capabilities_url

    if tile_info:
        tile_extension = tile_profile.get("tileExtension") or tile_info["extension"]
        sample_y = tile_info["y"]
        if target_tile_scheme:
            transformed_sample_y = _transform_tile_y(tile_info["zoom"], sample_y, source_tile_scheme, target_tile_scheme)
            if transformed_sample_y is not None:
                sample_y = str(transformed_sample_y)

        if publish_method in {"xyz", "tms"} and publication_id:
            tile_template_url = _build_publication_asset_url(
                publication_id,
                f"{{z}}/{{x}}/{{y}}{tile_extension}",
            )
            sample_url = _build_publication_asset_url(
                publication_id,
                f"{tile_info['zoom']}/{tile_info['x']}/{sample_y}{tile_extension}",
            )
        else:
            static_base = _nginx_public_base_url() if publish_method == "nginx-static" else public_base
            tile_template_url = f"{static_base}/published/{normalized_path}/{{z}}/{{x}}/{{y}}{tile_extension}"
            sample_url = f"{static_base}/published/{normalized_path}/{tile_info['zoom']}/{tile_info['x']}/{sample_y}{tile_extension}"

        if publish_method != "wmts":
            access_url = tile_template_url
            launch_url = sample_url or browser_url

    if publish_method == "nginx-static" and not tile_info and not tileset_entry:
        static_url = f"{_nginx_public_base_url()}/published/{normalized_path}"
        browser_url = static_url
        access_url = static_url
        launch_url = static_url

    if is_vector_tile_publish:
        vector_tileset_path = os.path.join(full_path, "tileset.json")
        if os.path.isfile(vector_tileset_path):
            launch_url = f"{public_base}/published/{normalized_path}/tileset.json"

    return {
        "browserUrl": browser_url,
        "accessUrl": access_url,
        "launchUrl": launch_url,
        "sampleUrl": sample_url,
        "publicBaseUrl": public_base,
    }


def _augment_publication_response(payload, include_runtime_state=True, include_vector_details=True):
    if not isinstance(payload, dict):
        return payload
    response = dict(payload)
    metadata = _safe_dict(response.get("metadata"))
    publish_path = response.get("publishPath") or metadata.get("workspacePath")
    access_payload = _build_publication_access_payload(
        publish_path,
        metadata.get("publishMethod"),
        response.get("publishType"),
        response.get("publicationId") or response.get("id"),
        metadata,
    )
    for key, value in access_payload.items():
        existing_value = response.get(key)
        response[key] = existing_value if existing_value else value
    if "enabled" not in metadata:
        metadata["enabled"] = str(response.get("status") or "").lower() in {"enabled", "published", "active"}
    response["metadata"] = metadata
    if str(response.get("status") or "").lower() == "published":
        response["status"] = "enabled" if metadata.get("enabled", True) else "disabled"
    # Surface common publication fields at top-level for simpler API usage.
    response["publishMethod"] = response.get("publishMethod") or metadata.get("publishMethod")
    response["visibility"] = response.get("visibility") or metadata.get("visibility")
    response["note"] = response.get("note") or metadata.get("note")
    response["enabled"] = bool(metadata.get("enabled", True))
    response["customMetadata"] = _safe_dict(response.get("customMetadata") or metadata.get("customMetadata"))
    response["publicationId"] = response.get("publicationId") or response.get("id")
    if include_runtime_state:
        cache_state = _publication_runtime_cache_state(response["publicationId"], metadata)
        response["cache"] = cache_state
    else:
        response["cache"] = {
            "runtimeDir": _publication_runtime_dir(response["publicationId"]),
            "runtimeDirExists": False,
            "mosaicJsonPath": metadata.get("mosaicJsonPath"),
            "mosaicReady": False,
            "buildState": _safe_dict(metadata.get("buildState")),
            "titiler": None,
        }
    response["sourceEntryCount"] = int(metadata.get("sourceEntryCount") or 0)
    response["sourceFileCount"] = int(metadata.get("sourceFileCount") or 0)
    response["optimizedSourceCount"] = int(metadata.get("optimizedSourceCount") or 0)
    response["buildState"] = _safe_dict(metadata.get("buildState"))

    publish_method = str(response.get("publishMethod") or metadata.get("publishMethod") or "").strip().lower()
    publish_type = str(response.get("publishType") or "").strip().lower()
    publish_path = response.get("publishPath") or metadata.get("workspacePath")
    is_vector_tile_publish = publish_method in {"mvt", "vector-tile", "vector-tiles", "geojson-tile", "geojson-tiles"} or publish_type == "vector"
    if include_vector_details and is_vector_tile_publish and publish_path:
        try:
            normalized_path, full_path = _resolve_tiles_path(publish_path)
            vector_tileset = _load_vector_tileset_metadata(full_path)
            if vector_tileset:
                vector_publication = {
                    "kind": "mvt" if publish_method in {"mvt", "vector-tile", "vector-tiles"} else "geojson",
                    "tileJsonUrl": response.get("launchUrl"),
                    "xyzTemplate": response.get("accessUrl"),
                    "sampleTileUrl": response.get("sampleUrl"),
                    "tilesetUrl": f"{_public_base_url()}/published/{normalized_path}/tileset.json",
                    "format": vector_tileset.get("format"),
                    "scheme": vector_tileset.get("scheme"),
                    "minzoom": vector_tileset.get("minzoom"),
                    "maxzoom": vector_tileset.get("maxzoom"),
                    "bounds": vector_tileset.get("bounds"),
                    "vectorLayers": vector_tileset.get("vectorLayers") or [],
                }
                response["vectorPublication"] = vector_publication
                metadata["vectorLayers"] = vector_publication["vectorLayers"]
        except Exception as exc:
            logMessage(f"补充矢量发布详情失败: {publish_path} - {exc}", "WARNING")

    return response


def _publication_descriptor_dir(alias):
    return os.path.join(config["tilesDir"], PUBLICATIONS_DIRNAME, str(alias or "").strip() or "publication")


def _publication_runtime_dir(publication_id):
    publication_token = str(publication_id or "").strip() or "publication"
    return os.path.join(config["tilesDir"], PUBLICATIONS_DIRNAME, publication_token)


def _publication_runtime_relative_path(publication_id, filename):
    return _normalize_relative_path(os.path.join(PUBLICATIONS_DIRNAME, str(publication_id or "").strip() or "publication", filename))


def _cleanup_publication_runtime_dir(publication_id):
    runtime_dir = _publication_runtime_dir(publication_id)
    if os.path.isdir(runtime_dir):
        shutil.rmtree(runtime_dir, ignore_errors=True)


def _is_async_titiler_publication(prepared):
    if not isinstance(prepared, dict):
        return False
    descriptor = _safe_dict(prepared.get("descriptor"))
    metadata = _safe_dict(descriptor.get("metadata"))
    return (
        str(metadata.get("sourceMode") or "").strip().lower() == "datasource"
        and _is_titiler_publish_method(metadata.get("publishMethod"))
    )


def _mark_publication_build_state(metadata, state=None, progress=None, message=None, error=None):
    metadata = _safe_dict(metadata)
    build_state = _safe_dict(metadata.get("buildState"))
    if state is not None:
        build_state["state"] = str(state)
    if progress is not None:
        try:
            build_state["progress"] = max(0, min(100, int(progress)))
        except (TypeError, ValueError):
            build_state["progress"] = 0
    if message is not None:
        build_state["message"] = str(message)
    if error is not None:
        build_state["error"] = str(error) if error else None
    build_state["updatedAt"] = datetime.now(timezone.utc).isoformat()
    metadata["buildState"] = build_state
    return metadata


def _persist_publication_record(prepared, metadata_override=None, status_override=None):
    descriptor = _safe_dict(prepared.get("descriptor"))
    metadata = metadata_override if isinstance(metadata_override, dict) else _safe_dict(descriptor.get("metadata"))
    status_value = status_override or descriptor.get("status") or "draft"
    access_payload = _build_publication_access_payload(
        prepared["publishPath"],
        metadata.get("publishMethod"),
        prepared["publishType"],
        prepared["publicationId"],
        metadata,
    )
    persisted = upsertPublicationRecord(
        publication_id=prepared["publicationId"],
        artifact_id=prepared["artifactId"],
        publish_type=prepared["publishType"],
        publish_path=prepared["publishPath"],
        alias=prepared["alias"],
        status=status_value,
        metadata=metadata,
        published_at=prepared["publishedAt"],
        browser_url=access_payload.get("browserUrl"),
        access_url=access_payload.get("accessUrl"),
        launch_url=access_payload.get("launchUrl"),
        sample_url=access_payload.get("sampleUrl"),
        public_base_url=access_payload.get("publicBaseUrl"),
    )
    if isDatabaseEnabled() and not persisted:
        raise RuntimeError("发布记录写入数据库失败")
    return access_payload


def _run_titiler_publication_build(prepared):
    publication_id = prepared["publicationId"]
    build_thread = None
    mosaic_json_info = None
    try:
        descriptor = _safe_dict(prepared.get("descriptor"))
        metadata = _safe_dict(descriptor.get("metadata"))
        source_entries = _normalize_data_source_paths(metadata.get("sourcePaths"))

        metadata = _mark_publication_build_state(metadata, state="running", progress=5, message="正在检查数据源")
        _persist_publication_record(prepared, metadata_override=metadata, status_override="draft")

        titiler_source_info = _validate_titiler_source_paths(source_entries or [metadata.get("sourcePath") or prepared["workspacePath"]])
        resolved_sources = titiler_source_info["resolvedSources"]

        metadata = _mark_publication_build_state(
            metadata,
            state="running",
            progress=25,
            message=f"正在准备 {len(resolved_sources)} 个 GeoTIFF/COG",
        )
        _persist_publication_record(prepared, metadata_override=metadata, status_override="draft")

        prepared_sources = _prepare_titiler_sources(publication_id, resolved_sources)
        mosaic_json_info = _build_mosaic_json(publication_id, prepared_sources)

        metadata["sourcePath"] = resolved_sources[0]["path"] if resolved_sources else metadata.get("sourcePath")
        metadata["workspacePath"] = metadata.get("sourcePath") or metadata.get("workspacePath")
        metadata["sourcePaths"] = source_entries
        metadata["sourceEntryCount"] = len(source_entries)
        metadata["sourceFileCount"] = len(resolved_sources)
        metadata["optimizedSourceCount"] = sum(1 for item in prepared_sources if item.get("optimized"))
        metadata["mosaicJsonPath"] = mosaic_json_info["relativePath"]
        custom_metadata = _safe_dict(metadata.get("customMetadata"))
        custom_metadata["sourceMode"] = "datasource"
        custom_metadata["sourcePath"] = metadata["sourcePath"]
        custom_metadata["sourcePaths"] = source_entries
        custom_metadata["sourceEntryCount"] = len(source_entries)
        custom_metadata["sourceFileCount"] = len(resolved_sources)
        custom_metadata["optimizedSourceCount"] = metadata["optimizedSourceCount"]
        custom_metadata["mosaicJsonPath"] = mosaic_json_info["relativePath"]
        metadata["customMetadata"] = custom_metadata
        metadata = _mark_publication_build_state(metadata, state="ready", progress=100, message="动态发布已就绪", error=None)
        _persist_publication_record(prepared, metadata_override=metadata, status_override="enabled" if metadata.get("enabled", True) else "disabled")
        logMessage(f"TiTiler 发布构建完成: {publication_id}", "INFO")
    except Exception as exc:
        publication = _get_publication_snapshot(publication_id)
        metadata = _safe_dict(_safe_dict(publication).get("metadata") if publication else _safe_dict(prepared.get("descriptor", {}).get("metadata")))
        metadata = _mark_publication_build_state(metadata, state="failed", progress=100, message="动态发布构建失败", error=str(exc))
        try:
            _persist_publication_record(prepared, metadata_override=metadata, status_override="failed")
        except Exception as persist_exc:
            logMessage(f"写入 TiTiler 发布失败状态失败 {publication_id}: {persist_exc}", "ERROR")
        logMessage(f"TiTiler 发布构建失败 {publication_id}: {exc}", "ERROR")
    finally:
        with _PUBLICATION_BUILD_LOCK:
            build_thread = _PUBLICATION_BUILD_THREADS.pop(publication_id, None)
        del build_thread


def _start_titiler_publication_build(prepared):
    publication_id = prepared["publicationId"]
    with _PUBLICATION_BUILD_LOCK:
        existing_thread = _PUBLICATION_BUILD_THREADS.get(publication_id)
        if existing_thread and existing_thread.is_alive():
            return False
        build_thread = threading.Thread(
            target=_run_titiler_publication_build,
            args=(prepared,),
            daemon=True,
            name=f"titiler-publication-{publication_id}",
        )
        _PUBLICATION_BUILD_THREADS[publication_id] = build_thread
        build_thread.start()
    return True


def _generate_publication_id():
    return str(uuid.uuid4())


def _cleanup_publication_descriptor(publication):
    if not isinstance(publication, dict):
        return

    publication_id = str(publication.get("publicationId") or publication.get("id") or "").strip()
    if publication_id:
        _cleanup_publication_runtime_dir(publication_id)

    metadata = publication.get("metadata") or {}
    descriptor_path = metadata.get("descriptorPath") or publication.get("descriptorPath")
    if descriptor_path and os.path.exists(descriptor_path):
        try:
            os.remove(descriptor_path)
        except FileNotFoundError:
            pass

        descriptor_dir = os.path.dirname(descriptor_path)
        if os.path.isdir(descriptor_dir):
            try:
                if not os.listdir(descriptor_dir):
                    os.rmdir(descriptor_dir)
            except OSError:
                pass


def _write_publication_descriptor(descriptor, alias, previous_publication=None):
    # 数据库持久化开启后，发布记录仅写入数据库，不再向 /tiles/_publications 落盘。
    return None


def _get_publication_snapshot(publication_id):
    record = fetchPublicationRecord(publication_id)
    if record:
        response = _publication_record_to_response(record)
        return response if _is_supported_publication_record(response) else None

    if not isDatabaseEnabled():
        for publication in _scan_publication_files(limit=500):
            if publication.get("id") == publication_id or publication.get("publicationId") == publication_id:
                response = _augment_publication_response(publication)
                return response if _is_supported_publication_record(response) else None
    return None


def _get_task_record(task_id):
    with taskLock:
        in_memory_task = taskStatus.get(task_id)
        if isinstance(in_memory_task, dict):
            return dict(in_memory_task)
    snapshot = fetchTaskSnapshot(task_id)
    return snapshot if isinstance(snapshot, dict) else None


def _resolve_task_publication_source(task_id):
    task_record = _get_task_record(task_id)
    if not task_record:
        return None

    result = task_record.get("result") if isinstance(task_record.get("result"), dict) else {}
    workspace_path = _normalize_relative_path(result.get("mergedOutputPath") or result.get("outputPath"))
    artifact_id = str(result.get("artifactId") or "").strip()
    return {
        "task": task_record,
        "workspacePath": workspace_path,
        "artifactId": artifact_id,
    }


def _prepare_publication_payload(data, existing_publication=None):
    data = _safe_dict(data)
    existing_publication = existing_publication or {}
    existing_metadata = _safe_dict(existing_publication.get("metadata"))
    existing_custom_metadata = _safe_dict(existing_metadata.get("customMetadata"))

    task_id = _first_non_blank(
        data.get("taskId"),
        existing_metadata.get("taskId"),
    )
    artifact_id = _first_non_blank(
        data.get("artifactId"),
        existing_publication.get("artifactId"),
    )
    workspace_path = _normalize_relative_path(
        _first_non_blank(
            data.get("workspacePath"),
            data.get("sourcePath"),
            existing_publication.get("publishPath"),
            existing_metadata.get("workspacePath"),
        )
    )
    artifact = None

    if task_id:
        task_source = _resolve_task_publication_source(task_id)
        if not task_source:
            return None, ("目标任务不存在", 404)
        artifact_id = artifact_id or task_source.get("artifactId") or ""
        workspace_path = workspace_path or task_source.get("workspacePath") or ""

    if artifact_id:
        artifact = _resolve_artifact(artifact_id)
        if not artifact:
            return None, ("目标产物不存在", 404)

    publish_method = _first_defined(
        data.get("publishMethod"),
        existing_metadata.get("publishMethod"),
    )
    publish_method = str(publish_method).strip() if publish_method is not None else None
    normalized_publish_method = str(publish_method or "").strip().lower()
    incoming_source_paths = _first_defined(
        data.get("sourcePaths"),
        existing_metadata.get("sourcePaths"),
        existing_custom_metadata.get("sourcePaths"),
    )
    source_entries = []
    resolved_sources = []
    if normalized_publish_method in TITILER_PUBLISH_METHODS:
        source_entries = _normalize_data_source_paths(incoming_source_paths)
        if not source_entries and workspace_path:
            source_entries = _normalize_data_source_paths([workspace_path])
        workspace_path = source_entries[0] if source_entries else _normalize_data_source_path(workspace_path)
    else:
        workspace_path = workspace_path or _normalize_relative_path(artifact.get("outputPath") if artifact else "")

    if not workspace_path:
        return None, ("缺少参数: taskId、artifactId、workspacePath 或 sourcePath", 400)

    source_mode_input = _first_non_blank(
        data.get("sourceMode"),
        existing_metadata.get("sourceMode"),
        existing_custom_metadata.get("sourceMode"),
    ).lower()
    if normalized_publish_method in TITILER_PUBLISH_METHODS:
        source_mode_input = "datasource"
    if source_mode_input not in {"task", "manual", "artifact", "datasource"}:
        if task_id:
            source_mode_input = "task"
        elif artifact_id:
            source_mode_input = "artifact"
        else:
            source_mode_input = "manual"
    if source_mode_input == "datasource" and normalized_publish_method not in TITILER_PUBLISH_METHODS:
        return None, ("数据源文件发布目前仅支持 TiTiler 动态影像发布", 400)
    if source_mode_input == "datasource":
        publish_method = DATASOURCE_PUBLISH_METHOD
        normalized_publish_method = DATASOURCE_PUBLISH_METHOD

    if source_mode_input == "datasource":
        if normalized_publish_method in TITILER_PUBLISH_METHODS:
            try:
                titiler_source_info = _validate_titiler_source_paths(source_entries or [workspace_path])
                source_entries = titiler_source_info["sourceEntries"]
                resolved_sources = titiler_source_info["resolvedSources"]
            except ValueError as exc:
                return None, (str(exc), 400)
            workspace_path = resolved_sources[0]["path"]
        else:
            workspace_path = _normalize_data_source_path(workspace_path)
    else:
        is_valid_workspace_path, full_workspace_path = validateWorkspacePath(workspace_path)
        if not is_valid_workspace_path:
            return None, (full_workspace_path, 400)
        if not os.path.exists(full_workspace_path):
            return None, ("目标工作空间路径不存在", 404)

    publish_type = _first_non_blank(
        data.get("publishType"),
        existing_publication.get("publishType"),
        "imagery",
    )
    if source_mode_input == "datasource":
        publish_type = DATASOURCE_PUBLISH_TYPE
    default_alias = artifact_id or task_id or os.path.basename(workspace_path.rstrip("/")) or "publication"
    alias = _first_non_blank(
        data.get("alias"),
        existing_publication.get("alias"),
        default_alias,
    )
    incoming_publication_id = _first_non_blank(
        data.get("publicationId"),
    )
    existing_publication_id = str(existing_publication.get("publicationId") or existing_publication.get("id") or "").strip()
    publication_id = incoming_publication_id or existing_publication_id or _generate_publication_id()
    default_publish_path = workspace_path or (artifact.get("outputPath") if artifact else "") or ""
    raw_publish_path = _first_non_blank(
        data.get("publishPath"),
        existing_publication.get("publishPath"),
        default_publish_path,
    )
    publish_path_input = _normalize_data_source_path(raw_publish_path) if source_mode_input == "datasource" else _normalize_relative_path(raw_publish_path)
    publish_path = publish_path_input or default_publish_path

    if source_mode_input == "datasource":
        if normalized_publish_method in TITILER_PUBLISH_METHODS:
            is_valid_publish_path, full_publish_path = validateDataSourcePath(publish_path)
            if not is_valid_publish_path:
                return None, (full_publish_path, 400)
        else:
            is_valid_publish_path, full_publish_path = validateDataSourcePath(publish_path)
            if not is_valid_publish_path:
                return None, (full_publish_path, 400)
            if not os.path.isfile(full_publish_path):
                return None, ("发布文件不存在", 404)
    else:
        is_valid_publish_path, full_publish_path = validateWorkspacePath(publish_path)
        if not is_valid_publish_path:
            return None, (full_publish_path, 400)
        if not os.path.exists(full_publish_path):
            return None, ("发布目录不存在", 404)

    visibility = _first_defined(
        data.get("visibility"),
        existing_metadata.get("visibility"),
        "private",
    )
    note = _first_defined(
        data.get("note"),
        existing_metadata.get("note"),
    )
    enabled_input = _first_defined(
        data.get("enabled"),
        existing_metadata.get("enabled"),
    )
    enabled = True if enabled_input is None else str(enabled_input).strip().lower() not in {"0", "false", "no", "off", "disabled"}
    incoming_custom_metadata = _safe_dict(data.get("customMetadata"))
    custom_metadata = dict(existing_custom_metadata)
    custom_metadata.update(incoming_custom_metadata)
    custom_metadata.pop("enabled", None)
    custom_metadata["sourceMode"] = source_mode_input
    if source_mode_input == "datasource":
        custom_metadata["sourcePath"] = workspace_path
        if normalized_publish_method in TITILER_PUBLISH_METHODS:
            custom_metadata["sourcePaths"] = source_entries
            custom_metadata["sourceEntryCount"] = len(source_entries)
            custom_metadata["sourceFileCount"] = len(resolved_sources)
            custom_metadata["optimizedSourceCount"] = 0
            custom_metadata.pop("mosaicJsonPath", None)
        else:
            custom_metadata["sourcePaths"] = [workspace_path]
            custom_metadata["sourceEntryCount"] = 1
            custom_metadata["sourceFileCount"] = 1
            custom_metadata["optimizedSourceCount"] = 0
    else:
        custom_metadata.pop("sourcePath", None)
        custom_metadata.pop("sourcePaths", None)
        custom_metadata.pop("mosaicJsonPath", None)
        custom_metadata.pop("sourceEntryCount", None)
        custom_metadata.pop("sourceFileCount", None)
        custom_metadata.pop("optimizedSourceCount", None)

    tile_profile = {} if source_mode_input == "datasource" else _resolve_tile_publish_profile(full_publish_path, metadata=existing_metadata, artifact=artifact)
    source_tile_scheme = _normalize_tile_scheme(
        _first_non_blank(
            incoming_custom_metadata.get("sourceTileScheme"),
            tile_profile.get("sourceTileScheme"),
            existing_custom_metadata.get("sourceTileScheme"),
        )
    )
    tile_extension = _first_non_blank(
        incoming_custom_metadata.get("tileExtension"),
        tile_profile.get("tileExtension"),
        existing_custom_metadata.get("tileExtension"),
    )
    if source_tile_scheme:
        custom_metadata["sourceTileScheme"] = source_tile_scheme
    if tile_extension:
        custom_metadata["tileExtension"] = tile_extension

    # Persist an explicit timezone-aware timestamp to avoid frontend double-shifting.
    published_at = datetime.now(timezone.utc).isoformat()
    descriptor = {
        "id": publication_id,
        "artifactId": artifact_id,
        "publishType": publish_type,
        "publishPath": publish_path,
        "alias": alias,
        "status": "enabled" if enabled else "disabled",
        "publishedAt": published_at,
        "createdAt": existing_publication.get("createdAt") or published_at,
        "metadata": {
            "artifactOutputPath": artifact.get("outputPath") if artifact else existing_metadata.get("artifactOutputPath"),
            "manifestPath": artifact.get("manifestPath") if artifact else existing_metadata.get("manifestPath"),
            "workspacePath": workspace_path or None,
            "sourcePath": workspace_path if source_mode_input == "datasource" else None,
            "sourcePaths": source_entries if source_mode_input == "datasource" else None,
            "sourceEntryCount": len(source_entries) if source_mode_input == "datasource" else None,
            "sourceFileCount": (
                len(resolved_sources) if normalized_publish_method in TITILER_PUBLISH_METHODS else len(source_entries)
            ) if source_mode_input == "datasource" else None,
            "optimizedSourceCount": 0 if source_mode_input == "datasource" and normalized_publish_method in TITILER_PUBLISH_METHODS else None,
            "mosaicJsonPath": None,
            "taskId": task_id or None,
            "sourceMode": source_mode_input,
            "publishMethod": publish_method,
            "visibility": visibility,
            "note": note,
            "enabled": enabled,
            "sourceTileScheme": source_tile_scheme,
            "tileExtension": tile_extension,
            "buildState": {
                "state": "pending" if source_mode_input == "datasource" and normalized_publish_method in TITILER_PUBLISH_METHODS else "ready",
                "progress": 0 if source_mode_input == "datasource" and normalized_publish_method in TITILER_PUBLISH_METHODS else 100,
                "message": "等待后台构建缓存" if source_mode_input == "datasource" and normalized_publish_method in TITILER_PUBLISH_METHODS else "已就绪",
                "error": None,
                "updatedAt": published_at,
            },
            "customMetadata": custom_metadata,
        },
    }

    return {
        "taskId": task_id,
        "artifactId": artifact_id,
        "workspacePath": workspace_path,
        "sourcePaths": source_entries,
        "sourceFileCount": len(resolved_sources),
        "publishType": publish_type,
        "alias": alias,
        "publicationId": publication_id,
        "publishPath": publish_path,
        "descriptor": descriptor,
        "publishedAt": published_at,
        "artifact": artifact,
        "mosaicJsonInfo": mosaic_json_info,
    }, None


def _ensure_publication_db_ready():
    require_db = bool(config.get("publicationRequireDb", True))
    if require_db and not isDatabaseEnabled():
        return False, ("数据库持久化未启用，发布记录不会入库。请设置 TF_DB_ENABLED=1 并重启服务。", 503)
    return True, None


def _manifest_summary(manifest, manifest_path=None):
    artifact = manifest.get("artifact", {}) if isinstance(manifest, dict) else {}
    task = manifest.get("task", {}) if isinstance(manifest, dict) else {}
    artifact_id = manifest.get("artifactId")
    return {
        "artifactId": artifact_id,
        "buildJobId": manifest.get("buildJobId"),
        "artifactType": artifact.get("type"),
        "format": artifact.get("format"),
        "outputPath": artifact.get("outputPath"),
        "manifestPath": manifest_path,
        "status": artifact.get("status") or task.get("status"),
        "fileCount": artifact.get("fileCount"),
        "totalSize": artifact.get("totalSize"),
        "bounds": artifact.get("bounds"),
        "generatedAt": manifest.get("generatedAt"),
    }


def _scan_manifest_files(limit=None):
    tiles_dir = config["tilesDir"]
    manifests = []
    if not os.path.exists(tiles_dir):
        return manifests

    for root, _, files in os.walk(tiles_dir):
        if "manifest.json" not in files:
            continue
        manifest_path = os.path.join(root, "manifest.json")
        try:
            manifest = _load_manifest(manifest_path)
            manifests.append(_manifest_summary(manifest, manifest_path=manifest_path))
        except Exception as exc:
            logMessage(f"读取 manifest 失败: {manifest_path} - {exc}", "WARNING")
        if limit is not None and len(manifests) >= limit:
            break
    return manifests


def _scan_publication_files(limit=None):
    publications_dir = os.path.join(config["tilesDir"], PUBLICATIONS_DIRNAME)
    records = []
    if not os.path.exists(publications_dir):
        return records

    for root, _, files in os.walk(publications_dir):
        if "publication.json" not in files:
            continue
        descriptor_path = os.path.join(root, "publication.json")
        try:
            with open(descriptor_path, "r", encoding="utf-8") as publication_file:
                publication = json.load(publication_file)
            publication["descriptorPath"] = descriptor_path
            records.append(publication)
        except Exception as exc:
            logMessage(f"读取 publication 失败: {descriptor_path} - {exc}", "WARNING")
        if limit is not None and len(records) >= limit:
            break
    return records


def _artifact_record_to_response(record):
    if not isinstance(record, dict):
        return None
    metadata = record.get("metadata") or {}
    return {
        "artifactId": record.get("id"),
        "buildJobId": record.get("buildJobId"),
        "artifactType": record.get("artifactType"),
        "version": record.get("version"),
        "format": record.get("format"),
        "outputPath": record.get("outputPath"),
        "bounds": record.get("bounds"),
        "metadata": metadata,
        "manifestPath": metadata.get("manifestPath"),
        "createdAt": record.get("createdAt"),
    }


def _publication_record_to_response(record, include_runtime_state=True, include_vector_details=True):
    if not isinstance(record, dict):
        return None
    metadata = record.get("metadata") or {}
    computed_access_payload = _build_publication_access_payload(
        record.get("publishPath"),
        metadata.get("publishMethod"),
        record.get("publishType"),
        record.get("id"),
        metadata,
    )
    response = _augment_publication_response({
        "publicationId": record.get("id"),
        "artifactId": record.get("artifactId"),
        "publishType": record.get("publishType"),
        "publishPath": record.get("publishPath"),
        "alias": record.get("alias"),
        "status": record.get("status"),
        "metadata": metadata,
        "browserUrl": record.get("browserUrl"),
        "accessUrl": record.get("accessUrl"),
        "launchUrl": record.get("launchUrl"),
        "sampleUrl": record.get("sampleUrl"),
        "publicBaseUrl": record.get("publicBaseUrl"),
        "publishedAt": record.get("publishedAt"),
        "createdAt": record.get("createdAt"),
        "updatedAt": record.get("updatedAt"),
    }, include_runtime_state=include_runtime_state, include_vector_details=include_vector_details)

    stored_base = str(record.get("publicBaseUrl") or "").strip()
    computed_base = str(computed_access_payload.get("publicBaseUrl") or "").strip()
    stored_access = str(record.get("accessUrl") or "").strip()
    computed_access = str(computed_access_payload.get("accessUrl") or "").strip()
    should_refresh_urls = any(not record.get(key) for key in ("browserUrl", "accessUrl", "launchUrl", "sampleUrl", "publicBaseUrl"))
    if not should_refresh_urls and computed_base and stored_base and stored_base != computed_base:
        should_refresh_urls = True
    if not should_refresh_urls and stored_access and computed_access and stored_access != computed_access:
        should_refresh_urls = True

    if should_refresh_urls:
        response.update(computed_access_payload)

    if should_refresh_urls and isDatabaseEnabled():
        try:
            persisted = upsertPublicationRecord(
                publication_id=record.get("id"),
                artifact_id=record.get("artifactId"),
                publish_type=record.get("publishType"),
                publish_path=record.get("publishPath"),
                alias=record.get("alias"),
                status=response.get("status") or record.get("status"),
                metadata=metadata,
                published_at=record.get("publishedAt"),
                browser_url=response.get("browserUrl"),
                access_url=response.get("accessUrl"),
                launch_url=response.get("launchUrl"),
                sample_url=response.get("sampleUrl"),
                public_base_url=response.get("publicBaseUrl"),
            )
            if not persisted:
                logMessage(f"发布 URL 回填失败: {record.get('id')}", "WARNING")
        except Exception as exc:
            logMessage(f"发布 URL 回填异常 {record.get('id')}: {exc}", "WARNING")
    return response


def _find_manifest_for_artifact(artifact_id):
    for summary in _scan_manifest_files(limit=500):
        if summary.get("artifactId") == artifact_id:
            return summary
    return None


def _resolve_artifact(artifact_id):
    record = fetchArtifactRecord(artifact_id)
    response = _artifact_record_to_response(record) if record else None
    if response:
        return response

    manifest_summary = _find_manifest_for_artifact(artifact_id)
    if manifest_summary:
        return manifest_summary
    return None


def listArtifacts():
    try:
        page, page_size = parse_pagination_args(request.args, default_page_size=10, max_page_size=200)
        artifact_type = request.args.get("artifactType")
        keyword = str(request.args.get("keyword", "")).strip().lower()

        artifacts = {}
        artifact_record_count = countTableRows("tf_artifacts")
        for record in listArtifactRecords(limit=max(50, artifact_record_count or 0)):
            response = _artifact_record_to_response(record)
            if not response:
                continue
            if artifact_type and response.get("artifactType") != artifact_type:
                continue
            artifacts[response["artifactId"]] = response

        for summary in _scan_manifest_files():
            artifact_id = summary.get("artifactId")
            if not artifact_id:
                continue
            if artifact_type and summary.get("artifactType") != artifact_type:
                continue
            artifacts.setdefault(artifact_id, summary)

        items = list(artifacts.values())
        if keyword:
            items = [
                item for item in items
                if any(
                    keyword in str(field or "").lower()
                    for field in (
                        item.get("artifactId"),
                        item.get("artifactType"),
                        item.get("format"),
                        item.get("outputPath"),
                        item.get("buildJobId"),
                    )
                )
            ]
        items.sort(key=lambda item: str(item.get("createdAt") or item.get("generatedAt") or ""), reverse=True)
        paged_items, pagination = paginate_items(items, page, page_size)

        return jsonify({
            "success": True,
            "artifacts": paged_items,
            **pagination,
        })
    except Exception as exc:
        logMessage(f"列出产物失败: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def getArtifact(artifact_id=None, artifactId=None):
    try:
        artifact_id = artifact_id or artifactId
        artifact = _resolve_artifact(artifact_id)
        if not artifact:
            return jsonify({"error": "产物不存在"}), 404
        return jsonify({"success": True, "artifact": artifact})
    except Exception as exc:
        logMessage(f"读取产物失败 {artifact_id}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def getArtifactManifest(artifact_id=None, artifactId=None):
    try:
        artifact_id = artifact_id or artifactId
        artifact = _resolve_artifact(artifact_id)
        if not artifact:
            return jsonify({"error": "产物不存在"}), 404

        manifest_path = artifact.get("manifestPath")
        if not manifest_path or not os.path.exists(manifest_path):
            return jsonify({"error": "manifest 不存在"}), 404

        manifest = _load_manifest(manifest_path)
        return jsonify({"success": True, "manifest": manifest})
    except Exception as exc:
        logMessage(f"读取产物 manifest 失败 {artifact_id}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def createPublication():
    try:
        db_ready, db_error = _ensure_publication_db_ready()
        if not db_ready:
            message, status_code = db_error
            return jsonify({"success": False, "error": message}), status_code

        data = request.get_json(silent=True) or {}
        prepared, error = _prepare_publication_payload(data)
        if error:
            message, status_code = error
            return jsonify({"error": message}), status_code

        descriptor = prepared["descriptor"]
        publication_id = prepared["publicationId"]
        artifact_id = prepared["artifactId"]
        publish_type = prepared["publishType"]
        publish_path = prepared["publishPath"]
        alias = prepared["alias"]
        task_id = prepared["taskId"]
        workspace_path = prepared["workspacePath"]
        artifact = prepared["artifact"]

        descriptor_path = _write_publication_descriptor(descriptor, alias)
        metadata = {
            "descriptorPath": descriptor_path,
            "artifactOutputPath": artifact.get("outputPath") if artifact else None,
            "manifestPath": artifact.get("manifestPath") if artifact else None,
            "workspacePath": workspace_path or None,
            "sourcePath": descriptor["metadata"].get("sourcePath"),
            "sourcePaths": descriptor["metadata"].get("sourcePaths"),
            "sourceEntryCount": descriptor["metadata"].get("sourceEntryCount"),
            "sourceFileCount": descriptor["metadata"].get("sourceFileCount"),
            "optimizedSourceCount": descriptor["metadata"].get("optimizedSourceCount"),
            "mosaicJsonPath": descriptor["metadata"].get("mosaicJsonPath"),
            "taskId": task_id or None,
            "sourceMode": descriptor["metadata"].get("sourceMode"),
            "publishMethod": descriptor["metadata"].get("publishMethod"),
            "visibility": descriptor["metadata"].get("visibility", "private"),
            "note": descriptor["metadata"].get("note"),
            "enabled": descriptor["metadata"].get("enabled", True),
            "sourceTileScheme": descriptor["metadata"].get("sourceTileScheme"),
            "tileExtension": descriptor["metadata"].get("tileExtension"),
            "buildState": descriptor["metadata"].get("buildState"),
            "customMetadata": descriptor["metadata"].get("customMetadata", {}),
        }
        prepared["descriptor"]["metadata"] = metadata
        initial_status = "draft" if _is_async_titiler_publication(prepared) else descriptor["status"]
        _persist_publication_record(prepared, metadata_override=metadata, status_override=initial_status)

        build_job_id = artifact.get("buildJobId") if artifact else None
        if build_job_id:
            appendJobEvent(
                build_job_id,
                "publication.created",
                {
                    "publicationId": publication_id,
                    "artifactId": artifact_id,
                    "taskId": task_id or None,
                    "publishType": publish_type,
                    "publishPath": publish_path,
                    "alias": alias,
                },
            )

        publication_response = _get_publication_snapshot(publication_id) or _augment_publication_response({
            **descriptor,
            "descriptorPath": descriptor_path,
            "publicationId": publication_id,
        })

        if _is_async_titiler_publication(prepared):
            _start_titiler_publication_build(prepared)

        logMessage(f"发布记录已创建: {publication_id} -> {artifact_id or task_id or workspace_path}", "INFO")
        return jsonify({
            "success": True,
            "publication": publication_response,
        })
    except Exception as exc:
        logMessage(f"创建发布记录失败: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def updatePublication(publication_id=None, publicationId=None):
    try:
        db_ready, db_error = _ensure_publication_db_ready()
        if not db_ready:
            message, status_code = db_error
            return jsonify({"success": False, "error": message}), status_code

        publication_id = publication_id or publicationId
        existing_publication = _get_publication_snapshot(publication_id)
        if not existing_publication:
            return jsonify({"error": "发布记录不存在"}), 404

        data = request.get_json(silent=True) or {}
        data["publicationId"] = str(data.get("publicationId", publication_id)).strip() or publication_id

        prepared, error = _prepare_publication_payload(data, existing_publication=existing_publication)
        if error:
            message, status_code = error
            return jsonify({"error": message}), status_code

        descriptor = prepared["descriptor"]
        if descriptor["metadata"].get("sourceMode") != "datasource":
            _cleanup_publication_runtime_dir(prepared["publicationId"])
        descriptor_path = _write_publication_descriptor(descriptor, prepared["alias"], previous_publication=existing_publication)
        metadata = {
            **descriptor["metadata"],
            "descriptorPath": descriptor_path,
        }
        prepared["descriptor"]["metadata"] = metadata
        if _is_async_titiler_publication(prepared):
            _cleanup_publication_runtime_dir(prepared["publicationId"])
            metadata = _mark_publication_build_state(metadata, state="pending", progress=0, message="等待后台构建缓存", error=None)
            metadata["mosaicJsonPath"] = None
            metadata["optimizedSourceCount"] = 0
            custom_metadata = _safe_dict(metadata.get("customMetadata"))
            custom_metadata.pop("mosaicJsonPath", None)
            custom_metadata["optimizedSourceCount"] = 0
            metadata["customMetadata"] = custom_metadata
            prepared["descriptor"]["metadata"] = metadata
        _persist_publication_record(
            prepared,
            metadata_override=prepared["descriptor"]["metadata"],
            status_override="draft" if _is_async_titiler_publication(prepared) else descriptor["status"],
        )

        if publication_id != prepared["publicationId"]:
            _cleanup_publication_runtime_dir(publication_id)
            deletePublicationRecord(publication_id)

        publication_response = _get_publication_snapshot(prepared["publicationId"]) or _augment_publication_response({
            **descriptor,
            "descriptorPath": descriptor_path,
            "publicationId": prepared["publicationId"],
        })

        if _is_async_titiler_publication(prepared):
            _start_titiler_publication_build(prepared)

        logMessage(f"发布记录已更新: {publication_id} -> {prepared['publicationId']}", "INFO")
        return jsonify({
            "success": True,
            "publication": publication_response,
        })
    except Exception as exc:
        logMessage(f"更新发布记录失败 {publication_id}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def listPublications():
    try:
        page, page_size = parse_pagination_args(request.args, default_page_size=10, max_page_size=200)
        keyword = str(request.args.get("keyword", "")).strip().lower()
        publish_type = str(request.args.get("publishType", "")).strip().lower()
        status_filter = str(request.args.get("status", "")).strip().lower()
        publications = {}

        for record in listPublicationRecords(limit=1000):
            response = _publication_record_to_response(record, include_runtime_state=False, include_vector_details=False)
            if not response:
                continue
            if not _is_supported_publication_record(response):
                continue
            publications[response["publicationId"]] = response

        if not isDatabaseEnabled():
            for record in _scan_publication_files():
                publication_id = record.get("id")
                if not publication_id:
                    continue
                publications.setdefault(
                    publication_id,
                    _augment_publication_response({
                        "publicationId": record.get("id"),
                        "artifactId": record.get("artifactId"),
                        "publishType": record.get("publishType"),
                        "publishPath": record.get("publishPath"),
                        "alias": record.get("alias"),
                        "status": record.get("status"),
                        "metadata": record.get("metadata", {}),
                        "publishedAt": record.get("publishedAt"),
                        "createdAt": record.get("createdAt"),
                        "descriptorPath": record.get("descriptorPath"),
                    }, include_runtime_state=False, include_vector_details=False),
                )
                if not _is_supported_publication_record(publications.get(publication_id)):
                    publications.pop(publication_id, None)

        items = list(publications.values())
        if publish_type:
            items = [item for item in items if str(item.get("publishType") or "").strip().lower() == publish_type]
        if status_filter:
            items = [item for item in items if str(item.get("status") or "").strip().lower() == status_filter]
        if keyword:
            items = [
                item for item in items
                if any(
                    keyword in str(field or "").lower()
                    for field in (
                        item.get("publicationId"),
                        item.get("alias"),
                        item.get("publishPath"),
                        item.get("accessUrl"),
                        (item.get("metadata") or {}).get("workspacePath"),
                        (item.get("metadata") or {}).get("taskId"),
                        (item.get("metadata") or {}).get("publishMethod"),
                        item.get("publishType"),
                        item.get("status"),
                    )
                )
            ]
        items.sort(key=lambda item: str(item.get("publishedAt") or item.get("createdAt") or ""), reverse=True)
        paged_items, pagination = paginate_items(items, page, page_size)
        return jsonify({
            "success": True,
            "publications": paged_items,
            **pagination,
        })
    except Exception as exc:
        logMessage(f"列出发布记录失败: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def getPublication(publication_id=None, publicationId=None):
    try:
        publication_id = publication_id or publicationId
        record = fetchPublicationRecord(publication_id)
        if record:
            return jsonify({"success": True, "publication": _publication_record_to_response(record)})

        if not isDatabaseEnabled():
            for publication in _scan_publication_files(limit=500):
                if publication.get("id") == publication_id:
                    return jsonify({"success": True, "publication": _augment_publication_response(publication)})

        return jsonify({"error": "发布记录不存在"}), 404
    except Exception as exc:
        logMessage(f"读取发布记录失败 {publication_id}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def deletePublication(publication_id=None, publicationId=None):
    try:
        publication_id = publication_id or publicationId
        publication = _get_publication_snapshot(publication_id)
        if not publication:
            return jsonify({"error": "发布记录不存在"}), 404

        _cleanup_publication_descriptor(publication)
        deletePublicationRecord(publication_id)

        logMessage(f"发布记录已删除: {publication_id}", "INFO")
        return jsonify({
            "success": True,
            "publicationId": publication_id,
        })
    except Exception as exc:
        logMessage(f"删除发布记录失败 {publication_id}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def _build_publication_update_payload(publication):
    metadata = _safe_dict((publication or {}).get("metadata"))
    source_mode = metadata.get("sourceMode") or ("datasource" if _is_titiler_publish_method(metadata.get("publishMethod")) else "manual")
    payload = {
        "publicationId": publication.get("publicationId") or publication.get("id"),
        "sourceMode": source_mode,
        "taskId": metadata.get("taskId"),
        "workspacePath": metadata.get("workspacePath"),
        "sourcePath": metadata.get("sourcePath"),
        "sourcePaths": metadata.get("sourcePaths"),
        "publishPath": publication.get("publishPath"),
        "alias": publication.get("alias"),
        "publishType": publication.get("publishType"),
        "publishMethod": metadata.get("publishMethod"),
        "enabled": metadata.get("enabled", True),
        "visibility": metadata.get("visibility"),
        "note": metadata.get("note"),
        "customMetadata": _safe_dict(metadata.get("customMetadata")),
    }
    if source_mode == "task":
        payload["workspacePath"] = None
        payload["sourcePath"] = None
        payload["sourcePaths"] = None
    elif source_mode == "manual":
        payload["taskId"] = None
        payload["sourcePath"] = None
        payload["sourcePaths"] = None
    elif source_mode == "datasource":
        payload["taskId"] = None
        payload["workspacePath"] = metadata.get("sourcePath") or metadata.get("workspacePath")
        payload["sourcePath"] = metadata.get("sourcePath") or metadata.get("workspacePath")
    return payload


def clearPublicationCache(publication_id=None, publicationId=None):
    try:
        publication_id = publication_id or publicationId
        publication = _get_publication_snapshot(publication_id)
        if not publication:
            return jsonify({"error": "发布记录不存在"}), 404
        metadata = _safe_dict(publication.get("metadata"))
        if metadata.get("sourceMode") != "datasource" or not _is_titiler_publish_method(metadata.get("publishMethod")):
            return jsonify({"error": "仅 TiTiler 数据源发布支持缓存清理"}), 400
        _cleanup_publication_runtime_dir(publication_id)
        response = _augment_publication_response(publication)
        logMessage(f"发布缓存已清理: {publication_id}", "INFO")
        return jsonify({"success": True, "publication": response, "action": "cache-cleared"})
    except Exception as exc:
        logMessage(f"清理发布缓存失败 {publication_id}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def rebuildPublicationCache(publication_id=None, publicationId=None):
    try:
        db_ready, db_error = _ensure_publication_db_ready()
        if not db_ready:
            message, status_code = db_error
            return jsonify({"success": False, "error": message}), status_code

        publication_id = publication_id or publicationId
        publication = _get_publication_snapshot(publication_id)
        if not publication:
            return jsonify({"error": "发布记录不存在"}), 404
        metadata = _safe_dict(publication.get("metadata"))
        if metadata.get("sourceMode") != "datasource" or not _is_titiler_publish_method(metadata.get("publishMethod")):
            return jsonify({"error": "仅 TiTiler 数据源发布支持缓存重建"}), 400

        payload = _build_publication_update_payload(publication)
        _cleanup_publication_runtime_dir(publication_id)
        prepared, error = _prepare_publication_payload(payload, existing_publication=publication)
        if error:
            message, status_code = error
            return jsonify({"error": message}), status_code
        descriptor = prepared["descriptor"]
        metadata = {
            **descriptor["metadata"],
            "descriptorPath": publication.get("descriptorPath") or _safe_dict(publication.get("metadata")).get("descriptorPath"),
        }
        metadata = _mark_publication_build_state(metadata, state="pending", progress=0, message="等待后台重建缓存", error=None)
        metadata["mosaicJsonPath"] = None
        metadata["optimizedSourceCount"] = 0
        custom_metadata = _safe_dict(metadata.get("customMetadata"))
        custom_metadata.pop("mosaicJsonPath", None)
        custom_metadata["optimizedSourceCount"] = 0
        metadata["customMetadata"] = custom_metadata
        prepared["descriptor"]["metadata"] = metadata
        _persist_publication_record(prepared, metadata_override=metadata, status_override="draft")
        _start_titiler_publication_build(prepared)

        response = _get_publication_snapshot(prepared["publicationId"]) or _augment_publication_response({
            **descriptor,
            "publicationId": prepared["publicationId"],
        })
        logMessage(f"发布缓存已进入后台重建: {publication_id}", "INFO")
        return jsonify({"success": True, "publication": response, "action": "cache-rebuild-started"})
    except Exception as exc:
        logMessage(f"重建发布缓存失败 {publication_id}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def _send_published_entry(full_path, normalized_path, url_builder=None):
    if os.path.isdir(full_path):
        for index_name in ("index.html", "index.htm"):
            index_path = os.path.join(full_path, index_name)
            if os.path.exists(index_path):
                return send_from_directory(full_path, index_name)

        entries = []
        for entry_name in sorted(os.listdir(full_path))[:200]:
            child_relative_path = _normalize_relative_path(os.path.join(normalized_path, entry_name))
            child_full_path = os.path.join(full_path, entry_name)
            entries.append({
                "name": entry_name,
                "path": child_relative_path,
                "type": "directory" if os.path.isdir(child_full_path) else "file",
                "url": url_builder(child_relative_path) if callable(url_builder) else _build_access_url(child_relative_path),
            })

        return jsonify({
            "success": True,
            "path": normalized_path,
            "type": "directory",
            "accessUrl": url_builder(normalized_path) if callable(url_builder) else _build_access_url(normalized_path),
            "entries": entries,
        })

    parent_dir = os.path.dirname(full_path)
    filename = os.path.basename(full_path)
    mimetype = _mime_from_extension(os.path.splitext(filename)[1])
    if mimetype:
        return send_from_directory(parent_dir, filename, mimetype=mimetype)
    return send_from_directory(parent_dir, filename)


def _resolve_publication_relative_path(base_full_path, relative_path):
    normalized_relative = _normalize_relative_path(relative_path)
    if not normalized_relative:
        return base_full_path

    target_path = os.path.abspath(os.path.join(base_full_path, normalized_relative.replace("/", os.sep)))
    if target_path != base_full_path and not target_path.startswith(f"{base_full_path}{os.sep}"):
        raise ValueError("目标路径非法")
    return target_path


def _resolve_publication_asset_path(publication, relative_path=""):
    metadata = _safe_dict(publication.get("metadata"))
    publish_path = publication.get("publishPath") or metadata.get("workspacePath")
    normalized_publish_path, full_publish_path = _resolve_tiles_path(publish_path)
    normalized_relative = _normalize_relative_path(relative_path)
    publish_method = str(metadata.get("publishMethod") or "").strip().lower()
    tile_request = _parse_tile_request_path(normalized_relative)

    if tile_request and publish_method in {"xyz", "tms"}:
        tile_profile = _resolve_tile_publish_profile(full_publish_path, metadata=metadata)
        source_tile_scheme = tile_profile.get("sourceTileScheme") or "tms"
        requested_tile_scheme = _target_tile_scheme_for_publish_method(publish_method)
        actual_y = _transform_tile_y(tile_request["zoom"], tile_request["y"], requested_tile_scheme, source_tile_scheme)
        if actual_y is None:
            raise FileNotFoundError("瓦片坐标超出范围")
        actual_relative = _normalize_relative_path(
            os.path.join(
                normalized_publish_path,
                str(tile_request["zoom"]),
                str(tile_request["x"]),
                f"{actual_y}{tile_request['extension']}",
            )
        )
        _, actual_full_path = _resolve_tiles_path(actual_relative)
        return actual_relative, actual_full_path

    resolved_full_path = _resolve_publication_relative_path(full_publish_path, normalized_relative)
    if not normalized_relative:
        return normalized_publish_path, resolved_full_path
    return f"{normalized_publish_path}/{normalized_relative}".strip("/"), resolved_full_path


def servePublishedPath(relative_path=""):
    try:
        redirect_url = _build_nginx_published_url(relative_path)
        return redirect(redirect_url, code=307)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logMessage(f"读取发布资源失败 {relative_path}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def servePublicationAsset(publication_id=None, relative_path=""):
    try:
        publication = _get_publication_snapshot(publication_id)
        if not publication:
            return jsonify({"error": "发布记录不存在"}), 404

        normalized_relative_path, full_path = _resolve_publication_asset_path(publication, relative_path)
        if not os.path.exists(full_path):
            return jsonify({"error": "目标发布资源不存在"}), 404

        return redirect(_build_nginx_published_url(normalized_relative_path), code=307)
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logMessage(f"读取发布资源失败 {publication_id}/{relative_path}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def _collect_publication_items(limit=500):
    publications = {}

    for record in listPublicationRecords(limit=limit):
        response = _publication_record_to_response(record, include_runtime_state=False, include_vector_details=False)
        if not response:
            continue
        if not _is_supported_publication_record(response):
            continue
        publication_id = response.get("publicationId")
        if publication_id:
            publications[publication_id] = response

    if not isDatabaseEnabled():
        for record in _scan_publication_files(limit=limit * 2):
            publication_id = record.get("id")
            if not publication_id:
                continue
            publications.setdefault(
                publication_id,
                _augment_publication_response({
                    "publicationId": record.get("id"),
                    "artifactId": record.get("artifactId"),
                    "publishType": record.get("publishType"),
                    "publishPath": record.get("publishPath"),
                    "alias": record.get("alias"),
                    "status": record.get("status"),
                    "metadata": record.get("metadata", {}),
                    "publishedAt": record.get("publishedAt"),
                    "createdAt": record.get("createdAt"),
                    "descriptorPath": record.get("descriptorPath"),
                }),
            )
            if not _is_supported_publication_record(publications.get(publication_id)):
                publications.pop(publication_id, None)

    return list(publications.values())


def _collect_wmts_layers():
    layers = []
    for publication in _collect_publication_items(limit=500):
        metadata = publication.get("metadata") or {}
        publish_method = str(metadata.get("publishMethod") or "").strip().lower()
        if publish_method != "wmts":
            continue

        enabled = metadata.get("enabled")
        if enabled is None:
            enabled = str(publication.get("status") or "").strip().lower() in {"enabled", "published", "active"}
        if not bool(enabled):
            continue

        publication_id = str(publication.get("publicationId") or publication.get("id") or "").strip()
        if not publication_id:
            continue

        publish_path = publication.get("publishPath") or metadata.get("workspacePath")
        normalized_path, full_path = _resolve_tiles_path(publish_path)
        tile_info = _find_tile_template_info(full_path)
        if not tile_info:
            continue

        tile_profile = _resolve_tile_publish_profile(full_path, metadata=metadata)
        source_tile_scheme = tile_profile.get("sourceTileScheme") or "tms"
        extension = str(tile_profile.get("tileExtension") or tile_info.get("extension") or "").strip().lower()
        mime_type = _mime_from_extension(extension)
        if not mime_type:
            continue

        sample_y = _transform_tile_y(tile_info.get("zoom") or 0, tile_info.get("y") or 0, source_tile_scheme, "google")
        if sample_y is None:
            sample_y = 0

        layers.append({
            "id": publication_id,
            "alias": str(publication.get("alias") or publication_id),
            "publishPath": normalized_path,
            "extension": extension,
            "mimeType": mime_type,
            "sourceTileScheme": source_tile_scheme,
            "sampleZoom": str(tile_info.get("zoom") or "0"),
            "sampleX": str(tile_info.get("x") or "0"),
            "sampleY": str(sample_y),
        })

    layers.sort(key=lambda item: item.get("id", ""))
    return layers


def _find_wmts_layer(layer_name, layers):
    token = str(layer_name or "").strip().lower()
    if not token:
        return None
    for layer in layers:
        layer_id = str(layer.get("id") or "").strip().lower()
        alias = str(layer.get("alias") or "").strip().lower()
        publish_path = str(layer.get("publishPath") or "").strip().lower()
        if token in {layer_id, alias, publish_path}:
            return layer
    return None


def _parse_wmts_matrix(value):
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("缺少参数 TILEMATRIX")
    if raw.isdigit():
        return int(raw)

    parts = [segment for segment in raw.split(":") if segment]
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    raise ValueError("参数 TILEMATRIX 非法")


def _build_wmts_capabilities(layers):
    namespaces = {
        "": "http://www.opengis.net/wmts/1.0",
        "ows": "http://www.opengis.net/ows/1.1",
        "xlink": "http://www.w3.org/1999/xlink",
    }
    ET.register_namespace("", namespaces[""])
    ET.register_namespace("ows", namespaces["ows"])
    ET.register_namespace("xlink", namespaces["xlink"])

    base_url = f"{_public_base_url().rstrip('/')}/wmts"
    capabilities = ET.Element(
        f"{{{namespaces['']}}}Capabilities",
        attrib={"version": "1.0.0"},
    )

    service_identification = ET.SubElement(capabilities, f"{{{namespaces['ows']}}}ServiceIdentification")
    ET.SubElement(service_identification, f"{{{namespaces['ows']}}}Title").text = "terra forge WMTS Service"
    ET.SubElement(service_identification, f"{{{namespaces['ows']}}}ServiceType").text = "OGC WMTS"
    ET.SubElement(service_identification, f"{{{namespaces['ows']}}}ServiceTypeVersion").text = "1.0.0"

    operations = ET.SubElement(capabilities, f"{{{namespaces['ows']}}}OperationsMetadata")
    for operation_name in ("GetCapabilities", "GetTile"):
        operation = ET.SubElement(operations, f"{{{namespaces['ows']}}}Operation", attrib={"name": operation_name})
        dcp = ET.SubElement(operation, f"{{{namespaces['ows']}}}DCP")
        http = ET.SubElement(dcp, f"{{{namespaces['ows']}}}HTTP")
        ET.SubElement(http, f"{{{namespaces['ows']}}}Get", attrib={f"{{{namespaces['xlink']}}}href": f"{base_url}?"})

    contents = ET.SubElement(capabilities, f"{{{namespaces['']}}}Contents")
    for layer in layers:
        layer_node = ET.SubElement(contents, f"{{{namespaces['']}}}Layer")
        ET.SubElement(layer_node, f"{{{namespaces['ows']}}}Title").text = layer["alias"]
        ET.SubElement(layer_node, f"{{{namespaces['ows']}}}Identifier").text = layer["id"]

        style = ET.SubElement(layer_node, f"{{{namespaces['']}}}Style", attrib={"isDefault": "true"})
        ET.SubElement(style, f"{{{namespaces['ows']}}}Identifier").text = "default"
        ET.SubElement(layer_node, f"{{{namespaces['']}}}Format").text = layer["mimeType"]

        resource_url = (
            f"{base_url}?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            f"&LAYER={quote(layer['id'], safe='')}&STYLE=default&TILEMATRIXSET={WMTS_DEFAULT_MATRIX_SET}"
            f"&TILEMATRIX={{TileMatrix}}&TILEROW={{TileRow}}&TILECOL={{TileCol}}&FORMAT={layer['mimeType']}"
        )
        ET.SubElement(
            layer_node,
            f"{{{namespaces['']}}}ResourceURL",
            attrib={"format": layer["mimeType"], "resourceType": "tile", "template": resource_url},
        )

        matrix_link = ET.SubElement(layer_node, f"{{{namespaces['']}}}TileMatrixSetLink")
        ET.SubElement(matrix_link, f"{{{namespaces['']}}}TileMatrixSet").text = WMTS_DEFAULT_MATRIX_SET

    tile_matrix_set = ET.SubElement(contents, f"{{{namespaces['']}}}TileMatrixSet")
    ET.SubElement(tile_matrix_set, f"{{{namespaces['ows']}}}Identifier").text = WMTS_DEFAULT_MATRIX_SET
    ET.SubElement(tile_matrix_set, f"{{{namespaces['ows']}}}SupportedCRS").text = "urn:ogc:def:crs:EPSG::3857"

    for zoom in range(WMTS_MIN_ZOOM, WMTS_MAX_ZOOM + 1):
        matrix = ET.SubElement(tile_matrix_set, f"{{{namespaces['']}}}TileMatrix")
        ET.SubElement(matrix, f"{{{namespaces['ows']}}}Identifier").text = str(zoom)
        ET.SubElement(matrix, f"{{{namespaces['']}}}ScaleDenominator").text = f"{WMTS_INITIAL_SCALE_DENOMINATOR / (2 ** zoom):.12f}"
        ET.SubElement(matrix, f"{{{namespaces['']}}}TopLeftCorner").text = WMTS_TOP_LEFT_CORNER
        ET.SubElement(matrix, f"{{{namespaces['']}}}TileWidth").text = "256"
        ET.SubElement(matrix, f"{{{namespaces['']}}}TileHeight").text = "256"
        ET.SubElement(matrix, f"{{{namespaces['']}}}MatrixWidth").text = str(2 ** zoom)
        ET.SubElement(matrix, f"{{{namespaces['']}}}MatrixHeight").text = str(2 ** zoom)

    payload = ET.tostring(capabilities, encoding="utf-8", xml_declaration=True)
    return Response(payload, status=200, content_type="application/xml; charset=utf-8")


def _serve_wmts_tile(layers):
    layer_name = _wmts_param("LAYER")
    if not layer_name:
        return _wmts_error("缺少参数 LAYER", locator="LAYER")

    tile_matrix_set = _wmts_param("TILEMATRIXSET", WMTS_DEFAULT_MATRIX_SET)
    if str(tile_matrix_set).strip().lower() not in WMTS_SUPPORTED_MATRIX_SET:
        return _wmts_error("参数 TILEMATRIXSET 不受支持", locator="TILEMATRIXSET")

    try:
        zoom = _parse_wmts_matrix(_wmts_param("TILEMATRIX"))
    except ValueError as exc:
        return _wmts_error(str(exc), locator="TILEMATRIX")

    try:
        tile_row = int(_wmts_param("TILEROW"))
        tile_col = int(_wmts_param("TILECOL"))
    except (TypeError, ValueError):
        return _wmts_error("参数 TILEROW 或 TILECOL 非法", locator="TILEROW/TILECOL")

    if zoom < WMTS_MIN_ZOOM or zoom > WMTS_MAX_ZOOM or tile_row < 0 or tile_col < 0:
        return _wmts_error("瓦片坐标超出范围", exception_code="TileOutOfRange", locator="TILEMATRIX/TILEROW/TILECOL", status_code=404)

    layer = _find_wmts_layer(layer_name, layers)
    if not layer:
        return _wmts_error("图层不存在", exception_code="LayerNotDefined", locator="LAYER", status_code=404)

    style = _wmts_param("STYLE", "default").strip().lower()
    if style not in {"", "default"}:
        return _wmts_error("参数 STYLE 不受支持", locator="STYLE")

    request_format = _wmts_param("FORMAT")
    if request_format:
        requested_extension = _extension_from_mime(request_format)
        if not requested_extension:
            return _wmts_error("参数 FORMAT 不受支持", locator="FORMAT")
        if requested_extension != layer["extension"]:
            return _wmts_error("请求 FORMAT 与图层格式不匹配", locator="FORMAT")

    max_index = 2 ** zoom
    if tile_row >= max_index or tile_col >= max_index:
        return _wmts_error("瓦片坐标超出范围", exception_code="TileOutOfRange", locator="TILEROW/TILECOL", status_code=404)

    actual_tile_row = _transform_tile_y(zoom, tile_row, "google", layer.get("sourceTileScheme") or "tms")
    if actual_tile_row is None:
        return _wmts_error("瓦片坐标超出范围", exception_code="TileOutOfRange", locator="TILEROW", status_code=404)

    tile_relative_path = f"{layer['publishPath']}/{zoom}/{tile_col}/{actual_tile_row}{layer['extension']}"
    _, tile_full_path = _resolve_tiles_path(tile_relative_path)
    if not os.path.exists(tile_full_path):
        return _wmts_error("瓦片不存在", exception_code="TileOutOfRange", locator="TILEMATRIX/TILEROW/TILECOL", status_code=404)

    parent_dir = os.path.dirname(tile_full_path)
    filename = os.path.basename(tile_full_path)
    return send_from_directory(parent_dir, filename, mimetype=layer["mimeType"])


def serveWmts():
    try:
        service = _wmts_param("SERVICE", "WMTS").strip().upper()
        if service and service != "WMTS":
            return _wmts_error("参数 SERVICE 必须为 WMTS", locator="SERVICE")

        operation = _wmts_param("REQUEST", "GetCapabilities").strip().lower()
        layers = _collect_wmts_layers()
        if operation == "getcapabilities":
            return _build_wmts_capabilities(layers)
        if operation == "gettile":
            return _serve_wmts_tile(layers)
        return _wmts_error("参数 REQUEST 不受支持，仅支持 GetCapabilities/GetTile", locator="REQUEST")
    except ValueError as exc:
        return _wmts_error(str(exc))
    except Exception as exc:
        logMessage(f"WMTS 服务异常: {exc}", "ERROR")
        return _wmts_error(str(exc), exception_code="NoApplicableCode", status_code=500)

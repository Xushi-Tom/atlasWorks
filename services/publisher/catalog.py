#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import os
import socket
import sqlite3
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlsplit
import xml.etree.ElementTree as ET

from flask import Response, has_request_context, jsonify, redirect, request, send_from_directory

from config import config, taskLock, taskStatus
from geoserverOps import deleteStore, getSeedStatus, publishGeoserverPayload
from db import (
    appendJobEvent,
    countTableRows,
    deletePublicationRecord,
    syncTaskSnapshot,
    fetchArtifactRecord,
    fetchPublicationRecord,
    fetchTaskSnapshot,
    isDatabaseEnabled,
    listArtifactRecords,
    listPublicationRecords,
    listPublicationRecordsPage,
    upsertPublicationRecord,
)
from pagination import paginate_items, parse_pagination_args
from taskState import normalizeTaskRecord
from utils import logMessage, normalizeProjection, validateDataSourcePath, validateWorkspacePath


PUBLICATIONS_DIRNAME = "_publications"
WMTS_DEFAULT_MATRIX_SET = "GoogleMapsCompatible"
WMTS_SUPPORTED_MATRIX_SET = {"googlemapscompatible", "epsg:3857", "epsg3857", "webmercatorquad"}
WMTS_TOP_LEFT_CORNER = "-20037508.342789244 20037508.342789244"
WMTS_INITIAL_SCALE_DENOMINATOR = 559082264.0287178
WMTS_MIN_ZOOM = 0
WMTS_MAX_ZOOM = 22
GEOSERVER_PUBLISH_METHODS = {"geoserver-wms", "geoserver-wmts"}
GEOSERVER_RASTER_EXTENSIONS = {".tif", ".tiff"}
DATASOURCE_PUBLISH_TYPE = "imagery"
DATASOURCE_PUBLISH_METHOD = "geoserver-wmts"
MBTILES_PUBLISH_METHOD = "mbtiles-mvt"
MBTILES_SOURCE_EXTENSIONS = {".geojson", ".json", ".shp", ".gpkg", ".mbtiles"}
MBTILES_VECTOR_SOURCE_EXTENSIONS = {".geojson", ".json", ".shp", ".gpkg"}
STATIC_MVT_PUBLISH_METHODS = {"mvt", "mvt-xyz", "mvt-tms", "vector-tile", "vector-tiles"}
STATIC_GEOJSON_TILE_METHODS = {"geojson-tile", "geojson-tiles"}
GEOSERVER_WMTS_GRIDSET = "EPSG:900913"
WEB_MERCATOR_MAX = 20037508.342789244
WEB_MERCATOR_MAX_LAT = 85.05112878
TIPPECANOE_RESILIENT_ARGS = [
    "--detect-shared-borders",
    "--coalesce-densest-as-needed",
    "--extend-zooms-if-still-dropping",
]


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
        ".terrain": "application/vnd.quantized-mesh",
    }
    return mapping.get(ext)


def _is_gzip_file(full_path):
    """检查文件头是否为 gzip，避免已解压的 terrain 被错误标记编码。"""
    try:
        with open(full_path, "rb") as file_obj:
            return file_obj.read(2) == b"\x1f\x8b"
    except OSError:
        return False


def _is_mbtiles_publish_method(publish_method):
    return str(publish_method or "").strip().lower() in {"mbtiles-mvt", "mvt-dynamic", "dynamic-mvt"}


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
    if normalized in {"xyz", "wmts", "mvt-xyz"}:
        return "google"
    if normalized in {"tms", "mvt-tms"}:
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
    projection = _first_non_blank(
        render_options.get("projection"),
        result_summary.get("projection"),
        build_parameters.get("projection"),
    )
    if projection:
        profile["sourceProjection"] = normalizeProjection(projection)
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
    stored_projection = _first_non_blank(
        metadata.get("sourceProjection"),
        custom_metadata.get("sourceProjection"),
        artifact_render_options.get("projection"),
        artifact_result.get("projection"),
        artifact_build_parameters.get("projection"),
    )
    if stored_projection:
        profile["sourceProjection"] = normalizeProjection(stored_projection)

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
            if not profile.get("sourceProjection") and render_options.get("projection"):
                profile["sourceProjection"] = normalizeProjection(render_options.get("projection"))
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
    profile["sourceProjection"] = normalizeProjection(profile.get("sourceProjection")) if profile.get("sourceProjection") else ""
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


def _mbtiles_metadata(mbtiles_path):
    metadata = {}
    with sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True) as connection:
        for name, value in connection.execute("SELECT name, value FROM metadata"):
            metadata[str(name)] = value
    json_metadata = metadata.get("json")
    if json_metadata:
        try:
            parsed = json.loads(json_metadata)
            if isinstance(parsed, dict):
                metadata["json"] = parsed
        except Exception:
            pass
    return metadata


def _parse_bounds(value):
    if isinstance(value, list) and len(value) == 4:
        try:
            return [float(item) for item in value]
        except Exception:
            return None
    parts = str(value or "").split(",")
    if len(parts) != 4:
        return None
    try:
        return [float(item.strip()) for item in parts]
    except Exception:
        return None


def _mbtiles_tilejson(publication, metadata=None):
    metadata = dict(metadata or {})
    publication_id = str(publication.get("publicationId") or publication.get("id") or "").strip()
    public_base = _public_base_url()
    vector_layers = []
    parsed_json = metadata.get("json")
    if isinstance(parsed_json, dict):
        vector_layers = parsed_json.get("vector_layers") or parsed_json.get("vectorLayers") or []
    if not isinstance(vector_layers, list):
        vector_layers = []
    return {
        "tilejson": "2.2.0",
        "name": metadata.get("name") or publication.get("alias") or publication_id,
        "format": "pbf",
        "scheme": "xyz",
        "minzoom": int(metadata.get("minzoom") or 0),
        "maxzoom": int(metadata.get("maxzoom") or 14),
        "bounds": _parse_bounds(metadata.get("bounds")) or [-180, -85.05112878, 180, 85.05112878],
        "center": _parse_bounds(metadata.get("center")),
        "tiles": [f"{public_base}/mvt/{publication_id}/{{z}}/{{x}}/{{y}}.pbf"],
        "vector_layers": vector_layers,
    }


def _resolve_mbtiles_publication(publication_id):
    publication = _get_publication_snapshot(publication_id)
    if not publication:
        return None, None, "发布记录不存在"
    metadata = _safe_dict(publication.get("metadata"))
    publish_method = metadata.get("publishMethod") or publication.get("publishMethod")
    if not _is_mbtiles_publish_method(publish_method):
        return None, None, "发布记录不是 MBTiles 动态 MVT"
    enabled = metadata.get("enabled")
    if enabled is None:
        enabled = str(publication.get("status") or "").strip().lower() in {"enabled", "published", "active"}
    if not bool(enabled):
        return None, None, "发布记录未启用"
    publish_path = publication.get("publishPath") or metadata.get("sourcePath") or metadata.get("workspacePath")
    normalized_path, full_path = _resolve_datasource_path(publish_path)
    if not os.path.isfile(full_path):
        return None, None, "MBTiles 文件不存在"
    if not full_path.lower().endswith(".mbtiles"):
        return None, None, "发布源不是 .mbtiles 文件"
    return publication, full_path, None


def _sanitize_mbtiles_layer_name(value):
    text = str(value or "").strip()
    text = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text).strip("_")
    if not text:
        text = "atlasworks_mvt"
    if text[0].isdigit():
        text = f"layer_{text}"
    return text[:63]


def _run_publish_command(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or f"命令执行失败: {' '.join(command)}")
    return result


def _build_mbtiles_from_vector_source(source_path, alias, custom_metadata=None):
    custom_metadata = _safe_dict(custom_metadata)
    min_zoom = max(0, min(22, int(custom_metadata.get("minZoom") or 0)))
    max_zoom = max(0, min(22, int(custom_metadata.get("maxZoom") or 14)))
    if max_zoom < min_zoom:
        raise ValueError("maxZoom 不能小于 minZoom")

    layer_name = _sanitize_mbtiles_layer_name(
        custom_metadata.get("layerName")
        or os.path.splitext(os.path.basename(source_path))[0]
        or alias
    )
    safe_alias = _sanitize_mbtiles_layer_name(alias or os.path.splitext(os.path.basename(source_path))[0] or "mbtiles")
    output_dir = os.path.join(config["dataSourceDir"], "_generated", "mbtiles")
    os.makedirs(output_dir, exist_ok=True)
    output_name = f"{safe_alias}-{datetime.now().strftime('%Y%m%d%H%M%S')}.mbtiles"
    output_path = os.path.join(output_dir, output_name)

    temp_dir = tempfile.mkdtemp(prefix="atlasworks-publish-mbtiles-")
    try:
        gpkg_path = os.path.join(temp_dir, "source_layers.gpkg")
        geojsonseq_path = os.path.join(temp_dir, "tippecanoe_input.geojsonseq")
        source_layer = _sanitize_mbtiles_layer_name(os.path.splitext(os.path.basename(source_path))[0] or layer_name)
        _run_publish_command([
            "ogr2ogr",
            "-f", "GPKG",
            gpkg_path,
            source_path,
            "-nln", source_layer,
            "-skipfailures",
        ])
        _run_publish_command([
            "ogr2ogr",
            "-f", "GeoJSONSeq",
            geojsonseq_path,
            gpkg_path,
            "-t_srs", "EPSG:4326",
        ])
        _run_publish_command([
            "tippecanoe",
            "-o", output_path,
            "-Z", str(min_zoom),
            "-z", str(max_zoom),
            "-l", layer_name,
            "--force",
            *TIPPECANOE_RESILIENT_ARGS,
            geojsonseq_path,
        ])
    finally:
        try:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

    relative_output = os.path.relpath(output_path, config["dataSourceDir"]).replace("\\", "/")
    return {
        "path": relative_output,
        "fullPath": output_path,
        "minZoom": min_zoom,
        "maxZoom": max_zoom,
        "layerName": layer_name,
    }


def _run_async_mbtiles_generation(publication_id, source_path, alias, custom_metadata=None):
    def _worker():
        try:
            publication = _get_publication_snapshot(publication_id)
            if not publication:
                return

            base_metadata = _safe_dict(publication.get("metadata"))
            merged_custom_metadata = _safe_dict(base_metadata.get("customMetadata"))
            merged_custom_metadata.update(_safe_dict(custom_metadata))

            generated = _build_mbtiles_from_vector_source(
                source_path,
                alias,
                merged_custom_metadata,
            )

            merged_custom_metadata.update({
                "generatedFrom": source_path,
                "generatedMbtiles": generated["path"],
                "minZoom": generated["minZoom"],
                "maxZoom": generated["maxZoom"],
                "layerName": generated["layerName"],
                "buildState": "ready",
                "buildError": "",
            })

            updated_metadata = {
                **base_metadata,
                "workspacePath": generated["path"],
                "sourcePath": generated["path"],
                "sourcePaths": [generated["path"]],
                "sourceEntryCount": 1,
                "sourceFileCount": 1,
                "customMetadata": merged_custom_metadata,
            }

            publication["publishPath"] = generated["path"]
            publication["status"] = "enabled" if bool(updated_metadata.get("enabled", True)) else "disabled"
            publication["metadata"] = updated_metadata
            publication["updatedAt"] = datetime.now(timezone.utc).isoformat()
            _persist_publication_snapshot(publication, metadata_override=updated_metadata, status_override=publication["status"])
            logMessage(f"动态 MVT 后台生成完成: {publication_id} -> {generated['path']}", "INFO")
        except Exception as exc:
            publication = _get_publication_snapshot(publication_id)
            if publication:
                failed_metadata = _safe_dict(publication.get("metadata"))
                failed_custom_metadata = _safe_dict(failed_metadata.get("customMetadata"))
                failed_custom_metadata.update({
                    "generatedFrom": source_path,
                    "buildState": "failed",
                    "buildError": str(exc),
                })
                failed_metadata["customMetadata"] = failed_custom_metadata
                publication["status"] = "failed"
                publication["metadata"] = failed_metadata
                publication["updatedAt"] = datetime.now(timezone.utc).isoformat()
                _persist_publication_snapshot(publication, metadata_override=failed_metadata, status_override="failed")
            logMessage(f"动态 MVT 后台生成失败 {publication_id}: {exc}", "ERROR")

    thread = threading.Thread(target=_worker, name=f"atlasworks-mbtiles-{publication_id}", daemon=True)
    thread.start()


def serveMbtilesTileJson(publication_id=None):
    try:
        publication, mbtiles_path, error = _resolve_mbtiles_publication(publication_id)
        if error:
            return jsonify({"success": False, "error": error}), 404
        metadata = _mbtiles_metadata(mbtiles_path)
        return jsonify(_mbtiles_tilejson(publication, metadata))
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logMessage(f"读取 MBTiles TileJSON 失败 {publication_id}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def serveMbtilesTile(publication_id=None, z=None, x=None, y=None):
    try:
        publication, mbtiles_path, error = _resolve_mbtiles_publication(publication_id)
        if error:
            return jsonify({"success": False, "error": error}), 404
        zoom = int(z)
        tile_column = int(x)
        xyz_y = int(str(y).split(".")[0])
        if zoom < 0 or tile_column < 0 or xyz_y < 0:
            return jsonify({"success": False, "error": "瓦片坐标非法"}), 400
        tile_row = (2 ** zoom - 1) - xyz_y
        if tile_row < 0:
            return jsonify({"success": False, "error": "瓦片坐标超出范围"}), 404
        with sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                (zoom, tile_column, tile_row),
            ).fetchone()
        if not row:
            return jsonify({"success": False, "error": "瓦片不存在"}), 404
        tile_data = row[0]
        response = Response(tile_data, mimetype="application/vnd.mapbox-vector-tile")
        if bytes(tile_data[:2]) == b"\x1f\x8b":
            response.headers["Content-Encoding"] = "gzip"
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
    except ValueError:
        return jsonify({"success": False, "error": "瓦片坐标非法"}), 400
    except Exception as exc:
        logMessage(f"读取 MBTiles 瓦片失败 {publication_id}/{z}/{x}/{y}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


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


def _public_base_url():
    configured_base_url = str(config.get("publicBaseUrl") or "").strip().rstrip("/")
    if configured_base_url:
        return configured_base_url

    if not has_request_context():
        configured_base_host = str(config.get("publicBaseHost") or "").strip()
        target_scheme = str(config.get("publicBaseScheme") or "http").strip() or "http"
        try:
            explicit_port = int(config.get("publicBasePort") or 0)
        except (TypeError, ValueError):
            explicit_port = 0
        target_port = explicit_port or int(config.get("port") or 18000)
        if configured_base_host:
            return _build_host_url(target_scheme, configured_base_host, target_port)
        detected_host = _detect_container_ip() or "127.0.0.1"
        return _build_host_url(target_scheme, detected_host, target_port)

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

    zoom_names = sorted(
        [name for name in os.listdir(full_path) if str(name).isdigit()],
        key=lambda value: int(value),
        reverse=True,
    )
    for zoom_name in zoom_names:
        zoom_dir = os.path.join(full_path, str(zoom_name))
        if not os.path.isdir(zoom_dir):
            continue

        x_names = sorted(
            [name for name in os.listdir(zoom_dir) if str(name).isdigit() and os.path.isdir(os.path.join(zoom_dir, str(name)))],
            key=lambda value: int(value),
        )
        if not x_names:
            continue

        x_name = x_names[len(x_names) // 2]
        x_dir = os.path.join(zoom_dir, str(x_name))
        tile_candidates = []
        for filename in sorted(os.listdir(x_dir)):
            if filename.endswith(".aux.xml"):
                continue
            stem, extension = os.path.splitext(filename)
            if not stem.isdigit() or not extension:
                continue
            tile_candidates.append((stem, extension))

        if not tile_candidates:
            continue

        y_name, extension = tile_candidates[len(tile_candidates) // 2]
        return {
            "extension": extension,
            "zoom": str(zoom_name),
            "x": str(x_name),
            "y": y_name,
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


def _tile_metadata_wgs84_bounds(full_path):
    metadata_path = os.path.join(full_path, "tile_metadata.json")
    if not os.path.isfile(metadata_path):
        return None
    try:
        with open(metadata_path, "r", encoding="utf-8") as file_obj:
            tile_metadata = json.load(file_obj)
    except Exception as exc:
        logMessage(f"读取 tile_metadata 范围失败: {metadata_path} - {exc}", "WARNING")
        return None
    bounds = _normalize_wgs84_bounds(tile_metadata.get("bounds"))
    if bounds and (abs(bounds[2] - bounds[0]) > 20 or abs(bounds[3] - bounds[1]) > 12):
        return None
    if bounds:
        return bounds
    source_bounds = []
    for tile_info in tile_metadata.get("tileIndex") or []:
        for source_file in _safe_dict(tile_info).get("sourceFiles") or []:
            source_bounds.append(_safe_dict(source_file).get("bounds"))
    return _union_wgs84_bounds(source_bounds)


def _normalize_wgs84_bounds(bounds):
    if not (isinstance(bounds, list) and len(bounds) == 4):
        return None
    try:
        west, south, east, north = [float(value) for value in bounds]
    except (TypeError, ValueError):
        return None
    if west < -180 or east > 180 or south < -90 or north > 90:
        return None
    west = max(-180.0, min(180.0, west))
    east = max(-180.0, min(180.0, east))
    south = max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, south))
    north = max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, north))
    if west >= east or south >= north:
        return None
    return [west, south, east, north]


def _web_mercator_to_wgs84_bounds(bounds):
    try:
        west, south, east, north = [float(value) for value in bounds]
    except (TypeError, ValueError):
        return None
    if west >= east or south >= north:
        return None
    west = max(-WEB_MERCATOR_MAX, min(WEB_MERCATOR_MAX, west))
    east = max(-WEB_MERCATOR_MAX, min(WEB_MERCATOR_MAX, east))
    south = max(-WEB_MERCATOR_MAX, min(WEB_MERCATOR_MAX, south))
    north = max(-WEB_MERCATOR_MAX, min(WEB_MERCATOR_MAX, north))

    def mercator_x_to_lon(value):
        return (value / WEB_MERCATOR_MAX) * 180.0

    def mercator_y_to_lat(value):
        return math.degrees(2.0 * math.atan(math.exp(value / 6378137.0)) - (math.pi / 2.0))

    return _normalize_wgs84_bounds([
        mercator_x_to_lon(west),
        mercator_y_to_lat(south),
        mercator_x_to_lon(east),
        mercator_y_to_lat(north),
    ])


def _union_wgs84_bounds(bounds_list):
    valid_bounds = [_normalize_wgs84_bounds(bounds) for bounds in bounds_list]
    valid_bounds = [bounds for bounds in valid_bounds if bounds]
    if not valid_bounds:
        return None
    return [
        min(bounds[0] for bounds in valid_bounds),
        min(bounds[1] for bounds in valid_bounds),
        max(bounds[2] for bounds in valid_bounds),
        max(bounds[3] for bounds in valid_bounds),
    ]


def _dataset_wgs84_bounds(full_path):
    try:
        from osgeo import gdal, osr
    except Exception as exc:
        logMessage(f"GDAL 不可用，无法读取数据源范围: {exc}", "WARNING")
        return None

    dataset = gdal.Open(full_path)
    if dataset is None:
        return None
    try:
        transform = dataset.GetGeoTransform(can_return_null=True)
        if not transform:
            return None
        width = int(dataset.RasterXSize or 0)
        height = int(dataset.RasterYSize or 0)
        if width <= 0 or height <= 0:
            return None

        pixel_corners = ((0, 0), (width, 0), (0, height), (width, height))
        points = [
            (
                transform[0] + px * transform[1] + py * transform[2],
                transform[3] + px * transform[4] + py * transform[5],
            )
            for px, py in pixel_corners
        ]

        projection = dataset.GetProjection() or dataset.GetProjectionRef() or ""
        if projection:
            source_srs = osr.SpatialReference()
            if source_srs.ImportFromWkt(projection) == 0:
                target_srs = osr.SpatialReference()
                target_srs.ImportFromEPSG(4326)
                source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                transform_to_wgs84 = osr.CoordinateTransformation(source_srs, target_srs)
                points = [transform_to_wgs84.TransformPoint(x, y)[:2] for x, y in points]

        bounds = [
            min(point[0] for point in points),
            min(point[1] for point in points),
            max(point[0] for point in points),
            max(point[1] for point in points),
        ]
        return _normalize_wgs84_bounds(bounds)
    except Exception as exc:
        logMessage(f"读取数据源范围失败: {full_path} - {exc}", "WARNING")
        return None
    finally:
        dataset = None


def _datasource_wgs84_bounds(source_paths):
    bounds_list = []
    for source_path in _normalize_data_source_paths(source_paths if isinstance(source_paths, list) else [source_paths]):
        try:
            _, full_path = _resolve_data_source_path(source_path)
        except Exception as exc:
            logMessage(f"数据源范围路径解析失败: {source_path} - {exc}", "WARNING")
            continue
        candidate_files = []
        if os.path.isfile(full_path):
            candidate_files = [full_path]
        elif os.path.isdir(full_path):
            candidate_files = [
                os.path.join(full_path, name)
                for name in sorted(os.listdir(full_path))
                if os.path.splitext(name)[1].lower() in GEOSERVER_RASTER_EXTENSIONS
            ]
        for candidate in candidate_files:
            bounds = _dataset_wgs84_bounds(candidate)
            if bounds:
                bounds_list.append(bounds)
    return _union_wgs84_bounds(bounds_list)


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


def _resolve_datasource_path(path_value=""):
    normalized_path = _normalize_relative_path(path_value)
    data_root = os.path.abspath(config["dataSourceDir"])
    full_path = os.path.abspath(os.path.join(data_root, normalized_path))
    if full_path != data_root and not full_path.startswith(f"{data_root}{os.sep}"):
        raise ValueError("数据源路径非法")
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


def _is_geoserver_publish_method(publish_method):
    return str(publish_method or "").strip().lower() in GEOSERVER_PUBLISH_METHODS


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
        return _is_geoserver_publish_method(publish_method) or _is_mbtiles_publish_method(publish_method)
    return True


def _record_geoserver_seed_task(publication_id, alias, publish_result_payload):
    seed_payload = publish_result_payload.get("seed")
    seed_error = str(publish_result_payload.get("seedError") or "").strip()
    if not seed_payload and not seed_error:
        return None

    task_id = f"geoserver-seed-{publication_id}"
    success = not seed_error
    message = "GeoServer 预切片已提交" if success else f"GeoServer 预切片失败: {seed_error}"
    status = "completed" if success else "failed"
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    task_payload = normalizeTaskRecord(task_id, {
        "taskId": task_id,
        "status": status,
        "progress": 100 if success else 0,
        "message": message,
        "startTime": now_text,
        "endTime": now_text,
        "currentStage": "GeoServer 预切片",
        "result": {
            "method": "geoserver-seed",
            "publicationId": publication_id,
            "layerName": publish_result_payload.get("layerName"),
            "workspace": publish_result_payload.get("workspace"),
            "seed": seed_payload,
            "seedError": seed_error or None,
        },
        "files": {"total": 1, "completed": 1 if success else 0, "failed": 0 if success else 1, "current": alias},
        "stats": {"totalTiles": 0, "processedTiles": 0, "failedTiles": 0 if success else 1, "remainingTiles": 0},
    })

    with taskLock:
        taskStatus[task_id] = task_payload
    syncTaskSnapshot(task_id, task_payload)
    return task_id


def _geoserver_public_base_url():
    explicit = str(config.get("geoserverPublicBaseUrl") or "").strip()
    if explicit:
        return explicit.rstrip("/")

    host = str(config.get("publicBaseHost") or "localhost").strip() or "localhost"
    if "://" in host:
        return host.rstrip("/")
    scheme = str(config.get("publicBaseScheme") or "http").strip() or "http"
    port = int(config.get("geoserverPublicBasePort") or 18083)
    return f"{scheme}://{host}:{port}/geoserver"


def _build_geoserver_urls(layer_name="", workspace=""):
    normalized_layer = str(layer_name or "").strip()
    normalized_workspace = str(workspace or config.get("geoserverWorkspace") or "atlasworks").strip()
    layer_id = f"{normalized_workspace}:{normalized_layer}" if normalized_workspace else normalized_layer
    encoded_layer = quote(layer_id, safe=":")
    public_base = _geoserver_public_base_url()
    wms_url = (
        f"{public_base}/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
        f"&LAYERS={encoded_layer}&STYLES=&SRS=EPSG:3857"
        "&BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=true"
    )
    wmts_capabilities_url = f"{public_base}/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetCapabilities"
    wmts_template_url = (
        f"{public_base}/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
        f"&LAYER={encoded_layer}&STYLE=raster&TILEMATRIXSET={GEOSERVER_WMTS_GRIDSET}"
        f"&TILEMATRIX={GEOSERVER_WMTS_GRIDSET}:{{z}}&TILEROW={{y}}&TILECOL={{x}}&FORMAT=image/png"
    )
    wmts_sample_url = (
        f"{public_base}/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
        f"&LAYER={encoded_layer}&STYLE=raster&TILEMATRIXSET={GEOSERVER_WMTS_GRIDSET}&TILEMATRIX={GEOSERVER_WMTS_GRIDSET}:0&TILEROW=0&TILECOL=0&FORMAT=image/png"
    )
    return {
        "browserUrl": wmts_sample_url,
        "accessUrl": wmts_template_url,
        "launchUrl": wmts_capabilities_url,
        "sampleUrl": wmts_sample_url,
        "backendBaseUrl": public_base,
        "layerId": layer_id,
        "wmsUrl": wms_url,
        "wmtsCapabilitiesUrl": wmts_capabilities_url,
        "wmtsTileUrl": wmts_template_url,
        "wmtsTileMatrixSet": GEOSERVER_WMTS_GRIDSET,
    }


def _build_geoserver_wms_url(layer_names=None, workspace=""):
    names = [str(item or "").strip() for item in (layer_names or []) if str(item or "").strip()]
    if not names:
        return ""
    normalized_workspace = str(workspace or config.get("geoserverWorkspace") or "atlasworks").strip()
    layer_ids = ",".join(f"{normalized_workspace}:{name}" if normalized_workspace else name for name in names)
    return (
        f"{_geoserver_public_base_url()}/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap"
        f"&LAYERS={quote(layer_ids, safe=':,')}&STYLES=&SRS=EPSG:3857"
        "&BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=true"
    )


def _extract_geoserver_bounds(layer_info):
    coverage = _safe_dict(_safe_dict(layer_info).get("coverage"))
    for bbox_name in ("latLonBoundingBox", "latlonBoundingBox"):
        lat_lon_bbox = _safe_dict(coverage.get(bbox_name))
        west = _first_defined(lat_lon_bbox.get("minx"), lat_lon_bbox.get("minX"))
        south = _first_defined(lat_lon_bbox.get("miny"), lat_lon_bbox.get("minY"))
        east = _first_defined(lat_lon_bbox.get("maxx"), lat_lon_bbox.get("maxX"))
        north = _first_defined(lat_lon_bbox.get("maxy"), lat_lon_bbox.get("maxY"))
        bounds = _normalize_wgs84_bounds([west, south, east, north])
        if bounds:
            return bounds

    native_bbox = _safe_dict(coverage.get("nativeBoundingBox"))
    west = _first_defined(native_bbox.get("minx"), native_bbox.get("minX"))
    south = _first_defined(native_bbox.get("miny"), native_bbox.get("minY"))
    east = _first_defined(native_bbox.get("maxx"), native_bbox.get("maxX"))
    north = _first_defined(native_bbox.get("maxy"), native_bbox.get("maxY"))
    raw_native_bounds = [west, south, east, north]
    native_crs = str(
        _first_non_blank(
            native_bbox.get("crs"),
            coverage.get("nativeCRS"),
            coverage.get("srs"),
            coverage.get("nativeSRS"),
        )
        or ""
    ).upper()
    if "3857" in native_crs or "900913" in native_crs:
        return _web_mercator_to_wgs84_bounds(raw_native_bounds)
    bounds = _normalize_wgs84_bounds(raw_native_bounds)
    if bounds:
        return bounds
    return None


def _publication_bounds(payload=None, metadata=None):
    candidates = (
        _safe_dict(payload).get("bounds"),
        _safe_dict(metadata).get("bounds"),
        _safe_dict(_safe_dict(payload).get("customMetadata")).get("bounds"),
        _safe_dict(_safe_dict(metadata).get("customMetadata")).get("bounds"),
    )
    for candidate in candidates:
        bounds = _normalize_wgs84_bounds(candidate)
        if bounds:
            return bounds
    return None


def _filter_focus_bounds(bounds):
    normalized = _normalize_wgs84_bounds(bounds)
    if not normalized:
        return None
    if abs(normalized[2] - normalized[0]) > 20 or abs(normalized[3] - normalized[1]) > 12:
        return None
    return normalized


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

    if _is_mbtiles_publish_method(publish_method):
        publication_key = str(publication_id or "").strip()
        if publication_key:
            access_url = f"{public_base}/mvt/{publication_key}/{{z}}/{{x}}/{{y}}.pbf"
            launch_url = f"{public_base}/mvt/{publication_key}/tiles.json"
            sample_url = f"{public_base}/mvt/{publication_key}/0/0/0.pbf"
            browser_url = launch_url
        return {
            "browserUrl": browser_url,
            "accessUrl": access_url,
            "launchUrl": launch_url,
            "sampleUrl": sample_url,
            "publicBaseUrl": public_base,
        }

    if publish_method in GEOSERVER_PUBLISH_METHODS:
        metadata_layer_names = metadata.get("geoserverLayerNames") or _safe_dict(metadata.get("customMetadata")).get("geoserverLayerNames")
        geoserver_urls = _build_geoserver_urls(
            layer_name=_first_non_blank(
                metadata.get("geoserverLayerName"),
                metadata.get("layerName"),
                publication_id,
                normalized_path,
            ),
            workspace=_first_non_blank(
                metadata.get("geoserverWorkspace"),
                config.get("geoserverWorkspace"),
                "atlasworks",
            ),
        )
        if isinstance(metadata_layer_names, list) and len(metadata_layer_names) > 1:
            geoserver_urls["wmsUrl"] = _build_geoserver_wms_url(
                metadata_layer_names,
                _first_non_blank(
                    metadata.get("geoserverWorkspace"),
                    config.get("geoserverWorkspace"),
                    "atlasworks",
                ),
            )
        return {
            "browserUrl": geoserver_urls["browserUrl"],
            "accessUrl": geoserver_urls["accessUrl"],
            "launchUrl": geoserver_urls["launchUrl"],
            "sampleUrl": geoserver_urls["sampleUrl"],
            "publicBaseUrl": public_base,
            "backendBaseUrl": geoserver_urls["backendBaseUrl"],
            "layerId": geoserver_urls["layerId"],
            "wmsUrl": geoserver_urls.get("wmsUrl"),
            "wmtsCapabilitiesUrl": geoserver_urls.get("wmtsCapabilitiesUrl"),
            "wmtsTileUrl": geoserver_urls.get("wmtsTileUrl"),
            "wmtsTileMatrixSet": geoserver_urls.get("wmtsTileMatrixSet"),
        }

    _, full_path = _resolve_tiles_path(normalized_path)
    tile_profile = _resolve_tile_publish_profile(full_path, metadata=metadata)
    source_tile_scheme = tile_profile.get("sourceTileScheme") or "tms"
    target_tile_scheme = _target_tile_scheme_for_publish_method(publish_method)
    is_vector_tile_publish = publish_method in STATIC_MVT_PUBLISH_METHODS or publish_method in STATIC_GEOJSON_TILE_METHODS
    tileset_entry = _find_tileset_entry(full_path) if publish_method == "3d-tiles" or publish_type == "3dtiles" else None
    enable_tile_template = (
        publish_method in {"wmts", "tms", "xyz", "quantized-mesh", "cesium-terrain", "terrain"} or publish_method in STATIC_MVT_PUBLISH_METHODS or publish_method in STATIC_GEOJSON_TILE_METHODS
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

        if (publish_method in {"xyz", "tms"} or publish_method in {"mvt-xyz", "mvt-tms"}) and publication_id:
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
    publish_method = str(response.get("publishMethod") or metadata.get("publishMethod") or "").strip().lower()
    publish_type = str(response.get("publishType") or "").strip().lower()
    publish_path = response.get("publishPath") or metadata.get("workspacePath")
    response["bounds"] = _filter_focus_bounds(_publication_bounds(response, metadata))
    if not response["bounds"] and not _is_mbtiles_publish_method(publish_method):
        try:
            _, full_path = _resolve_tiles_path(publish_path)
            response["bounds"] = _tile_metadata_wgs84_bounds(full_path)
            if response["bounds"]:
                metadata["bounds"] = response["bounds"]
        except Exception as exc:
            logMessage(f"补充瓦片发布范围失败: {publish_path} - {exc}", "WARNING")
    response["sourceEntryCount"] = int(metadata.get("sourceEntryCount") or 0)
    response["sourceFileCount"] = int(metadata.get("sourceFileCount") or 0)

    if publish_path and not metadata.get("sourceProjection") and not _is_mbtiles_publish_method(publish_method):
        try:
            _, full_path = _resolve_tiles_path(publish_path)
            tile_profile = _resolve_tile_publish_profile(full_path, metadata=metadata)
            if tile_profile.get("sourceProjection"):
                metadata["sourceProjection"] = tile_profile.get("sourceProjection")
        except Exception as exc:
            logMessage(f"补充发布投影信息失败: {publish_path} - {exc}", "WARNING")
    response["sourceProjection"] = metadata.get("sourceProjection") or ""
    is_vector_tile_publish = publish_method in STATIC_MVT_PUBLISH_METHODS or publish_method in STATIC_GEOJSON_TILE_METHODS or _is_mbtiles_publish_method(publish_method) or publish_type == "vector"
    if include_vector_details and is_vector_tile_publish and publish_path:
        try:
            if _is_mbtiles_publish_method(publish_method):
                normalized_path, full_path = _resolve_datasource_path(publish_path)
                mbtiles_meta = _mbtiles_metadata(full_path) if os.path.isfile(full_path) else {}
                vector_tileset = _mbtiles_tilejson(response, mbtiles_meta) if mbtiles_meta else None
            else:
                normalized_path, full_path = _resolve_tiles_path(publish_path)
                vector_tileset = _load_vector_tileset_metadata(full_path)
            if vector_tileset:
                vector_publication = {
                    "kind": "mvt" if publish_method in STATIC_MVT_PUBLISH_METHODS or _is_mbtiles_publish_method(publish_method) else "geojson",
                    "tileJsonUrl": response.get("launchUrl"),
                    "xyzTemplate": response.get("accessUrl"),
                    "sampleTileUrl": response.get("sampleUrl"),
                    "tilesetUrl": response.get("launchUrl") if _is_mbtiles_publish_method(publish_method) else f"{_public_base_url()}/published/{normalized_path}/tileset.json",
                    "format": vector_tileset.get("format"),
                    "scheme": vector_tileset.get("scheme"),
                    "minzoom": vector_tileset.get("minzoom"),
                    "maxzoom": vector_tileset.get("maxzoom"),
                    "bounds": vector_tileset.get("bounds"),
                    "vectorLayers": vector_tileset.get("vectorLayers") or vector_tileset.get("vector_layers") or [],
                }
                response["vectorPublication"] = vector_publication
                metadata["vectorLayers"] = vector_publication["vectorLayers"]
        except Exception as exc:
            logMessage(f"补充矢量发布详情失败: {publish_path} - {exc}", "WARNING")

    return response


def _publication_descriptor_dir(alias):
    return os.path.join(config["tilesDir"], PUBLICATIONS_DIRNAME, str(alias or "").strip() or "publication")
def _persist_publication_record(prepared, metadata_override=None, status_override=None, touch_record_timestamp=True):
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
        touch_updated_at=touch_record_timestamp,
    )
    if isDatabaseEnabled() and not persisted:
        raise RuntimeError("发布记录写入数据库失败")
    return access_payload


def _publish_geoserver_publication(prepared, metadata):
    metadata = _safe_dict(metadata)
    custom_metadata = _safe_dict(metadata.get("customMetadata"))
    alias = prepared.get("alias")
    geoserver_payload = {
        "workspace": _first_non_blank(
            metadata.get("geoserverWorkspace"),
            custom_metadata.get("geoserverWorkspace"),
            config.get("geoserverWorkspace"),
            "atlasworks",
        ),
        "alias": alias,
        "sourcePath": metadata.get("sourcePath") or metadata.get("workspacePath") or prepared.get("workspacePath"),
        "targetCrs": _first_non_blank(
            metadata.get("sourceProjection"),
            custom_metadata.get("sourceProjection"),
            custom_metadata.get("targetCrs"),
            "EPSG:3857",
        ),
        "minZoom": custom_metadata.get("minZoom", 0),
        "maxZoom": custom_metadata.get("maxZoom", 16),
        "seedEnabled": bool(custom_metadata.get("seedEnabled")),
        "tileFormat": custom_metadata.get("tileFormat", "image/png"),
        "styleName": custom_metadata.get("styleName", "raster"),
        "nodataValue": custom_metadata.get("nodataValue"),
        "overwrite": True,
    }
    publish_result_payload = publishGeoserverPayload(geoserver_payload)
    datasource_bounds = _datasource_wgs84_bounds(
        metadata.get("sourcePaths")
        or custom_metadata.get("sourcePaths")
        or [geoserver_payload.get("sourcePath")]
    )
    metadata["geoserverWorkspace"] = publish_result_payload.get("workspace")
    metadata["geoserverLayerName"] = publish_result_payload.get("layerName")
    metadata["geoserverLayerNames"] = publish_result_payload.get("layerNames")
    metadata["geoserverStoreName"] = publish_result_payload.get("storeName")
    metadata["geoserverStoreNames"] = publish_result_payload.get("storeNames")
    metadata["geoserverMode"] = publish_result_payload.get("mode")
    metadata["sourceProjection"] = geoserver_payload.get("targetCrs")
    metadata["seed"] = publish_result_payload.get("seed")
    metadata["seedError"] = publish_result_payload.get("seedError")
    metadata["bounds"] = _extract_geoserver_bounds(publish_result_payload.get("layerInfo")) or datasource_bounds
    custom_metadata["geoserverWorkspace"] = publish_result_payload.get("workspace")
    custom_metadata["geoserverLayerName"] = publish_result_payload.get("layerName")
    custom_metadata["geoserverLayerNames"] = publish_result_payload.get("layerNames")
    custom_metadata["geoserverStoreName"] = publish_result_payload.get("storeName")
    custom_metadata["geoserverStoreNames"] = publish_result_payload.get("storeNames")
    custom_metadata["geoserverMode"] = publish_result_payload.get("mode")
    custom_metadata["targetCrs"] = geoserver_payload.get("targetCrs")
    custom_metadata["seed"] = publish_result_payload.get("seed")
    custom_metadata["seedError"] = publish_result_payload.get("seedError")
    custom_metadata["bounds"] = metadata.get("bounds")
    metadata["customMetadata"] = custom_metadata
    return metadata


def _augment_geoserver_bounds_from_source(publication):
    if not isinstance(publication, dict):
        return publication
    metadata = _safe_dict(publication.get("metadata"))
    if not _is_geoserver_publish_method(metadata.get("publishMethod")):
        return publication
    if _publication_bounds(publication, metadata):
        return publication
    custom_metadata = _safe_dict(metadata.get("customMetadata"))
    source_paths = (
        metadata.get("sourcePaths")
        or custom_metadata.get("sourcePaths")
        or [metadata.get("sourcePath") or publication.get("publishPath")]
    )
    bounds = _datasource_wgs84_bounds(source_paths)
    if not bounds:
        return publication
    metadata["bounds"] = bounds
    custom_metadata["bounds"] = bounds
    metadata["customMetadata"] = custom_metadata
    publication["metadata"] = metadata
    publication["bounds"] = bounds
    return publication


def _cleanup_geoserver_publication(publication):
    metadata = _safe_dict((publication or {}).get("metadata"))
    if not _is_geoserver_publish_method(metadata.get("publishMethod")):
        return
    workspace = _first_non_blank(
        metadata.get("geoserverWorkspace"),
        _safe_dict(metadata.get("customMetadata")).get("geoserverWorkspace"),
        config.get("geoserverWorkspace"),
        "atlasworks",
    )
    custom_metadata = _safe_dict(metadata.get("customMetadata"))
    store_names = metadata.get("geoserverStoreNames") or custom_metadata.get("geoserverStoreNames")
    if not isinstance(store_names, list):
        store_names = []
    fallback_store_name = _first_non_blank(
        metadata.get("geoserverStoreName"),
        custom_metadata.get("geoserverStoreName"),
        metadata.get("geoserverLayerName"),
    )
    if fallback_store_name and fallback_store_name not in store_names:
        store_names.append(fallback_store_name)
    if not store_names:
        return
    for store_name in store_names:
        try:
            deleteStore(workspace, store_name)
        except Exception as exc:
            logMessage(f"GeoServer 发布资源清理失败 {workspace}:{store_name}: {exc}", "WARNING")


def _generate_publication_id():
    return str(uuid.uuid4())


def _cleanup_publication_descriptor(publication):
    if not isinstance(publication, dict):
        return

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


def _get_publication_response(publication_id, include_runtime_state=True, include_vector_details=True):
    record = fetchPublicationRecord(publication_id)
    if record:
        publication_record = _augment_geoserver_bounds_from_source(record)
        response = _publication_record_to_response(
            publication_record,
            include_runtime_state=include_runtime_state,
            include_vector_details=include_vector_details,
        )
        return response if _is_supported_publication_record(response) else None

    if not isDatabaseEnabled():
        for publication in _scan_publication_files(limit=500):
            if publication.get("id") == publication_id or publication.get("publicationId") == publication_id:
                response = _augment_publication_response(
                    publication,
                    include_runtime_state=include_runtime_state,
                    include_vector_details=include_vector_details,
                )
                return response if _is_supported_publication_record(response) else None
    return None


def _persist_publication_snapshot(publication, metadata_override=None, status_override=None, touch_record_timestamp=True):
    if not isinstance(publication, dict):
        return False
    publication_id = publication.get("publicationId") or publication.get("id")
    if not publication_id:
        return False
    metadata = metadata_override if isinstance(metadata_override, dict) else _safe_dict(publication.get("metadata"))
    prepared = {
        "publicationId": publication_id,
        "artifactId": publication.get("artifactId"),
        "publishType": publication.get("publishType"),
        "publishPath": publication.get("publishPath"),
        "alias": publication.get("alias"),
        "publishedAt": publication.get("publishedAt") or publication.get("createdAt") or datetime.now(timezone.utc).isoformat(),
        "descriptor": {
            "id": publication_id,
            "artifactId": publication.get("artifactId"),
            "publishType": publication.get("publishType"),
            "publishPath": publication.get("publishPath"),
            "alias": publication.get("alias"),
            "status": status_override or publication.get("status") or "draft",
            "publishedAt": publication.get("publishedAt"),
            "createdAt": publication.get("createdAt"),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata,
        },
    }
    _persist_publication_record(
        prepared,
        metadata_override=metadata,
        status_override=status_override or publication.get("status") or "draft",
        touch_record_timestamp=touch_record_timestamp,
    )
    return True


def _get_publication_geoserver_identity(publication):
    metadata = _safe_dict((publication or {}).get("metadata"))
    if not _is_geoserver_publish_method(metadata.get("publishMethod")):
        return None, None
    custom_metadata = _safe_dict(metadata.get("customMetadata"))
    workspace = _first_non_blank(
        metadata.get("geoserverWorkspace"),
        custom_metadata.get("geoserverWorkspace"),
        config.get("geoserverWorkspace"),
        "atlasworks",
    )
    layer_names = metadata.get("geoserverLayerNames") or custom_metadata.get("geoserverLayerNames") or []
    if not isinstance(layer_names, list):
        layer_names = []
    layer_names = [str(name).strip() for name in layer_names if str(name).strip()]
    if not layer_names:
        single_name = _first_non_blank(
            metadata.get("geoserverLayerName"),
            custom_metadata.get("geoserverLayerName"),
        )
        if single_name:
            layer_names.append(single_name)
    return workspace, layer_names


def _normalize_seed_status_payload(payload):
    payload = _safe_dict(payload)
    running = bool(payload.get("running"))
    status_text = str(payload.get("statusText") or payload.get("status") or "").strip()
    lowered = status_text.lower()
    if running:
        state = "running"
    elif not status_text or status_text == "当前没有运行中的预热任务" or "no running" in lowered or "idle" in lowered:
        state = "idle"
    elif "error" in lowered or "failed" in lowered:
        state = "failed"
    else:
        state = "submitted"
    return {
        "running": running,
        "state": state,
        "status": payload.get("status"),
        "statusText": status_text or "当前没有运行中的预热任务",
        "taskCount": int(payload.get("taskCount") or 0),
        "taskQueues": payload.get("taskQueues") or [],
        "workspace": payload.get("workspace"),
        "layerName": payload.get("layerName"),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }


def _store_publication_seed_status(publication, seed_status):
    if not isinstance(publication, dict):
        return seed_status
    metadata = _safe_dict(publication.get("metadata"))
    custom_metadata = _safe_dict(metadata.get("customMetadata"))
    normalized_status = _normalize_seed_status_payload(seed_status)
    previous_status = _safe_dict(metadata.get("seedStatus") or custom_metadata.get("seedStatus"))
    if (
        normalized_status.get("state") == "idle"
        and (
            bool(previous_status.get("running"))
            or str(previous_status.get("state") or "").strip().lower() in {"running", "submitted", "completed"}
        )
    ):
        normalized_status["state"] = "completed"
        normalized_status["statusText"] = "预热已完成"
    metadata["seedStatus"] = normalized_status
    custom_metadata["seedStatus"] = normalized_status
    metadata["customMetadata"] = custom_metadata
    publication["metadata"] = metadata
    publication["customMetadata"] = custom_metadata
    _persist_publication_snapshot(
        publication,
        metadata_override=metadata,
        status_override=publication.get("status"),
        touch_record_timestamp=False,
    )
    return normalized_status


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
    mosaic_json_info = None

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
    if normalized_publish_method in GEOSERVER_PUBLISH_METHODS or _is_mbtiles_publish_method(normalized_publish_method):
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
    if normalized_publish_method in GEOSERVER_PUBLISH_METHODS or _is_mbtiles_publish_method(normalized_publish_method):
        source_mode_input = "datasource"
    if source_mode_input not in {"task", "manual", "artifact", "datasource"}:
        if task_id:
            source_mode_input = "task"
        elif artifact_id:
            source_mode_input = "artifact"
        else:
            source_mode_input = "manual"
    if source_mode_input == "datasource":
        if _is_mbtiles_publish_method(normalized_publish_method):
            publish_method = MBTILES_PUBLISH_METHOD
            normalized_publish_method = MBTILES_PUBLISH_METHOD
        elif str(data.get("publishType") or "").strip().lower() == "vector" and not normalized_publish_method:
            publish_method = MBTILES_PUBLISH_METHOD
            normalized_publish_method = MBTILES_PUBLISH_METHOD
        elif not normalized_publish_method or normalized_publish_method not in GEOSERVER_PUBLISH_METHODS:
            publish_method = DATASOURCE_PUBLISH_METHOD
            normalized_publish_method = DATASOURCE_PUBLISH_METHOD

    if source_mode_input == "datasource":
        source_entries = _normalize_data_source_paths(source_entries or [workspace_path])
        workspace_path = source_entries[0] if source_entries else _normalize_data_source_path(workspace_path)
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
        publish_type = "vector" if _is_mbtiles_publish_method(normalized_publish_method) else DATASOURCE_PUBLISH_TYPE
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

    mbtiles_source_path = None
    if source_mode_input == "datasource":
        is_valid_publish_path, full_publish_path = validateDataSourcePath(publish_path)
        if not is_valid_publish_path:
            return None, (full_publish_path, 400)
        if not os.path.exists(full_publish_path):
            return None, ("发布数据源不存在", 404)
        if _is_mbtiles_publish_method(normalized_publish_method):
            source_extension = os.path.splitext(full_publish_path)[1].lower()
            if not os.path.isfile(full_publish_path) or source_extension not in MBTILES_SOURCE_EXTENSIONS:
                return None, ("动态 MVT 发布请选择 .mbtiles、.geojson、.shp 或 .gpkg 文件", 400)
            if source_extension in MBTILES_VECTOR_SOURCE_EXTENSIONS:
                original_source_path = publish_path
                mbtiles_source_path = full_publish_path
                custom_metadata = _safe_dict(data.get("customMetadata"))
                custom_metadata.update({
                    "generatedFrom": original_source_path,
                    "buildState": "pending",
                    "buildError": "",
                })
                data = {**data, "customMetadata": custom_metadata}
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
        custom_metadata["sourcePaths"] = source_entries
        custom_metadata["sourceEntryCount"] = len(source_entries)
        custom_metadata["sourceFileCount"] = len(source_entries)
    else:
        custom_metadata.pop("sourcePath", None)
        custom_metadata.pop("sourcePaths", None)
        custom_metadata.pop("sourceEntryCount", None)
        custom_metadata.pop("sourceFileCount", None)

    tile_profile = {} if source_mode_input == "datasource" else _resolve_tile_publish_profile(full_publish_path, metadata=existing_metadata, artifact=artifact)
    source_tile_scheme = _normalize_tile_scheme(
        _first_non_blank(
            incoming_custom_metadata.get("sourceTileScheme"),
            tile_profile.get("sourceTileScheme"),
            existing_custom_metadata.get("sourceTileScheme"),
        )
    )
    source_projection = _first_non_blank(
        incoming_custom_metadata.get("sourceProjection"),
        tile_profile.get("sourceProjection"),
        existing_custom_metadata.get("sourceProjection"),
    )
    tile_extension = _first_non_blank(
        incoming_custom_metadata.get("tileExtension"),
        tile_profile.get("tileExtension"),
        existing_custom_metadata.get("tileExtension"),
    )
    if source_tile_scheme:
        custom_metadata["sourceTileScheme"] = source_tile_scheme
    if source_projection:
        custom_metadata["sourceProjection"] = normalizeProjection(source_projection)
    if tile_extension:
        custom_metadata["tileExtension"] = tile_extension

    # Keep publish order stable on update: only initial creation should define publishedAt.
    # Later edits such as enable/disable should refresh updatedAt but not change publishedAt.
    published_at = (
        existing_publication.get("publishedAt")
        or existing_publication.get("createdAt")
        or datetime.now(timezone.utc).isoformat()
    )
    updated_at = datetime.now(timezone.utc).isoformat()
    descriptor = {
        "id": publication_id,
        "artifactId": artifact_id,
        "publishType": publish_type,
        "publishPath": publish_path,
        "alias": alias,
        "status": ("draft" if source_mode_input == "datasource" and _is_mbtiles_publish_method(normalized_publish_method) and mbtiles_source_path else ("enabled" if enabled else "disabled")),
        "publishedAt": published_at,
        "createdAt": existing_publication.get("createdAt") or published_at,
        "updatedAt": updated_at,
        "metadata": {
            "artifactOutputPath": artifact.get("outputPath") if artifact else existing_metadata.get("artifactOutputPath"),
            "manifestPath": artifact.get("manifestPath") if artifact else existing_metadata.get("manifestPath"),
            "workspacePath": workspace_path or None,
            "sourcePath": workspace_path if source_mode_input == "datasource" else None,
            "sourcePaths": source_entries if source_mode_input == "datasource" else None,
            "sourceEntryCount": len(source_entries) if source_mode_input == "datasource" else None,
            "sourceFileCount": len(source_entries) if source_mode_input == "datasource" else None,
            "taskId": task_id or None,
            "sourceMode": source_mode_input,
            "publishMethod": publish_method,
            "visibility": visibility,
            "note": note,
            "enabled": enabled,
            "sourceTileScheme": source_tile_scheme,
            "sourceProjection": normalizeProjection(source_projection) if source_projection else None,
            "tileExtension": tile_extension,
            "customMetadata": custom_metadata,
        },
    }

    return {
        "taskId": task_id,
        "artifactId": artifact_id,
        "workspacePath": workspace_path,
        "sourcePaths": source_entries,
        "sourceFileCount": len(source_entries),
        "publishType": publish_type,
        "alias": alias,
        "publicationId": publication_id,
        "publishPath": publish_path,
        "descriptor": descriptor,
        "publishedAt": published_at,
        "artifact": artifact,
        "pendingMbtilesSourcePath": mbtiles_source_path,
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
    if not should_refresh_urls:
        stored_sample = str(record.get("sampleUrl") or "").strip()
        computed_sample = str(computed_access_payload.get("sampleUrl") or "").strip()
        if stored_sample and computed_sample and stored_sample != computed_sample:
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
                touch_updated_at=False,
            )
            if not persisted:
                logMessage(f"发布 URL 回填失败: {record.get('id')}", "WARNING")
        except Exception as exc:
            logMessage(f"发布 URL 回填异常 {record.get('id')}: {exc}", "WARNING")
    return response


def _normalize_publication_status(status, metadata=None):
    metadata = _safe_dict(metadata)
    normalized_status = str(status or "").strip().lower()
    custom_metadata = _safe_dict(metadata.get("customMetadata"))
    if _is_mbtiles_publish_method(metadata.get("publishMethod")) and custom_metadata.get("buildState") == "pending":
        return "draft"
    if normalized_status == "published":
        return "enabled" if metadata.get("enabled", True) else "disabled"
    return normalized_status or str(status or "").strip()


def _publication_record_to_list_item(record):
    if not isinstance(record, dict):
        return None

    metadata = _safe_dict(record.get("metadata"))
    if any(record.get(key) for key in ("browserUrl", "accessUrl", "launchUrl", "sampleUrl")):
        access_payload = {
            "browserUrl": record.get("browserUrl"),
            "accessUrl": record.get("accessUrl"),
            "launchUrl": record.get("launchUrl"),
            "sampleUrl": record.get("sampleUrl"),
            "publicBaseUrl": record.get("publicBaseUrl"),
        }
    else:
        access_payload = _build_publication_access_payload(
            record.get("publishPath"),
            metadata.get("publishMethod"),
            record.get("publishType"),
            record.get("id"),
            metadata,
        )
    return {
        "publicationId": record.get("id"),
        "artifactId": record.get("artifactId"),
        "publishType": record.get("publishType"),
        "publishPath": record.get("publishPath"),
        "alias": record.get("alias"),
        "status": _normalize_publication_status(record.get("status"), metadata),
        "metadata": metadata,
        "publishMethod": metadata.get("publishMethod"),
        "visibility": metadata.get("visibility"),
        "note": metadata.get("note"),
        "enabled": bool(metadata.get("enabled", True)),
        "customMetadata": _safe_dict(metadata.get("customMetadata")),
        "sourceEntryCount": int(metadata.get("sourceEntryCount") or 0),
        "sourceFileCount": int(metadata.get("sourceFileCount") or 0),
        "bounds": _publication_bounds(record, metadata),
        "browserUrl": access_payload.get("browserUrl"),
        "accessUrl": access_payload.get("accessUrl"),
        "launchUrl": access_payload.get("launchUrl"),
        "sampleUrl": access_payload.get("sampleUrl"),
        "publishedAt": record.get("publishedAt"),
        "createdAt": record.get("createdAt"),
        "updatedAt": record.get("updatedAt"),
    }


def _publication_descriptor_to_list_item(payload):
    if not isinstance(payload, dict):
        return None

    metadata = _safe_dict(payload.get("metadata"))
    publication_id = payload.get("publicationId") or payload.get("id")
    access_payload = _build_publication_access_payload(
        payload.get("publishPath"),
        metadata.get("publishMethod"),
        payload.get("publishType"),
        publication_id,
        metadata,
    )
    return {
        "publicationId": publication_id,
        "artifactId": payload.get("artifactId"),
        "publishType": payload.get("publishType"),
        "publishPath": payload.get("publishPath"),
        "alias": payload.get("alias"),
        "status": _normalize_publication_status(payload.get("status"), metadata),
        "metadata": metadata,
        "publishMethod": metadata.get("publishMethod"),
        "visibility": metadata.get("visibility"),
        "note": metadata.get("note"),
        "enabled": bool(metadata.get("enabled", True)),
        "customMetadata": _safe_dict(metadata.get("customMetadata")),
        "sourceEntryCount": int(metadata.get("sourceEntryCount") or 0),
        "sourceFileCount": int(metadata.get("sourceFileCount") or 0),
        "bounds": _publication_bounds(payload, metadata),
        "browserUrl": access_payload.get("browserUrl"),
        "accessUrl": access_payload.get("accessUrl"),
        "launchUrl": access_payload.get("launchUrl"),
        "sampleUrl": access_payload.get("sampleUrl"),
        "publishedAt": payload.get("publishedAt"),
        "createdAt": payload.get("createdAt"),
        "updatedAt": payload.get("updatedAt"),
    }


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
            "taskId": task_id or None,
            "sourceMode": descriptor["metadata"].get("sourceMode"),
            "publishMethod": descriptor["metadata"].get("publishMethod"),
            "visibility": descriptor["metadata"].get("visibility", "private"),
            "note": descriptor["metadata"].get("note"),
            "enabled": descriptor["metadata"].get("enabled", True),
            "sourceTileScheme": descriptor["metadata"].get("sourceTileScheme"),
            "tileExtension": descriptor["metadata"].get("tileExtension"),
            "customMetadata": descriptor["metadata"].get("customMetadata", {}),
        }
        prepared["descriptor"]["metadata"] = metadata
        initial_status = descriptor["status"]

        if _is_geoserver_publish_method(metadata.get("publishMethod")):
            metadata = _publish_geoserver_publication(prepared, metadata)
            prepared["descriptor"]["metadata"] = metadata

        _persist_publication_record(prepared, metadata_override=metadata, status_override=initial_status)

        pending_mbtiles_source_path = prepared.get("pendingMbtilesSourcePath")
        if pending_mbtiles_source_path:
            _run_async_mbtiles_generation(
                publication_id,
                pending_mbtiles_source_path,
                alias or os.path.splitext(os.path.basename(pending_mbtiles_source_path))[0],
                metadata.get("customMetadata"),
            )

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

        publication_response = _get_publication_response(publication_id, include_runtime_state=False) or _augment_publication_response({
            **descriptor,
            "descriptorPath": descriptor_path,
            "publicationId": publication_id,
        }, include_runtime_state=False)

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
        existing_publication = _get_publication_response(publication_id, include_runtime_state=False)
        if not existing_publication:
            return jsonify({"error": "发布记录不存在"}), 404

        data = request.get_json(silent=True) or {}
        data["publicationId"] = str(data.get("publicationId", publication_id)).strip() or publication_id

        prepared, error = _prepare_publication_payload(data, existing_publication=existing_publication)
        if error:
            message, status_code = error
            return jsonify({"error": message}), status_code

        descriptor = prepared["descriptor"]
        descriptor_path = _write_publication_descriptor(descriptor, prepared["alias"], previous_publication=existing_publication)
        metadata = {
            **descriptor["metadata"],
            "descriptorPath": descriptor_path,
        }
        prepared["descriptor"]["metadata"] = metadata
        if _is_geoserver_publish_method(metadata.get("publishMethod")):
            _cleanup_geoserver_publication(existing_publication)
            metadata = _publish_geoserver_publication(prepared, metadata)
            prepared["descriptor"]["metadata"] = metadata
        _persist_publication_record(
            prepared,
            metadata_override=prepared["descriptor"]["metadata"],
            status_override=descriptor["status"],
        )

        pending_mbtiles_source_path = prepared.get("pendingMbtilesSourcePath")
        if pending_mbtiles_source_path:
            _run_async_mbtiles_generation(
                prepared["publicationId"],
                pending_mbtiles_source_path,
                prepared["alias"] or os.path.splitext(os.path.basename(pending_mbtiles_source_path))[0],
                prepared["descriptor"]["metadata"].get("customMetadata"),
            )

        if publication_id != prepared["publicationId"]:
            deletePublicationRecord(publication_id)

        publication_response = _get_publication_response(prepared["publicationId"], include_runtime_state=False) or _augment_publication_response({
            **descriptor,
            "descriptorPath": descriptor_path,
            "publicationId": prepared["publicationId"],
        }, include_runtime_state=False)

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
        include_details = str(request.args.get("includeDetails", "")).strip().lower() in {"1", "true", "yes", "on"}

        if isDatabaseEnabled() and not include_details:
            records, pagination = listPublicationRecordsPage(
                page=page,
                page_size=page_size,
                keyword=keyword,
                publish_type=publish_type,
                status=status_filter,
            )
            return jsonify({
                "success": True,
                "publications": [
                    item for item in (_publication_record_to_list_item(record) for record in records)
                    if _is_supported_publication_record(item)
                ],
                **pagination,
            })

        publications = {}

        for record in listPublicationRecords(limit=1000):
            response = (
                _publication_record_to_response(record, include_runtime_state=False, include_vector_details=False)
                if include_details
                else _publication_record_to_list_item(record)
            )
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
                    (
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
                            "updatedAt": record.get("updatedAt"),
                            "descriptorPath": record.get("descriptorPath"),
                        }, include_runtime_state=False, include_vector_details=False)
                        if include_details
                        else _publication_descriptor_to_list_item({
                            "id": record.get("id"),
                            "artifactId": record.get("artifactId"),
                            "publishType": record.get("publishType"),
                            "publishPath": record.get("publishPath"),
                            "alias": record.get("alias"),
                            "status": record.get("status"),
                            "metadata": record.get("metadata", {}),
                            "publishedAt": record.get("publishedAt"),
                            "createdAt": record.get("createdAt"),
                            "updatedAt": record.get("updatedAt"),
                        })
                    ),
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
                        (item.get("metadata") or {}).get("workspacePath"),
                        (item.get("metadata") or {}).get("sourcePath"),
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
        response = _get_publication_response(publication_id)
        if response:
            return jsonify({"success": True, "publication": response})

        if not isDatabaseEnabled():
            for publication in _scan_publication_files(limit=500):
                if publication.get("id") == publication_id:
                    return jsonify({"success": True, "publication": _augment_publication_response(
                        _augment_geoserver_bounds_from_source(publication)
                    )})

        return jsonify({"error": "发布记录不存在"}), 404
    except Exception as exc:
        logMessage(f"读取发布记录失败 {publication_id}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def getPublicationSeedRuntime(publication_id=None, publicationId=None):
    try:
        publication_id = publication_id or publicationId
        publication = _get_publication_response(publication_id, include_runtime_state=False)
        if not publication:
            return jsonify({"error": "发布记录不存在"}), 404

        workspace, layer_names = _get_publication_geoserver_identity(publication)
        if not workspace or not layer_names:
            return jsonify({"error": "当前发布不存在可用的 GeoServer 图层"}), 400

        seed_status = getSeedStatus(workspace, layer_names[0])
        normalized_status = _store_publication_seed_status(publication, seed_status)
        return jsonify({
            "success": True,
            "publicationId": publication_id,
            **normalized_status,
        })
    except Exception as exc:
        logMessage(f"读取发布预热状态失败 {publication_id}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def deletePublication(publication_id=None, publicationId=None):
    try:
        publication_id = publication_id or publicationId
        publication = _get_publication_snapshot(publication_id)
        if not publication:
            return jsonify({"error": "发布记录不存在"}), 404

        _cleanup_publication_descriptor(publication)
        _cleanup_geoserver_publication(publication)
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
    source_mode = metadata.get("sourceMode") or ("datasource" if _is_geoserver_publish_method(metadata.get("publishMethod")) else "manual")
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


def togglePublicationEnabled(publication_id=None, publicationId=None):
    try:
        db_ready, db_error = _ensure_publication_db_ready()
        if not db_ready:
            message, status_code = db_error
            return jsonify({"success": False, "error": message}), status_code

        publication_id = publication_id or publicationId
        publication = _get_publication_snapshot(publication_id)
        if not publication:
            return jsonify({"error": "发布记录不存在"}), 404

        data = request.get_json(silent=True) or {}
        if "enabled" not in data:
            return jsonify({"error": "缺少参数: enabled"}), 400

        enabled = str(data.get("enabled")).strip().lower() not in {"0", "false", "no", "off", "disabled"}
        metadata = _safe_dict(publication.get("metadata"))
        custom_metadata = _safe_dict(metadata.get("customMetadata"))
        metadata["enabled"] = enabled
        metadata["customMetadata"] = custom_metadata
        publication["metadata"] = metadata
        publication["status"] = "enabled" if enabled else "disabled"
        publication["updatedAt"] = datetime.now(timezone.utc).isoformat()

        prepared = {
            "publicationId": publication.get("publicationId") or publication.get("id") or publication_id,
            "artifactId": publication.get("artifactId"),
            "publishType": publication.get("publishType"),
            "publishPath": publication.get("publishPath"),
            "alias": publication.get("alias"),
            "publishedAt": publication.get("publishedAt") or publication.get("createdAt") or publication["updatedAt"],
            "descriptor": {
                "id": publication.get("publicationId") or publication.get("id") or publication_id,
                "artifactId": publication.get("artifactId"),
                "publishType": publication.get("publishType"),
                "publishPath": publication.get("publishPath"),
                "alias": publication.get("alias"),
                "status": publication["status"],
                "publishedAt": publication.get("publishedAt"),
                "createdAt": publication.get("createdAt"),
                "updatedAt": publication["updatedAt"],
                "metadata": metadata,
            },
        }
        _persist_publication_record(prepared, metadata_override=metadata, status_override=publication["status"])
        response = _get_publication_response(prepared["publicationId"], include_runtime_state=False) or _augment_publication_response(prepared["descriptor"], include_runtime_state=False)
        return jsonify({"success": True, "publication": response})
    except Exception as exc:
        logMessage(f"切换发布启停失败 {publication_id}: {exc}", "ERROR")
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
    
    response = send_from_directory(parent_dir, filename, mimetype=mimetype) if mimetype else send_from_directory(parent_dir, filename)
    extension = os.path.splitext(filename)[1].lower()
    if extension in {".terrain", ".pbf"}:
        response.headers["Access-Control-Allow-Origin"] = "*"
        if extension == ".pbf" or _is_gzip_file(full_path):
            response.headers["Content-Encoding"] = "gzip"
        
    return response


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

    if tile_request and publish_method in {"xyz", "tms", "mvt-xyz", "mvt-tms"}:
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
        normalized_relative_path, full_path = _resolve_tiles_path(relative_path)
        if not os.path.exists(full_path):
            return jsonify({"error": "目标发布资源不存在"}), 404
        return _send_published_entry(
            full_path, 
            normalized_relative_path, 
            lambda p: f"{_public_base_url()}/published/{p}" if p else f"{_public_base_url()}/published/"
        )
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

        return _send_published_entry(
            full_path, 
            normalized_relative_path, 
            lambda p: f"{_public_base_url()}/publication-assets/{publication_id}/{p}" if p else f"{_public_base_url()}/publication-assets/{publication_id}"
        )
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

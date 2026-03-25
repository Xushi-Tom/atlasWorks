#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import socket
from datetime import datetime
from urllib.parse import quote, unquote, urlsplit
import xml.etree.ElementTree as ET

from flask import Response, jsonify, request, send_from_directory

from config import config, taskLock, taskStatus
from db import (
    appendJobEvent,
    deletePublicationRecord,
    fetchArtifactRecord,
    fetchPublicationRecord,
    fetchTaskSnapshot,
    isDatabaseEnabled,
    listArtifactRecords,
    listPublicationRecords,
    upsertPublicationRecord,
)
from utils import logMessage, validateWorkspacePath


PUBLICATIONS_DIRNAME = "_publications"
WMTS_DEFAULT_MATRIX_SET = "GoogleMapsCompatible"
WMTS_SUPPORTED_MATRIX_SET = {"googlemapscompatible", "epsg:3857", "epsg3857", "webmercatorquad"}
WMTS_TOP_LEFT_CORNER = "-20037508.342789244 20037508.342789244"
WMTS_INITIAL_SCALE_DENOMINATOR = 559082264.0287178
WMTS_MIN_ZOOM = 0
WMTS_MAX_ZOOM = 22


def _mime_from_extension(extension):
    ext = str(extension or "").strip().lower()
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    return mapping.get(ext)


def _extension_from_mime(mime_type):
    mime = str(mime_type or "").strip().lower().split(";")[0]
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
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


def _load_manifest(manifest_path):
    with open(manifest_path, "r", encoding="utf-8") as manifest_file:
        return json.load(manifest_file)


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


def _build_publication_access_payload(publish_path, publish_method=None, publish_type=None, publication_id=None):
    public_base = _public_base_url()
    browser_url = _build_access_url(publish_path)
    access_url = browser_url
    launch_url = browser_url
    sample_url = None

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
    _, full_path = _resolve_tiles_path(normalized_path)
    enable_tile_template = publish_method in {"wmts", "tms", "xyz", "quantized-mesh", "cesium-terrain", "terrain"} or publish_type == "terrain"
    tile_info = _find_tile_template_info(full_path) if enable_tile_template else None

    if publish_method == "wmts":
        layer_identifier = str(publication_id or normalized_path).strip()
        tile_extension = (tile_info or {}).get("extension") or ".png"
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
            sample_y = (tile_info or {}).get("y", "0")
            sample_url = (
                f"{public_base}/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                f"&LAYER={encoded_layer}&STYLE=default&TILEMATRIXSET={WMTS_DEFAULT_MATRIX_SET}"
                f"&TILEMATRIX={sample_zoom}&TILEROW={sample_y}&TILECOL={sample_x}&FORMAT={tile_mime}"
            )
        launch_url = capabilities_url

    if tile_info:
        tile_template_url = f"{public_base}/published/{normalized_path}/{{z}}/{{x}}/{{y}}{tile_info['extension']}"
        sample_url = f"{public_base}/published/{normalized_path}/{tile_info['zoom']}/{tile_info['x']}/{tile_info['y']}{tile_info['extension']}"
        if publish_method != "wmts":
            access_url = tile_template_url
            launch_url = sample_url or browser_url

    return {
        "browserUrl": browser_url,
        "accessUrl": access_url,
        "launchUrl": launch_url,
        "sampleUrl": sample_url,
        "publicBaseUrl": public_base,
    }


def _augment_publication_response(payload):
    if not isinstance(payload, dict):
        return payload
    response = dict(payload)
    metadata = response.get("metadata") or {}
    publish_path = response.get("publishPath") or metadata.get("workspacePath")
    access_payload = _build_publication_access_payload(
        publish_path,
        metadata.get("publishMethod"),
        response.get("publishType"),
        response.get("publicationId") or response.get("id"),
    )
    for key, value in access_payload.items():
        existing_value = response.get(key)
        response[key] = existing_value if existing_value else value
    if "enabled" not in metadata:
        metadata["enabled"] = str(response.get("status") or "").lower() in {"enabled", "published", "active"}
    response["metadata"] = metadata
    if str(response.get("status") or "").lower() == "published":
        response["status"] = "enabled" if metadata.get("enabled", True) else "disabled"
    response["publicationId"] = response.get("publicationId") or response.get("id")
    return response


def _publication_descriptor_dir(alias):
    return os.path.join(config["tilesDir"], PUBLICATIONS_DIRNAME, str(alias or "").strip() or "publication")


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
    previous_alias = (previous_publication or {}).get("alias")
    previous_metadata = (previous_publication or {}).get("metadata") or {}
    previous_descriptor_path = previous_metadata.get("descriptorPath") or (previous_publication or {}).get("descriptorPath")

    descriptor_dir = _publication_descriptor_dir(alias)
    os.makedirs(descriptor_dir, exist_ok=True)
    descriptor_path = os.path.join(descriptor_dir, "publication.json")
    with open(descriptor_path, "w", encoding="utf-8") as publication_file:
        json.dump(descriptor, publication_file, ensure_ascii=False, indent=2)

    if previous_alias and previous_alias != alias and previous_descriptor_path and os.path.exists(previous_descriptor_path):
        _cleanup_publication_descriptor(previous_publication)

    return descriptor_path


def _get_publication_snapshot(publication_id):
    record = fetchPublicationRecord(publication_id)
    if record:
        return _publication_record_to_response(record)

    for publication in _scan_publication_files(limit=500):
        if publication.get("id") == publication_id or publication.get("publicationId") == publication_id:
            return _augment_publication_response(publication)
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
    existing_publication = existing_publication or {}
    existing_metadata = existing_publication.get("metadata") or {}

    task_id = str(data.get("taskId", existing_metadata.get("taskId") or "")).strip()
    artifact_id = str(data.get("artifactId", existing_publication.get("artifactId") or "")).strip()
    workspace_path = _normalize_relative_path(
        data.get(
            "workspacePath",
            data.get("sourcePath", existing_publication.get("publishPath") or existing_metadata.get("workspacePath") or "")
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

    workspace_path = workspace_path or _normalize_relative_path(artifact.get("outputPath") if artifact else "")
    if not workspace_path:
        return None, ("缺少参数: taskId、artifactId 或 workspacePath", 400)

    is_valid_workspace_path, full_workspace_path = validateWorkspacePath(workspace_path)
    if not is_valid_workspace_path:
        return None, (full_workspace_path, 400)
    if not os.path.exists(full_workspace_path):
        return None, ("目标工作空间路径不存在", 404)

    publish_type = str(data.get("publishType", existing_publication.get("publishType") or "imagery")).strip() or "imagery"
    default_alias = artifact_id or task_id or os.path.basename(workspace_path.rstrip("/")) or "publication"
    alias = str(data.get("alias", existing_publication.get("alias") or default_alias)).strip() or default_alias
    publication_id = str(data.get("publicationId", existing_publication.get("publicationId") or existing_publication.get("id") or f"publication-{alias}")).strip() or f"publication-{alias}"
    default_publish_path = workspace_path or (artifact.get("outputPath") if artifact else "") or ""
    publish_path_input = _normalize_relative_path(data.get("publishPath", existing_publication.get("publishPath", default_publish_path)))
    publish_path = publish_path_input or default_publish_path

    is_valid_publish_path, full_publish_path = validateWorkspacePath(publish_path)
    if not is_valid_publish_path:
        return None, (full_publish_path, 400)
    if not os.path.exists(full_publish_path):
        return None, ("发布目录不存在", 404)

    publish_method = data.get("publishMethod")
    if publish_method is None:
        publish_method = existing_metadata.get("publishMethod") or _safe_json(data.get("metadata"), {}).get("publishMethod")
    visibility = data.get("visibility", existing_metadata.get("visibility", "private"))
    note = data.get("note", existing_metadata.get("note"))
    enabled_input = data.get("enabled", existing_metadata.get("enabled"))
    enabled = True if enabled_input is None else str(enabled_input).strip().lower() not in {"0", "false", "no", "off", "disabled"}
    custom_metadata = dict(existing_metadata.get("customMetadata") or {})
    custom_metadata.update(_safe_json(data.get("metadata"), {}) or {})
    custom_metadata.pop("enabled", None)

    published_at = datetime.now().isoformat()
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
            "taskId": task_id or None,
            "publishMethod": publish_method,
            "visibility": visibility,
            "note": note,
            "enabled": enabled,
            "customMetadata": custom_metadata,
        },
    }

    return {
        "taskId": task_id,
        "artifactId": artifact_id,
        "workspacePath": workspace_path,
        "publishType": publish_type,
        "alias": alias,
        "publicationId": publication_id,
        "publishPath": publish_path,
        "descriptor": descriptor,
        "publishedAt": published_at,
        "artifact": artifact,
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


def _scan_manifest_files(limit=100):
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
        if len(manifests) >= limit:
            break
    return manifests


def _scan_publication_files(limit=100):
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
        if len(records) >= limit:
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


def _publication_record_to_response(record):
    if not isinstance(record, dict):
        return None
    metadata = record.get("metadata") or {}
    computed_access_payload = _build_publication_access_payload(
        record.get("publishPath"),
        metadata.get("publishMethod"),
        record.get("publishType"),
        record.get("id"),
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
    })

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
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
        artifact_type = request.args.get("artifactType")

        artifacts = {}
        for record in listArtifactRecords(limit=limit):
            response = _artifact_record_to_response(record)
            if not response:
                continue
            if artifact_type and response.get("artifactType") != artifact_type:
                continue
            artifacts[response["artifactId"]] = response

        for summary in _scan_manifest_files(limit=limit * 2):
            artifact_id = summary.get("artifactId")
            if not artifact_id:
                continue
            if artifact_type and summary.get("artifactType") != artifact_type:
                continue
            artifacts.setdefault(artifact_id, summary)

        items = list(artifacts.values())
        items.sort(key=lambda item: str(item.get("createdAt") or item.get("generatedAt") or ""), reverse=True)
        items = items[:limit]

        return jsonify({
            "success": True,
            "count": len(items),
            "artifacts": items,
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

        data = request.get_json() or {}
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
        access_payload = _build_publication_access_payload(
            publish_path,
            descriptor["metadata"].get("publishMethod"),
            publish_type,
            publication_id,
        )

        persisted = upsertPublicationRecord(
            publication_id=publication_id,
            artifact_id=artifact_id,
            publish_type=publish_type,
            publish_path=publish_path,
            alias=alias,
            status=descriptor["status"],
            metadata={
                "descriptorPath": descriptor_path,
                "artifactOutputPath": artifact.get("outputPath") if artifact else None,
                "manifestPath": artifact.get("manifestPath") if artifact else None,
                "workspacePath": workspace_path or None,
                "taskId": task_id or None,
                "publishMethod": descriptor["metadata"].get("publishMethod"),
                "visibility": descriptor["metadata"].get("visibility", "private"),
                "note": descriptor["metadata"].get("note"),
                "enabled": descriptor["metadata"].get("enabled", True),
                "customMetadata": descriptor["metadata"].get("customMetadata", {}),
            },
            published_at=prepared["publishedAt"],
            browser_url=access_payload.get("browserUrl"),
            access_url=access_payload.get("accessUrl"),
            launch_url=access_payload.get("launchUrl"),
            sample_url=access_payload.get("sampleUrl"),
            public_base_url=access_payload.get("publicBaseUrl"),
        )
        if isDatabaseEnabled() and not persisted:
            raise RuntimeError("发布记录写入数据库失败")

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

        logMessage(f"发布记录已创建: {publication_id} -> {artifact_id or task_id or workspace_path}", "INFO")
        return jsonify({
            "success": True,
            "publication": _augment_publication_response({
                **descriptor,
                "descriptorPath": descriptor_path,
            }),
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

        data = request.get_json() or {}
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
        access_payload = _build_publication_access_payload(
            prepared["publishPath"],
            descriptor["metadata"].get("publishMethod"),
            prepared["publishType"],
            prepared["publicationId"],
        )

        persisted = upsertPublicationRecord(
            publication_id=prepared["publicationId"],
            artifact_id=prepared["artifactId"],
            publish_type=prepared["publishType"],
            publish_path=prepared["publishPath"],
            alias=prepared["alias"],
            status=descriptor["status"],
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

        if publication_id != prepared["publicationId"]:
            deletePublicationRecord(publication_id)

        logMessage(f"发布记录已更新: {publication_id} -> {prepared['publicationId']}", "INFO")
        return jsonify({
            "success": True,
            "publication": _augment_publication_response({
                **descriptor,
                "descriptorPath": descriptor_path,
                "publicationId": prepared["publicationId"],
            }),
        })
    except Exception as exc:
        logMessage(f"更新发布记录失败 {publication_id}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def listPublications():
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
        publications = {}

        for record in listPublicationRecords(limit=limit):
            response = _publication_record_to_response(record)
            if not response:
                continue
            publications[response["publicationId"]] = response

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

        items = list(publications.values())
        items.sort(key=lambda item: str(item.get("publishedAt") or item.get("createdAt") or ""), reverse=True)
        items = items[:limit]
        return jsonify({
            "success": True,
            "count": len(items),
            "publications": items,
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


def servePublishedPath(relative_path=""):
    try:
        normalized_path, full_path = _resolve_tiles_path(relative_path)
        if not os.path.exists(full_path):
            return jsonify({"error": "目标发布资源不存在"}), 404

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
                    "url": _build_access_url(child_relative_path),
                })

            return jsonify({
                "success": True,
                "path": normalized_path,
                "type": "directory",
                "accessUrl": _build_access_url(normalized_path),
                "entries": entries,
            })

        parent_dir = os.path.dirname(full_path)
        filename = os.path.basename(full_path)
        return send_from_directory(parent_dir, filename)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logMessage(f"读取发布资源失败 {relative_path}: {exc}", "ERROR")
        return jsonify({"success": False, "error": str(exc)}), 500


def _collect_publication_items(limit=500):
    publications = {}

    for record in listPublicationRecords(limit=limit):
        response = _publication_record_to_response(record)
        if not response:
            continue
        publication_id = response.get("publicationId")
        if publication_id:
            publications[publication_id] = response

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

        extension = str(tile_info.get("extension") or "").strip().lower()
        mime_type = _mime_from_extension(extension)
        if not mime_type:
            continue

        layers.append({
            "id": publication_id,
            "alias": str(publication.get("alias") or publication_id),
            "publishPath": normalized_path,
            "extension": extension,
            "mimeType": mime_type,
            "sampleZoom": str(tile_info.get("zoom") or "0"),
            "sampleX": str(tile_info.get("x") or "0"),
            "sampleY": str(tile_info.get("y") or "0"),
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

    tile_relative_path = f"{layer['publishPath']}/{zoom}/{tile_col}/{tile_row}{layer['extension']}"
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import jsonify


_ENVELOPE_KEYS = {"success", "code", "message", "data", "meta", "error"}
_SKIP_PATHS = {"/api/openapi.json"}


def should_wrap_json_response(path, response):
    normalized_path = str(path or "").strip()
    if normalized_path in _SKIP_PATHS:
        return False
    if not normalized_path.startswith("/api/"):
        return False
    if response.status_code == 204:
        return False
    return str(getattr(response, "mimetype", "") or "").lower() == "application/json"


def is_enveloped_payload(payload):
    if not isinstance(payload, dict):
        return False
    return "success" in payload and "message" in payload and "data" in payload


def normalize_envelope(payload, status_code):
    if is_enveloped_payload(payload):
        success = bool(payload.get("success"))
        message = str(payload.get("message") or ("ok" if success else "Request failed"))
        code = str(payload.get("code") or ("OK" if success else f"HTTP_{status_code}"))
        normalized = {
            "success": success,
            "code": code,
            "message": message,
            "data": payload.get("data"),
            "meta": payload.get("meta") or {},
        }
        if not success:
            normalized["error"] = payload.get("error") or {"detail": message}
        return normalized

    if not isinstance(payload, dict):
        success = status_code < 400
        return {
            "success": success,
            "code": "OK" if success else f"HTTP_{status_code}",
            "message": "ok" if success else "Request failed",
            "data": payload if success else None,
            "meta": {},
            **({"error": {"detail": "Request failed"}} if not success else {}),
        }

    legacy_success = payload.get("success")
    success = bool(legacy_success) if isinstance(legacy_success, bool) else status_code < 400
    message = str(payload.get("message") or payload.get("error") or ("ok" if success else "Request failed"))
    code = str(payload.get("code") or ("OK" if success else f"HTTP_{status_code}"))
    meta = payload.get("meta") or {}

    if not success:
        error_payload = dict(payload)
        error_payload.pop("success", None)
        error_payload.pop("code", None)
        error_payload.pop("meta", None)
        if "message" in error_payload and "error" not in error_payload:
            error_payload.pop("message", None)
        detail = error_payload.pop("error", None) or message
        error = {"detail": detail}
        for key, value in error_payload.items():
            if key == "message":
                continue
            error[key] = value
        return {
            "success": False,
            "code": code,
            "message": message,
            "data": None if status_code >= 400 else _build_legacy_data(payload),
            "meta": meta,
            "error": error,
        }

    return {
        "success": True,
        "code": code,
        "message": message,
        "data": _build_legacy_data(payload),
        "meta": meta,
    }


def build_json_response(payload, response):
    wrapped = normalize_envelope(payload, response.status_code)
    new_response = jsonify(wrapped)
    new_response.status_code = response.status_code
    for header_name, header_value in response.headers.items():
        if header_name.lower() in {"content-length", "content-type"}:
            continue
        new_response.headers.add(header_name, header_value)
    return new_response


def _build_legacy_data(payload):
    if not isinstance(payload, dict):
        return payload

    if "success" not in payload:
        return payload

    data = dict(payload)
    for key in ("success", "code", "error"):
        data.pop(key, None)
    if "message" in payload:
        data.pop("message", None)
    if "meta" in payload:
        data.pop("meta", None)
    return data or None

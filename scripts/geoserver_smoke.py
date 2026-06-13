#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import sys
import time
from urllib.parse import urljoin

import requests


def request_json(method, base_url, path, **kwargs):
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 20), **kwargs)
    content_type = response.headers.get("content-type", "")
    payload = response.json() if "application/json" in content_type else {"raw": response.text}
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> HTTP {response.status_code}: {payload}")
    return payload


def main():
    parser = argparse.ArgumentParser(description="AtlasWorks GeoServer smoke checks")
    parser.add_argument("--base-url", default="http://localhost:18000", help="AtlasWorks API base URL")
    parser.add_argument("--source", default="", help="Optional datasource-relative tif path for a tiny real tile job")
    parser.add_argument("--output", default="smoke/geoserver-map", help="Output path for optional real tile job")
    args = parser.parse_args()

    health = request_json("GET", args.base_url, "/api/health")
    if not health.get("success"):
        raise RuntimeError(f"API health failed: {health}")

    geoserver = request_json("GET", args.base_url, "/api/geoserver/health")
    if not geoserver.get("success"):
        raise RuntimeError(f"GeoServer health failed: {geoserver}")

    invalid = request_json("POST", args.base_url, "/api/tile/indexedTiles", json={
        "folderPaths": [],
        "filePatterns": ["__missing_smoke_file__.tif"],
        "outputPath": ["smoke", "invalid"],
        "minZoom": 0,
        "maxZoom": 0,
    })
    if invalid.get("success") is not False:
        raise RuntimeError(f"Expected invalid map tile request to fail validation: {invalid}")

    if args.source:
        task_id = f"smoke-geoserver-{int(time.time())}"
        task = request_json("POST", args.base_url, "/api/tile/indexedTiles", json={
            "taskId": task_id,
            "folderPaths": [],
            "filePatterns": [args.source],
            "outputPath": args.output.split("/"),
            "minZoom": 0,
            "maxZoom": 0,
            "tileSize": 256,
            "imageFormat": "png",
            "tileScheme": "google",
            "wmsConcurrency": 1,
            "enableIncrementalUpdate": True,
        })
        if not task.get("success"):
            raise RuntimeError(f"Real tile smoke submit failed: {task}")

        for _ in range(120):
            status = request_json("GET", args.base_url, f"/api/tasks/{task_id}")
            data = status.get("data") or status
            state = str(data.get("status") or "").lower()
            if state in {"completed", "failed", "stopped"}:
                if state != "completed":
                    raise RuntimeError(f"Real tile smoke did not complete: {data}")
                break
            time.sleep(2)
        else:
            raise RuntimeError(f"Real tile smoke timed out: {task_id}")

    print("geoserver-smoke: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

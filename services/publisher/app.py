#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

from flask import Flask, jsonify, request
from flask_cors import CORS

from api_response import build_json_response, should_wrap_json_response
from catalog import (
    createPublication,
    deletePublication,
    getArtifact,
    getArtifactManifest,
    getPublication,
    listArtifacts,
    listPublications,
    servePublicationAsset,
    servePublishedPath,
    serveWmts,
    updatePublication,
)
from config import config
from db import initializeDatabase
from systemOps import healthCheck
from utils import logMessage


app = Flask(__name__)
CORS(
    app,
    resources={
        r"/api/*": {"origins": "*", "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization"]},
        r"/published": {"origins": "*", "methods": ["GET", "HEAD", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization", "Range"]},
        r"/published/*": {"origins": "*", "methods": ["GET", "HEAD", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization", "Range"]},
        r"/publication-assets": {"origins": "*", "methods": ["GET", "HEAD", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization", "Range"]},
        r"/publication-assets/*": {"origins": "*", "methods": ["GET", "HEAD", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization", "Range"]},
        r"/wmts": {"origins": "*", "methods": ["GET", "HEAD", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization"]},
    },
)
app.config["JSON_AS_ASCII"] = False
app.json.ensure_ascii = False


def _bootstrap_publisher():
    os.makedirs(config["logDir"], exist_ok=True)
    os.makedirs(config["tilesDir"], exist_ok=True)
    initializeDatabase()
    logMessage("AtlasWorks 发布服务启动", "INFO")


def _handle_publications():
    if request.method == "POST":
        return createPublication()
    return listPublications()


def _handle_publication_detail(publication_id):
    if request.method == "PUT":
        return updatePublication(publication_id=publication_id)
    if request.method == "DELETE":
        return deletePublication(publication_id=publication_id)
    return getPublication(publication_id=publication_id)


@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }
        return ("", 204, headers)


@app.after_request
def normalize_api_json_responses(response):
    try:
        if not should_wrap_json_response(request.path, response):
            return response
        payload = response.get_json(silent=True)
        if payload is None:
            return response
        return build_json_response(payload, response)
    except Exception as exc:
        logMessage(f"发布服务响应封装失败: {exc}", "WARNING")
        return response


app.add_url_rule("/api/health", endpoint="publisher_health", view_func=healthCheck, methods=["GET"])
app.add_url_rule("/api/artifacts", endpoint="publisher_artifacts", view_func=listArtifacts, methods=["GET"])
app.add_url_rule("/api/artifacts/<artifactId>", endpoint="publisher_artifact", view_func=getArtifact, methods=["GET"])
app.add_url_rule("/api/artifacts/<artifactId>/manifest", endpoint="publisher_artifact_manifest", view_func=getArtifactManifest, methods=["GET"])
app.add_url_rule("/api/publications", endpoint="publisher_publications", view_func=_handle_publications, methods=["GET", "POST"])
app.add_url_rule("/api/publications/<publication_id>", endpoint="publisher_publication_detail", view_func=_handle_publication_detail, methods=["GET", "PUT", "DELETE"])
app.add_url_rule("/publication-assets/<publication_id>", endpoint="publisher_publication_root", view_func=servePublicationAsset, defaults={"relative_path": ""}, methods=["GET"])
app.add_url_rule("/publication-assets/<publication_id>/<path:relative_path>", endpoint="publisher_publication_asset", view_func=servePublicationAsset, methods=["GET"])
app.add_url_rule("/published", endpoint="publisher_published_root", view_func=servePublishedPath, defaults={"relative_path": ""}, methods=["GET"])
app.add_url_rule("/published/<path:relative_path>", endpoint="publisher_published_asset", view_func=servePublishedPath, methods=["GET"])
app.add_url_rule("/wmts", endpoint="publisher_wmts", view_func=serveWmts, methods=["GET", "OPTIONS"])
app.add_url_rule("/", endpoint="publisher_root", view_func=lambda: jsonify({"service": "atlasworks-publisher", "status": "ok"}), methods=["GET"])


_bootstrap_publisher()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 18001))
    host = os.environ.get("HOST", "0.0.0.0")
    app.run(host=host, port=port, threaded=True)

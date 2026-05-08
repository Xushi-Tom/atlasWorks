#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import request

from apiDocs import getOpenApiSpec, getSwaggerUi
from catalog import clearPublicationCache, createPublication, deletePublication, getArtifact, getArtifactManifest, getPublication, listArtifacts, listPublications, rebuildPublicationCache, servePublicationAsset, servePublishedPath, serveWmts, updatePublication
from dataSourceOps import getDataSourceInfo, getDataSourceWorkspaceInfo, listDataSources, recommendConfig, resolveDataSourceFiles, serveDataSourceFile
from fileSplitOps import splitLargeFile
from indexedTilesOps import createIndexedTiles, deleteNodataTiles, scanNodataTiles
from preflight import runPreflightCheck
from systemOps import healthCheck, listApiRoutes, systemInfo, updateContainerInfo
from taskCenter import cleanupTasks, deleteTask, getTaskStatus, listTaskEventStream, listTasks, stopTask
from terrainOps import createTerrainTiles, decompressTerrain, updateLayerJson
from tileAdminOps import convertTileFormat, getCacheInfo
from tiles3dOps import create3DTiles
from uploadOps import extractArchiveFile, uploadFolderFiles, uploadSingleFile, uploadZipArchive
from vectorTilesOps import createVectorTiles
from workspaceOps import browseDirectory, createDatasourceFolder, createWorkspaceFolder, deleteDatasourceFile, deleteDatasourceFolder, deleteWorkspaceFile, deleteWorkspaceFolder, getFileDetails, getWorkspaceInfo, moveWorkspaceItem, renameWorkspaceFile, renameWorkspaceFolder, serveWorkspaceFile


def handlePublications():
    if request.method == "POST":
        return createPublication()
    return listPublications()


def handlePublicationDetail(publicationId):
    if request.method == "PUT":
        return updatePublication(publicationId=publicationId)
    if request.method == "DELETE":
        return deletePublication(publicationId=publicationId)
    return getPublication(publicationId=publicationId)


def handlePublicationCache(publicationId):
    if request.method == "DELETE":
        return clearPublicationCache(publicationId=publicationId)
    return rebuildPublicationCache(publicationId=publicationId)


def registerRoutes(app):
    app.add_url_rule("/", endpoint="atlasworks_console", view_func=lambda: app.send_static_file("index.html"), methods=["GET"])
    app.add_url_rule("/console", endpoint="atlasworks_console_alias", view_func=lambda: app.send_static_file("index.html"), methods=["GET"])

    app.add_url_rule("/api/health", endpoint="health_check", view_func=healthCheck, methods=["GET"])
    app.add_url_rule("/api/openapi.json", endpoint="openapi_spec", view_func=getOpenApiSpec, methods=["GET"])
    app.add_url_rule("/api/docs", endpoint="swagger_docs", view_func=getSwaggerUi, methods=["GET"])

    app.add_url_rule("/api/dataSources", endpoint="list_data_sources", view_func=listDataSources, defaults={"subpath": ""}, methods=["GET"])
    app.add_url_rule("/api/datasources", endpoint="list_data_sources_alias", view_func=listDataSources, defaults={"subpath": ""}, methods=["GET"])
    app.add_url_rule("/api/dataSources/<path:subpath>", endpoint="list_data_sources_subpath", view_func=listDataSources, methods=["GET"])
    app.add_url_rule("/api/datasources/<path:subpath>", endpoint="list_data_sources_subpath_alias", view_func=listDataSources, methods=["GET"])
    app.add_url_rule("/api/dataSources/info/<path:filename>", endpoint="get_data_source_info", view_func=getDataSourceInfo, methods=["GET"])
    app.add_url_rule("/api/datasources/info/<path:filename>", endpoint="get_data_source_info_alias", view_func=getDataSourceInfo, methods=["GET"])
    app.add_url_rule("/api/dataSources/raw/<path:filename>", endpoint="get_data_source_file", view_func=serveDataSourceFile, methods=["GET"])
    app.add_url_rule("/api/datasources/raw/<path:filename>", endpoint="get_data_source_file_alias", view_func=serveDataSourceFile, methods=["GET"])
    app.add_url_rule("/api/dataSources/workspace", endpoint="get_data_source_workspace", view_func=getDataSourceWorkspaceInfo, methods=["GET"])
    app.add_url_rule("/api/datasources/workspace", endpoint="get_data_source_workspace_alias", view_func=getDataSourceWorkspaceInfo, methods=["GET"])
    app.add_url_rule("/api/dataSources/resolve", endpoint="resolve_data_source_files", view_func=resolveDataSourceFiles, methods=["POST"])
    app.add_url_rule("/api/datasources/resolve", endpoint="resolve_data_source_files_alias", view_func=resolveDataSourceFiles, methods=["POST"])
    app.add_url_rule("/api/dataSources/split", endpoint="split_large_file", view_func=splitLargeFile, methods=["POST"])
    app.add_url_rule("/api/datasources/split", endpoint="split_large_file_alias", view_func=splitLargeFile, methods=["POST"])
    app.add_url_rule("/api/datasources/createFolder", endpoint="create_datasource_folder", view_func=createDatasourceFolder, methods=["POST"])
    app.add_url_rule("/api/preflight", endpoint="run_preflight", view_func=runPreflightCheck, methods=["POST"])

    app.add_url_rule("/api/upload/file", endpoint="upload_single_file", view_func=uploadSingleFile, methods=["POST"])
    app.add_url_rule("/api/upload/zip", endpoint="upload_zip", view_func=uploadZipArchive, methods=["POST"])
    app.add_url_rule("/api/upload/folder", endpoint="upload_folder", view_func=uploadFolderFiles, methods=["POST"])
    app.add_url_rule("/api/files/extract", endpoint="extract_archive_file", view_func=extractArchiveFile, methods=["POST"])

    app.add_url_rule("/api/results", endpoint="browse_results", view_func=browseDirectory, methods=["GET"])
    app.add_url_rule("/api/fileDetails", endpoint="get_file_details", view_func=getFileDetails, methods=["GET"])
    app.add_url_rule("/api/workspace/raw/<path:filename>", endpoint="get_workspace_file", view_func=serveWorkspaceFile, methods=["GET"])

    app.add_url_rule("/api/tile/terrain", endpoint="create_terrain_tiles", view_func=createTerrainTiles, methods=["POST"])
    app.add_url_rule("/api/tile/indexedTiles", endpoint="create_indexed_tiles", view_func=createIndexedTiles, methods=["POST"])
    app.add_url_rule("/api/tile/mvt", endpoint="create_vector_tiles", view_func=createVectorTiles, methods=["POST"])
    app.add_url_rule("/api/tile/3dtiles", endpoint="create_3d_tiles", view_func=create3DTiles, methods=["POST"])
    app.add_url_rule("/api/tile/convert", endpoint="convert_tile_format", view_func=convertTileFormat, methods=["POST"])

    app.add_url_rule("/api/tasks/<taskId>", endpoint="get_task_status", view_func=getTaskStatus, methods=["GET"])
    app.add_url_rule("/api/tasks/<taskId>/events", endpoint="get_task_events", view_func=listTaskEventStream, methods=["GET"])
    app.add_url_rule("/api/tasks", endpoint="list_tasks", view_func=listTasks, methods=["GET"])
    app.add_url_rule("/api/tasks/cleanup", endpoint="cleanup_tasks", view_func=cleanupTasks, methods=["POST"])
    app.add_url_rule("/api/tasks/<taskId>/stop", endpoint="stop_task", view_func=stopTask, methods=["POST"])
    app.add_url_rule("/api/tasks/<taskId>", endpoint="delete_task", view_func=deleteTask, methods=["DELETE"])

    app.add_url_rule("/api/artifacts", endpoint="list_artifacts", view_func=listArtifacts, methods=["GET"])
    app.add_url_rule("/api/artifacts/<artifactId>", endpoint="get_artifact", view_func=getArtifact, methods=["GET"])
    app.add_url_rule("/api/artifacts/<artifactId>/manifest", endpoint="get_artifact_manifest", view_func=getArtifactManifest, methods=["GET"])

    app.add_url_rule("/api/publications", endpoint="publications", view_func=handlePublications, methods=["GET", "POST"])
    app.add_url_rule("/api/publications/<publicationId>", endpoint="publication_detail", view_func=handlePublicationDetail, methods=["GET", "PUT", "DELETE"])
    app.add_url_rule("/api/publications/<publicationId>/cache", endpoint="publication_cache", view_func=handlePublicationCache, methods=["POST", "DELETE"])
    app.add_url_rule("/publication-assets/<publication_id>", endpoint="published_publication_root", view_func=servePublicationAsset, defaults={"relative_path": ""}, methods=["GET"])
    app.add_url_rule("/publication-assets/<publication_id>/<path:relative_path>", endpoint="published_publication_asset", view_func=servePublicationAsset, methods=["GET"])
    app.add_url_rule("/published", endpoint="published_root", view_func=servePublishedPath, defaults={"relative_path": ""}, methods=["GET"])
    app.add_url_rule("/published/<path:relative_path>", endpoint="published_asset", view_func=servePublishedPath, methods=["GET"])
    app.add_url_rule("/wmts", endpoint="wmts_service", view_func=serveWmts, methods=["GET", "OPTIONS"])

    app.add_url_rule("/api/config/recommend", endpoint="recommend_config", view_func=recommendConfig, methods=["POST"])
    app.add_url_rule("/api/cache/info", endpoint="get_cache_info", view_func=getCacheInfo, methods=["GET"])
    app.add_url_rule("/api/system/info", endpoint="system_info", view_func=systemInfo, methods=["GET"])
    app.add_url_rule("/api/container/update", endpoint="update_container", view_func=updateContainerInfo, methods=["POST"])
    app.add_url_rule("/api/routes", endpoint="list_api_routes", view_func=listApiRoutes, methods=["GET"])

    app.add_url_rule("/api/workspace/createFolder", endpoint="create_workspace_folder", view_func=createWorkspaceFolder, methods=["POST"])
    app.add_url_rule("/api/datasources/folder/<path:folderPath>", endpoint="delete_datasource_folder", view_func=deleteDatasourceFolder, methods=["DELETE", "OPTIONS"])
    app.add_url_rule("/api/datasources/file/<path:filePath>", endpoint="delete_datasource_file", view_func=deleteDatasourceFile, methods=["DELETE", "OPTIONS"])
    app.add_url_rule("/api/workspace/folder/<path:folderPath>", endpoint="delete_workspace_folder", view_func=deleteWorkspaceFolder, methods=["DELETE", "OPTIONS"])
    app.add_url_rule("/api/workspace/folder/<path:folderPath>/rename", endpoint="rename_workspace_folder", view_func=renameWorkspaceFolder, methods=["PUT"])
    app.add_url_rule("/api/workspace/file/<path:filePath>", endpoint="delete_workspace_file", view_func=deleteWorkspaceFile, methods=["DELETE", "OPTIONS"])
    app.add_url_rule("/api/workspace/file/<path:filePath>/rename", endpoint="rename_workspace_file", view_func=renameWorkspaceFile, methods=["PUT"])
    app.add_url_rule("/api/workspace/move", endpoint="move_workspace_item", view_func=moveWorkspaceItem, methods=["PUT"])
    app.add_url_rule("/api/workspace/info", endpoint="get_workspace_info", view_func=getWorkspaceInfo, methods=["GET"])

    app.add_url_rule("/api/tiles/nodata/scan", endpoint="scan_nodata_tiles", view_func=scanNodataTiles, methods=["POST"])
    app.add_url_rule("/api/tiles/nodata/delete", endpoint="delete_nodata_tiles", view_func=deleteNodataTiles, methods=["POST"])

    app.add_url_rule("/api/terrain/layer", endpoint="update_layer_json", view_func=updateLayerJson, methods=["POST"])
    app.add_url_rule("/api/terrain/decompress", endpoint="decompress_terrain", view_func=decompressTerrain, methods=["POST"])

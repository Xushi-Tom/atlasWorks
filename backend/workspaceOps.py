#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shutil
import urllib.parse
from datetime import datetime

from flask import jsonify, request

from config import config
from dataSourceOps import getFileInfo
from utils import formatFileSize, logMessage, validateDataSourcePath, validateWorkspacePath


def _delete_path(item_path, validator, item_kind):
    decoded_path = urllib.parse.unquote(item_path)
    is_valid, full_path = validator(decoded_path)
    if not is_valid:
        return False, None, full_path

    exists = os.path.exists(full_path)
    if item_kind == "folder" and exists and os.path.isdir(full_path):
        shutil.rmtree(full_path)
        return True, decoded_path, full_path
    if item_kind == "file" and exists and os.path.isfile(full_path):
        os.remove(full_path)
        return True, decoded_path, full_path
    return False, decoded_path, full_path


def createDatasourceFolder():
    try:
        data = request.get_json() or {}
        folder_path = data.get("folderPath", "")
        if not folder_path:
            return jsonify({"error": "缺少参数: folderPath"}), 400

        is_valid, full_path = validateDataSourcePath(folder_path)
        if not is_valid:
            return jsonify({"error": full_path}), 400

        if not os.path.exists(full_path):
            os.makedirs(full_path, exist_ok=True)
            return jsonify({
                "success": True,
                "message": "数据源文件夹创建成功",
                "folderPath": folder_path,
            })
        return jsonify({"error": "文件夹已存在"}), 409
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def deleteDatasourceFolder(folderPath):
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        deleted, decoded_path, details = _delete_path(folderPath, validateDataSourcePath, "folder")
        if deleted:
            logMessage(f"数据源文件夹删除成功: {details}")
            return jsonify({
                "success": True,
                "message": "数据源文件夹删除成功",
                "folderPath": decoded_path,
            })
        if decoded_path is None:
            return jsonify({"error": details}), 400
        return jsonify({"error": "数据源文件夹不存在", "folderPath": decoded_path}), 404
    except Exception as exc:
        logMessage(f"删除数据源文件夹失败: {exc}", "ERROR")
        return jsonify({"error": str(exc), "folderPath": folderPath}), 500


def deleteDatasourceFile(filePath):
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        deleted, decoded_path, details = _delete_path(filePath, validateDataSourcePath, "file")
        if deleted:
            logMessage(f"数据源文件删除成功: {details}")
            return jsonify({
                "success": True,
                "message": "数据源文件删除成功",
                "filePath": decoded_path,
            })
        if decoded_path is None:
            return jsonify({"error": details}), 400
        return jsonify({"error": "数据源文件不存在", "filePath": decoded_path}), 404
    except Exception as exc:
        logMessage(f"删除数据源文件失败: {exc}", "ERROR")
        return jsonify({"error": str(exc), "filePath": filePath}), 500


def createWorkspaceFolder():
    try:
        data = request.get_json() or {}
        folder_path = data.get("folderPath", "")
        if not folder_path:
            return jsonify({"error": "缺少参数: folderPath"}), 400

        is_valid, full_path = validateWorkspacePath(folder_path)
        if not is_valid:
            return jsonify({"error": full_path}), 400

        if not os.path.exists(full_path):
            os.makedirs(full_path, exist_ok=True)
            return jsonify({
                "success": True,
                "message": "文件夹创建成功",
                "folderPath": folder_path,
            })
        return jsonify({"error": "文件夹已存在"}), 409
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def deleteWorkspaceFolder(folderPath):
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        logMessage(f"收到删除文件夹请求: {folderPath}")
        folder_path = urllib.parse.unquote(folderPath)
        logMessage(f"URL解码后的路径: {folder_path}")

        is_valid, full_path = validateWorkspacePath(folder_path)
        logMessage(f"路径验证结果: isValid={is_valid}, fullPath={full_path}")
        if not is_valid:
            logMessage(f"路径验证失败: {full_path}")
            return jsonify({"error": full_path}), 400

        folder_exists = os.path.exists(full_path)
        is_dir = os.path.isdir(full_path)
        logMessage(f"文件夹检查: exists={folder_exists}, isDir={is_dir}, path={full_path}")

        if folder_exists and is_dir:
            try:
                shutil.rmtree(full_path)
                logMessage(f"文件夹删除成功: {full_path}")
                return jsonify({
                    "success": True,
                    "message": "文件夹删除成功",
                    "folderPath": folder_path,
                })
            except Exception as exc:
                logMessage(f"文件夹删除操作失败: {str(exc)}", "ERROR")
                return jsonify({
                    "error": f"删除失败: {str(exc)}",
                    "folderPath": folder_path,
                }), 500

        logMessage(f"文件夹不存在: {full_path}")
        return jsonify({
            "error": "文件夹不存在",
            "folderPath": folder_path,
            "fullPath": full_path,
            "exists": folder_exists,
            "isDir": is_dir,
        }), 404
    except Exception as exc:
        logMessage(f"删除文件夹处理失败: {str(exc)}", "ERROR")
        return jsonify({"error": str(exc), "folderPath": folderPath}), 500


def renameWorkspaceFolder(folderPath):
    try:
        data = request.get_json() or {}
        new_name = data.get("newName", "")
        if not new_name:
            return jsonify({"error": "缺少参数: newName"}), 400

        is_valid, full_path = validateWorkspacePath(folderPath)
        if not is_valid:
            return jsonify({"error": full_path}), 400
        if not os.path.exists(full_path):
            return jsonify({"error": "源文件夹不存在"}), 404

        parent_dir = os.path.dirname(full_path)
        new_path = os.path.join(parent_dir, new_name)
        if os.path.exists(new_path):
            return jsonify({"error": "目标文件夹已存在"}), 409

        os.rename(full_path, new_path)
        return jsonify({
            "success": True,
            "message": "文件夹重命名成功",
            "oldPath": folderPath,
            "newPath": os.path.relpath(new_path, config["tilesDir"]),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def renameWorkspaceFile(filePath):
    try:
        data = request.get_json() or {}
        new_name = data.get("newName", "")
        if not new_name:
            return jsonify({"error": "缺少参数: newName"}), 400

        is_valid, full_path = validateWorkspacePath(filePath)
        if not is_valid:
            return jsonify({"error": full_path}), 400
        if not os.path.exists(full_path):
            return jsonify({"error": "源文件不存在"}), 404
        if not os.path.isfile(full_path):
            return jsonify({"error": "目标不是文件"}), 400

        parent_dir = os.path.dirname(full_path)
        new_path = os.path.join(parent_dir, new_name)
        if os.path.exists(new_path):
            return jsonify({"error": "目标文件已存在"}), 409

        os.rename(full_path, new_path)
        return jsonify({
            "success": True,
            "message": "文件重命名成功",
            "oldPath": filePath,
            "newPath": os.path.relpath(new_path, config["tilesDir"]).replace("\\", "/"),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def moveWorkspaceItem():
    try:
        data = request.get_json() or {}
        source_path = data.get("sourcePath", "")
        target_path = data.get("targetPath", "")
        if not source_path or not target_path:
            return jsonify({"error": "缺少参数: sourcePath 或 targetPath"}), 400

        is_source_valid, source_full_path = validateWorkspacePath(source_path)
        if not is_source_valid:
            return jsonify({"error": source_full_path}), 400
        if not os.path.exists(source_full_path):
            return jsonify({"error": "源路径不存在"}), 404

        is_target_valid, target_full_path = validateWorkspacePath(target_path)
        if not is_target_valid:
            return jsonify({"error": target_full_path}), 400

        target_parent = os.path.dirname(target_full_path)
        os.makedirs(target_parent, exist_ok=True)
        if os.path.exists(target_full_path):
            return jsonify({"error": "目标路径已存在"}), 409

        os.rename(source_full_path, target_full_path)
        return jsonify({
            "success": True,
            "message": "项目移动成功",
            "sourcePath": source_path,
            "targetPath": target_path,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def deleteWorkspaceFile(filePath):
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        logMessage(f"收到删除文件请求: {filePath}")
        file_path = urllib.parse.unquote(filePath)
        logMessage(f"URL解码后的路径: {file_path}")

        is_valid, full_path = validateWorkspacePath(file_path)
        logMessage(f"路径验证结果: isValid={is_valid}, fullPath={full_path}")
        if not is_valid:
            logMessage(f"路径验证失败: {full_path}")
            return jsonify({"error": full_path}), 400

        file_exists = os.path.exists(full_path)
        is_file = os.path.isfile(full_path)
        logMessage(f"文件检查: exists={file_exists}, isFile={is_file}, path={full_path}")

        if file_exists and is_file:
            try:
                os.remove(full_path)
                logMessage(f"文件删除成功: {full_path}")
                return jsonify({
                    "success": True,
                    "message": "文件删除成功",
                    "filePath": file_path,
                })
            except Exception as exc:
                logMessage(f"文件删除操作失败: {str(exc)}", "ERROR")
                return jsonify({
                    "error": f"删除失败: {str(exc)}",
                    "filePath": file_path,
                }), 500

        logMessage(f"文件不存在: {full_path}")
        return jsonify({
            "error": "文件不存在",
            "filePath": file_path,
            "fullPath": full_path,
            "exists": file_exists,
            "isFile": is_file,
        }), 404
    except Exception as exc:
        logMessage(f"删除文件处理失败: {str(exc)}", "ERROR")
        return jsonify({"error": str(exc), "filePath": filePath}), 500


def getWorkspaceInfo():
    try:
        tiles_dir = config["tilesDir"]
        total_size = 0
        total_files = 0
        total_dirs = 0

        for root, dirs, files in os.walk(tiles_dir):
            total_dirs += len(dirs)
            total_files += len(files)
            for filename in files:
                try:
                    file_path = os.path.join(root, filename)
                    total_size += os.path.getsize(file_path)
                except Exception:
                    pass

        return jsonify({
            "success": True,
            "workspaceInfo": {
                "basePath": tiles_dir,
                "totalSize": total_size,
                "totalSizeFormatted": formatFileSize(total_size),
                "totalFiles": total_files,
                "totalDirectories": total_dirs,
                "lastUpdated": datetime.now().isoformat(),
            },
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def browseDirectory():
    """逐级浏览结果目录或数据源目录。"""
    try:
        browse_type = request.args.get("type", "results")
        path = request.args.get("path", "").strip("/")
        base_dir = config["dataSourceDir"] if browse_type == "datasource" else config["tilesDir"]
        full_path = os.path.join(base_dir, path) if path else base_dir
        full_path = os.path.abspath(full_path)
        base_dir = os.path.abspath(base_dir)

        if not full_path.startswith(base_dir):
            return jsonify({"error": "路径不允许访问"}), 403
        if not os.path.exists(full_path):
            return jsonify({"error": "目录不存在"}), 404
        if not os.path.isdir(full_path):
            return jsonify({"error": "路径不是目录"}), 400

        directories = []
        files = []
        try:
            items = os.listdir(full_path)
            items.sort()
            for item in items:
                item_path = os.path.join(full_path, item)
                if os.path.isdir(item_path):
                    try:
                        sub_items = os.listdir(item_path)
                        sub_file_count = len([name for name in sub_items if os.path.isfile(os.path.join(item_path, name))])
                        sub_dir_count = len([name for name in sub_items if os.path.isdir(os.path.join(item_path, name))])
                    except Exception:
                        sub_file_count = 0
                        sub_dir_count = 0

                    directories.append(
                        {
                            "name": item,
                            "type": "directory",
                            "path": os.path.join(path, item) if path else item,
                            "fileCount": sub_file_count,
                            "dirCount": sub_dir_count,
                        }
                    )
                elif os.path.isfile(item_path):
                    file_size = os.path.getsize(item_path)
                    mod_time = os.path.getmtime(item_path)
                    files.append(
                        {
                            "name": item,
                            "type": "file",
                            "size": file_size,
                            "sizeFormatted": formatFileSize(file_size),
                            "modifiedTime": mod_time,
                            "extension": os.path.splitext(item)[1].lower(),
                            "path": os.path.join(path, item) if path else item,
                        }
                    )
        except PermissionError:
            return jsonify({"error": "权限不足"}), 403

        parent_path = None
        if path:
            path_parts = path.split("/")
            parent_path = "/".join(path_parts[:-1]) if len(path_parts) > 1 else ""

        return jsonify(
            {
                "currentPath": path,
                "parentPath": parent_path,
                "baseType": browse_type,
                "directories": directories,
                "files": files,
                "totalDirectories": len(directories),
                "totalFiles": len(files),
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def getFileDetails():
    """获取结果文件或数据源文件的详细信息。"""
    try:
        browse_type = request.args.get("type", "results")
        file_path = request.args.get("path", "")
        if not file_path:
            return jsonify({"error": "缺少文件路径参数"}), 400

        base_dir = config["dataSourceDir"] if browse_type == "datasource" else config["tilesDir"]
        full_path = os.path.join(base_dir, file_path)
        full_path = os.path.abspath(full_path)
        base_dir = os.path.abspath(base_dir)

        if not full_path.startswith(base_dir):
            return jsonify({"error": "路径不允许访问"}), 403
        if not os.path.exists(full_path):
            return jsonify({"error": "文件不存在"}), 404
        if not os.path.isfile(full_path):
            return jsonify({"error": "路径不是文件"}), 400

        return jsonify(getFileInfo(full_path))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

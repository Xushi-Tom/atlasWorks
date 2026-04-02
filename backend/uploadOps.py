#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

from flask import jsonify, request
from werkzeug.utils import secure_filename

from config import config
from utils import formatFileSize, logMessage, safeJoin, validateDataSourcePath, validateWorkspacePath


def _normalize_relpath(value: str) -> str:
    text = str(value or "").replace("\\", "/").strip()
    text = text.lstrip("/")
    # collapse .. and .
    normalized = os.path.normpath(text).replace("\\", "/")
    normalized = normalized.lstrip("/")
    if normalized in {".", ""}:
        return ""
    if normalized.startswith("../") or "/../" in normalized or normalized == "..":
        raise ValueError("路径包含非法字符")
    return normalized


def _get_target_dir():
    target_path = request.form.get("targetPath", "")
    target_type = str(request.form.get("targetType", "datasource")).strip().lower() or "datasource"
    validator = validateWorkspacePath if target_type == "workspace" else validateDataSourcePath
    ok, full_path = validator(target_path)
    if not ok:
        raise ValueError(full_path)
    os.makedirs(full_path, exist_ok=True)
    return target_path.strip("/"), full_path, target_type


def _get_validator(target_type: str):
    return validateWorkspacePath if target_type == "workspace" else validateDataSourcePath


def _extract_zip_to_dir(zip_path: str, output_dir: str):
    extracted = []
    total_uncompressed = 0
    max_files = 20000
    max_uncompressed_bytes = 20 * 1024 * 1024 * 1024

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        infos = [info for info in zip_ref.infolist() if not info.is_dir()]
        if len(infos) > max_files:
            raise ValueError(f"压缩包文件数量过多（>{max_files}）")

        for info in infos:
            total_uncompressed += int(info.file_size or 0)
            if total_uncompressed > max_uncompressed_bytes:
                raise ValueError(f"压缩包解压总大小超过限制（>{formatFileSize(max_uncompressed_bytes)}）")

            rel_name = _normalize_relpath(info.filename)
            if not rel_name:
                continue

            dest_path = safeJoin(output_dir, rel_name)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with zip_ref.open(info, "r") as src, open(dest_path, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            extracted.append(rel_name)

    return extracted


def _extract_tar_to_dir(archive_path: str, output_dir: str):
    extracted = []
    total_uncompressed = 0
    max_files = 20000
    max_uncompressed_bytes = 20 * 1024 * 1024 * 1024

    with tarfile.open(archive_path, "r:*") as tar_ref:
        members = [member for member in tar_ref.getmembers() if member.isfile()]
        if len(members) > max_files:
            raise ValueError(f"压缩包文件数量过多（>{max_files}）")

        for member in members:
            total_uncompressed += int(member.size or 0)
            if total_uncompressed > max_uncompressed_bytes:
                raise ValueError(f"压缩包解压总大小超过限制（>{formatFileSize(max_uncompressed_bytes)}）")

            rel_name = _normalize_relpath(member.name)
            if not rel_name:
                continue

            dest_path = safeJoin(output_dir, rel_name)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            src = tar_ref.extractfile(member)
            if src is None:
                continue
            with src, open(dest_path, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            extracted.append(rel_name)

    return extracted


def _extract_7z_to_dir(archive_path: str, output_dir: str):
    seven_zip = shutil.which("7z")
    if not seven_zip:
        raise ValueError("当前服务未安装 7z 解压组件")

    result = subprocess.run(
        [seven_zip, "x", "-y", f"-o{output_dir}", archive_path],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise ValueError(message or "7z 解压失败")

    extracted = []
    for root, _, files in os.walk(output_dir):
        for filename in files:
            rel_name = os.path.relpath(os.path.join(root, filename), output_dir).replace("\\", "/")
            extracted.append(rel_name)
    return extracted


def extractArchiveFile():
    """解压已存在的数据源或工作空间压缩文件到其所在目录。"""
    try:
        data = request.get_json(silent=True) or {}
        rel_path = _normalize_relpath(data.get("path", ""))
        target_type = str(data.get("targetType", "datasource")).strip().lower() or "datasource"
        overwrite = bool(data.get("overwrite", False))
        if not rel_path:
            return jsonify({"error": "缺少参数: path"}), 400

        validator = _get_validator(target_type)
        ok, archive_path = validator(rel_path)
        if not ok:
            return jsonify({"error": archive_path}), 400
        if not os.path.exists(archive_path) or not os.path.isfile(archive_path):
            return jsonify({"error": "压缩文件不存在"}), 404

        parent_dir = os.path.dirname(archive_path)
        temp_dir = tempfile.mkdtemp(prefix="atlasworks_extract_", dir=tempfile.gettempdir())
        try:
            archive_name = os.path.basename(archive_path).lower()
            if zipfile.is_zipfile(archive_path):
                extracted = _extract_zip_to_dir(archive_path, temp_dir)
            elif tarfile.is_tarfile(archive_path):
                extracted = _extract_tar_to_dir(archive_path, temp_dir)
            elif archive_name.endswith(".7z"):
                extracted = _extract_7z_to_dir(archive_path, temp_dir)
            else:
                return jsonify({"error": "当前仅支持 zip、tar 系列和 7z 解压"}), 400

            copied = []
            for rel_name in extracted:
                temp_file = safeJoin(temp_dir, rel_name)
                dest_path = safeJoin(parent_dir, rel_name)
                if os.path.exists(dest_path) and not overwrite:
                    continue
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(temp_file, dest_path)

                archive_dir_ok, archive_root = validator("")
                rel_saved = os.path.relpath(dest_path, archive_root).replace("\\", "/") if archive_dir_ok else rel_name
                copied.append(rel_saved)

            logMessage(f"压缩文件解压完成: {archive_path}, files={len(copied)}, targetType={target_type}", "INFO")
            return jsonify({
                "success": True,
                "message": "解压完成",
                "targetType": target_type,
                "sourcePath": rel_path,
                "count": len(copied),
                "files": copied[:200],
                "note": "仅返回前200个文件路径" if len(copied) > 200 else None,
            })
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except zipfile.BadZipFile:
        return jsonify({"error": "ZIP 文件损坏或格式不正确"}), 400
    except tarfile.ReadError:
        return jsonify({"error": "TAR 文件损坏或格式不正确"}), 400
    except Exception as exc:
        logMessage(f"压缩文件解压失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def uploadSingleFile():
    """
    上传单个文件到数据源目录。
    multipart/form-data:
      - file: File
      - targetPath: str (optional)
      - overwrite: 0/1 (optional)
    """
    try:
        if "file" not in request.files:
            return jsonify({"error": "缺少文件字段: file"}), 400

        file_obj = request.files["file"]
        if not file_obj or not file_obj.filename:
            return jsonify({"error": "文件名为空"}), 400

        overwrite = str(request.form.get("overwrite", "0")).strip().lower() in {"1", "true", "yes", "on"}
        rel_target, target_dir, target_type = _get_target_dir()

        original_name = file_obj.filename
        safe_name = secure_filename(original_name) or os.path.basename(original_name)
        if not safe_name:
            return jsonify({"error": "无法解析文件名"}), 400

        dest_path = safeJoin(target_dir, safe_name)
        if os.path.exists(dest_path) and not overwrite:
            return jsonify({"error": "目标文件已存在，请勾选覆盖或更换文件名"}), 409

        file_obj.save(dest_path)
        size_bytes = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
        rel_saved = f"{rel_target}/{safe_name}".strip("/") if rel_target else safe_name

        logMessage(f"上传文件成功: {original_name} -> {dest_path} ({formatFileSize(size_bytes)})", "INFO")
        return jsonify({
            "success": True,
            "message": "上传成功",
            "saved": {
                "name": safe_name,
                "path": rel_saved,
                "fullPath": dest_path,
                "size": size_bytes,
                "sizeFormatted": formatFileSize(size_bytes),
            },
            "targetType": target_type,
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logMessage(f"上传文件失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def uploadZipArchive():
    """
    上传 ZIP 并解压到数据源目录。
    multipart/form-data:
      - file: File (.zip)
      - targetPath: str (optional)
      - overwrite: 0/1 (optional)
      - stripTopLevel: 0/1 (optional)  是否去掉顶层目录（如果 zip 只有一个顶层文件夹）
    """
    try:
        if "file" not in request.files:
            return jsonify({"error": "缺少文件字段: file"}), 400

        file_obj = request.files["file"]
        if not file_obj or not file_obj.filename:
            return jsonify({"error": "文件名为空"}), 400

        filename = file_obj.filename
        if not filename.lower().endswith(".zip"):
            return jsonify({"error": "仅支持 .zip 文件"}), 400

        overwrite = str(request.form.get("overwrite", "0")).strip().lower() in {"1", "true", "yes", "on"}
        strip_top_level = str(request.form.get("stripTopLevel", "1")).strip().lower() in {"1", "true", "yes", "on"}
        rel_target, target_dir, target_type = _get_target_dir()

        temp_dir = tempfile.mkdtemp(prefix="atlasworks_zip_", dir=tempfile.gettempdir())
        try:
            temp_zip = os.path.join(temp_dir, "upload.zip")
            file_obj.save(temp_zip)

            extracted_files = []
            total_uncompressed = 0
            max_files = 20000
            max_uncompressed_bytes = 20 * 1024 * 1024 * 1024  # 20GB

            with zipfile.ZipFile(temp_zip, "r") as zip_ref:
                infos = [info for info in zip_ref.infolist() if not info.is_dir()]
                if len(infos) > max_files:
                    return jsonify({"error": f"ZIP 文件数量过多（>{max_files}）"}), 400

                # 尝试识别单一顶层目录
                top_level_prefix = None
                if strip_top_level:
                    prefixes = set()
                    for info in infos[:5000]:
                        raw = info.filename.replace("\\", "/").lstrip("/")
                        parts = [p for p in raw.split("/") if p]
                        if len(parts) >= 2:
                            prefixes.add(parts[0])
                        else:
                            prefixes.add("")
                    if len(prefixes) == 1 and "" not in prefixes:
                        top_level_prefix = list(prefixes)[0] + "/"

                for info in infos:
                    total_uncompressed += int(info.file_size or 0)
                    if total_uncompressed > max_uncompressed_bytes:
                        return jsonify({"error": f"ZIP 解压总大小超过限制（>{formatFileSize(max_uncompressed_bytes)}）"}), 400

                    raw_name = info.filename.replace("\\", "/").lstrip("/")
                    if top_level_prefix and raw_name.startswith(top_level_prefix):
                        raw_name = raw_name[len(top_level_prefix):]

                    rel_name = _normalize_relpath(raw_name)
                    if not rel_name:
                        continue

                    dest_path = safeJoin(target_dir, rel_name)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    if os.path.exists(dest_path) and not overwrite:
                        continue

                    with zip_ref.open(info, "r") as src, open(dest_path, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)

                    rel_saved = f"{rel_target}/{rel_name}".strip("/") if rel_target else rel_name
                    extracted_files.append(rel_saved)

            logMessage(f"ZIP 解压完成: {filename} -> {target_dir}, files={len(extracted_files)}", "INFO")
            return jsonify({
                "success": True,
                "message": "ZIP 上传并解压完成",
                "targetPath": rel_target,
                "targetType": target_type,
                "count": len(extracted_files),
                "files": extracted_files[:200],
                "note": "仅返回前200个文件路径" if len(extracted_files) > 200 else None,
            })
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except zipfile.BadZipFile:
        return jsonify({"error": "ZIP 文件损坏或格式不正确"}), 400
    except Exception as exc:
        logMessage(f"ZIP 上传失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500


def uploadFolderFiles():
    """
    上传文件夹（多个文件 + 相对路径数组）。
    multipart/form-data:
      - files: File[] (multiple)
      - paths: str[] (multiple, each is relative path like a/b/c.tif)
      - targetPath: str (optional)
      - overwrite: 0/1 (optional)
    """
    try:
        files = request.files.getlist("files")
        paths = request.form.getlist("paths")
        if not files:
            return jsonify({"error": "缺少文件字段: files"}), 400

        overwrite = str(request.form.get("overwrite", "0")).strip().lower() in {"1", "true", "yes", "on"}
        rel_target, target_dir, target_type = _get_target_dir()

        saved = []
        for index, file_obj in enumerate(files):
            if not file_obj or not file_obj.filename:
                continue

            rel_name = ""
            if index < len(paths) and paths[index]:
                rel_name = _normalize_relpath(paths[index])
            else:
                rel_name = secure_filename(file_obj.filename) or os.path.basename(file_obj.filename)
                rel_name = _normalize_relpath(rel_name)

            if not rel_name:
                continue

            dest_path = safeJoin(target_dir, rel_name)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            if os.path.exists(dest_path) and not overwrite:
                continue

            file_obj.save(dest_path)
            rel_saved = f"{rel_target}/{rel_name}".strip("/") if rel_target else rel_name
            saved.append(rel_saved)

        logMessage(f"文件夹上传完成: target={target_dir}, saved={len(saved)}", "INFO")
        return jsonify({
            "success": True,
            "message": "文件夹上传完成",
            "targetPath": rel_target,
            "targetType": target_type,
            "count": len(saved),
            "files": saved[:200],
            "note": "仅返回前200个文件路径" if len(saved) > 200 else None,
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logMessage(f"文件夹上传失败: {exc}", "ERROR")
        return jsonify({"error": str(exc)}), 500

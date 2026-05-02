#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import signal
import psutil
import math
import re
import ctypes
from datetime import datetime
from typing import Dict, List, Optional, Union
from config import config, taskStatus, taskProcesses, taskStopFlags, taskLock

try:
    import psutil
    psutilAvailable = True
except ImportError:
    psutilAvailable = False

try:
    import numpy as np
    numpyAvailable = True
except ImportError:
    numpyAvailable = False

try:
    from PIL import Image, ImageChops
    pilAvailable = True
except ImportError:
    pilAvailable = False

def getOptimalCacheSize():
    """
    获取最优缓存大小，基于系统内存自动计算
    
    @return 缓存大小字符串（MB）
    """
    if not psutilAvailable:
        return "512"
    
    try:
        totalMemory = psutil.virtual_memory().total
        cacheMb = max(256, min(2048, totalMemory // (1024 * 1024 * 8)))
        return str(cacheMb)
    except:
        return "512"

def getOptimalProcesses():
    """
    获取最优进程数，基于CPU核心数和可用内存计算
    
    @return 最优进程数
    """
    if not psutilAvailable:
        return 4
    
    try:
        cpuCount = psutil.cpu_count() or 4
        availableMemory = psutil.virtual_memory().available
        
        # 基于内存限制进程数（每个进程预估需要2GB内存）
        memoryBasedProcesses = max(1, availableMemory // (2 * 1024 * 1024 * 1024))
        
        # 取CPU核心数和内存限制进程数的最小值
        return min(cpuCount, memoryBasedProcesses, 8)  # 最多8个进程
    except:
        return 4

def convertMemoryToMb(memoryStr):
    """
    将内存字符串转换为MB单位
    
    @param memoryStr 内存字符串，如"1g"、"512m"等
    @return 转换后的MB数值字符串
    """
    if memoryStr.endswith('g') or memoryStr.endswith('G'):
        return str(int(float(memoryStr[:-1]) * 1024))
    elif memoryStr.endswith('m') or memoryStr.endswith('M'):
        return memoryStr[:-1]
    else:
        return memoryStr

def convertMemoryToBytes(memoryStr):
    """
    将内存字符串转换为字节
    
    @param memoryStr 内存字符串，如"1g"、"512m"、"1024k"等
    @return 转换后的字节数
    """
    if memoryStr.endswith('g') or memoryStr.endswith('G'):
        return int(float(memoryStr[:-1]) * 1024 * 1024 * 1024)
    elif memoryStr.endswith('m') or memoryStr.endswith('M'):
        return int(float(memoryStr[:-1]) * 1024 * 1024)
    elif memoryStr.endswith('k') or memoryStr.endswith('K'):
        return int(float(memoryStr[:-1]) * 1024)
    else:
        try:
            return int(memoryStr)
        except:
            return 1024 * 1024 * 1024  # 默认1GB

def normalizeProjection(projection):
    """规范化投影标识。"""
    if not projection:
        return "EPSG:3857"
    value = str(projection).strip()
    normalized = value.lower()
    mapping = {
        "wgs84 web mercator": "EPSG:3857",
        "wgs84 pseudo-mercator": "EPSG:3857",
        "web mercator": "EPSG:3857",
        "mercator": "EPSG:3857",
        "wgs84": "EPSG:4326",
        "epsg:4326": "EPSG:4326",
        "cgcs2000": "EPSG:4490",
        "epsg:4490": "EPSG:4490",
    }
    return mapping.get(normalized, value)

def normalizeImageFormat(imageFormat):
    """规范化输出图片格式。"""
    if not imageFormat:
        return "png"
    value = str(imageFormat).strip().lower()
    if value in ("jpg", "jpeg"):
        return "jpeg"
    return "png"

def normalizeTileScheme(tileScheme):
    """规范化瓦片坐标系名称。"""
    if not tileScheme:
        return "tms"
    value = str(tileScheme).strip().lower()
    if value in ("google", "googlexyz", "xyz"):
        return "google"
    return "tms"

def normalizeBandMismatchPolicy(policy):
    """规范化波段不匹配处理策略。"""
    if not policy:
        return "auto"
    value = str(policy).strip().lower()
    if value in ("strict", "skip"):
        return value
    return "auto"

def normalizeInt(value, defaultValue, minValue=None, maxValue=None):
    """安全转换为整数并限制范围。"""
    try:
        result = int(value)
    except Exception:
        result = defaultValue
    if minValue is not None:
        result = max(minValue, result)
    if maxValue is not None:
        result = min(maxValue, result)
    return result

def normalizeFloat(value, defaultValue=None):
    """安全转换为浮点数。"""
    if value is None or value == "":
        return defaultValue
    try:
        return float(value)
    except Exception:
        return defaultValue

def parseMemoryToGb(memoryValue, defaultGb=8.0):
    """将内存配置转换为 GB。"""
    if memoryValue is None or memoryValue == "":
        return float(defaultGb)
    if isinstance(memoryValue, (int, float)):
        return max(0.5, float(memoryValue))
    text = str(memoryValue).strip().lower()
    match = re.match(r'^([0-9]+(?:\.[0-9]+)?)\s*([kmgt]?)b?$', text)
    if not match:
        return float(defaultGb)
    value = float(match.group(1))
    unit = match.group(2)
    if unit == 't':
        value *= 1024.0
    elif unit == 'm':
        value /= 1024.0
    elif unit == 'k':
        value /= (1024.0 * 1024.0)
    return max(0.5, value)

def formatFileSize(sizeBytes: int) -> str:
    """
    格式化文件大小为人类可读的格式
    
    @param sizeBytes 文件大小（字节）
    @return 格式化后的文件大小字符串
    """
    if sizeBytes < 1024:
        return f"{sizeBytes} B"
    elif sizeBytes < 1024 * 1024:
        return f"{sizeBytes / 1024:.1f} KB"
    elif sizeBytes < 1024 * 1024 * 1024:
        return f"{sizeBytes / (1024 * 1024):.1f} MB"
    else:
        return f"{sizeBytes / (1024 * 1024 * 1024):.1f} GB"

def formatDuration(seconds: float) -> str:
    """
    格式化时间间隔为人类可读的格式
    
    @param seconds 时间间隔（秒）
    @return 格式化后的时间字符串
    """
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        return f"{seconds // 60:.0f}分{seconds % 60:.0f}秒"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours:.0f}小时{minutes:.0f}分钟"

def logMessage(message: str, level: str = "INFO"):
    """
    记录日志消息到控制台和日志文件
    
    @param message 日志消息内容
    @param level 日志级别（INFO、WARNING、ERROR）
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logLine = f"[{timestamp}] {level}: {message}"
    print(logLine)
    
    try:
        logFile = os.path.join(config["logDir"], f"tile_service_{datetime.now().strftime('%Y%m%d')}.log")
        with open(logFile, 'a', encoding='utf-8') as f:
            f.write(logLine + '\n')
    except Exception as e:
        print(f"日志写入失败: {e}")

def runCommand(cmd: List[str], cwd: str = None, env: dict = None) -> Dict:
    """运行系统命令"""
    try:
        if env is None:
            env = os.environ.copy()
        
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=3600  # 1小时超时
        )
        
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "命令执行超时"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def runCommandWithProcessTracking(cmd: List[str], taskId: str, cwd: str = None, env: dict = None) -> Dict:
    """运行命令并跟踪进程"""
    previous_entry = None
    process = None
    try:
        if env is None:
            env = os.environ.copy()
        
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # 记录进程
        with taskLock:
            previous_entry = taskProcesses.get(taskId)
            taskProcesses[taskId] = process
        
        stdout, stderr = process.communicate()
        
        # 清理进程记录
        with taskLock:
            current = taskProcesses.get(taskId)
            if current is process:
                if previous_entry is not None:
                    taskProcesses[taskId] = previous_entry
                else:
                    del taskProcesses[taskId]
        
        return {
            "success": process.returncode == 0,
            "returncode": process.returncode,
            "stdout": stdout,
            "stderr": stderr
        }
    except Exception as e:
        # 清理进程记录
        with taskLock:
            current = taskProcesses.get(taskId)
            if process is not None and current is process:
                if previous_entry is not None:
                    taskProcesses[taskId] = previous_entry
                else:
                    del taskProcesses[taskId]
        return {
            "success": False,
            "error": str(e)
        }

def _force_stop_thread(thread_obj) -> bool:
    """尝试向线程注入 SystemExit，实现强制停止。"""
    thread_id = getattr(thread_obj, "ident", None)
    if not thread_id:
        return False

    try:
        result = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(int(thread_id)),
            ctypes.py_object(SystemExit),
        )
        if result == 0:
            return False
        if result > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(int(thread_id)), None)
            return False
        return True
    except Exception:
        return False

def stopTaskProcess(taskId: str) -> bool:
    """停止任务进程（支持subprocess和Thread）"""
    try:
        with taskLock:
            if taskId in taskProcesses:
                process_or_thread = taskProcesses[taskId]
                taskStopFlags[taskId] = True
                
                # 检查是线程还是进程
                if hasattr(process_or_thread, 'terminate'):
                    # 这是一个subprocess.Popen对象
                    try:
                        # 尝试优雅关闭
                        process_or_thread.terminate()
                        process_or_thread.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        # 强制终止
                        process_or_thread.kill()
                        process_or_thread.wait()
                else:
                    # 这是一个Thread对象
                    # 注意：Python的Thread对象无法强制停止
                    # 我们设置停止标志让线程自己检查并退出
                    forced = False
                    if str(taskId or "").startswith("tiles3d"):
                        forced = _force_stop_thread(process_or_thread)
                    if forced:
                        logMessage(f"线程任务 {taskId} 已执行强制停止", "INFO")
                    else:
                        logMessage(f"线程任务 {taskId} 已标记为停止状态", "INFO")
                
                del taskProcesses[taskId]
                return True
            return False
    except Exception as e:
        logMessage(f"停止任务进程失败: {e}", "ERROR")
        return False

def cleanupTempFiles(tempFiles):
    """清理临时文件"""
    for filePath in tempFiles:
        try:
            if os.path.exists(filePath):
                fileSize = os.path.getsize(filePath)
                os.remove(filePath)
                logMessage(f"已删除临时文件: {filePath} ({formatFileSize(fileSize)})")
        except Exception as e:
            logMessage(f"删除临时文件失败 {filePath}: {e}", "WARNING")

def validateWorkspacePath(subpath: str) -> tuple:
    """验证工作空间路径"""
    try:
        # 去除前后斜杠
        subpath = subpath.strip('/')
        
        # 检查路径是否包含危险字符
        if '..' in subpath or subpath.startswith('/'):
            return False, "路径包含非法字符"
        
        # 构建完整路径
        fullPath = os.path.join(config["tilesDir"], subpath)
        
        # 安全检查：确保路径在允许的目录内
        fullPath = os.path.abspath(fullPath)
        tilesDir = os.path.abspath(config["tilesDir"])
        
        if not fullPath.startswith(tilesDir):
            return False, "路径不在允许的目录内"
        
        # 记录路径信息
        logMessage(f"验证路径: {subpath} -> {fullPath}")
        
        return True, fullPath
    except Exception as e:
        logMessage(f"路径验证失败: {str(e)}")
        return False, str(e)


def safeJoin(baseDir: str, *paths: str) -> str:
    """
    安全拼接路径，防止目录遍历。
    返回绝对路径；若越界则抛 ValueError。
    """
    baseDirAbs = os.path.abspath(baseDir)
    candidate = os.path.abspath(os.path.join(baseDirAbs, *[p or "" for p in paths]))
    if not candidate.startswith(baseDirAbs):
        raise ValueError("路径不在允许的目录内")
    return candidate


def resolveTilesOutputPath(outputPathValue, folderPrefix: str) -> tuple:
    """
    解析产物输出目录。
    如果未传 outputPath，则自动生成:
    tilesDir/YYYYMMDD/<folderPrefix>-HHMMSS[-NN]
    """
    baseDir = os.path.abspath(config["tilesDir"])
    normalizedPrefix = re.sub(r"[^a-z0-9_-]+", "-", str(folderPrefix or "output").strip().lower()).strip("-") or "output"

    if isinstance(outputPathValue, list):
        outputParts = [str(part or "").strip().strip("/\\") for part in outputPathValue if str(part or "").strip().strip("/\\")]
        if outputParts:
            return safeJoin(baseDir, *outputParts), outputParts, False
    elif isinstance(outputPathValue, str):
        normalizedValue = outputPathValue.strip().strip("/\\")
        if normalizedValue:
            return safeJoin(baseDir, normalizedValue), normalizedValue, False
    elif outputPathValue not in (None, "", []):
        normalizedValue = str(outputPathValue).strip().strip("/\\")
        if normalizedValue:
            return safeJoin(baseDir, normalizedValue), normalizedValue, False

    now = datetime.now()
    dateFolder = now.strftime("%Y%m%d")
    timeToken = now.strftime("%H%M%S")
    attempt = 0
    while True:
        suffix = "" if attempt == 0 else f"-{attempt:02d}"
        folderName = f"{normalizedPrefix}-{timeToken}{suffix}"
        outputParts = [dateFolder, folderName]
        outputPath = safeJoin(baseDir, *outputParts)
        if not os.path.exists(outputPath):
            return outputPath, outputParts, True
        attempt += 1


def validateDataSourcePath(subpath: str) -> tuple:
    """验证数据源路径（相对于 dataSourceDir）。"""
    try:
        subpath = (subpath or "").strip().strip("/")
        if not subpath:
            return True, os.path.abspath(config["dataSourceDir"])

        if ".." in subpath or subpath.startswith("/") or subpath.startswith("\\"):
            return False, "路径包含非法字符"

        fullPath = os.path.abspath(os.path.join(config["dataSourceDir"], subpath))
        dataDir = os.path.abspath(config["dataSourceDir"])
        if not fullPath.startswith(dataDir):
            return False, "路径不在允许的目录内"

        logMessage(f"验证数据源路径: {subpath} -> {fullPath}")
        return True, fullPath
    except Exception as exc:
        logMessage(f"数据源路径验证失败: {exc}", "WARNING")
        return False, str(exc)

def analyzeCoordinateSystem(gdalinfoOutput: str) -> dict:
    """分析坐标系统"""
    try:
        # 初始化结果
        result = {
            "type": "unknown",
            "epsg": None,
            "description": "未知坐标系",
            "suitable": False
        }
        
        # 检测地理坐标系（WGS84）
        if 'GEOGCS["WGS 84"' in gdalinfoOutput and 'PROJCS[' not in gdalinfoOutput:
            result.update({
                "type": "geographic",
                "epsg": "4326",
                "description": "WGS84地理坐标系",
                "suitable": True
            })
        
        # 检测Web墨卡托投影
        elif 'PROJCS["WGS 84 / Pseudo-Mercator"' in gdalinfoOutput or 'EPSG","3857"' in gdalinfoOutput:
            result.update({
                "type": "webMercator",
                "epsg": "3857",
                "description": "Web墨卡托投影",
                "suitable": True
            })
        
        # 检测世界墨卡托投影
        elif 'PROJCS["World_Mercator"' in gdalinfoOutput or 'PROJCS["WGS 84 / World Mercator"' in gdalinfoOutput:
            result.update({
                "type": "worldMercator",
                "epsg": "3395",
                "description": "世界墨卡托投影",
                "suitable": True
            })
        
        # 检测UTM投影
        elif 'PROJCS[' in gdalinfoOutput and 'UTM' in gdalinfoOutput:
            result.update({
                "type": "utm",
                "description": "UTM投影坐标系",
                "suitable": False
            })
            
            if 'UTM Zone' in gdalinfoOutput:
                zoneMatch = re.search(r'UTM Zone (\d+)', gdalinfoOutput)
                if zoneMatch:
                    zone = zoneMatch.group(1)
                    result["description"] = f"UTM Zone {zone}"
                    result["zone"] = zone
        
        # 检测其他投影坐标系
        elif 'PROJCS[' in gdalinfoOutput:
            result.update({
                "type": "customProjected",
                "description": "自定义投影坐标系",
                "suitable": False
            })
            
            # 尝试提取投影名称
            nameMatch = re.search(r'PROJCS\["([^"]+)"', gdalinfoOutput)
            if nameMatch:
                result["description"] = nameMatch.group(1)
        
        return result
        
    except Exception as e:
        logMessage(f"坐标系分析失败: {e}", "ERROR")
        return {
            "type": "error",
            "description": f"坐标系分析失败: {str(e)}",
            "suitable": False
        }

def deg2tile(lat_deg, lon_deg, zoom):
    """经纬度转瓦片坐标"""
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    x = int((lon_deg + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (x, y)

def tile2deg(x, y, zoom):
    """瓦片坐标转经纬度"""
    n = 2.0 ** zoom
    lon_deg = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)

def calculateOptimalGridSize(maxZoom: int, fileCount: int) -> int:
    """计算最优网格分割大小"""
    # 基于最大缩放级别和文件数量计算网格大小
    if maxZoom >= 18:
        return min(4, max(2, fileCount // 2))
    elif maxZoom >= 15:
        return min(3, max(2, fileCount // 3))
    elif maxZoom >= 12:
        return 2
    else:
        return 1

def extractGeographicBounds(gdalinfoOutput: str) -> Dict:
    """从gdalinfo输出中提取地理边界"""
    try:
        bounds = {}
        lines = gdalinfoOutput.split('\n')
        
        for line in lines:
            if 'Upper Left' in line:
                # 解析左上角坐标
                coordMatch = re.search(r'Upper Left\s*\(\s*([^,]+),\s*([^)]+)\)', line)
                if coordMatch:
                    try:
                        bounds['west'] = float(coordMatch.group(1).strip())
                        bounds['north'] = float(coordMatch.group(2).strip())
                    except:
                        # 如果是度分秒格式，尝试解析
                        pass
            elif 'Lower Right' in line:
                # 解析右下角坐标
                coordMatch = re.search(r'Lower Right\s*\(\s*([^,]+),\s*([^)]+)\)', line)
                if coordMatch:
                    try:
                        bounds['east'] = float(coordMatch.group(1).strip())
                        bounds['south'] = float(coordMatch.group(2).strip())
                    except:
                        # 如果是度分秒格式，尝试解析
                        pass
        
        # 计算宽度和高度
        if all(key in bounds for key in ['west', 'east', 'north', 'south']):
            bounds['widthDegrees'] = abs(bounds['east'] - bounds['west'])
            bounds['heightDegrees'] = abs(bounds['north'] - bounds['south'])
        
        return bounds
    except Exception as e:
        logMessage(f"提取地理边界失败: {e}", "ERROR")
        return {}

def isSuitableForLevelZero(geoBounds: Dict, imageWidth: int, imageHeight: int) -> bool:
    """判断是否适合0级切片"""
    try:
        # 检查是否有地理边界信息
        if not all(key in geoBounds for key in ['widthDegrees', 'heightDegrees']):
            return False
        
        widthDegrees = geoBounds.get('widthDegrees', 0)
        heightDegrees = geoBounds.get('heightDegrees', 0)
        
        # 全球覆盖的判断条件
        globalCoverageThreshold = {
            'width': 180,    # 至少覆盖180度经度
            'height': 90     # 至少覆盖90度纬度
        }
        
        # 高分辨率的判断条件
        highResolutionThreshold = {
            'width': 32768,  # 至少32K像素宽度
            'height': 16384  # 至少16K像素高度
        }
        
        # 条件1：地理覆盖范围广
        isGlobalCoverage = (widthDegrees >= globalCoverageThreshold['width'] and 
                           heightDegrees >= globalCoverageThreshold['height'])
        
        # 条件2：高分辨率图像
        isHighResolution = (imageWidth >= highResolutionThreshold['width'] and 
                           imageHeight >= highResolutionThreshold['height'])
        
        # 满足任一条件即可
        return isGlobalCoverage or isHighResolution
        
    except Exception as e:
        logMessage(f"判断0级切片适用性失败: {e}", "ERROR")
        return False 

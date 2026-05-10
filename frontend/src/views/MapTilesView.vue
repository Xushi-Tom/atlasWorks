<script setup>
import { onBeforeUnmount, reactive, ref, watch } from 'vue';

import PathPickerModal from '../components/PathPickerModal.vue';
import RecommendationModal from '../components/RecommendationModal.vue';
import { api } from '../services/api';
import { normalizeListInput } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const emit = defineEmits(['navigate']);

const form = reactive({
    folderPaths: '',
    filePatterns: '*.tif',
    outputPath: '',
    minZoom: 0,
    maxZoom: 16,
    tileSize: 256,
    processes: 4,
    threads: 4,
    maxMemory: '8g',
    resampling: 'near',
    projection: 'EPSG:3857',
    dataFormat: 'xyz',
    imageFormat: 'png',
    tileScheme: 'tms',
    redBand: 1,
    greenBand: 2,
    blueBand: 3,
    nodataValue: '',
    srcNodataValue: '',
    dstNodataValue: '',
    stretchType: 'percent',
    stretchLowPercent: 2,
    stretchHighPercent: 98,
    jpegQuality: 90,
    pngCompression: 6,
    bandMismatchPolicy: 'auto',
    transparencyThreshold: 0.1,
    generateShpIndex: true,
    enableIncrementalUpdate: false,
    skipNodataTiles: true
});

const picker = reactive({
    visible: false,
    title: '',
    source: 'datasource',
    selectionMode: 'file',
    multiple: false,
    field: '',
    allowedExtensions: []
});

const recommendationVisible = ref(false);
const recommendationSourceFile = ref('');
const recommendationData = ref(null);
const apiDocsUrl = `${window.location.origin}/api/docs`;
const bandHint = ref('支持自动读取：单个 tif 直接读取；多个 tif 按最小公共波段数。');
const bandOptions = ref(Array.from({ length: 16 }, (_, index) => index + 1));
const projectionOptions = [
    { value: 'EPSG:3857', label: 'Web 墨卡托 (EPSG:3857)' },
    { value: 'EPSG:4326', label: 'WGS84 经纬度 (EPSG:4326)' },
    { value: 'EPSG:4490', label: 'CGCS2000 (EPSG:4490)' }
];
const memoryOptions = [
    { value: '2g', label: '2 GB' },
    { value: '4g', label: '4 GB' },
    { value: '8g', label: '8 GB' },
    { value: '12g', label: '12 GB' },
    { value: '16g', label: '16 GB' },
    { value: '24g', label: '24 GB' },
    { value: '32g', label: '32 GB' },
    { value: '48g', label: '48 GB' },
    { value: '64g', label: '64 GB' }
];
const dataFormatOptions = [
    { value: 'xyz', label: 'XYZ 目录瓦片' },
    { value: 'tms', label: 'TMS 目录瓦片' }
];

let bandRefreshTimer = null;

function openPicker(config) {
    Object.assign(picker, config, { visible: true });
}

function getPickerCurrentValue() {
    return picker.field ? String(form[picker.field] || '') : '';
}

function applyPickerSelection(paths) {
    const nextValue = picker.multiple ? paths.join(', ') : (paths[0] || '');
    if (picker.field) {
        form[picker.field] = nextValue;
    }
}

function clearField(field) {
    form[field] = '';
}

function buildBandOptions(maxBandCount) {
    const safeMax = Math.max(1, Number.parseInt(maxBandCount, 10) || 1);
    return Array.from({ length: safeMax }, (_, index) => index + 1);
}

function applyBandRange(maxBandCount) {
    bandOptions.value = buildBandOptions(maxBandCount);
    form.redBand = Math.min(Math.max(Number(form.redBand) || 1, 1), bandOptions.value.length);
    form.greenBand = Math.min(Math.max(Number(form.greenBand) || 2, 1), bandOptions.value.length);
    form.blueBand = Math.min(Math.max(Number(form.blueBand) || 3, 1), bandOptions.value.length);
}

async function refreshBandOptions(showToast = false) {
    const folderPaths = normalizeListInput(form.folderPaths);
    const filePatterns = normalizeListInput(form.filePatterns);

    if (!filePatterns.length) {
        applyBandRange(16);
        bandHint.value = '未选择文件模式，当前为手动波段选择（1-16）。';
        if (showToast) pushToast('请先选择具体 tif、通配符或 txt 文件列表', 'warning');
        return;
    }

    try {
        const response = await api.resolveDatasourceFiles({
            folderPaths,
            filePatterns,
            maxFiles: 200
        });
        const payload = response?.data || {};
        const commonBandCount = Number.parseInt(payload?.bandSummary?.commonBandCount, 10);

        if (!Number.isFinite(commonBandCount) || commonBandCount <= 0) {
            applyBandRange(16);
            bandHint.value = '匹配到了文件，但未读取到有效波段数，已回退为手动波段选择（1-16）。';
            if (showToast) pushToast('未读取到有效波段数，已回退为手动选择', 'warning');
            return;
        }

        applyBandRange(commonBandCount);
        bandHint.value = payload.totalMatched === 1
            ? `已读取 1 个文件，可用波段数：${commonBandCount}。`
            : `已匹配 ${payload.totalMatched} 个文件，按最小公共波段数 ${commonBandCount} 生成下拉。${payload.truncated ? ' 当前仅统计前 200 个匹配文件。' : ''}`;

        if (showToast) {
            pushToast(`已按最小公共波段数 ${commonBandCount} 更新下拉`, 'success');
        }
    } catch (error) {
        applyBandRange(16);
        bandHint.value = '自动读取波段失败，已回退为手动波段选择（1-16）。';
        if (showToast) pushToast(`自动读取波段失败: ${error.message}`, 'warning');
    }
}

function scheduleRefreshBandOptions() {
    if (bandRefreshTimer) {
        window.clearTimeout(bandRefreshTimer);
    }
    bandRefreshTimer = window.setTimeout(() => {
        refreshBandOptions(false);
    }, 300);
}

function resolveRecommendationFile() {
    const patterns = normalizeListInput(form.filePatterns);
    if (!patterns.length) {
        pushToast('请先选择文件', 'warning');
        return null;
    }

    if (patterns.some(item => item.includes('*') || item.includes('?'))) {
        pushToast('智能推荐不支持通配符，请选择具体的 tif 文件', 'warning');
        return null;
    }

    if (patterns.some(item => item.toLowerCase().endsWith('.txt'))) {
        pushToast('智能推荐不支持 txt 文件，请只选择 tif 文件', 'warning');
        return null;
    }

    const tifFiles = patterns.filter(item => {
        const lower = item.toLowerCase();
        return lower.endsWith('.tif') || lower.endsWith('.tiff');
    });

    if (tifFiles.length !== 1 || patterns.length !== 1) {
        pushToast('智能推荐只支持单个 tif 文件', 'warning');
        return null;
    }

    return tifFiles[0];
}

async function requestRecommendation() {
    const sourceFile = resolveRecommendationFile();
    if (!sourceFile) return;

    try {
        recommendationSourceFile.value = sourceFile;
        const response = await api.recommendConfig({
            sourceFile,
            tileType: 'map'
        });
        recommendationData.value = response?.data || null;
        recommendationVisible.value = true;
    } catch (error) {
        pushToast(`智能推荐失败: ${error.message}`, 'error', 5000);
    }
}

function applyRecommendation(recommendations) {
    if (recommendations.minZoom !== undefined) form.minZoom = recommendations.minZoom;
    if (recommendations.maxZoom !== undefined) form.maxZoom = recommendations.maxZoom;
    if (recommendations.processes !== undefined) {
        form.processes = recommendations.processes;
        form.threads = recommendations.processes;
    }
    if (recommendations.maxMemory !== undefined) form.maxMemory = recommendations.maxMemory;
    if (recommendations.resampling !== undefined) form.resampling = recommendations.resampling;
    if (recommendations.tileFormat !== undefined) {
        const format = String(recommendations.tileFormat).toLowerCase();
        if (format === 'png' || format === 'jpeg' || format === 'jpg') {
            form.imageFormat = format === 'jpg' ? 'jpeg' : format;
        }
    }
    pushToast('已应用智能推荐参数', 'success');
}

async function submit() {
    const filePatterns = normalizeListInput(form.filePatterns);
    if (!form.outputPath || !filePatterns.length) {
        pushToast('请填写输出目录，并提供文件模式、具体文件或网络地址', 'warning');
        return;
    }

    try {
        const payload = {
            folderPaths: normalizeListInput(form.folderPaths),
            filePatterns,
            outputPath: form.outputPath,
            minZoom: Number(form.minZoom),
            maxZoom: Number(form.maxZoom),
            tileSize: Number(form.tileSize),
            processes: Number(form.processes),
            threads: Number(form.threads),
            maxMemory: form.maxMemory,
            resampling: form.resampling,
            projection: form.projection,
            dataFormat: form.dataFormat,
            imageFormat: form.imageFormat,
            tileScheme: form.tileScheme,
            redBand: Number(form.redBand),
            greenBand: Number(form.greenBand),
            blueBand: Number(form.blueBand),
            nodataValue: form.nodataValue === '' ? null : Number(form.nodataValue),
            srcNodataValue: form.srcNodataValue === '' ? null : Number(form.srcNodataValue),
            dstNodataValue: form.dstNodataValue === '' ? null : Number(form.dstNodataValue),
            stretchType: form.stretchType,
            stretchLowPercent: Number(form.stretchLowPercent),
            stretchHighPercent: Number(form.stretchHighPercent),
            jpegQuality: Number(form.jpegQuality),
            pngCompression: Number(form.pngCompression),
            bandMismatchPolicy: form.bandMismatchPolicy,
            transparencyThreshold: Number(form.transparencyThreshold),
            generateShpIndex: Boolean(form.generateShpIndex),
            enableIncrementalUpdate: Boolean(form.enableIncrementalUpdate),
            skipNodataTiles: Boolean(form.skipNodataTiles)
        };

        const result = await api.createIndexedTiles(payload);
        if (result?.success === false) {
            pushToast(result.message || '地图切片参数校验失败', 'warning', 5000);
        } else {
            pushToast(`地图切片任务已启动: ${result?.data?.taskId}`, 'success');
        }
        emit('navigate', { section: 'tasks' });
    } catch (error) {
        pushToast(`地图切片失败: ${error.message}`, 'error', 5000);
    }
}

watch(() => `${form.folderPaths}|${form.filePatterns}`, () => {
    scheduleRefreshBandOptions();
});

onBeforeUnmount(() => {
    if (bandRefreshTimer) {
        window.clearTimeout(bandRefreshTimer);
    }
});
</script>

<template>
    <section class="app-view standard-page">
        <div class="app-scroll">
            <div class="tile-page">
                <div class="tile-page-toolbar">
                    <div class="tile-page-toolbar__meta">
                        <div class="tile-page-toolbar__title">地图切片</div>
                        <div class="tile-page-toolbar__desc">按输入、核心参数、波段和构建策略自上而下配置二维栅格切片。</div>
                    </div>
                    <div class="tile-page-toolbar__actions">
                        <el-button @click="requestRecommendation">智能推荐</el-button>
                        <el-button type="primary" @click="submit">开始地图切片</el-button>
                    </div>
                </div>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">输入与输出</div></template>
                    <el-form label-position="top" class="tile-form">
                        <el-form-item label="数据源目录">
                            <div class="path-field path-field-inline">
                                <el-input v-model="form.folderPaths" placeholder="多个目录用逗号分隔，可留空" />
                                <div class="path-field-actions">
                                    <el-button @click="openPicker({ title: '选择数据源目录', source: 'datasource', selectionMode: 'folder', multiple: true, field: 'folderPaths', allowedExtensions: [] })">选择目录</el-button>
                                    <el-button @click="clearField('folderPaths')">清空</el-button>
                                </div>
                            </div>
                            <div class="tile-help">可留空。留空时默认从数据源根目录开始匹配。</div>
                        </el-form-item>

                        <el-form-item label="文件匹配模式">
                            <div class="path-field path-field-inline">
                                <el-input v-model="form.filePatterns" placeholder="支持具体 tif、通配符、txt 文件列表或 http/https 网络地址" />
                                <div class="path-field-actions">
                                    <el-button @click="openPicker({ title: '选择数据源文件', source: 'datasource', selectionMode: 'file', multiple: true, field: 'filePatterns', allowedExtensions: ['.tif', '.tiff', '.txt'] })">选择文件</el-button>
                                    <el-button @click="requestRecommendation">智能推荐</el-button>
                                    <el-button @click="clearField('filePatterns')">清空</el-button>
                                </div>
                            </div>
                            <div class="tile-help">
                                可直接传网络地址，例如 <code>https://example.com/aoi.tif</code>；多个来源用逗号分隔。
                                <a :href="apiDocsUrl" target="_blank" rel="noreferrer">接口示例</a>
                            </div>
                        </el-form-item>

                        <el-form-item label="输出目录">
                            <div class="path-field path-field-inline">
                                <el-input v-model="form.outputPath" placeholder="例如 map/project/v1" />
                                <div class="path-field-actions">
                                    <el-button @click="openPicker({ title: '选择输出目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'outputPath', allowedExtensions: [] })">选择目录</el-button>
                                    <el-button @click="clearField('outputPath')">清空</el-button>
                                </div>
                            </div>
                        </el-form-item>
                    </el-form>
                </el-card>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">核心参数</div></template>
                    <el-form label-position="top" class="tile-form">
                        <el-row :gutter="16">
                            <el-col :xs="24" :md="12"><el-form-item label="最小层级"><el-input-number v-model="form.minZoom" :min="0" :max="30" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="最大层级"><el-input-number v-model="form.maxZoom" :min="0" :max="30" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="瓦片尺寸"><el-input-number v-model="form.tileSize" :min="64" :step="64" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="进程数"><el-input-number v-model="form.processes" :min="1" :max="128" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="线程数"><el-input-number v-model="form.threads" :min="1" :max="64" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item label="最大内存">
                                    <el-select v-model="form.maxMemory">
                                        <el-option v-for="option in memoryOptions" :key="option.value" :label="option.label" :value="option.value" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item label="重采样">
                                    <el-select v-model="form.resampling">
                                        <el-option label="最近邻" value="near" />
                                        <el-option label="双线性" value="bilinear" />
                                        <el-option label="三次卷积" value="cubic" />
                                        <el-option label="Lanczos" value="lanczos" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item label="投影">
                                    <el-select v-model="form.projection">
                                        <el-option v-for="option in projectionOptions" :key="option.value" :label="option.label" :value="option.value" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item label="数据格式">
                                    <el-select v-model="form.dataFormat">
                                        <el-option v-for="option in dataFormatOptions" :key="option.value" :label="option.label" :value="option.value" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item label="图片格式">
                                    <el-select v-model="form.imageFormat">
                                        <el-option label="PNG" value="png" />
                                        <el-option label="JPEG" value="jpeg" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item label="瓦片坐标系">
                                    <el-select v-model="form.tileScheme">
                                        <el-option label="TMS 原点" value="tms" />
                                        <el-option label="XYZ 原点" value="google" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item label="波段不匹配策略">
                                    <el-select v-model="form.bandMismatchPolicy">
                                        <el-option label="自动处理" value="auto" />
                                        <el-option label="严格校验" value="strict" />
                                        <el-option label="跳过异常文件" value="skip" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                        </el-row>
                    </el-form>
                </el-card>

                <el-card shadow="never" class="tile-module">
                    <template #header>
                        <div class="tile-module__head">
                            <span class="tile-module__title">波段选择</span>
                            <el-button @click="refreshBandOptions(true)">获取波段信息</el-button>
                        </div>
                    </template>
                    <div class="band-hint">{{ bandHint }}</div>
                    <el-form label-position="top" class="tile-form">
                        <el-row :gutter="16">
                            <el-col :xs="24" :md="8">
                                <el-form-item label="红波段">
                                    <el-select v-model="form.redBand">
                                        <el-option v-for="band in bandOptions" :key="`red-${band}`" :label="`波段 ${band}`" :value="band" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="8">
                                <el-form-item label="绿波段">
                                    <el-select v-model="form.greenBand">
                                        <el-option v-for="band in bandOptions" :key="`green-${band}`" :label="`波段 ${band}`" :value="band" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="8">
                                <el-form-item label="蓝波段">
                                    <el-select v-model="form.blueBand">
                                        <el-option v-for="band in bandOptions" :key="`blue-${band}`" :label="`波段 ${band}`" :value="band" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                        </el-row>
                    </el-form>
                </el-card>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">NoData 与拉伸</div></template>
                    <el-form label-position="top" class="tile-form">
                        <el-row :gutter="16">
                            <el-col :xs="24" :md="12"><el-form-item label="NoData 值"><el-input v-model="form.nodataValue" placeholder="例如 0、255 或 -9999" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="源 NoData"><el-input v-model="form.srcNodataValue" placeholder="例如 0、255 或 -9999" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="目标 NoData"><el-input v-model="form.dstNodataValue" placeholder="例如 0、255 或 -9999" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item label="拉伸类型">
                                    <el-select v-model="form.stretchType">
                                        <el-option label="不拉伸" value="none" />
                                        <el-option label="百分位拉伸" value="percent" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="拉伸低百分位"><el-input-number v-model="form.stretchLowPercent" :step="0.1" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="拉伸高百分位"><el-input-number v-model="form.stretchHighPercent" :step="0.1" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="JPEG 质量"><el-input-number v-model="form.jpegQuality" :min="1" :max="100" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="PNG 压缩"><el-input-number v-model="form.pngCompression" :min="0" :max="9" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="透明阈值"><el-input-number v-model="form.transparencyThreshold" :min="0" :max="1" :step="0.01" controls-position="right" /></el-form-item></el-col>
                        </el-row>
                    </el-form>
                </el-card>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">构建策略</div></template>
                    <div class="tile-check-grid">
                        <el-checkbox v-model="form.generateShpIndex">生成网格文件</el-checkbox>
                        <el-checkbox v-model="form.enableIncrementalUpdate">启用增量更新</el-checkbox>
                        <el-checkbox v-model="form.skipNodataTiles">跳过透明瓦片</el-checkbox>
                    </div>
                </el-card>
            </div>
        </div>

        <PathPickerModal
            v-model="picker.visible"
            :title="picker.title"
            :source="picker.source"
            :selection-mode="picker.selectionMode"
            :multiple="picker.multiple"
            :current-value="getPickerCurrentValue()"
            :allowed-extensions="picker.allowedExtensions"
            @apply="applyPickerSelection"
        />

        <RecommendationModal
            v-model="recommendationVisible"
            type="map"
            :source-file="recommendationSourceFile"
            :recommendation-data="recommendationData"
            @apply="applyRecommendation"
        />
    </section>
</template>

<style scoped>
.tile-page {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.tile-page-toolbar {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    padding: 20px 22px;
    border: 1px solid #e5eaf3;
    border-radius: 16px;
    background: linear-gradient(180deg, #ffffff 0%, #f9fbfe 100%);
}

.tile-page-toolbar__title {
    color: #1f2d3d;
    font-size: 18px;
    font-weight: 700;
}

.tile-page-toolbar__desc {
    margin-top: 6px;
    color: #6b7280;
    font-size: 13px;
    line-height: 1.7;
}

.tile-page-toolbar__actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.tile-module {
    border-radius: 16px;
}

.tile-module__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.tile-module__title {
    color: #1f2d3d;
    font-size: 15px;
    font-weight: 600;
}

.tile-form :deep(.el-input),
.tile-form :deep(.el-select),
.tile-form :deep(.el-input-number) {
    width: 100%;
}

.path-field-inline {
    align-items: center;
}

.path-field-inline :deep(.el-input) {
    flex: 1 1 auto;
    min-width: 0;
}

.path-field-inline .path-field-actions {
    flex: 0 0 auto;
}

.tile-help {
    margin-top: 8px;
    color: #6b7280;
    font-size: 13px;
    line-height: 1.7;
}

.tile-help code {
    padding: 2px 6px;
    border-radius: 6px;
    background: #f3f6fb;
    color: #334155;
}

.tile-help a {
    margin-left: 8px;
    color: #409eff;
    text-decoration: none;
}

.band-hint {
    margin-bottom: 16px;
    padding: 10px 12px;
    border-radius: 10px;
    background: #f7faff;
    color: #526071;
    font-size: 13px;
    line-height: 1.7;
}

.tile-check-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px 18px;
}

@media (max-width: 900px) {
    .tile-page-toolbar {
        flex-direction: column;
        align-items: stretch;
    }

    .path-field-inline {
        flex-direction: column;
        align-items: stretch;
    }
}
</style>

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

function isHttpSourcePattern(value) {
    const text = String(value || '').trim().toLowerCase();
    return text.startsWith('http://') || text.startsWith('https://');
}

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
    <section class="app-view app-view-workbench">
        <div class="section-header section-header-workbench section-header-compact">
            <div class="section-header-actions">
                <button class="btn btn-primary btn-header-action" type="button" @click="submit">开始地图切片</button>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack content-stack-workbench">
                <div class="workbench-shell">
                    <section class="form-section workbench-section-wide workbench-section-lead">
                            <div class="workbench-section-head">
                                <div>
                                    <h3>输入与输出</h3>
                                </div>
                            </div>
                        <div class="form-stack">
                            <div class="form-group">
                                <label>数据源目录</label>
                                <div class="path-field">
                                    <input v-model="form.folderPaths" type="text" placeholder="多个目录用逗号分隔，可留空">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择数据源目录', source: 'datasource', selectionMode: 'folder', multiple: true, field: 'folderPaths', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('folderPaths')">清空</button>
                                    </div>
                                </div>
                                <p class="workbench-note form-inline-help">可留空。留空时会默认从数据源根目录开始匹配。</p>
                            </div>
                            <div class="form-group">
                                <label>文件匹配模式</label>
                                <div class="path-field">
                                    <input v-model="form.filePatterns" type="text" placeholder="支持具体 tif、通配符、txt 文件列表或 http/https 网络地址">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择数据源文件', source: 'datasource', selectionMode: 'file', multiple: true, field: 'filePatterns', allowedExtensions: ['.tif', '.tiff', '.txt'] })">选择文件</button>
                                        <button class="btn btn-secondary" type="button" @click="requestRecommendation">智能推荐</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('filePatterns')">清空</button>
                                    </div>
                                </div>
                                <p class="workbench-note form-inline-help">
                                    可直接传网络地址，例如 <code>https://example.com/aoi.tif</code>；多个来源用逗号分隔。系统会自动下载到数据源目录下当天日期文件夹（YYYYMMDD）后继续切片。
                                    <a :href="apiDocsUrl" target="_blank" rel="noreferrer">接口示例</a>
                                </p>
                            </div>
                            <div class="form-group">
                                <label>输出目录</label>
                                <div class="path-field">
                                    <input v-model="form.outputPath" type="text" placeholder="例如 map/project/v1">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择输出目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'outputPath', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('outputPath')">清空</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </section>

                    <div class="workbench-grid">
                        <section class="form-section workbench-section-wide">
                            <div class="workbench-section-head">
                                <div>
                                    <h3>核心参数</h3>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>最小层级</label>
                                    <input v-model="form.minZoom" type="number" min="0" max="30">
                                </div>
                                <div class="form-group">
                                    <label>最大层级</label>
                                    <input v-model="form.maxZoom" type="number" min="0" max="30">
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>瓦片尺寸</label>
                                    <input v-model="form.tileSize" type="number" min="64" step="64">
                                </div>
                                <div class="form-group">
                                    <label>进程数</label>
                                    <input v-model="form.processes" type="number" min="1" max="128">
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>线程数</label>
                                    <input v-model="form.threads" type="number" min="1" max="64">
                                </div>
                                <div class="form-group">
                                    <label>最大内存</label>
                                    <select v-model="form.maxMemory">
                                        <option v-for="option in memoryOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                                    </select>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>重采样</label>
                                    <select v-model="form.resampling">
                                        <option value="near">最近邻</option>
                                        <option value="bilinear">双线性</option>
                                        <option value="cubic">三次卷积</option>
                                        <option value="lanczos">Lanczos</option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>投影</label>
                                    <select v-model="form.projection">
                                        <option v-for="option in projectionOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                                    </select>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>数据格式</label>
                                    <select v-model="form.dataFormat">
                                        <option v-for="option in dataFormatOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>图片格式</label>
                                    <select v-model="form.imageFormat">
                                        <option value="png">PNG</option>
                                        <option value="jpeg">JPEG</option>
                                    </select>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>瓦片坐标系</label>
                                    <select v-model="form.tileScheme">
                                        <option value="tms">TMS 原点</option>
                                        <option value="google">XYZ 原点</option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>波段不匹配策略</label>
                                    <select v-model="form.bandMismatchPolicy">
                                        <option value="auto">自动处理</option>
                                        <option value="strict">严格校验</option>
                                        <option value="skip">跳过异常文件</option>
                                    </select>
                                </div>
                            </div>
                        </section>

                        <section class="form-section">
                            <div class="workbench-section-head">
                                <div>
                                    <h3>波段选择</h3>
                                </div>
                                <button class="btn btn-secondary" type="button" @click="refreshBandOptions(true)">获取波段信息</button>
                            </div>
                            <p class="band-source-hint">{{ bandHint }}</p>
                            <div class="form-stack">
                                <div class="form-group">
                                    <label>红波段</label>
                                    <select v-model="form.redBand">
                                        <option v-for="band in bandOptions" :key="`red-${band}`" :value="band">波段 {{ band }}</option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>绿波段</label>
                                    <select v-model="form.greenBand">
                                        <option v-for="band in bandOptions" :key="`green-${band}`" :value="band">波段 {{ band }}</option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>蓝波段</label>
                                    <select v-model="form.blueBand">
                                        <option v-for="band in bandOptions" :key="`blue-${band}`" :value="band">波段 {{ band }}</option>
                                    </select>
                                </div>
                            </div>
                        </section>

                        <section class="form-section">
                            <div class="workbench-section-head">
                                <div>
                                    <h3>NoData 与拉伸</h3>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>NoData 值</label>
                                    <input v-model="form.nodataValue" type="text" inputmode="decimal" placeholder="例如 0、255 或 -9999">
                                </div>
                                <div class="form-group">
                                    <label>源 NoData</label>
                                    <input v-model="form.srcNodataValue" type="text" inputmode="decimal" placeholder="例如 0、255 或 -9999">
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>目标 NoData</label>
                                    <input v-model="form.dstNodataValue" type="text" inputmode="decimal" placeholder="例如 0、255 或 -9999">
                                </div>
                                <div class="form-group">
                                    <label>拉伸类型</label>
                                    <select v-model="form.stretchType">
                                        <option value="none">不拉伸</option>
                                        <option value="percent">百分位拉伸</option>
                                    </select>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>拉伸低百分位</label>
                                    <input v-model="form.stretchLowPercent" type="number" step="0.1">
                                </div>
                                <div class="form-group">
                                    <label>拉伸高百分位</label>
                                    <input v-model="form.stretchHighPercent" type="number" step="0.1">
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>JPEG 质量</label>
                                    <input v-model="form.jpegQuality" type="number" min="1" max="100">
                                </div>
                                <div class="form-group">
                                    <label>PNG 压缩</label>
                                    <input v-model="form.pngCompression" type="number" min="0" max="9">
                                </div>
                            </div>
                            <div class="form-group">
                                <label>透明阈值</label>
                                <input v-model="form.transparencyThreshold" type="number" min="0" max="1" step="0.01">
                            </div>
                        </section>

                        <section class="form-section workbench-section-wide">
                            <div class="workbench-section-head">
                                <div>
                                    <h3>构建策略</h3>
                                </div>
                            </div>
                            <div class="checkbox-grid">
                                <label class="checkbox-label">
                                    <input v-model="form.generateShpIndex" type="checkbox">
                                    生成网格文件
                                </label>
                                <label class="checkbox-label">
                                    <input v-model="form.enableIncrementalUpdate" type="checkbox">
                                    启用增量更新
                                </label>
                                <label class="checkbox-label">
                                    <input v-model="form.skipNodataTiles" type="checkbox">
                                    跳过透明瓦片
                                </label>
                            </div>
                        </section>
                    </div>

                </div>
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
.form-inline-help {
    margin-top: 8px;
}

.form-inline-help code {
    background: rgba(103, 240, 255, 0.12);
    color: var(--tf-accent);
    border-radius: 6px;
    padding: 2px 6px;
}

.form-inline-help a {
    margin-left: 8px;
    color: var(--tf-accent);
    text-decoration: none;
}

.form-inline-help a:hover {
    color: var(--tf-accent-warm);
    text-decoration: underline;
}
</style>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';

import PathPickerModal from '../components/PathPickerModal.vue';
import RecommendationModal from '../components/RecommendationModal.vue';
import { api } from '../services/api';
import { normalizeListInput } from '../utils/formatters';
import { pushToast } from '../composables/useToast';
import { addNavigationIntentListener, consumeNavigationIntent } from '../utils/navigationIntent';

const emit = defineEmits(['navigate']);

const form = reactive({
    folderPaths: '',
    filePatterns: '*.tif',
    outputPath: '',
    minZoom: 0,
    maxZoom: 16,
    tileSize: 256,
    projection: 'EPSG:3857',
    imageFormat: 'png',
    tileScheme: 'google',
    wmsConcurrency: 4,
    transparentBackground: true,
    nodataValue: '',
    renderMode: 'auto',
    redBand: 1,
    greenBand: 2,
    blueBand: 3
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
const advancedVisible = ref(false);
const apiDocsUrl = `${window.location.origin}/api/docs`;
const bandHint = ref('支持自动读取：单个 tif 直接读取；多个 tif 按最小公共波段数。');
const bandOptions = ref(Array.from({ length: 16 }, (_, index) => index + 1));
const projectionOptions = [
    { value: 'EPSG:3857', label: 'Web 墨卡托 (EPSG:3857)' },
    { value: 'EPSG:4326', label: 'WGS84 经纬度 (EPSG:4326)' },
    { value: 'EPSG:4490', label: 'CGCS2000 (EPSG:4490)' }
];
const tileSchemeOptions = [
    { value: 'google', label: 'XYZ' },
    { value: 'tms', label: 'TMS' }
];
const renderModeOptions = [
    { value: 'auto', label: '自动渲染' },
    { value: 'gray', label: '单波段灰度' },
    { value: 'rgb', label: '指定 RGB 波段' }
];

let bandRefreshTimer = null;
let removeNavigationIntentListener = null;

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
        form.wmsConcurrency = recommendations.processes;
    }
    if (recommendations.tileFormat !== undefined) {
        const format = String(recommendations.tileFormat).toLowerCase();
        if (format === 'png' || format === 'jpeg' || format === 'jpg') {
            form.imageFormat = format === 'jpg' ? 'jpeg' : format;
        }
    }
    pushToast('已应用智能推荐参数', 'success');
}

async function submit() {
    const folderPaths = normalizeListInput(form.folderPaths);
    const filePatterns = normalizeListInput(form.filePatterns);
    if (!form.outputPath || !filePatterns.length) {
        pushToast('请填写输出目录，并提供文件模式、具体文件或网络地址', 'warning');
        return;
    }

    try {
        const payload = {
            ...form,
            folderPaths,
            filePatterns,
            minZoom: Number(form.minZoom),
            maxZoom: Number(form.maxZoom),
            tileSize: Number(form.tileSize),
            wmsConcurrency: Number(form.wmsConcurrency),
            transparentBackground: Boolean(form.transparentBackground),
            nodataValue: String(form.nodataValue || '').trim() || null,
            renderMode: form.renderMode,
            redBand: Number(form.redBand),
            greenBand: Number(form.greenBand),
            blueBand: Number(form.blueBand)
        };

        const result = await api.createIndexedTiles(payload);
        if (result?.success === false) {
            pushToast(result.message || '地图切片任务启动失败', 'warning', 5000);
        } else {
            pushToast(`地图切片任务已启动: ${result?.data?.taskId || result?.taskId || ''}`, 'success');
        }
        emit('navigate', { section: 'tasks' });
    } catch (error) {
        pushToast(`地图切片任务启动失败: ${error.message}`, 'error', 5000);
    }
}

function applyIntent(intent = {}) {
    if (!intent || intent.section !== 'map-tiles') return;
    const sourcePath = String(intent.sourcePath || '').trim();
    if (!sourcePath) return;
    form.folderPaths = '';
    form.filePatterns = sourcePath;
    const fileName = sourcePath.split('/').filter(Boolean).pop() || 'map-task';
    const stem = fileName.replace(/\.[^.]+$/, '');
    if (!String(form.outputPath || '').trim()) {
        form.outputPath = `map/${stem}`;
    }
    scheduleRefreshBandOptions();
}

watch(() => `${form.folderPaths}|${form.filePatterns}`, () => {
    scheduleRefreshBandOptions();
});

onBeforeUnmount(() => {
    if (bandRefreshTimer) {
        window.clearTimeout(bandRefreshTimer);
    }
    removeNavigationIntentListener?.();
    removeNavigationIntentListener = null;
});

onMounted(() => {
    const initialIntent = consumeNavigationIntent('map-tiles');
    if (initialIntent) {
        applyIntent(initialIntent);
    }
    removeNavigationIntentListener = addNavigationIntentListener(intent => {
        if (intent?.section === 'map-tiles') {
            applyIntent(intent);
        }
    });
});
</script>

<template>
    <section class="app-view standard-page">
        <div class="app-scroll">
            <div class="tile-page">
                <div class="tile-page-toolbar">
                    <div class="tile-page-toolbar__meta">
                        <div class="tile-page-toolbar__title">地图切片</div>
                        <div class="tile-page-toolbar__desc">使用 GeoServer WMS 渲染影像，并落盘为 XYZ/TMS 栅格瓦片。</div>
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
                                可直接传网络地址，系统会先下载到数据源缓存目录后再交给 GeoServer 渲染；多个来源用逗号分隔。
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
                            <div class="tile-help">用于地图切片任务的输出标识；影像瓦片由 GeoServer 渲染并写入该输出目录。</div>
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
                            <el-col :xs="24" :md="12">
                                <el-form-item label="投影">
                                    <el-select v-model="form.projection">
                                        <el-option v-for="option in projectionOptions" :key="option.value" :label="option.label" :value="option.value" />
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
                                <el-form-item label="瓦片行号规则">
                                    <el-select v-model="form.tileScheme">
                                        <el-option v-for="option in tileSchemeOptions" :key="option.value" :label="option.label" :value="option.value" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                        </el-row>
                    </el-form>
                </el-card>

                <el-card shadow="never" class="tile-module">
                    <template #header>
                        <div class="tile-module__head">
                            <span class="tile-module__title">高级配置</span>
                            <div class="tile-module__actions">
                                <el-button v-if="advancedVisible" @click="refreshBandOptions(true)">获取波段信息</el-button>
                                <el-button text type="primary" @click="advancedVisible = !advancedVisible">
                                    {{ advancedVisible ? '收起' : '展开配置' }}
                                </el-button>
                            </div>
                        </div>
                    </template>
                    <el-form v-show="advancedVisible" label-position="top" class="tile-form">
                        <div class="advanced-config-grid">
                            <section class="advanced-config-section">
                                <div class="advanced-config-section__title">性能</div>
                                <div class="advanced-config-section__desc">控制同时请求 GeoServer WMS 的瓦片数量，过高会增加 GeoServer 压力。</div>
                                <el-form-item label="WMS 并发数">
                                    <el-input-number v-model="form.wmsConcurrency" :min="1" :max="16" controls-position="right" />
                                </el-form-item>
                            </section>

                            <section class="advanced-config-section">
                                <div class="advanced-config-section__title">输出与透明</div>
                                <div class="advanced-config-section__desc">PNG 默认启用透明背景；如需覆盖渲染时的 NoData，可手动填写。</div>
                                <div class="switch-row">
                                    <el-form-item label="透明背景"><el-switch v-model="form.transparentBackground" /></el-form-item>
                                </div>
                                <el-form-item label="手动 NoData 值">
                                    <el-input v-model="form.nodataValue" placeholder="留空则按 GeoServer 默认渲染" />
                                </el-form-item>
                            </section>

                            <section class="advanced-config-section advanced-config-section--wide">
                                <div class="advanced-config-section__title">渲染与波段</div>
                                <div class="advanced-config-section__desc">GeoServer 默认按源文件元数据渲染；多光谱或波段顺序特殊时，切换为指定 RGB 波段。</div>
                                <el-row :gutter="16">
                                    <el-col :xs="24" :md="8">
                                        <el-form-item label="渲染模式">
                                            <el-select v-model="form.renderMode">
                                                <el-option v-for="option in renderModeOptions" :key="option.value" :label="option.label" :value="option.value" />
                                            </el-select>
                                        </el-form-item>
                                    </el-col>
                                    <el-col :xs="24" :md="8">
                                        <el-form-item label="红波段">
                                            <el-select v-model="form.redBand" :disabled="form.renderMode !== 'rgb'">
                                                <el-option v-for="band in bandOptions" :key="`red-${band}`" :label="`波段 ${band}`" :value="band" />
                                            </el-select>
                                        </el-form-item>
                                    </el-col>
                                    <el-col :xs="24" :md="8">
                                        <el-form-item label="绿波段">
                                            <el-select v-model="form.greenBand" :disabled="form.renderMode !== 'rgb'">
                                                <el-option v-for="band in bandOptions" :key="`green-${band}`" :label="`波段 ${band}`" :value="band" />
                                            </el-select>
                                        </el-form-item>
                                    </el-col>
                                    <el-col :xs="24" :md="8">
                                        <el-form-item label="蓝波段">
                                            <el-select v-model="form.blueBand" :disabled="form.renderMode !== 'rgb'">
                                                <el-option v-for="band in bandOptions" :key="`blue-${band}`" :label="`波段 ${band}`" :value="band" />
                                            </el-select>
                                        </el-form-item>
                                    </el-col>
                                </el-row>
                                <div class="band-hint">{{ bandHint }}</div>
                            </section>
                        </div>
                    </el-form>
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
    position: sticky;
    top: 0;
    z-index: 30;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    padding: 20px 22px;
    border: 1px solid var(--tf-border);
    border-radius: 16px;
    background: var(--tf-surface);
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
}

.tile-page-toolbar__title {
    color: var(--tf-text-primary);
    font-size: 18px;
    font-weight: 700;
}

.tile-page-toolbar__desc {
    margin-top: 6px;
    color: var(--tf-text-secondary);
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

.tile-module__actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    justify-content: flex-end;
}

.tile-module__title {
    color: var(--tf-text-primary);
    font-size: 15px;
    font-weight: 700;
}

.tile-form :deep(.el-form-item__label) {
    color: var(--tf-text-primary);
    font-weight: 600;
}

.tile-form :deep(.el-input),
.tile-form :deep(.el-input-number),
.tile-form :deep(.el-select) {
    width: 100%;
}

.path-field {
    display: flex;
    gap: 10px;
    align-items: stretch;
}

.path-field-inline {
    align-items: center;
}

.path-field :deep(.el-input) {
    flex: 1;
}

.path-field-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.tile-help,
.band-hint {
    margin-top: 8px;
    color: var(--tf-text-secondary);
    font-size: 12px;
    line-height: 1.6;
}

.tile-help a {
    margin-left: 6px;
}

.advanced-config-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
}

.advanced-config-section {
    padding: 16px;
    border: 1px solid var(--tf-border);
    border-radius: 14px;
    background: color-mix(in srgb, var(--tf-surface) 92%, var(--tf-primary) 8%);
}

.advanced-config-section--wide {
    grid-column: 1 / -1;
}

.advanced-config-section__title {
    color: var(--tf-text-primary);
    font-size: 14px;
    font-weight: 700;
}

.advanced-config-section__desc {
    margin: 6px 0 14px;
    color: var(--tf-text-secondary);
    font-size: 12px;
    line-height: 1.6;
}

.switch-row {
    display: flex;
    gap: 28px;
    flex-wrap: wrap;
    align-items: center;
}

@media (max-width: 900px) {
    .tile-page-toolbar {
        flex-direction: column;
    }

    .advanced-config-grid {
        grid-template-columns: 1fr;
    }
}
</style>

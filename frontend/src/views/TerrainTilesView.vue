<script setup>
import { reactive, ref } from 'vue';

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
    startZoom: 0,
    endZoom: 8,
    maxTriangles: 32768,
    bounds: '',
    compression: true,
    decompress: true,
    threads: 4,
    maxMemory: '8g',
    autoZoom: true,
    zoomStrategy: 'conservative',
    mergeTerrains: false
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
            tileType: 'terrain'
        });
        recommendationData.value = response?.data || null;
        recommendationVisible.value = true;
    } catch (error) {
        pushToast(`智能推荐失败: ${error.message}`, 'error', 5000);
    }
}

function applyRecommendation(recommendations) {
    if (recommendations.minZoom !== undefined) form.startZoom = recommendations.minZoom;
    if (recommendations.maxZoom !== undefined) form.endZoom = recommendations.maxZoom;
    if (recommendations.processes !== undefined) form.threads = recommendations.processes;
    if (recommendations.maxMemory !== undefined) form.maxMemory = recommendations.maxMemory;
    if (recommendations.compression !== undefined) form.compression = recommendations.compression;
    if (recommendations.decompress !== undefined) form.decompress = recommendations.decompress;
    if (recommendations.autoZoom !== undefined) form.autoZoom = recommendations.autoZoom;
    if (recommendations.zoomStrategy !== undefined) form.zoomStrategy = recommendations.zoomStrategy;
    pushToast('已应用智能推荐参数', 'success');
}

async function submit() {
    const filePatterns = normalizeListInput(form.filePatterns);
    if (!form.outputPath || !filePatterns.length) {
        pushToast('请填写输出目录，并提供文件模式、具体文件或网络地址', 'warning');
        return;
    }

    try {
        const bounds = form.bounds
            ? form.bounds.split(',').map(item => Number(item.trim())).filter(Number.isFinite)
            : null;

        const payload = {
            folderPaths: normalizeListInput(form.folderPaths),
            filePatterns,
            outputPath: form.outputPath,
            startZoom: Number(form.startZoom),
            endZoom: Number(form.endZoom),
            maxTriangles: Number(form.maxTriangles),
            bounds: bounds?.length === 4 ? bounds : null,
            compression: Boolean(form.compression),
            decompress: Boolean(form.decompress),
            threads: Number(form.threads),
            maxMemory: form.maxMemory,
            autoZoom: Boolean(form.autoZoom),
            zoomStrategy: form.zoomStrategy,
            mergeTerrains: Boolean(form.mergeTerrains)
        };

        const result = await api.createTerrainTiles(payload);
        pushToast(`地形切片任务已启动: ${result?.data?.taskId}`, 'success');
        emit('navigate', { section: 'tasks' });
    } catch (error) {
        pushToast(`地形切片失败: ${error.message}`, 'error', 5000);
    }
}
</script>

<template>
    <section class="app-view standard-page">
        <div class="app-scroll">
            <div class="tile-page">
                <div class="tile-page-toolbar">
                    <div class="tile-page-toolbar__meta">
                        <div class="tile-page-toolbar__title">地形切片</div>
                        <div class="tile-page-toolbar__desc">DEM 输入、层级范围、执行策略和构建选项按纵向模块拆开配置。</div>
                    </div>
                    <div class="tile-page-toolbar__actions">
                        <el-button @click="requestRecommendation">智能推荐</el-button>
                        <el-button type="primary" @click="submit">开始地形切片</el-button>
                    </div>
                </div>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">输入与输出</div></template>
                    <el-form label-position="top" class="tile-form">
                        <el-form-item label="数据源目录">
                            <div class="path-field path-field-inline">
                                <el-input v-model="form.folderPaths" placeholder="多个目录用逗号分隔，可留空" />
                                <div class="path-field-actions">
                                    <el-button @click="openPicker({ title: '选择地形数据源目录', source: 'datasource', selectionMode: 'folder', multiple: true, field: 'folderPaths', allowedExtensions: [] })">选择目录</el-button>
                                    <el-button @click="clearField('folderPaths')">清空</el-button>
                                </div>
                            </div>
                            <div class="tile-help">可留空。留空时默认从数据源根目录开始匹配。</div>
                        </el-form-item>

                        <el-form-item label="文件匹配模式">
                            <div class="path-field path-field-inline">
                                <el-input v-model="form.filePatterns" placeholder="支持具体 tif、通配符、txt 文件列表或 http/https 网络地址" />
                                <div class="path-field-actions">
                                    <el-button @click="openPicker({ title: '选择地形源文件', source: 'datasource', selectionMode: 'file', multiple: true, field: 'filePatterns', allowedExtensions: ['.tif', '.tiff', '.txt'] })">选择文件</el-button>
                                    <el-button @click="requestRecommendation">智能推荐</el-button>
                                    <el-button @click="clearField('filePatterns')">清空</el-button>
                                </div>
                            </div>
                            <div class="tile-help">
                                可直接传网络地址，例如 <code>https://example.com/dem.tif</code>；多个来源用逗号分隔。
                                <a :href="apiDocsUrl" target="_blank" rel="noreferrer">接口示例</a>
                            </div>
                        </el-form-item>

                        <el-form-item label="输出目录">
                            <div class="path-field path-field-inline">
                                <el-input v-model="form.outputPath" placeholder="例如 terrain/project/v1" />
                                <div class="path-field-actions">
                                    <el-button @click="openPicker({ title: '选择地形输出目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'outputPath', allowedExtensions: [] })">选择目录</el-button>
                                    <el-button @click="clearField('outputPath')">清空</el-button>
                                </div>
                            </div>
                        </el-form-item>
                    </el-form>
                </el-card>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">层级与范围</div></template>
                    <el-form label-position="top" class="tile-form">
                        <el-row :gutter="16">
                            <el-col :xs="24" :md="12"><el-form-item label="起始层级"><el-input-number v-model="form.startZoom" :min="0" :max="20" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="结束层级"><el-input-number v-model="form.endZoom" :min="0" :max="20" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="最大三角形数"><el-input-number v-model="form.maxTriangles" :min="1024" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="地理边界"><el-input v-model="form.bounds" placeholder="west,south,east,north" /></el-form-item></el-col>
                        </el-row>
                    </el-form>
                </el-card>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">执行策略</div></template>
                    <el-form label-position="top" class="tile-form">
                        <el-row :gutter="16">
                            <el-col :xs="24" :md="12"><el-form-item label="线程数"><el-input-number v-model="form.threads" :min="1" :max="64" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item label="最大内存">
                                    <el-select v-model="form.maxMemory">
                                        <el-option v-for="option in memoryOptions" :key="option.value" :label="option.label" :value="option.value" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item label="分级策略">
                                    <el-select v-model="form.zoomStrategy">
                                        <el-option label="稳健优先" value="conservative" />
                                        <el-option label="均衡模式" value="balanced" />
                                        <el-option label="激进压缩" value="aggressive" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                        </el-row>
                    </el-form>
                </el-card>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">构建选项</div></template>
                    <div class="tile-check-grid">
                        <el-checkbox v-model="form.compression">输出压缩</el-checkbox>
                        <el-checkbox v-model="form.decompress">构建后自动解压</el-checkbox>
                        <el-checkbox v-model="form.autoZoom">启用智能分级</el-checkbox>
                        <el-checkbox v-model="form.mergeTerrains">合并多个地形输入</el-checkbox>
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
            type="terrain"
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
    border: 1px solid var(--tf-border);
    border-radius: 16px;
    background: var(--tf-surface);
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

.tile-module__title {
    color: var(--tf-text-primary);
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
    color: var(--tf-text-secondary);
    font-size: 13px;
    line-height: 1.7;
}

.tile-help code {
    padding: 2px 6px;
    border-radius: 6px;
    background: var(--tf-surface-soft);
    color: var(--tf-text-primary);
}

.tile-help a {
    margin-left: 8px;
    color: var(--tf-accent);
    text-decoration: none;
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

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
    <section class="app-view app-view-workbench">
        <div class="section-header section-header-workbench section-header-compact">
            <div class="section-header-actions">
                <button class="btn btn-primary btn-header-action" type="button" @click="submit">开始地形切片</button>
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
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择地形数据源目录', source: 'datasource', selectionMode: 'folder', multiple: true, field: 'folderPaths', allowedExtensions: [] })">选择目录</button>
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
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择地形源文件', source: 'datasource', selectionMode: 'file', multiple: true, field: 'filePatterns', allowedExtensions: ['.tif', '.tiff', '.txt'] })">选择文件</button>
                                        <button class="btn btn-secondary" type="button" @click="requestRecommendation">智能推荐</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('filePatterns')">清空</button>
                                    </div>
                                </div>
                                <p class="workbench-note form-inline-help">
                                    可直接传网络地址，例如 <code>https://example.com/dem.tif</code>；多个来源用逗号分隔。系统会自动下载到数据源目录下当天日期文件夹（YYYYMMDD）后继续切片。
                                    <a :href="apiDocsUrl" target="_blank" rel="noreferrer">接口示例</a>
                                </p>
                            </div>
                            <div class="form-group">
                                <label>输出目录</label>
                                <div class="path-field">
                                    <input v-model="form.outputPath" type="text" placeholder="例如 terrain/project/v1">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择地形输出目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'outputPath', allowedExtensions: [] })">选择目录</button>
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
                                    <h3>层级与范围</h3>
                                </div>
                            </div>
                            <div class="form-row form-row-3">
                                <div class="form-group">
                                    <label>起始层级</label>
                                    <input v-model="form.startZoom" type="number" min="0" max="20">
                                </div>
                                <div class="form-group">
                                    <label>结束层级</label>
                                    <input v-model="form.endZoom" type="number" min="0" max="20">
                                </div>
                                <div class="form-group">
                                    <label>最大三角形数</label>
                                    <input v-model="form.maxTriangles" type="number" min="1024">
                                </div>
                            </div>
                            <div class="form-group">
                                <label>地理边界</label>
                                <input v-model="form.bounds" type="text" placeholder="west,south,east,north">
                            </div>
                        </section>

                        <section class="form-section">
                            <div class="workbench-section-head">
                                <div>
                                    <h3>执行策略</h3>
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
                            <div class="form-group">
                                <label>分级策略</label>
                                <select v-model="form.zoomStrategy">
                                    <option value="conservative">稳健优先</option>
                                    <option value="balanced">均衡模式</option>
                                    <option value="aggressive">激进压缩</option>
                                </select>
                            </div>
                        </section>

                        <section class="form-section">
                            <div class="workbench-section-head">
                                <div>
                                    <h3>构建选项</h3>
                                </div>
                            </div>
                            <div class="checkbox-grid">
                                <label class="checkbox-label">
                                    <input v-model="form.compression" type="checkbox">
                                    输出压缩
                                </label>
                                <label class="checkbox-label">
                                    <input v-model="form.decompress" type="checkbox">
                                    构建后自动解压
                                </label>
                                <label class="checkbox-label">
                                    <input v-model="form.autoZoom" type="checkbox">
                                    启用智能分级
                                </label>
                                <label class="checkbox-label">
                                    <input v-model="form.mergeTerrains" type="checkbox">
                                    合并多个地形输入
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
            type="terrain"
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

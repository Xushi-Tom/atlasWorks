<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';

import PathPickerModal from '../components/PathPickerModal.vue';
import { api } from '../services/api';
import { pushToast } from '../composables/useToast';

const props = defineProps({
    activeSubsection: { type: String, default: 'toolNodataTiles' },
    standaloneMode: { type: Boolean, default: false }
});

const emit = defineEmits(['update:activeSubsection']);

const tabs = [
    { id: 'toolNodataTiles', label: '透明瓦片治理' },
    { id: 'toolLayerJson', label: '地形元数据修复' },
    { id: 'toolTerrainDecompress', label: '地形数据解压' }
];

const tabMeta = {
    toolNodataTiles: {
        title: '透明瓦片治理',
        subtitle: '针对工作空间中的透明瓦片开展识别与清理，减少无效瓦片对发布质量和体量的影响。',
        resultTitle: '执行结果',
        resultTag: 'Transparency'
    },
    toolLayerJson: {
        title: '地形元数据修复',
        subtitle: '围绕 terrain 目录的边界、源文件与资源参数进行校正，修复 layer.json 元数据。',
        resultTitle: '修复回执',
        resultTag: 'layer.json'
    },
    toolTerrainDecompress: {
        title: '地形数据解压',
        subtitle: '对 terrain 目录执行批量解压还原，便于质量核验、问题排查与后续重构。',
        resultTitle: '执行回执',
        resultTag: 'Terrain'
    }
};

const currentTab = ref(props.activeSubsection);
watch(() => props.activeSubsection, value => {
    currentTab.value = value || tabs[0].id;
});
watch(currentTab, value => {
    if (!props.standaloneMode) {
        emit('update:activeSubsection', value);
    }
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

const forms = reactive({
    nodataFolder: '',
    nodataThreshold: 0.1,
    nodataIncludeDetails: true,
    layerJsonFolder: '',
    layerJsonBounds: '',
    layerJsonSourceFile: '',
    layerJsonThreads: 2,
    layerJsonMaxMemory: '8g',
    terrainDecompressFolder: ''
});

const resultText = reactive({
    nodata: '',
    layerJson: '',
    terrainDecompress: ''
});

const currentMeta = computed(() => tabMeta[currentTab.value] || tabMeta.toolNodataTiles);

function openPicker(config) {
    Object.assign(picker, config, { visible: true });
}

function getPickerCurrentValue() {
    return picker.field ? String(forms[picker.field] || '') : '';
}

function applyPickerSelection(paths) {
    const nextValue = picker.multiple ? paths.join(', ') : (paths[0] || '');
    if (picker.field) {
        forms[picker.field] = nextValue;
    }
}

function clearField(field) {
    forms[field] = '';
}

function setResult(key, payload) {
    resultText[key] = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
}

async function runNodata(action) {
    if (!forms.nodataFolder) {
        pushToast('请先选择工作空间目录', 'warning');
        return;
    }
    try {
        const response = action === 'scan'
            ? await api.scanNodataTiles({
                path: forms.nodataFolder,
                transparencyThreshold: Number(forms.nodataThreshold),
                includeDetails: forms.nodataIncludeDetails
            })
            : await api.deleteNodataTiles({
                path: forms.nodataFolder,
                transparencyThreshold: Number(forms.nodataThreshold),
                includeDetails: forms.nodataIncludeDetails
            });
        setResult('nodata', response?.data || response);
        pushToast(action === 'scan' ? '透明瓦片扫描完成' : '透明瓦片清理完成', 'success');
    } catch (error) {
        setResult('nodata', `执行失败: ${error.message}`);
        pushToast(`执行失败: ${error.message}`, 'error', 5000);
    }
}

async function runLayerJson() {
    if (!forms.layerJsonFolder) {
        pushToast('请先选择地形目录', 'warning');
        return;
    }
    try {
        const bounds = forms.layerJsonBounds
            ? forms.layerJsonBounds.split(',').map(item => Number(item.trim())).filter(Number.isFinite)
            : undefined;
        const response = await api.updateLayerJson({
            folderPath: forms.layerJsonFolder,
            bounds: bounds?.length === 4 ? bounds : undefined,
            sourceFile: forms.layerJsonSourceFile || undefined,
            threads: Number(forms.layerJsonThreads),
            maxMemory: forms.layerJsonMaxMemory
        });
        setResult('layerJson', response?.data || response);
        pushToast(response?.message || '地形元数据修复完成', 'success');
    } catch (error) {
        setResult('layerJson', `处理失败: ${error.message}`);
        pushToast(`处理失败: ${error.message}`, 'error', 5000);
    }
}

async function runTerrainDecompress() {
    if (!forms.terrainDecompressFolder) {
        pushToast('请先选择地形目录', 'warning');
        return;
    }
    try {
        const response = await api.decompressTerrain({ folderPath: forms.terrainDecompressFolder });
        setResult('terrainDecompress', response?.data || response);
        pushToast(response?.message || '地形数据解压完成', 'success');
    } catch (error) {
        setResult('terrainDecompress', `解压失败: ${error.message}`);
        pushToast(`解压失败: ${error.message}`, 'error', 5000);
    }
}

onMounted(() => {
    if (tabs.every(item => item.id !== currentTab.value)) {
        currentTab.value = tabs[0].id;
    }
});
</script>

<template>
    <section class="app-view standard-page">
        <div class="app-scroll">
            <div class="tool-shell">
                <section class="tool-toolbar">
                    <div class="tool-toolbar__meta">
                        <div class="tool-toolbar__title">{{ currentMeta.title }}</div>
                        <div class="tool-toolbar__desc">{{ currentMeta.subtitle }}</div>
                    </div>
                </section>

                <section v-if="currentTab === 'toolNodataTiles'" class="tool-panel">
                    <div class="tool-stack">
                        <div class="tool-form-card">
                            <div class="tool-card-title">治理参数</div>
                            <div class="tool-form">
                                <div class="tool-field">
                                    <label>工作空间目录</label>
                                    <div class="path-field path-field-inline">
                                        <input v-model="forms.nodataFolder" type="text" placeholder="选择待治理的瓦片目录">
                                        <div class="path-field-actions">
                                            <button class="btn" type="button" @click="openPicker({ title: '选择瓦片目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'nodataFolder', allowedExtensions: [] })">选择目录</button>
                                            <button class="btn" type="button" @click="clearField('nodataFolder')">清空</button>
                                        </div>
                                    </div>
                                </div>
                                <div class="tool-form-row">
                                    <div class="tool-field">
                                        <label>透明阈值</label>
                                        <input v-model="forms.nodataThreshold" type="number" step="0.01" min="0" max="1">
                                    </div>
                                    <div class="tool-field">
                                        <label>返回明细结果</label>
                                        <div class="tool-switch-row">
                                            <el-switch v-model="forms.nodataIncludeDetails" />
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="tool-action-row">
                                <el-button type="primary" @click="runNodata('scan')">执行扫描</el-button>
                                <el-button type="danger" @click="runNodata('delete')">执行清理</el-button>
                            </div>
                        </div>

                        <section class="tool-result-card">
                            <div class="tool-result-card__head">
                                <span>{{ currentMeta.resultTitle }}</span>
                                <span class="tool-chip">{{ currentMeta.resultTag }}</span>
                            </div>
                            <pre class="tool-result-card__body">{{ resultText.nodata || '扫描结果、命中明细和清理回执会在这里展示。' }}</pre>
                        </section>
                    </div>
                </section>

                <section v-else-if="currentTab === 'toolLayerJson'" class="tool-panel">
                    <div class="tool-stack">
                        <div class="tool-form-card">
                            <div class="tool-card-title">修复参数</div>
                            <div class="tool-form">
                                <div class="tool-field">
                                    <label>地形目录</label>
                                    <div class="path-field path-field-inline">
                                        <input v-model="forms.layerJsonFolder" type="text" placeholder="选择 terrain 目录">
                                        <div class="path-field-actions">
                                            <button class="btn" type="button" @click="openPicker({ title: '选择地形目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'layerJsonFolder', allowedExtensions: [] })">选择目录</button>
                                            <button class="btn" type="button" @click="clearField('layerJsonFolder')">清空</button>
                                        </div>
                                    </div>
                                </div>
                                <div class="tool-field">
                                    <label>边界范围</label>
                                    <input v-model="forms.layerJsonBounds" type="text" placeholder="west,south,east,north">
                                </div>
                                <div class="tool-field">
                                    <label>源数据文件</label>
                                    <div class="path-field path-field-inline">
                                        <input v-model="forms.layerJsonSourceFile" type="text" placeholder="选择用于校验的 tif 文件">
                                        <div class="path-field-actions">
                                            <button class="btn" type="button" @click="openPicker({ title: '选择源文件', source: 'datasource', selectionMode: 'file', multiple: false, field: 'layerJsonSourceFile', allowedExtensions: ['.tif', '.tiff'] })">选择文件</button>
                                            <button class="btn" type="button" @click="clearField('layerJsonSourceFile')">清空</button>
                                        </div>
                                    </div>
                                </div>
                                <div class="tool-form-row">
                                    <div class="tool-field">
                                        <label>线程数</label>
                                        <input v-model="forms.layerJsonThreads" type="number" min="1" max="32">
                                    </div>
                                    <div class="tool-field">
                                        <label>最大内存</label>
                                        <input v-model="forms.layerJsonMaxMemory" type="text" placeholder="例如 8g">
                                    </div>
                                </div>
                            </div>
                            <div class="tool-action-row">
                                <el-button type="primary" @click="runLayerJson">执行修复</el-button>
                            </div>
                        </div>

                        <section class="tool-result-card">
                            <div class="tool-result-card__head">
                                <span>{{ currentMeta.resultTitle }}</span>
                                <span class="tool-chip">{{ currentMeta.resultTag }}</span>
                            </div>
                            <pre class="tool-result-card__body">{{ resultText.layerJson || '修复结果、边界校正信息和执行回执会在这里展示。' }}</pre>
                        </section>
                    </div>
                </section>

                <section v-else-if="currentTab === 'toolTerrainDecompress'" class="tool-panel">
                    <div class="tool-stack">
                        <div class="tool-form-card">
                            <div class="tool-card-title">解压参数</div>
                            <div class="tool-form">
                                <div class="tool-field">
                                    <label>地形目录</label>
                                    <div class="path-field path-field-inline">
                                        <input v-model="forms.terrainDecompressFolder" type="text" placeholder="选择待解压的 terrain 目录">
                                        <div class="path-field-actions">
                                            <button class="btn" type="button" @click="openPicker({ title: '选择地形目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'terrainDecompressFolder', allowedExtensions: [] })">选择目录</button>
                                            <button class="btn" type="button" @click="clearField('terrainDecompressFolder')">清空</button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="tool-action-row">
                                <el-button type="primary" @click="runTerrainDecompress">开始解压</el-button>
                            </div>
                        </div>

                        <section class="tool-result-card">
                            <div class="tool-result-card__head">
                                <span>{{ currentMeta.resultTitle }}</span>
                                <span class="tool-chip">{{ currentMeta.resultTag }}</span>
                            </div>
                            <pre class="tool-result-card__body">{{ resultText.terrainDecompress || '解压进度、处理摘要和执行结果会在这里展示。' }}</pre>
                        </section>
                    </div>
                </section>
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
    </section>
</template>

<style scoped>
.tool-shell {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.tool-toolbar {
    padding: 20px 22px;
    border: 1px solid var(--tf-border);
    border-radius: 16px;
    background: var(--tf-surface);
}

.tool-toolbar__title {
    color: var(--tf-text-primary);
    font-size: 18px;
    font-weight: 700;
}

.tool-toolbar__desc {
    margin-top: 6px;
    color: var(--tf-text-secondary);
    font-size: 13px;
    line-height: 1.7;
}

.tool-panel {
    display: block;
}

.tool-stack {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.tool-form-card,
.tool-result-card {
    background: var(--tf-surface);
    border: 1px solid var(--tf-border);
    border-radius: 16px;
    box-shadow: 0 10px 28px rgba(15, 23, 42, 0.04);
}

.tool-form-card {
    padding: 20px 22px;
}

.tool-card-title {
    margin-bottom: 18px;
    color: var(--tf-text-primary);
    font-size: 15px;
    font-weight: 600;
}

.tool-form {
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.tool-form-row {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
}

.tool-field label {
    display: block;
    margin-bottom: 8px;
    color: var(--tf-text-primary);
    font-size: 14px;
    font-weight: 500;
}

.tool-field input,
.tool-field select {
    width: 100%;
    height: 40px;
    padding: 0 12px;
    border: 1px solid var(--tf-border-strong);
    border-radius: 10px;
    background: var(--tf-surface);
    color: var(--tf-text-primary);
    font-size: 14px;
    transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.tool-field input:focus,
.tool-field select:focus {
    outline: none;
    border-color: var(--tf-accent);
    box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.12);
}

.path-field-inline {
    align-items: center;
}

.path-field-inline input {
    flex: 1 1 auto;
    min-width: 0;
}

.path-field-inline .path-field-actions {
    flex: 0 0 auto;
}

.tool-form-card :deep(.el-button),
.tool-form-card .btn {
    min-width: 86px;
}

.tool-switch-row {
    min-height: 40px;
    display: flex;
    align-items: center;
    padding: 0 2px;
}

.tool-action-row {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 20px;
}

.tool-result-card {
    overflow: hidden;
    min-width: 0;
}

.tool-result-card__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 16px 18px;
    border-bottom: 1px solid var(--tf-border);
    background: var(--tf-surface-soft);
    color: var(--tf-text-primary);
    font-size: 15px;
    font-weight: 600;
}

.tool-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 24px;
    padding: 0 10px;
    border-radius: 999px;
    background: var(--tf-accent-soft);
    border: 1px solid rgba(96, 165, 250, 0.28);
    color: var(--tf-accent);
    font-size: 12px;
    font-weight: 600;
}

.tool-result-card__body {
    margin: 0;
    min-height: 200px;
    max-height: 420px;
    padding: 16px 18px;
    overflow: auto;
    background: var(--tf-surface);
    color: var(--tf-text-secondary);
    font-size: 13px;
    line-height: 1.7;
    white-space: pre-wrap;
    word-break: break-word;
}

@media (max-width: 900px) {
    .tool-form-row {
        grid-template-columns: 1fr;
    }

    .path-field-inline {
        flex-direction: column;
        align-items: stretch;
    }
}
</style>

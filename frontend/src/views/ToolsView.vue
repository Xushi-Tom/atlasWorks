<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';

import PathPickerModal from '../components/PathPickerModal.vue';
import { api } from '../services/api';
import { normalizeListInput } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const props = defineProps({
    activeSubsection: { type: String, required: true }
});

const emit = defineEmits(['update:activeSubsection']);

const tabs = [
    { id: 'toolNodataTiles', label: '透明瓦片治理' },
    { id: 'toolLayerJson', label: '地形元数据修复' },
    { id: 'toolTerrainDecompress', label: '地形数据解压' },
    { id: 'toolPreflight', label: '生产预检' },
    { id: 'toolTileConverter', label: '瓦片结构转换' },
    { id: 'toolSplit', label: '大文件切分' },
    { id: 'toolArtifacts', label: '成果索引' }
];

const tabMeta = {
    toolNodataTiles: {
        kicker: 'Tile Governance',
        title: '透明瓦片治理',
        subtitle: '针对工作空间中的透明瓦片开展识别与清理，快速收敛无效瓦片对发布质量和体量的影响。'
    },
    toolLayerJson: {
        kicker: 'Terrain Metadata',
        title: '地形元数据修复',
        subtitle: '围绕地形目录的边界、源文件与计算资源配置进行校正，保障 terrain 元数据可用性。'
    },
    toolTerrainDecompress: {
        kicker: 'Terrain Recovery',
        title: '地形数据解压',
        subtitle: '对 terrain 目录执行批量解压还原，便于质量核验、问题排查与后续重构。'
    },
    toolPreflight: {
        kicker: 'Production Check',
        title: '生产预检',
        subtitle: '在正式启动地图或地形生产前，先对输入、波段、层级和输出位置进行一致性核验。'
    },
    toolTileConverter: {
        kicker: 'Layout Conversion',
        title: '瓦片结构转换',
        subtitle: '在不同瓦片目录结构之间进行迁移转换，便于交付适配、历史资产接入和结构统一。'
    },
    toolSplit: {
        kicker: 'Raster Partition',
        title: '大文件切分',
        subtitle: '将超大栅格拆解为更适合处理和分发的切分单元，降低生产与交付链路的单点压力。'
    },
    toolArtifacts: {
        kicker: 'Artifact Index',
        title: '成果索引',
        subtitle: '集中查看已登记的生产成果索引，便于追踪输出目录、产物编号与交付承接关系。'
    }
};

const currentTab = ref(props.activeSubsection);
watch(() => props.activeSubsection, value => {
    currentTab.value = value;
});
watch(currentTab, value => emit('update:activeSubsection', value));

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
    terrainDecompressFolder: '',
    preflightJobType: 'map_tiles',
    preflightFolderPaths: '',
    preflightFilePatterns: '*.tif',
    preflightOutputPath: '',
    preflightMinZoom: 0,
    preflightMaxZoom: 12,
    preflightHeightBand: '',
    preflightMaxFiles: 50,
    tileConvertSourcePath: '',
    tileConvertTargetPath: '',
    tileConvertSourceFormat: 'flat',
    tileConvertTargetFormat: 'nested',
    tileConvertOverwrite: false,
    splitSourceFile: '',
    splitOutputFolderPaths: '',
    splitTileSize: 4096,
    splitOverlap: 0,
    splitMaxFileSize: 1,
    splitNamingPattern: 'tile_{x}_{y}'
});

const resultText = reactive({
    nodata: '',
    layerJson: '',
    terrainDecompress: '',
    preflight: '',
    tileConvert: '',
    split: ''
});

const artifacts = ref([]);

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
        setResult('nodata', response);
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
        setResult('layerJson', response);
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
        setResult('terrainDecompress', response);
        pushToast(response?.message || '地形数据解压完成', 'success');
    } catch (error) {
        setResult('terrainDecompress', `解压失败: ${error.message}`);
        pushToast(`解压失败: ${error.message}`, 'error', 5000);
    }
}

async function runPreflight() {
    try {
        const response = await api.runPreflightCheck({
            jobType: forms.preflightJobType,
            folderPaths: normalizeListInput(forms.preflightFolderPaths),
            filePatterns: normalizeListInput(forms.preflightFilePatterns),
            outputPath: forms.preflightOutputPath,
            minZoom: Number(forms.preflightMinZoom),
            maxZoom: Number(forms.preflightMaxZoom),
            heightBand: forms.preflightHeightBand === '' ? null : Number(forms.preflightHeightBand),
            maxFiles: Number(forms.preflightMaxFiles)
        });
        setResult('preflight', response);
        pushToast(response?.success ? '生产预检完成' : '预检完成，请关注告警项', response?.success ? 'success' : 'warning');
    } catch (error) {
        setResult('preflight', `预检失败: ${error.message}`);
        pushToast(`预检失败: ${error.message}`, 'error', 5000);
    }
}

async function runTileConvert() {
    if (!forms.tileConvertSourcePath || !forms.tileConvertTargetPath) {
        pushToast('请先选择源目录与目标目录', 'warning');
        return;
    }
    try {
        const response = await api.convertTileFormat({
            sourcePath: forms.tileConvertSourcePath,
            targetPath: forms.tileConvertTargetPath,
            sourceFormat: forms.tileConvertSourceFormat,
            targetFormat: forms.tileConvertTargetFormat,
            overwrite: forms.tileConvertOverwrite
        });
        setResult('tileConvert', response);
        pushToast(response?.message || '结构转换任务已提交', 'success');
    } catch (error) {
        setResult('tileConvert', `转换失败: ${error.message}`);
        pushToast(`转换失败: ${error.message}`, 'error', 5000);
    }
}

async function runSplit() {
    const outputPath = normalizeListInput(forms.splitOutputFolderPaths)[0] || '';
    if (!forms.splitSourceFile || !outputPath) {
        pushToast('请先选择源文件和输出目录', 'warning');
        return;
    }
    try {
        const response = await api.splitLargeFile({
            sourceFile: forms.splitSourceFile,
            outputPath,
            tileSize: Number(forms.splitTileSize),
            overlap: Number(forms.splitOverlap),
            maxFileSize: Number(forms.splitMaxFileSize),
            namingPattern: forms.splitNamingPattern
        });
        setResult('split', response);
        pushToast(response?.skipSplit ? '当前文件无需切分' : (response?.message || '切分任务已提交'), response?.skipSplit ? 'info' : 'success');
    } catch (error) {
        setResult('split', `切分失败: ${error.message}`);
        pushToast(`切分失败: ${error.message}`, 'error', 5000);
    }
}

async function loadArtifacts() {
    try {
        const artifactResponse = await api.listArtifacts();
        artifacts.value = artifactResponse?.artifacts || [];
    } catch (error) {
        pushToast(`成果索引加载失败: ${error.message}`, 'error', 4500);
    }
}

watch(currentTab, value => {
    if (value === 'toolArtifacts') {
        loadArtifacts();
    }
});

onMounted(() => {
    if (tabs.every(item => item.id !== currentTab.value)) {
        currentTab.value = tabs[0].id;
    }
    if (currentTab.value === 'toolArtifacts') {
        loadArtifacts();
    }
});
</script>

<template>
    <section class="app-view">
        <div class="section-header section-header-product">
            <div>
                <span class="section-kicker">{{ currentMeta.kicker }}</span>
                <h2>{{ currentMeta.title }}</h2>
                <p class="section-subtitle">{{ currentMeta.subtitle }}</p>
            </div>
            <div class="tool-actions">
                <button v-if="currentTab === 'toolArtifacts'" class="btn btn-secondary" type="button" @click="loadArtifacts">刷新索引</button>
            </div>
        </div>
        <div class="view-subnav">
            <div class="subnav-tabs">
                <button
                    v-for="tab in tabs"
                    :key="tab.id"
                    class="subnav-tab"
                    :class="{ active: currentTab === tab.id }"
                    type="button"
                    @click="currentTab = tab.id"
                >{{ tab.label }}</button>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack content-stack-tools">
                <section v-if="currentTab === 'toolNodataTiles'" class="form-section tool-workbench">
                    <div class="tool-workbench-grid">
                        <div class="tool-workbench-main">
                            <div class="form-group">
                                <label>工作空间目录</label>
                                <div class="path-field">
                                    <input v-model="forms.nodataFolder" type="text" placeholder="选择待治理的瓦片目录">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择瓦片目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'nodataFolder', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('nodataFolder')">清空</button>
                                    </div>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>透明阈值</label>
                                    <input v-model="forms.nodataThreshold" type="number" step="0.01" min="0" max="1">
                                </div>
                                <div class="form-group">
                                    <label class="checkbox-label">
                                        <input v-model="forms.nodataIncludeDetails" type="checkbox">
                                        返回明细结果
                                    </label>
                                </div>
                            </div>
                            <div class="tool-actions">
                                <button class="btn btn-primary" type="button" @click="runNodata('scan')">执行扫描</button>
                                <button class="btn btn-danger" type="button" @click="runNodata('delete')">执行清理</button>
                            </div>
                        </div>
                        <aside class="tool-result-panel">
                            <div class="tool-result-header">
                                <h3>执行结果</h3>
                                <span class="status-chip">Transparency</span>
                            </div>
                            <pre class="tool-result-pre">{{ resultText.nodata || '扫描结果、命中明细和清理回执会在这里展示。' }}</pre>
                        </aside>
                    </div>
                </section>

                <section v-else-if="currentTab === 'toolLayerJson'" class="form-section tool-workbench">
                    <div class="tool-workbench-grid">
                        <div class="tool-workbench-main">
                            <div class="form-group">
                                <label>地形目录</label>
                                <div class="path-field">
                                    <input v-model="forms.layerJsonFolder" type="text" placeholder="选择 terrain 目录">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择地形目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'layerJsonFolder', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('layerJsonFolder')">清空</button>
                                    </div>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>边界范围</label>
                                <input v-model="forms.layerJsonBounds" type="text" placeholder="west,south,east,north">
                            </div>
                            <div class="form-group">
                                <label>源数据文件</label>
                                <div class="path-field">
                                    <input v-model="forms.layerJsonSourceFile" type="text" placeholder="选择用于校验的 tif 文件">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择源文件', source: 'datasource', selectionMode: 'file', multiple: false, field: 'layerJsonSourceFile', allowedExtensions: ['.tif', '.tiff'] })">选择文件</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('layerJsonSourceFile')">清空</button>
                                    </div>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>线程数</label>
                                    <input v-model="forms.layerJsonThreads" type="number" min="1" max="32">
                                </div>
                                <div class="form-group">
                                    <label>最大内存</label>
                                    <input v-model="forms.layerJsonMaxMemory" type="text" placeholder="例如 8g">
                                </div>
                            </div>
                            <div class="tool-actions">
                                <button class="btn btn-primary" type="button" @click="runLayerJson">执行修复</button>
                            </div>
                        </div>
                        <aside class="tool-result-panel">
                            <div class="tool-result-header">
                                <h3>修复回执</h3>
                                <span class="status-chip">layer.json</span>
                            </div>
                            <pre class="tool-result-pre">{{ resultText.layerJson || '修复结果、边界校正信息和执行回执会在这里展示。' }}</pre>
                        </aside>
                    </div>
                </section>

                <section v-else-if="currentTab === 'toolTerrainDecompress'" class="form-section tool-workbench">
                    <div class="tool-workbench-grid tool-workbench-grid-tight">
                        <div class="tool-workbench-main">
                            <div class="form-group">
                                <label>地形目录</label>
                                <div class="path-field">
                                    <input v-model="forms.terrainDecompressFolder" type="text" placeholder="选择待解压的 terrain 目录">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择地形目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'terrainDecompressFolder', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('terrainDecompressFolder')">清空</button>
                                    </div>
                                </div>
                            </div>
                            <div class="tool-actions">
                                <button class="btn btn-primary" type="button" @click="runTerrainDecompress">开始解压</button>
                            </div>
                        </div>
                        <aside class="tool-result-panel">
                            <div class="tool-result-header">
                                <h3>执行回执</h3>
                                <span class="status-chip">Terrain</span>
                            </div>
                            <pre class="tool-result-pre">{{ resultText.terrainDecompress || '解压进度、处理摘要和执行结果会在这里展示。' }}</pre>
                        </aside>
                    </div>
                </section>

                <section v-else-if="currentTab === 'toolPreflight'" class="form-section tool-workbench">
                    <div class="tool-workbench-grid">
                        <div class="tool-workbench-main">
                            <div class="form-row">
                                <div class="form-group">
                                    <label>生产类型</label>
                                    <select v-model="forms.preflightJobType">
                                        <option value="map_tiles">地图切片</option>
                                        <option value="terrain_tiles">地形切片</option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>最大扫描文件数</label>
                                    <input v-model="forms.preflightMaxFiles" type="number" min="1" max="500">
                                </div>
                            </div>
                            <div class="form-group">
                                <label>数据源目录</label>
                                <div class="path-field">
                                    <input v-model="forms.preflightFolderPaths" type="text" placeholder="多个目录以逗号分隔">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择预检数据源目录', source: 'datasource', selectionMode: 'folder', multiple: true, field: 'preflightFolderPaths', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('preflightFolderPaths')">清空</button>
                                    </div>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>文件匹配模式</label>
                                <div class="path-field">
                                    <input v-model="forms.preflightFilePatterns" type="text" placeholder="支持具体文件、通配符或 txt 列表">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择预检文件', source: 'datasource', selectionMode: 'file', multiple: true, field: 'preflightFilePatterns', allowedExtensions: ['.tif', '.tiff', '.txt'] })">选择文件</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('preflightFilePatterns')">清空</button>
                                    </div>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>输出目录</label>
                                <div class="path-field">
                                    <input v-model="forms.preflightOutputPath" type="text" placeholder="选择目标工作空间目录">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择预检输出目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'preflightOutputPath', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('preflightOutputPath')">清空</button>
                                    </div>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>最小层级</label>
                                    <input v-model="forms.preflightMinZoom" type="number" min="0" max="30">
                                </div>
                                <div class="form-group">
                                    <label>最大层级</label>
                                    <input v-model="forms.preflightMaxZoom" type="number" min="0" max="30">
                                </div>
                            </div>
                            <div class="form-group">
                                <label>高程波段</label>
                                <input v-model="forms.preflightHeightBand" type="number" min="1" placeholder="地形预检可选">
                            </div>
                            <div class="tool-actions">
                                <button class="btn btn-primary" type="button" @click="runPreflight">执行预检</button>
                            </div>
                        </div>
                        <aside class="tool-result-panel">
                            <div class="tool-result-header">
                                <h3>预检报告</h3>
                                <span class="status-chip">Preflight</span>
                            </div>
                            <pre class="tool-result-pre">{{ resultText.preflight || '输入一致性、层级范围和输出校验结果会在这里展示。' }}</pre>
                        </aside>
                    </div>
                </section>

                <section v-else-if="currentTab === 'toolTileConverter'" class="form-section tool-workbench">
                    <div class="tool-workbench-grid">
                        <div class="tool-workbench-main">
                            <div class="form-group">
                                <label>源目录</label>
                                <div class="path-field">
                                    <input v-model="forms.tileConvertSourcePath" type="text" placeholder="选择待转换的瓦片目录">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择源目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'tileConvertSourcePath', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('tileConvertSourcePath')">清空</button>
                                    </div>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>目标目录</label>
                                <div class="path-field">
                                    <input v-model="forms.tileConvertTargetPath" type="text" placeholder="选择转换后的输出目录">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择目标目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'tileConvertTargetPath', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('tileConvertTargetPath')">清空</button>
                                    </div>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>源结构</label>
                                    <select v-model="forms.tileConvertSourceFormat">
                                        <option value="flat">flat</option>
                                        <option value="nested">nested</option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>目标结构</label>
                                    <select v-model="forms.tileConvertTargetFormat">
                                        <option value="nested">nested</option>
                                        <option value="flat">flat</option>
                                    </select>
                                </div>
                            </div>
                            <div class="form-group">
                                <label class="checkbox-label">
                                    <input v-model="forms.tileConvertOverwrite" type="checkbox">
                                    允许覆盖目标目录
                                </label>
                            </div>
                            <div class="tool-actions">
                                <button class="btn btn-primary" type="button" @click="runTileConvert">开始转换</button>
                            </div>
                        </div>
                        <aside class="tool-result-panel">
                            <div class="tool-result-header">
                                <h3>转换结果</h3>
                                <span class="status-chip">Conversion</span>
                            </div>
                            <pre class="tool-result-pre">{{ resultText.tileConvert || '结构转换任务提交结果和处理摘要会在这里展示。' }}</pre>
                        </aside>
                    </div>
                </section>

                <section v-else-if="currentTab === 'toolSplit'" class="form-section tool-workbench">
                    <div class="tool-workbench-grid">
                        <div class="tool-workbench-main">
                            <div class="form-group">
                                <label>源文件</label>
                                <div class="path-field">
                                    <input v-model="forms.splitSourceFile" type="text" placeholder="选择待切分的栅格文件">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择切分源文件', source: 'datasource', selectionMode: 'file', multiple: false, field: 'splitSourceFile', allowedExtensions: ['.tif', '.tiff'] })">选择文件</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('splitSourceFile')">清空</button>
                                    </div>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>输出目录</label>
                                <div class="path-field">
                                    <input v-model="forms.splitOutputFolderPaths" type="text" placeholder="选择切分结果写入目录">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择切分输出目录', source: 'datasource', selectionMode: 'folder', multiple: false, field: 'splitOutputFolderPaths', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('splitOutputFolderPaths')">清空</button>
                                    </div>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>分块尺寸</label>
                                    <input v-model="forms.splitTileSize" type="number" min="256" step="256">
                                </div>
                                <div class="form-group">
                                    <label>重叠像素</label>
                                    <input v-model="forms.splitOverlap" type="number" min="0">
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>最大文件阈值 (GB)</label>
                                    <input v-model="forms.splitMaxFileSize" type="number" min="0.1" step="0.1">
                                </div>
                                <div class="form-group">
                                    <label>命名模式</label>
                                    <input v-model="forms.splitNamingPattern" type="text" placeholder="tile_{x}_{y}">
                                </div>
                            </div>
                            <div class="tool-actions">
                                <button class="btn btn-primary" type="button" @click="runSplit">开始切分</button>
                            </div>
                        </div>
                        <aside class="tool-result-panel">
                            <div class="tool-result-header">
                                <h3>切分回执</h3>
                                <span class="status-chip">Split</span>
                            </div>
                            <pre class="tool-result-pre">{{ resultText.split || '切分策略、任务回执和结果摘要会在这里展示。' }}</pre>
                        </aside>
                    </div>
                </section>

                <section v-else class="form-section tool-workbench">
                    <div class="tool-workbench-head">
                        <div>
                            <h3>成果清单</h3>
                            <p class="workbench-note">统一查看已登记的输出成果，为后续发布、复查和问题追踪提供稳定索引。</p>
                        </div>
                        <div class="tool-actions">
                            <button class="btn btn-secondary" type="button" @click="loadArtifacts">刷新索引</button>
                        </div>
                    </div>
                    <div v-if="artifacts.length" class="artifact-list">
                        <div v-for="item in artifacts" :key="item.artifactId" class="task-list-row">
                            <div class="task-list-main">
                                <div class="task-list-title-row">
                                    <strong>{{ item.artifactId }}</strong>
                                    <span class="status-chip">{{ item.jobType || 'artifact' }}</span>
                                </div>
                                <div class="task-list-meta">
                                    <span>任务：{{ item.taskId || '-' }}</span>
                                    <span>类型：{{ item.type || item.jobType || '-' }}</span>
                                    <span>时间：{{ item.createdAt || item.timestamp || '-' }}</span>
                                </div>
                                <div class="task-list-message">{{ item.outputPath || item.alias || '-' }}</div>
                            </div>
                        </div>
                    </div>
                    <div v-else class="message info">当前没有可展示的成果索引</div>
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

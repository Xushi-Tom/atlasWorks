<script setup>
import { computed, reactive, watch } from 'vue';

import PathPickerModal from '../components/PathPickerModal.vue';
import { api } from '../services/api';
import { normalizeListInput } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const emit = defineEmits(['navigate']);

const form = reactive({
    dataType: 'pointcloud',
    folderPaths: '',
    filePatterns: '',
    sourcePath: '',
    outputPath: '',
    crsPreset: '',
    crsCustom: '',
    heightField: 'height',
    defaultHeight: 30,
    contentFormat: 'b3dm',
    longitude: '',
    latitude: '',
    anchorMode: 'manual',
    height: 0,
    scale: 1,
    rotationZ: 0,
    jobs: 4,
    enablePyramid: false,
    pyramidLeafSize: 8,
    pyramidMaxDepth: 4
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

const CRS_PRESETS = [
    { value: '', label: '不指定（自动识别）' },
    { value: 'EPSG:4326', label: 'EPSG:4326 (WGS84 经纬度)' },
    { value: 'EPSG:4490', label: 'EPSG:4490 (CGCS2000 经纬度)' },
    { value: 'EPSG:3857', label: 'EPSG:3857 (Web Mercator)' },
    { value: 'EPSG:4978', label: 'EPSG:4978 (ECEF)' },
    { value: 'EPSG:32650', label: 'EPSG:32650 (UTM 50N)' },
    { value: 'EPSG:32651', label: 'EPSG:32651 (UTM 51N)' },
    { value: '__custom__', label: '自定义 EPSG/PROJ 字符串' }
];

const HEIGHT_FIELD_OPTIONS = [
    'height',
    'Height',
    'HGT',
    'z',
    'elevation',
    'floors',
    'building:levels'
];

const allowedExtensions = computed(() => {
    if (form.dataType === 'pointcloud') return ['.las', '.laz'];
    if (form.dataType === 'vector') return ['.geojson', '.shp'];
    if (form.dataType === 'model') return ['.obj'];
    return ['.osgb'];
});

const effectiveCrs = computed(() => (
    form.crsPreset === '__custom__'
        ? String(form.crsCustom || '').trim()
        : String(form.crsPreset || '').trim()
));

const sourcePlaceholder = computed(() => {
    if (form.dataType === 'pointcloud') return '选择 .las / .laz 点云文件（支持多选）';
    if (form.dataType === 'vector') return '选择 .geojson / .shp 建筑面文件';
    if (form.dataType === 'model') return '选择 .obj 模型文件';
    return 'OSGB 使用下方“单文件/目录”选择';
});

watch(() => form.dataType, nextType => {
    if (nextType !== 'osgb') {
        form.sourcePath = '';
    }
    if ((nextType === 'vector' || nextType === 'osgb') && !form.crsPreset) {
        form.crsPreset = 'EPSG:4326';
    }
    if (nextType !== 'vector' && nextType !== 'osgb') {
        form.enablePyramid = false;
    }
    if (nextType !== 'osgb') {
        form.anchorMode = 'manual';
    }
});

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

function resolveOsgbSourcePath(value) {
    const raw = String(value || '').trim();
    if (!raw) return undefined;

    if (raw.startsWith('[') && raw.endsWith(']')) {
        try {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) {
                const normalized = parsed.map(item => String(item || '').trim()).filter(Boolean);
                if (!normalized.length) return undefined;
                return normalized.length === 1 ? normalized[0] : normalized;
            }
        } catch (error) {
            // fallback to comma-separated parsing
        }
    }

    const list = normalizeListInput(raw);
    if (!list.length) return undefined;
    return list.length === 1 ? list[0] : list;
}

async function submit() {
    const filePatterns = normalizeListInput(form.filePatterns);
    const sourcePath = form.dataType === 'osgb'
        ? resolveOsgbSourcePath(form.sourcePath)
        : String(form.sourcePath || '').trim();
    if (form.dataType === 'osgb') {
        if (!sourcePath) {
            pushToast('OSGB 请先选择文件/目录（支持 *.osgb 和多文件）', 'warning');
            return;
        }
    } else if (!filePatterns.length) {
        pushToast('请先选择输入文件', 'warning');
        return;
    }
    if (!form.outputPath) {
        pushToast('请填写输出目录', 'warning');
        return;
    }

    if (form.dataType === 'model' && (!form.longitude || !form.latitude)) {
        pushToast('OBJ 需要填写经度和纬度锚点', 'warning');
        return;
    }
    if (form.dataType === 'osgb' && form.anchorMode === 'manual' && (!form.longitude || !form.latitude)) {
        pushToast('OSGB 手动模式需要填写经度和纬度锚点', 'warning');
        return;
    }

    try {
        const payload = {
            dataType: form.dataType,
            folderPaths: normalizeListInput(form.folderPaths),
            filePatterns: form.dataType === 'osgb' ? [] : filePatterns,
            sourcePath: sourcePath || undefined,
            outputPath: form.outputPath,
            crs: effectiveCrs.value || undefined,
            heightField: form.heightField,
            defaultHeight: Number(form.defaultHeight),
            contentFormat: form.dataType === 'pointcloud' ? undefined : form.contentFormat,
            longitude: form.longitude === '' ? undefined : Number(form.longitude),
            latitude: form.latitude === '' ? undefined : Number(form.latitude),
            anchorMode: form.dataType === 'osgb' ? form.anchorMode : undefined,
            height: Number(form.height),
            scale: Number(form.scale),
            rotationZ: Number(form.rotationZ),
            jobs: Number(form.jobs),
            enablePyramid: (form.dataType === 'vector' || form.dataType === 'osgb') ? Boolean(form.enablePyramid) : undefined,
            pyramidLeafSize: (form.dataType === 'vector' || form.dataType === 'osgb') ? Number(form.pyramidLeafSize) : undefined,
            pyramidMaxDepth: (form.dataType === 'vector' || form.dataType === 'osgb') ? Number(form.pyramidMaxDepth) : undefined
        };

        const result = await api.create3DTiles(payload);
        pushToast(`3D Tiles 任务已启动: ${result?.data?.taskId}`, 'success');
        emit('navigate', { section: 'tasks' });
    } catch (error) {
        pushToast(`3D Tiles 任务失败: ${error.message}`, 'error', 5000);
    }
}
</script>

<template>
    <section class="app-view app-view-workbench">
        <div class="section-header section-header-workbench">
            <div>
                <span class="section-kicker">3D Tiles Pipeline</span>
                <h2>3D Tiles 工位</h2>
                <p class="section-subtitle">在现有任务与发布体系上新增三维数据生产链，当前支持点云、矢量建筑、OBJ 与 OSGB（含目录批量）。</p>
            </div>
            <div class="section-header-actions">
                <button class="btn btn-primary btn-header-action" type="button" @click="submit">开始生成</button>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack content-stack-workbench">
                <div class="workbench-shell">
                    <section class="form-section workbench-section-wide workbench-section-lead">
                        <div class="workbench-section-head">
                            <div>
                                <span class="section-kicker">Source</span>
                                <h3>输入与输出</h3>
                                <p class="workbench-note">沿用数据源与工作空间目录结构，新建 3D Tiles 任务不会影响现有地图切片和地形切片链路。</p>
                            </div>
                        </div>
                        <div class="form-stack">
                            <div class="form-row form-row-2">
                                <div class="form-group">
                                    <label>数据类型</label>
                                    <select v-model="form.dataType">
                                        <option value="pointcloud">点云 LAS/LAZ</option>
                                        <option value="vector">矢量建筑 GeoJSON/SHP</option>
                                        <option value="model">OBJ 模型</option>
                                        <option value="osgb">OSGB 倾斜摄影</option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>输入坐标系</label>
                                    <select v-model="form.crsPreset">
                                        <option
                                            v-for="option in CRS_PRESETS"
                                            :key="option.value"
                                            :value="option.value"
                                        >
                                            {{ option.label }}
                                        </option>
                                    </select>
                                </div>
                            </div>

                            <div v-if="form.crsPreset === '__custom__'" class="form-group">
                                <label>自定义坐标系</label>
                                <input
                                    v-model="form.crsCustom"
                                    type="text"
                                    placeholder="例如 EPSG:4547 或 +proj=utm +zone=50 +datum=WGS84 +units=m +no_defs"
                                >
                            </div>

                            <div class="form-group">
                                <label>数据源目录</label>
                                <div class="path-field">
                                    <input v-model="form.folderPaths" type="text" placeholder="可留空，留空时从数据源根目录搜索">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择数据源目录', source: 'datasource', selectionMode: 'folder', multiple: true, field: 'folderPaths', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('folderPaths')">清空</button>
                                    </div>
                                </div>
                            </div>

                            <div v-if="form.dataType !== 'osgb'" class="form-group">
                                <label>输入文件</label>
                                <div class="path-field">
                                    <input v-model="form.filePatterns" type="text" :placeholder="sourcePlaceholder">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择 3D Tiles 输入文件', source: 'datasource', selectionMode: 'file', multiple: false, field: 'filePatterns', allowedExtensions: allowedExtensions })">选择文件</button>
                                        <button v-if="form.dataType === 'pointcloud'" class="btn btn-secondary" type="button" @click="openPicker({ title: '选择多个点云文件', source: 'datasource', selectionMode: 'file', multiple: true, field: 'filePatterns', allowedExtensions: allowedExtensions })">选择多个文件</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('filePatterns')">清空</button>
                                    </div>
                                </div>
                            </div>

                            <div v-else class="form-group">
                                <label>OSGB 输入（支持多文件/目录/*）</label>
                                <div class="path-field">
                                    <input v-model="form.sourcePath" type="text" placeholder="支持 .osgb、目录、*.osgb，多个文件可逗号分隔或点“选择多个文件”">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择 OSGB 文件', source: 'datasource', selectionMode: 'file', multiple: false, field: 'sourcePath', allowedExtensions: ['.osgb'] })">选择文件</button>
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择多个 OSGB 文件', source: 'datasource', selectionMode: 'file', multiple: true, field: 'sourcePath', allowedExtensions: ['.osgb'] })">选择多个文件</button>
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择 OSGB 目录', source: 'datasource', selectionMode: 'folder', multiple: false, field: 'sourcePath', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('sourcePath')">清空</button>
                                    </div>
                                </div>
                            </div>

                            <div class="form-group">
                                <label>输出目录</label>
                                <div class="path-field">
                                    <input v-model="form.outputPath" type="text" placeholder="例如 3dtiles/project-a/v1">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择 3D Tiles 输出目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'outputPath', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('outputPath')">清空</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </section>

                    <div class="workbench-grid">
                        <section class="form-section">
                            <div class="workbench-section-head">
                                <div>
                                    <span class="section-kicker">Build</span>
                                    <h3>执行参数</h3>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>并行作业数</label>
                                <input v-model="form.jobs" type="number" min="1" max="64">
                            </div>
                            <div v-if="form.dataType !== 'pointcloud'" class="form-group">
                                <label>内容格式</label>
                                <select v-model="form.contentFormat">
                                    <option value="b3dm">b3dm（推荐）</option>
                                    <option value="glb">glb</option>
                                </select>
                            </div>
                            <div v-if="form.dataType === 'vector' || form.dataType === 'osgb'" class="form-group">
                                <label class="checkbox-inline">
                                    <input v-model="form.enablePyramid" type="checkbox">
                                    <span class="checkbox-text">启用金字塔层级</span>
                                </label>
                            </div>
                            <div v-if="(form.dataType === 'vector' || form.dataType === 'osgb') && form.enablePyramid" class="form-row form-row-2">
                                <div class="form-group">
                                    <label>叶子容量</label>
                                    <input v-model="form.pyramidLeafSize" type="number" min="1" max="2000">
                                </div>
                                <div class="form-group">
                                    <label>最大层级</label>
                                    <input v-model="form.pyramidMaxDepth" type="number" min="1" max="12">
                                </div>
                            </div>
                            <div v-if="form.dataType === 'vector'" class="form-row form-row-2">
                                <div class="form-group">
                                    <label>高度字段</label>
                                    <input
                                        v-model="form.heightField"
                                        list="height-field-options"
                                        type="text"
                                        placeholder="可下拉选择，也可手动输入（例如 height / floors）"
                                    >
                                    <datalist id="height-field-options">
                                        <option
                                            v-for="field in HEIGHT_FIELD_OPTIONS"
                                            :key="field"
                                            :value="field"
                                        />
                                    </datalist>
                                </div>
                                <div class="form-group">
                                    <label>缺失高度时使用（米）</label>
                                    <input
                                        v-model="form.defaultHeight"
                                        type="number"
                                        min="0"
                                        step="0.1"
                                        placeholder="例如 6"
                                    >
                                    <p class="field-hint">当要素没有该高度字段或字段为空时，使用这个高度值。</p>
                                </div>
                            </div>
                        </section>

                        <section class="form-section">
                            <div class="workbench-section-head">
                                <div>
                                    <span class="section-kicker">Anchor</span>
                                    <h3>模型锚点</h3>
                                    <p class="workbench-note">OBJ 需要手动锚点；OSGB 可选手动或自动锚点。贴地高度可手动设置。</p>
                                </div>
                            </div>
                            <div v-if="form.dataType === 'osgb'" class="form-group">
                                <label>OSGB 锚点模式</label>
                                <select v-model="form.anchorMode">
                                    <option value="manual">手动（填写经纬度）</option>
                                    <option value="auto">自动（尝试从 xodr geoReference 识别）</option>
                                </select>
                            </div>
                            <p v-if="form.dataType === 'osgb' && form.anchorMode === 'auto'" class="workbench-note">
                                自动模式会在 OSGB 目录及上级目录搜索 `.xodr`，提取 `+lon_0/+lat_0` 作为锚点。
                            </p>
                            <div v-if="form.dataType === 'model' || (form.dataType === 'osgb' && form.anchorMode === 'manual')" class="form-row form-row-2">
                                <div class="form-group">
                                    <label>经度</label>
                                    <input v-model="form.longitude" type="number" step="0.000001" placeholder="例如 121.4737">
                                </div>
                                <div class="form-group">
                                    <label>纬度</label>
                                    <input v-model="form.latitude" type="number" step="0.000001" placeholder="例如 31.2304">
                                </div>
                            </div>
                            <div class="form-row form-row-3">
                                <div class="form-group">
                                    <label>贴地高度（米）</label>
                                    <input v-model="form.height" type="number" step="0.1" placeholder="OBJ/OSGB 可自定义，默认 0">
                                </div>
                                <div class="form-group">
                                    <label>缩放</label>
                                    <input v-model="form.scale" type="number" step="0.1" min="0.1">
                                </div>
                                <div class="form-group">
                                    <label>Z 旋转</label>
                                    <input v-model="form.rotationZ" type="number" step="1">
                                </div>
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
    </section>
</template>

<style scoped>
.form-group select {
    appearance: none;
    -webkit-appearance: none;
    -moz-appearance: none;
    cursor: pointer;
    padding-right: 44px;
    background-image:
        linear-gradient(180deg, rgba(103, 240, 255, 0.03), rgba(31, 164, 255, 0.05)),
        url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 8'%3E%3Cpath fill='%239ec1d7' d='M1.4.8L6 5.4 10.6.8 12 2.2 6 8 0 2.2z'/%3E%3C/svg%3E");
    background-repeat: no-repeat, no-repeat;
    background-position: 0 0, right 14px center;
    background-size: auto, 12px 8px;
}

.form-group select:hover {
    border-color: rgba(126, 186, 231, 0.58);
}

.checkbox-inline {
    width: auto;
    display: inline-flex;
    align-items: center;
    gap: 10px;
    margin: 0;
    padding: 2px 0;
    border: 0;
    background: transparent;
    color: var(--tf-text);
    cursor: pointer;
    user-select: none;
    transition: color 0.18s ease;
    line-height: 1.35;
}

.checkbox-inline:hover {
    color: #d9ecff;
}

.checkbox-text {
    display: inline-block;
}

.checkbox-inline input[type="checkbox"] {
    appearance: none;
    -webkit-appearance: none;
    width: 18px !important;
    height: 18px !important;
    min-height: 18px !important;
    padding: 0 !important;
    flex: 0 0 18px;
    margin: 0 !important;
    display: inline-block !important;
    border-radius: 4px;
    border: 1px solid rgba(120, 149, 189, 0.64);
    background: rgba(9, 20, 34, 0.95);
    position: relative;
    cursor: pointer;
    transition: all 0.18s ease;
}

.checkbox-inline input[type="checkbox"]:checked {
    border-color: rgba(103, 240, 255, 0.8);
    background: linear-gradient(140deg, rgba(66, 196, 230, 0.95), rgba(72, 130, 220, 0.94));
}

.checkbox-inline input[type="checkbox"]:checked::after {
    content: '';
    position: absolute;
    left: 5px;
    top: 2px;
    width: 5px;
    height: 9px;
    border-right: 2px solid #05121f;
    border-bottom: 2px solid #05121f;
    transform: rotate(45deg);
}

.checkbox-inline input[type="checkbox"]:focus-visible {
    outline: none;
    box-shadow: 0 0 0 3px rgba(31, 164, 255, 0.18);
}

.field-hint {
    margin: 6px 0 0;
    font-size: 12px;
    line-height: 1.5;
    color: var(--tf-text-soft);
}
</style>

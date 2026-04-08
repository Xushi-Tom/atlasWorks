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
    crs: '',
    heightField: 'height',
    defaultHeight: 30,
    contentFormat: 'b3dm',
    longitude: '',
    latitude: '',
    height: 0,
    scale: 1,
    rotationZ: 0,
    jobs: 4
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

const allowedExtensions = computed(() => {
    if (form.dataType === 'pointcloud') return ['.las', '.laz'];
    if (form.dataType === 'vector') return ['.geojson', '.shp'];
    if (form.dataType === 'model') return ['.obj'];
    return ['.osgb'];
});

const sourcePlaceholder = computed(() => {
    if (form.dataType === 'pointcloud') return '选择 .las / .laz 点云文件';
    if (form.dataType === 'vector') return '选择 .geojson / .shp 建筑面文件';
    if (form.dataType === 'model') return '选择 .obj 模型文件';
    return 'OSGB 使用下方“单文件/目录”选择';
});

watch(() => form.dataType, nextType => {
    if (nextType !== 'osgb') {
        form.sourcePath = '';
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

async function submit() {
    const filePatterns = normalizeListInput(form.filePatterns);
    const sourcePath = String(form.sourcePath || '').trim();
    if (form.dataType === 'osgb') {
        if (!sourcePath) {
            pushToast('OSGB 请先选择单个 .osgb 文件或目录', 'warning');
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

    if ((form.dataType === 'model' || form.dataType === 'osgb') && (!form.longitude || !form.latitude)) {
        pushToast('OBJ/OSGB 需要填写经度和纬度锚点', 'warning');
        return;
    }

    try {
        const payload = {
            dataType: form.dataType,
            folderPaths: normalizeListInput(form.folderPaths),
            filePatterns: form.dataType === 'osgb' ? [] : filePatterns,
            sourcePath: sourcePath || undefined,
            outputPath: form.outputPath,
            crs: form.crs,
            heightField: form.heightField,
            defaultHeight: Number(form.defaultHeight),
            contentFormat: form.dataType === 'pointcloud' ? undefined : form.contentFormat,
            longitude: form.longitude === '' ? undefined : Number(form.longitude),
            latitude: form.latitude === '' ? undefined : Number(form.latitude),
            height: Number(form.height),
            scale: Number(form.scale),
            rotationZ: Number(form.rotationZ),
            jobs: Number(form.jobs)
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
                                    <input
                                        v-model="form.crs"
                                        type="text"
                                        :placeholder="form.dataType === 'pointcloud' ? '例如 EPSG:32650，必须填写真实源坐标系' : '例如 EPSG:4326'"
                                    >
                                </div>
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
                                        <button class="btn btn-secondary" type="button" @click="clearField('filePatterns')">清空</button>
                                    </div>
                                </div>
                            </div>

                            <div v-else class="form-group">
                                <label>OSGB 输入（单文件或目录）</label>
                                <div class="path-field">
                                    <input v-model="form.sourcePath" type="text" placeholder="支持单个 .osgb，或选择目录进行递归批量处理">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择 OSGB 文件', source: 'datasource', selectionMode: 'file', multiple: false, field: 'sourcePath', allowedExtensions: ['.osgb'] })">选择文件</button>
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
                            <div class="form-row form-row-2">
                                <div class="form-group">
                                    <label>并行作业数</label>
                                    <input v-model="form.jobs" type="number" min="1" max="64">
                                </div>
                                <div class="form-group">
                                    <label>默认高度</label>
                                    <input v-model="form.defaultHeight" type="number" min="1">
                                </div>
                            </div>
                            <div v-if="form.dataType !== 'pointcloud'" class="form-group">
                                <label>内容格式</label>
                                <select v-model="form.contentFormat">
                                    <option value="b3dm">b3dm（推荐）</option>
                                    <option value="glb">glb</option>
                                </select>
                            </div>
                            <div v-if="form.dataType === 'vector'" class="form-group">
                                <label>高度字段</label>
                                <input v-model="form.heightField" type="text" placeholder="例如 height / floors">
                            </div>
                        </section>

                        <section class="form-section">
                            <div class="workbench-section-head">
                                <div>
                                    <span class="section-kicker">Anchor</span>
                                    <h3>模型锚点</h3>
                                    <p class="workbench-note">OBJ 与 OSGB 需要锚点坐标来生成可直接发布的 `tileset.json`。</p>
                                </div>
                            </div>
                            <div class="form-row form-row-2">
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
                                    <label>高程</label>
                                    <input v-model="form.height" type="number" step="0.1">
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

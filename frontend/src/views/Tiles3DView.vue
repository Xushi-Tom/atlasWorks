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
    outputPath: '',
    crsPreset: '',
    crsCustom: '',
    heightField: 'height',
    vectorHeightMode: 'meters',
    floorHeightMeters: 3.0,
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
    'Floor',
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
    return '支持单个 .osgb、多个 .osgb、*.osgb 或 **/*.osgb';
});

const defaultHeightUnitLabel = computed(() => (
    form.vectorHeightMode === 'floors' ? '层' : '米'
));

watch(() => form.dataType, nextType => {
    if ((nextType === 'vector' || nextType === 'osgb') && !form.crsPreset) {
        form.crsPreset = 'EPSG:4326';
    }
    if (nextType !== 'vector' && nextType !== 'model' && nextType !== 'osgb') {
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

async function submit() {
    const filePatterns = normalizeListInput(form.filePatterns);
    if (!filePatterns.length) {
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
            filePatterns,
            outputPath: form.outputPath,
            crs: effectiveCrs.value || undefined,
            heightField: form.heightField,
            vectorHeightMode: form.dataType === 'vector' ? form.vectorHeightMode : undefined,
            floorHeightMeters: form.dataType === 'vector' ? Number(form.floorHeightMeters) : undefined,
            defaultHeight: Number(form.defaultHeight),
            contentFormat: form.dataType === 'pointcloud' ? undefined : form.contentFormat,
            longitude: form.longitude === '' ? undefined : Number(form.longitude),
            latitude: form.latitude === '' ? undefined : Number(form.latitude),
            anchorMode: form.dataType === 'osgb' ? form.anchorMode : undefined,
            height: Number(form.height),
            scale: Number(form.scale),
            rotationZ: Number(form.rotationZ),
            jobs: Number(form.jobs),
            enablePyramid: (form.dataType === 'vector' || form.dataType === 'model' || form.dataType === 'osgb') ? Boolean(form.enablePyramid) : undefined,
            pyramidLeafSize: (form.dataType === 'vector' || form.dataType === 'model' || form.dataType === 'osgb') ? Number(form.pyramidLeafSize) : undefined,
            pyramidMaxDepth: (form.dataType === 'vector' || form.dataType === 'model' || form.dataType === 'osgb') ? Number(form.pyramidMaxDepth) : undefined
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
    <section class="app-view standard-page">
        <div class="app-scroll">
            <div class="tile-page">
                <div class="tile-page-toolbar">
                    <div class="tile-page-toolbar__meta">
                        <div class="tile-page-toolbar__title">3D Tiles</div>
                        <div class="tile-page-toolbar__desc">点云、矢量建筑、OBJ、OSGB 统一放到纵向模块里配置输入、锚点和输出策略。</div>
                    </div>
                    <div class="tile-page-toolbar__actions">
                        <el-button type="primary" @click="submit">开始生成</el-button>
                    </div>
                </div>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">输入与输出</div></template>
                    <el-form label-position="top" class="tile-form">
                        <el-row :gutter="16">
                            <el-col :xs="24" :md="12">
                                <el-form-item label="数据类型">
                                    <el-select v-model="form.dataType">
                                        <el-option label="点云 LAS/LAZ" value="pointcloud" />
                                        <el-option label="矢量建筑 GeoJSON/SHP" value="vector" />
                                        <el-option label="OBJ 模型" value="model" />
                                        <el-option label="OSGB 倾斜摄影" value="osgb" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item label="输入坐标系">
                                    <el-select v-model="form.crsPreset">
                                        <el-option
                                            v-for="option in CRS_PRESETS"
                                            :key="option.value"
                                            :label="option.label"
                                            :value="option.value"
                                        />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                        </el-row>

                        <el-form-item v-if="form.crsPreset === '__custom__'" label="自定义坐标系">
                            <el-input
                                v-model="form.crsCustom"
                                placeholder="例如 EPSG:4547 或 +proj=utm +zone=50 +datum=WGS84 +units=m +no_defs"
                            />
                        </el-form-item>

                        <el-form-item label="数据源目录">
                            <div class="path-field path-field-inline">
                                <el-input v-model="form.folderPaths" placeholder="可留空，留空时从数据源根目录搜索" />
                                <div class="path-field-actions">
                                    <el-button @click="openPicker({ title: '选择数据源目录', source: 'datasource', selectionMode: 'folder', multiple: true, field: 'folderPaths', allowedExtensions: [] })">选择目录</el-button>
                                    <el-button @click="clearField('folderPaths')">清空</el-button>
                                </div>
                            </div>
                        </el-form-item>

                        <el-form-item label="输入文件格式">
                            <div class="path-field path-field-inline">
                                <el-input v-model="form.filePatterns" :placeholder="sourcePlaceholder" />
                                <div class="path-field-actions">
                                    <el-button @click="openPicker({ title: '选择 3D Tiles 输入文件', source: 'datasource', selectionMode: 'file', multiple: false, field: 'filePatterns', allowedExtensions: allowedExtensions })">选择文件</el-button>
                                    <el-button
                                        v-if="form.dataType === 'pointcloud' || form.dataType === 'osgb'"
                                        @click="openPicker({ title: '选择多个 3D Tiles 输入文件', source: 'datasource', selectionMode: 'file', multiple: true, field: 'filePatterns', allowedExtensions: allowedExtensions })"
                                    >
                                        选择多个文件
                                    </el-button>
                                    <el-button @click="clearField('filePatterns')">清空</el-button>
                                </div>
                            </div>
                            <div v-if="form.dataType === 'osgb'" class="tile-help">
                                批量 OSGB：上方“数据源目录”选基础文件夹，例如 `redownload_20260409/osgb_batch`；这里填 `*.osgb`。也可以直接选择单个或多个 `.osgb` 文件。
                            </div>
                        </el-form-item>

                        <el-form-item label="输出目录">
                            <div class="path-field path-field-inline">
                                <el-input v-model="form.outputPath" placeholder="例如 3dtiles/project-a/v1" />
                                <div class="path-field-actions">
                                    <el-button @click="openPicker({ title: '选择 3D Tiles 输出目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'outputPath', allowedExtensions: [] })">选择目录</el-button>
                                    <el-button @click="clearField('outputPath')">清空</el-button>
                                </div>
                            </div>
                        </el-form-item>
                    </el-form>
                </el-card>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">执行参数</div></template>
                    <el-form label-position="top" class="tile-form">
                        <el-row :gutter="16">
                            <el-col :xs="24" :md="12"><el-form-item label="并行作业数"><el-input-number v-model="form.jobs" :min="1" :max="64" controls-position="right" /></el-form-item></el-col>
                            <el-col v-if="form.dataType !== 'pointcloud'" :xs="24" :md="12">
                                <el-form-item label="内容格式">
                                    <el-select v-model="form.contentFormat">
                                        <el-option label="b3dm（推荐）" value="b3dm" />
                                        <el-option label="glb" value="glb" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col v-if="form.dataType === 'vector' || form.dataType === 'model' || form.dataType === 'osgb'" :xs="24" :md="12">
                                <el-form-item label="金字塔层级">
                                    <el-switch v-model="form.enablePyramid" />
                                </el-form-item>
                            </el-col>
                            <template v-if="(form.dataType === 'vector' || form.dataType === 'model' || form.dataType === 'osgb') && form.enablePyramid">
                                <el-col :xs="24" :md="12"><el-form-item label="叶子容量"><el-input-number v-model="form.pyramidLeafSize" :min="1" :max="2000" controls-position="right" /></el-form-item></el-col>
                                <el-col :xs="24" :md="12"><el-form-item label="最大层级"><el-input-number v-model="form.pyramidMaxDepth" :min="1" :max="12" controls-position="right" /></el-form-item></el-col>
                            </template>
                        </el-row>
                    </el-form>
                </el-card>

                <el-card v-if="form.dataType === 'vector'" shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">矢量高度参数</div></template>
                    <el-form label-position="top" class="tile-form">
                        <el-row :gutter="16">
                            <el-col :xs="24" :md="12">
                                <el-form-item label="高度字段">
                                    <el-select
                                        v-model="form.heightField"
                                        filterable
                                        allow-create
                                        default-first-option
                                    >
                                        <el-option v-for="field in HEIGHT_FIELD_OPTIONS" :key="field" :label="field" :value="field" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item label="高度单位">
                                    <el-select v-model="form.vectorHeightMode">
                                        <el-option label="米（字段值即米）" value="meters" />
                                        <el-option label="层数（字段值为楼层）" value="floors" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col v-if="form.vectorHeightMode === 'floors'" :xs="24" :md="12">
                                <el-form-item label="每层高度（米）">
                                    <el-input-number v-model="form.floorHeightMeters" :min="0.1" :step="0.1" controls-position="right" />
                                    <div class="tile-help">默认 3.0 米/层，可按项目标准调整。</div>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="12">
                                <el-form-item :label="`缺失高度时使用（${defaultHeightUnitLabel}）`">
                                    <el-input-number v-model="form.defaultHeight" :min="0" :step="0.1" controls-position="right" />
                                    <div class="tile-help">要素没有高度字段或字段为空时，使用这个默认值。</div>
                                </el-form-item>
                            </el-col>
                        </el-row>
                    </el-form>
                </el-card>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">模型锚点</div></template>
                    <el-form label-position="top" class="tile-form">
                        <el-row :gutter="16">
                            <el-col v-if="form.dataType === 'osgb'" :xs="24" :md="12">
                                <el-form-item label="OSGB 锚点模式">
                                    <el-select v-model="form.anchorMode">
                                        <el-option label="手动（填写经纬度）" value="manual" />
                                        <el-option label="自动（尝试从 xodr geoReference 识别）" value="auto" />
                                    </el-select>
                                    <div v-if="form.anchorMode === 'auto'" class="tile-help">
                                        自动模式会在 OSGB 目录及上级目录搜索 `.xodr`，提取 `+lon_0/+lat_0` 作为锚点。
                                    </div>
                                </el-form-item>
                            </el-col>
                            <template v-if="form.dataType === 'model' || (form.dataType === 'osgb' && form.anchorMode === 'manual')">
                                <el-col :xs="24" :md="12"><el-form-item label="经度"><el-input v-model="form.longitude" placeholder="例如 121.4737" /></el-form-item></el-col>
                                <el-col :xs="24" :md="12"><el-form-item label="纬度"><el-input v-model="form.latitude" placeholder="例如 31.2304" /></el-form-item></el-col>
                            </template>
                            <el-col :xs="24" :md="8"><el-form-item label="贴地高度（米）"><el-input-number v-model="form.height" :step="0.1" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="8"><el-form-item label="缩放"><el-input-number v-model="form.scale" :min="0.1" :step="0.1" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="8"><el-form-item label="Z 旋转"><el-input-number v-model="form.rotationZ" :step="1" controls-position="right" /></el-form-item></el-col>
                        </el-row>
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

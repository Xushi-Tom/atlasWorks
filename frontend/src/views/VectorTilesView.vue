<script setup>
import { reactive } from 'vue';

import PathPickerModal from '../components/PathPickerModal.vue';
import { api } from '../services/api';
import { normalizeListInput } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const emit = defineEmits(['navigate']);

const LEVEL_RULE_TEMPLATE = [
    { values: 'country', minZoom: 0, maxZoom: 2 },
    { values: 'province', minZoom: 3, maxZoom: 4 },
    { values: 'city', minZoom: 5, maxZoom: 6 },
    { values: 'district', minZoom: 7, maxZoom: 8 }
];

const form = reactive({
    folderPaths: '',
    filePatterns: '*.geojson, *.shp',
    outputPath: '',
    datasetName: '',
    tileFormat: 'mvt',
    minZoom: 0,
    maxZoom: 14,
    levelField: '',
    levelRules: LEVEL_RULE_TEMPLATE.map(rule => ({ ...rule })),
    unmatchedPolicy: 'include',
    overwrite: false
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

function applyLevelRuleTemplate() {
    form.levelRules = LEVEL_RULE_TEMPLATE.map(rule => ({ ...rule }));
}

function addLevelRule() {
    form.levelRules.push({ values: '', minZoom: Number(form.minZoom) || 0, maxZoom: Number(form.maxZoom) || 14 });
}

function removeLevelRule(index) {
    form.levelRules.splice(index, 1);
}

function parseLevelRules() {
    const levelField = String(form.levelField || '').trim();
    if (form.tileFormat !== 'geojson' || !levelField) {
        return { levelField: '', levelRules: [] };
    }

    const levelRules = form.levelRules.map((rule, index) => {
        const rawValues = String(rule.values || '').trim();
        const minZoom = Number(rule.minZoom);
        const maxZoom = Number(rule.maxZoom);
        const rowHasValue = rawValues || String(rule.minZoom ?? '').trim() || String(rule.maxZoom ?? '').trim();
        if (!rowHasValue) {
            return null;
        }

        const values = rawValues.split(/[,，;；\s]+/).map(value => value.trim()).filter(Boolean);
        if (!values.length) {
            throw new Error(`第 ${index + 1} 条层级规则缺少层级值`);
        }
        if (!Number.isInteger(minZoom) || !Number.isInteger(maxZoom) || minZoom < 0 || maxZoom > 22 || maxZoom < minZoom) {
            throw new Error(`第 ${index + 1} 条层级规则的 minZoom/maxZoom 不合法`);
        }
        return { values, minZoom, maxZoom };
    }).filter(Boolean);

    if (!levelRules.length) {
        throw new Error('填写层级字段后至少需要配置一条层级规则');
    }

    return { levelField, levelRules };
}

async function submit() {
    const filePatterns = normalizeListInput(form.filePatterns);
    if (!filePatterns.length) {
        pushToast('请提供 GeoJSON、SHP 或 GPKG 文件', 'warning');
        return;
    }
    if (Number(form.maxZoom) < Number(form.minZoom)) {
        pushToast('最大层级不能小于最小层级', 'warning');
        return;
    }

    try {
        const { levelField, levelRules } = parseLevelRules();
        const payload = {
            folderPaths: normalizeListInput(form.folderPaths),
            filePatterns,
            outputPath: form.outputPath,
            datasetName: form.datasetName,
            tileFormat: form.tileFormat,
            minZoom: Number(form.minZoom),
            maxZoom: Number(form.maxZoom),
            overwrite: Boolean(form.overwrite)
        };
        if (form.tileFormat === 'geojson' && levelField) {
            payload.levelField = levelField;
            payload.levelRules = levelRules;
            payload.unmatchedPolicy = form.unmatchedPolicy;
        }

        const result = await api.createVectorTiles(payload);
        const responsePayload = result?.data || result;

        if (responsePayload?.success === false) {
            pushToast(responsePayload.message || '二维矢量切片参数校验失败', 'warning', 5000);
        } else {
            pushToast(`二维矢量切片任务已启动: ${responsePayload?.taskId}`, 'success');
            emit('navigate', { section: 'tasks' });
        }
    } catch (error) {
        pushToast(`二维矢量切片失败: ${error.message}`, 'error', 5000);
    }
}
</script>

<template>
    <section class="app-view standard-page">
        <div class="app-scroll">
            <div class="tile-page">
                <div class="tile-page-toolbar">
                    <div class="tile-page-toolbar__meta">
                        <div class="tile-page-toolbar__title">二维矢量切片</div>
                        <div class="tile-page-toolbar__desc">GeoJSON、SHP、GPKG 输出静态二维矢量瓦片；大范围 MVT 到 z12+ 会生成大量小文件。</div>
                    </div>
                    <div class="tile-page-toolbar__actions">
                        <el-button @click="applyLevelRuleTemplate" :disabled="form.tileFormat !== 'geojson'">填入行政区模板</el-button>
                        <el-button type="primary" @click="submit">开始矢量切片</el-button>
                    </div>
                </div>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">输入与输出</div></template>
                    <el-form label-position="top" class="tile-form">
                        <el-form-item label="数据源目录">
                            <div class="path-field path-field-inline">
                                <el-input v-model="form.folderPaths" placeholder="多个目录用逗号分隔，可留空" />
                                <div class="path-field-actions">
                                    <el-button @click="openPicker({ title: '选择矢量数据目录', source: 'datasource', selectionMode: 'folder', multiple: true, field: 'folderPaths', allowedExtensions: [] })">选择目录</el-button>
                                    <el-button @click="clearField('folderPaths')">清空</el-button>
                                </div>
                            </div>
                        </el-form-item>
                        <el-form-item label="文件匹配模式">
                            <div class="path-field path-field-inline">
                                <el-input v-model="form.filePatterns" placeholder="支持 .geojson、.shp、.gpkg 或通配符" />
                                <div class="path-field-actions">
                                    <el-button @click="openPicker({ title: '选择矢量文件', source: 'datasource', selectionMode: 'file', multiple: true, field: 'filePatterns', allowedExtensions: ['.geojson', '.json', '.shp', '.gpkg'] })">选择文件</el-button>
                                    <el-button @click="clearField('filePatterns')">清空</el-button>
                                </div>
                            </div>
                        </el-form-item>
                        <el-form-item label="输出目录">
                            <div class="path-field path-field-inline">
                                <el-input v-model="form.outputPath" placeholder="例如 vector/roads/v1" />
                                <div class="path-field-actions">
                                    <el-button @click="openPicker({ title: '选择输出目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'outputPath', allowedExtensions: [] })">选择目录</el-button>
                                    <el-button @click="clearField('outputPath')">清空</el-button>
                                </div>
                            </div>
                        </el-form-item>
                        <el-form-item label="数据集名称（可选）">
                            <el-input v-model="form.datasetName" placeholder="留空则自动生成默认名称" />
                        </el-form-item>
                    </el-form>
                </el-card>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">金字塔参数</div></template>
                    <el-form label-position="top" class="tile-form">
                        <el-row :gutter="16">
                            <el-col :xs="24" :md="12">
                                <el-form-item label="输出格式">
                                    <el-select v-model="form.tileFormat">
                                        <el-option label="MVT / PBF" value="mvt" />
                                        <el-option label="GeoJSON 瓦片" value="geojson" />
                                    </el-select>
                                </el-form-item>
                            </el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="最小层级"><el-input-number v-model="form.minZoom" :min="0" :max="22" controls-position="right" /></el-form-item></el-col>
                            <el-col :xs="24" :md="12"><el-form-item label="最大层级"><el-input-number v-model="form.maxZoom" :min="0" :max="22" controls-position="right" /></el-form-item></el-col>
                        </el-row>
                        <el-alert
                            v-if="form.tileFormat === 'mvt' && Number(form.maxZoom) >= 12"
                            type="warning"
                            :closable="false"
                            show-icon
                            title="静态 MVT 高层级会产生大量 .pbf 小文件，大范围数据建议先裁剪或降低到 z10/z11；动态 MVT 请走发布管理。"
                        />
                    </el-form>
                </el-card>

                <template v-if="form.tileFormat === 'geojson'">
                    <el-card shadow="never" class="tile-module">
                        <template #header><div class="tile-module__title">GeoJSON 层级规则</div></template>
                        <el-form label-position="top" class="tile-form">
                            <el-row :gutter="16">
                                <el-col :xs="24" :md="12">
                                    <el-form-item label="层级字段（可选）">
                                        <el-input v-model="form.levelField" placeholder="例如 level、ad_level、type；留空则不过滤" />
                                        <div class="tile-help">只有填写字段名时，才按字段值和 zoom 规则筛选要素。</div>
                                    </el-form-item>
                                </el-col>
                                <el-col :xs="24" :md="12">
                                    <el-form-item label="未匹配规则的要素">
                                        <el-select v-model="form.unmatchedPolicy">
                                            <el-option label="保留" value="include" />
                                            <el-option label="丢弃" value="exclude" />
                                        </el-select>
                                    </el-form-item>
                                </el-col>
                            </el-row>
                        </el-form>

                        <div class="rule-toolbar">
                            <el-button @click="applyLevelRuleTemplate">填入行政区模板</el-button>
                            <el-button type="primary" plain @click="addLevelRule">添加规则</el-button>
                        </div>

                        <el-table :data="form.levelRules" border stripe class="rule-table">
                            <el-table-column label="层级值" min-width="220">
                                <template #default="{ row }">
                                    <el-input v-model="row.values" placeholder="country 或 A,B" />
                                </template>
                            </el-table-column>
                            <el-table-column label="最小 zoom" width="140">
                                <template #default="{ row }">
                                    <el-input-number v-model="row.minZoom" :min="0" :max="22" controls-position="right" />
                                </template>
                            </el-table-column>
                            <el-table-column label="最大 zoom" width="140">
                                <template #default="{ row }">
                                    <el-input-number v-model="row.maxZoom" :min="0" :max="22" controls-position="right" />
                                </template>
                            </el-table-column>
                            <el-table-column label="操作" width="100" fixed="right">
                                <template #default="{ $index }">
                                    <el-button type="danger" link @click="removeLevelRule($index)">删除</el-button>
                                </template>
                            </el-table-column>
                        </el-table>

                        <div class="tile-help">层级值可填多个，用逗号、分号或空格分隔。</div>
                    </el-card>
                </template>

                <el-card shadow="never" class="tile-module">
                    <template #header><div class="tile-module__title">构建选项</div></template>
                    <div class="tile-check-grid">
                        <el-checkbox v-model="form.overwrite">允许覆盖非空输出目录</el-checkbox>
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

.rule-toolbar {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-bottom: 12px;
}

.rule-table {
    margin-top: 6px;
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

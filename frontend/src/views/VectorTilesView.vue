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
    <section class="app-view app-view-workbench">
        <div class="section-header section-header-workbench section-header-compact">
            <div class="section-header-actions">
                <button class="btn btn-primary btn-header-action" type="button" @click="submit">开始矢量切片</button>
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
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择矢量数据目录', source: 'datasource', selectionMode: 'folder', multiple: true, field: 'folderPaths', allowedExtensions: [] })">选择目录</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('folderPaths')">清空</button>
                                    </div>
                                </div>
                            </div>

                            <div class="form-group">
                                <label>文件匹配模式</label>
                                <div class="path-field">
                                    <input v-model="form.filePatterns" type="text" placeholder="支持 .geojson、.shp、.gpkg 或通配符">
                                    <div class="path-field-actions">
                                        <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择矢量文件', source: 'datasource', selectionMode: 'file', multiple: true, field: 'filePatterns', allowedExtensions: ['.geojson', '.json', '.shp', '.gpkg'] })">选择文件</button>
                                        <button class="btn btn-secondary" type="button" @click="clearField('filePatterns')">清空</button>
                                    </div>
                                </div>
                            </div>

                            <div class="form-row">
                                <div class="form-group">
                                    <label>输出目录</label>
                                    <div class="path-field">
                                        <input v-model="form.outputPath" type="text" placeholder="例如 vector/roads/v1">
                                        <div class="path-field-actions">
                                            <button class="btn btn-secondary" type="button" @click="openPicker({ title: '选择输出目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'outputPath', allowedExtensions: [] })">选择目录</button>
                                            <button class="btn btn-secondary" type="button" @click="clearField('outputPath')">清空</button>
                                        </div>
                                    </div>
                                </div>
                                <div class="form-group">
                                    <label>数据集名称（可选）</label>
                                    <input v-model="form.datasetName" type="text" placeholder="留空则自动生成默认名称">
                                </div>
                            </div>
                        </div>
                    </section>

                    <div class="workbench-grid">
                        <section class="form-section workbench-section-wide">
                            <div class="workbench-section-head">
                                <div>
                                    <h3>金字塔参数</h3>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>输出格式</label>
                                    <select v-model="form.tileFormat">
                                        <option value="mvt">MVT / PBF</option>
                                        <option value="geojson">GeoJSON 瓦片</option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label>最小层级</label>
                                    <input v-model="form.minZoom" type="number" min="0" max="22">
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>最大层级</label>
                                    <input v-model="form.maxZoom" type="number" min="0" max="22">
                                </div>
                            </div>
                            <div v-if="form.tileFormat === 'geojson'" class="form-stack">
                                <div class="form-group">
                                    <label>层级字段（可选）</label>
                                    <input v-model="form.levelField" type="text" placeholder="例如 level、ad_level、type；留空则不过滤">
                                    <p class="form-hint">只有填写字段名时，才按字段值和 zoom 规则筛选要素。</p>
                                </div>
                                <div class="form-row">
                                    <div class="form-group">
                                        <label>未匹配规则的要素</label>
                                        <select v-model="form.unmatchedPolicy">
                                            <option value="include">保留</option>
                                            <option value="exclude">丢弃</option>
                                        </select>
                                    </div>
                                    <div class="form-group level-rule-actions">
                                        <label>规则模板</label>
                                        <div class="level-rule-action-row">
                                            <button class="btn btn-secondary" type="button" @click="applyLevelRuleTemplate">填入行政区模板</button>
                                            <button class="btn btn-secondary" type="button" @click="addLevelRule">添加规则</button>
                                        </div>
                                    </div>
                                </div>
                                <div class="form-group">
                                    <label>层级规则</label>
                                    <div class="level-rule-table">
                                        <div class="level-rule-head">
                                            <span>层级值</span>
                                            <span>最小 zoom</span>
                                            <span>最大 zoom</span>
                                            <span>操作</span>
                                        </div>
                                        <div
                                            v-for="(rule, index) in form.levelRules"
                                            :key="index"
                                            class="level-rule-row"
                                        >
                                            <input v-model="rule.values" type="text" placeholder="country 或 A,B">
                                            <input v-model="rule.minZoom" type="number" min="0" max="22">
                                            <input v-model="rule.maxZoom" type="number" min="0" max="22">
                                            <button class="btn btn-ghost-danger level-rule-remove" type="button" @click="removeLevelRule(index)">删除</button>
                                        </div>
                                    </div>
                                    <p class="form-hint">层级值可填多个，用逗号、分号或空格分隔。</p>
                                </div>
                            </div>
                            <div class="checkbox-grid">
                                <label class="checkbox-label">
                                    <input v-model="form.overwrite" type="checkbox">
                                    允许覆盖非空输出目录
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
    </section>
</template>

<style scoped>
.level-rule-action-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
}

.level-rule-table {
    display: grid;
    gap: 8px;
}

.level-rule-head,
.level-rule-row {
    display: grid;
    grid-template-columns: minmax(160px, 1fr) minmax(96px, 120px) minmax(96px, 120px) 76px;
    gap: 10px;
    align-items: center;
}

.level-rule-head {
    color: var(--tf-text-soft);
    font-size: 12px;
    font-weight: 700;
}

.level-rule-remove {
    min-width: 0;
    width: 76px;
}

@media (max-width: 720px) {
    .level-rule-head {
        display: none;
    }

    .level-rule-row {
        grid-template-columns: 1fr 1fr;
    }

    .level-rule-row input:first-child,
    .level-rule-remove {
        grid-column: 1 / -1;
        width: 100%;
    }
}
</style>

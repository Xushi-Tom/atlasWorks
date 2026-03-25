<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';

import PathPickerModal from '../components/PathPickerModal.vue';
import { api } from '../services/api';
import { formatDateTime } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const picker = reactive({
    visible: false,
    title: '',
    source: 'workspace',
    selectionMode: 'folder',
    multiple: false,
    field: 'workspacePath',
    allowedExtensions: []
});

const form = reactive({
    sourceMode: 'task',
    taskId: '',
    workspacePath: '',
    alias: '',
    publicationId: '',
    publishType: 'imagery',
    publishMethod: 'wmts',
    enabled: true,
    visibility: 'private',
    note: ''
});

const createVisible = ref(false);
const keyword = ref('');
const publications = ref([]);
const tasks = ref([]);
const editingPublicationId = ref('');

const publishMethodCatalog = {
    imagery: [
        { value: 'wmts', label: 'WMTS 服务' },
        { value: 'tms', label: 'TMS 服务' },
        { value: 'xyz', label: 'XYZ 服务' }
    ],
    'electronic-map': [
        { value: 'wmts', label: 'WMTS 服务' },
        { value: 'tms', label: 'TMS 服务' },
        { value: 'xyz', label: 'XYZ 服务' }
    ],
    terrain: [
        { value: 'cesium-terrain', label: 'Cesium Terrain' },
        { value: 'quantized-mesh', label: 'Quantized Mesh' }
    ],
    '3dtiles': [
        { value: '3d-tiles', label: '3D Tiles 服务' }
    ],
    geo: [
        { value: 'wms', label: 'WMS 服务' },
        { value: 'wfs', label: 'WFS 服务' },
        { value: 'static-download', label: '静态下载' }
    ]
};

const publishTypeLabelMap = {
    imagery: '地图 / 遥感',
    'electronic-map': '地图 / 电子地图',
    terrain: '地形',
    '3dtiles': '3DTiles',
    geo: 'Geo 数据'
};

const visibilityLabelMap = {
    private: '私有',
    internal: '内部',
    public: '公开'
};

const publicationStatusLabelMap = {
    enabled: '已启用',
    disabled: '未启用',
    published: '已启用',
    draft: '草稿',
    failed: '失败'
};

const publicationStatusTagMap = {
    enabled: 'success',
    disabled: 'info',
    published: 'success',
    draft: 'warning',
    failed: 'danger'
};
const TILES_BASE_PATH = '/app/tiles';

const publishMethodOptions = computed(() => publishMethodCatalog[form.publishType] || []);

const publishableTasks = computed(() => {
    return [...tasks.value]
        .filter(task => task?.status === 'completed' && (task?.result?.mergedOutputPath || task?.result?.outputPath || task?.result?.artifactId))
        .sort((a, b) => String(b.startTime || '').localeCompare(String(a.startTime || '')));
});

const selectedTask = computed(() => publishableTasks.value.find(task => task.taskId === form.taskId) || null);
const modalTitle = computed(() => editingPublicationId.value ? '编辑发布' : '创建发布');

const filteredPublications = computed(() => {
    const needle = String(keyword.value || '').trim().toLowerCase();
    return [...publications.value]
        .filter(item => {
            if (!needle) return true;
            return [
                item.publicationId,
                item.alias,
                item.publishPath,
                item.metadata?.workspacePath,
                item.metadata?.taskId,
                item.metadata?.publishMethod,
                getPublishTypeLabel(item.publishType),
                getPublicationStatusLabel(item.status)
            ].some(value => String(value || '').toLowerCase().includes(needle));
        })
        .sort((a, b) => String(b.publishedAt || b.createdAt || '').localeCompare(String(a.publishedAt || a.createdAt || '')));
});

function isPublicationEnabled(item) {
    return Boolean(item?.metadata?.enabled ?? (item?.status === 'enabled' || item?.status === 'published'));
}

function normalizeWorkspacePath(pathValue) {
    let path = String(pathValue || '').trim().replace(/\\/g, '/');
    if (!path) return '';

    const lowerPath = path.toLowerCase();
    const lowerBase = TILES_BASE_PATH.toLowerCase();
    if (lowerPath === lowerBase) return '';
    if (lowerPath.startsWith(`${lowerBase}/`)) {
        path = path.slice(TILES_BASE_PATH.length + 1);
    }
    return path.replace(/^\/+|\/+$/g, '');
}

function getTaskResultPath(task) {
    const rawPath = task?.result?.mergedOutputPath || task?.result?.outputPath || '';
    const normalizedPath = normalizeWorkspacePath(rawPath);
    return normalizedPath || '-';
}

function getPublishTypeLabel(value) {
    return publishTypeLabelMap[value] || value || '-';
}

function getVisibilityLabel(value) {
    return visibilityLabelMap[value] || value || '-';
}

function getPublicationStatusLabel(value) {
    return publicationStatusLabelMap[value] || value || '-';
}

function getPublicationStatusTag(value) {
    return publicationStatusTagMap[value] || 'info';
}

function getPublishMethodLabel(publishType, publishMethod) {
    const option = (publishMethodCatalog[publishType] || []).find(item => item.value === publishMethod);
    return option?.label || publishMethod || '-';
}

function resetForm() {
    form.sourceMode = 'task';
    form.taskId = '';
    form.workspacePath = '';
    form.alias = '';
    form.publicationId = '';
    form.publishType = 'imagery';
    form.publishMethod = 'wmts';
    form.enabled = true;
    form.visibility = 'private';
    form.note = '';
}

function openCreateModal() {
    editingPublicationId.value = '';
    resetForm();
    createVisible.value = true;
}

function openPicker(config) {
    Object.assign(picker, config, { visible: true });
}

function getPickerCurrentValue() {
    return picker.field ? String(form[picker.field] || '') : '';
}

function applyPickerSelection(paths) {
    const nextValue = paths[0] || '';
    if (picker.field) {
        form[picker.field] = nextValue;
    }
}

function editPublication(item) {
    editingPublicationId.value = item.publicationId;
    form.sourceMode = item.metadata?.taskId ? 'task' : 'manual';
    form.taskId = item.metadata?.taskId || '';
    form.workspacePath = normalizeWorkspacePath(item.metadata?.workspacePath || item.publishPath || '');
    form.alias = item.alias || '';
    form.publicationId = item.publicationId || '';
    form.publishType = item.publishType || 'imagery';
    form.publishMethod = item.metadata?.publishMethod || 'wmts';
    form.enabled = isPublicationEnabled(item);
    form.visibility = item.metadata?.visibility || 'private';
    form.note = item.metadata?.note || '';
    createVisible.value = true;
}

async function togglePublicationStatus(item, explicitEnabled = null) {
    const nextEnabled = explicitEnabled === null ? !isPublicationEnabled(item) : Boolean(explicitEnabled);
    const normalizedWorkspacePath = normalizeWorkspacePath(item.metadata?.workspacePath || item.publishPath);
    try {
        await api.updatePublication(item.publicationId, {
            publicationId: item.publicationId,
            taskId: item.metadata?.taskId || undefined,
            workspacePath: item.metadata?.taskId ? undefined : normalizedWorkspacePath,
            publishPath: normalizedWorkspacePath,
            alias: item.alias,
            publishType: item.publishType,
            publishMethod: item.metadata?.publishMethod,
            enabled: nextEnabled,
            visibility: item.metadata?.visibility,
            note: item.metadata?.note,
            metadata: {
                sourceMode: item.metadata?.taskId ? 'task' : 'manual',
                publishMethod: item.metadata?.publishMethod
            }
        });
        pushToast(nextEnabled ? '发布已启用' : '发布已停用', 'success');
        await loadPublications();
    } catch (error) {
        pushToast(`切换发布状态失败: ${error.message}`, 'error', 5000);
    }
}

async function removePublication(item) {
    const confirmed = window.confirm(`确认删除发布记录「${item.alias || item.publicationId}」吗？`);
    if (!confirmed) return;

    try {
        await api.deletePublication(item.publicationId);
        pushToast('发布记录已删除', 'success');
        await loadPublications();
    } catch (error) {
        pushToast(`删除发布记录失败: ${error.message}`, 'error', 5000);
    }
}

watch(() => form.publishType, value => {
    const options = publishMethodCatalog[value] || [];
    if (!options.some(item => item.value === form.publishMethod)) {
        form.publishMethod = options[0]?.value || '';
    }
}, { immediate: true });

watch(() => form.sourceMode, value => {
    if (value === 'task') {
        form.workspacePath = '';
    } else {
        form.taskId = '';
    }
});

watch(() => form.taskId, value => {
    const task = publishableTasks.value.find(item => item.taskId === value);
    if (!task || form.alias) return;
    const path = getTaskResultPath(task);
    const pathParts = String(path || '').split('/').filter(Boolean);
    form.alias = pathParts[pathParts.length - 1] || task.taskId;
});

async function loadPublications() {
    try {
        const response = await api.listPublications();
        publications.value = response?.publications || [];
    } catch (error) {
        pushToast(`发布记录加载失败: ${error.message}`, 'error', 4500);
    }
}

async function loadTasks() {
    try {
        const response = await api.getAllTasks();
        tasks.value = Object.values(response?.tasks || {});
    } catch (error) {
        pushToast(`可发布任务加载失败: ${error.message}`, 'error', 4500);
    }
}

async function submitPublication() {
    if (form.sourceMode === 'task' && !form.taskId) {
        pushToast('请先选择任务结果', 'warning');
        return;
    }
    if (form.sourceMode === 'manual' && !form.workspacePath) {
        pushToast('请先选择工作空间目录', 'warning');
        return;
    }

    const normalizedWorkspacePath = normalizeWorkspacePath(form.workspacePath);
    const payload = {
        taskId: form.sourceMode === 'task' ? form.taskId : undefined,
        workspacePath: form.sourceMode === 'manual' ? normalizedWorkspacePath : undefined,
        publishPath: form.sourceMode === 'manual' ? normalizedWorkspacePath : undefined,
        alias: form.alias || undefined,
        publicationId: form.publicationId || undefined,
        publishType: form.publishType,
        publishMethod: form.publishMethod || undefined,
        enabled: form.enabled,
        visibility: form.visibility,
        note: form.note || undefined,
        metadata: {
            publishMethod: form.publishMethod || undefined,
            sourceMode: form.sourceMode
        }
    };

    try {
        if (editingPublicationId.value) {
            await api.updatePublication(editingPublicationId.value, payload);
            pushToast('发布记录已更新', 'success');
        } else {
            await api.createPublication(payload);
            pushToast('发布记录已创建', 'success');
        }

        createVisible.value = false;
        editingPublicationId.value = '';
        await Promise.all([loadPublications(), loadTasks()]);
    } catch (error) {
        pushToast(`${editingPublicationId.value ? '更新' : '创建'}发布记录失败: ${error.message}`, 'error', 5000);
    }
}

onMounted(async () => {
    await Promise.all([loadPublications(), loadTasks()]);
});
</script>

<template>
    <section class="app-view">
        <div class="section-header section-header-product">
            <div>
                <h2>发布中心</h2>
                <p class="section-subtitle">统一管理发布记录，支持按任务生成发布、手动目录发布、启停切换与生命周期维护。</p>
            </div>
            <div class="tool-actions">
                <el-button @click="loadPublications">刷新</el-button>
                <el-button type="primary" @click="openCreateModal">创建发布</el-button>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack">
                <div class="card publish-list-shell">
                    <div class="card-header task-filter-panel task-filter-panel-simple">
                        <el-input v-model="keyword" clearable placeholder="发布 ID / 别名 / 路径 / 任务 / 发布方式" />
                    </div>

                    <div class="card-body publish-table">
                        <el-table class="publish-data-table" :data="filteredPublications" stripe border height="100%">
                            <el-table-column prop="publicationId" label="发布 ID" min-width="220" />
                            <el-table-column prop="alias" label="发布名称" min-width="160">
                                <template #default="{ row }">
                                    {{ row.alias || '-' }}
                                </template>
                            </el-table-column>
                            <el-table-column label="发布类型" min-width="210">
                                <template #default="{ row }">
                                    {{ getPublishTypeLabel(row.publishType) }} / {{ getPublishMethodLabel(row.publishType, row.metadata?.publishMethod) }}
                                </template>
                            </el-table-column>
                            <el-table-column label="发布地址" min-width="300">
                                <template #default="{ row }">
                                    <a v-if="row.accessUrl" :href="row.accessUrl" target="_blank" rel="noreferrer">{{ row.accessUrl }}</a>
                                    <span v-else>-</span>
                                </template>
                            </el-table-column>
                            <el-table-column label="可见性" width="100">
                                <template #default="{ row }">
                                    {{ getVisibilityLabel(row.metadata?.visibility) }}
                                </template>
                            </el-table-column>
                            <el-table-column label="状态" width="100">
                                <template #default="{ row }">
                                    <el-tag :type="getPublicationStatusTag(row.status)">{{ getPublicationStatusLabel(row.status) }}</el-tag>
                                </template>
                            </el-table-column>
                            <el-table-column label="发布时间" min-width="170">
                                <template #default="{ row }">
                                    {{ formatDateTime(row.publishedAt || row.createdAt) }}
                                </template>
                            </el-table-column>
                            <el-table-column label="操作" width="260" fixed="right">
                                <template #default="{ row }">
                                    <div class="publish-table-actions">
                                        <el-switch
                                            :model-value="isPublicationEnabled(row)"
                                            active-text="启"
                                            inactive-text="停"
                                            inline-prompt
                                            @change="value => togglePublicationStatus(row, value)"
                                        />
                                        <el-button size="small" @click="editPublication(row)">编辑</el-button>
                                        <el-button size="small" type="danger" @click="removePublication(row)">删除</el-button>
                                    </div>
                                </template>
                            </el-table-column>
                        </el-table>
                    </div>
                </div>
            </div>
        </div>

        <el-dialog v-model="createVisible" class="publish-editor-dialog" :title="modalTitle" width="860px" destroy-on-close>
            <el-form class="publish-editor-form" label-width="110px">
                <el-form-item label="发布来源">
                    <el-radio-group v-model="form.sourceMode" class="publish-source-mode">
                        <el-radio-button label="task">按任务发布</el-radio-button>
                        <el-radio-button label="manual">手动目录</el-radio-button>
                    </el-radio-group>
                </el-form-item>

                <el-form-item v-if="form.sourceMode === 'task'" label="任务结果">
                    <el-select v-model="form.taskId" filterable placeholder="请选择已完成任务">
                        <el-option v-for="task in publishableTasks" :key="task.taskId" :label="`${task.taskId} / ${getTaskResultPath(task)}`" :value="task.taskId" />
                    </el-select>
                    <div v-if="selectedTask" class="publish-source-preview">
                        <span>结果目录：{{ getTaskResultPath(selectedTask) }}</span>
                        <span>产物 ID：{{ selectedTask.result?.artifactId || '-' }}</span>
                        <span>开始时间：{{ formatDateTime(selectedTask.startTime) }}</span>
                    </div>
                </el-form-item>

                <el-form-item v-else label="工作空间目录">
                    <div class="path-field">
                        <el-input v-model="form.workspacePath" placeholder="选择需要发布的工作空间目录" />
                        <el-button @click="openPicker({ title: '选择工作空间目录', source: 'workspace', selectionMode: 'folder', multiple: false, field: 'workspacePath', allowedExtensions: [] })">选择目录</el-button>
                    </div>
                </el-form-item>

                <el-form-item label="发布别名">
                    <el-input v-model="form.alias" placeholder="例如 imagery-release-v1" />
                </el-form-item>

                <el-form-item label="发布 ID">
                    <el-input v-model="form.publicationId" placeholder="为空则自动生成" />
                </el-form-item>

                <el-form-item label="发布类型">
                    <el-select v-model="form.publishType">
                        <el-option label="地图 / 遥感" value="imagery" />
                        <el-option label="地图 / 电子地图" value="electronic-map" />
                        <el-option label="地形" value="terrain" />
                        <el-option label="3DTiles" value="3dtiles" />
                        <el-option label="Geo 数据" value="geo" />
                    </el-select>
                </el-form-item>

                <el-form-item label="发布方式">
                    <el-select v-model="form.publishMethod">
                        <el-option v-for="option in publishMethodOptions" :key="option.value" :label="option.label" :value="option.value" />
                    </el-select>
                </el-form-item>

                <el-form-item label="可见性">
                    <el-select v-model="form.visibility">
                        <el-option label="私有" value="private" />
                        <el-option label="内部" value="internal" />
                        <el-option label="公开" value="public" />
                    </el-select>
                </el-form-item>

                <el-form-item label="启用状态">
                    <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
                </el-form-item>

                <el-form-item label="发布说明">
                    <el-input v-model="form.note" type="textarea" :rows="4" placeholder="记录来源、用途和版本说明" />
                </el-form-item>
            </el-form>

            <template #footer>
                <el-button @click="createVisible = false">取消</el-button>
                <el-button type="primary" @click="submitPublication">{{ editingPublicationId ? '保存修改' : '创建发布' }}</el-button>
            </template>
        </el-dialog>

        <PathPickerModal
            v-model="picker.visible"
            :title="picker.title"
            :source="picker.source"
            :selection-mode="picker.selectionMode"
            :multiple="picker.multiple"
            :current-value="getPickerCurrentValue()"
            :allowed-extensions="picker.allowedExtensions"
            overlay-class="picker-modal-overlay-top"
            @apply="applyPickerSelection"
        />
    </section>
</template>

<style scoped>
.publish-table {
    min-height: 520px;
}

.publish-table-actions {
    display: flex;
    align-items: center;
    gap: 8px;
}

.publish-table-actions :deep(.el-button) {
    min-width: 58px;
    padding-inline: 12px;
}

.path-field {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
}

.publish-source-preview {
    margin-top: 10px;
    padding: 10px 12px;
    border-radius: 10px;
    border: 1px solid var(--tf-border);
    background: rgba(6, 17, 31, 0.66);
    display: flex;
    flex-direction: column;
    gap: 4px;
    color: var(--tf-text-soft);
}

.publish-table a {
    color: var(--tf-accent);
    text-decoration: none;
}

.publish-table a:hover {
    color: var(--tf-accent-warm);
    text-decoration: underline;
}

.task-filter-panel :deep(.el-input__wrapper),
.publish-editor-form :deep(.el-input__wrapper),
.publish-editor-form :deep(.el-textarea__inner),
.publish-editor-form :deep(.el-select__wrapper) {
    background: rgba(3, 12, 24, 0.72);
    box-shadow: 0 0 0 1px rgba(74, 195, 255, 0.22) inset;
}

.task-filter-panel :deep(.el-input__inner),
.publish-editor-form :deep(.el-input__inner),
.publish-editor-form :deep(.el-textarea__inner),
.publish-editor-form :deep(.el-select__selected-item) {
    color: var(--tf-text);
}

.task-filter-panel :deep(.el-input__inner::placeholder),
.publish-editor-form :deep(.el-input__inner::placeholder),
.publish-editor-form :deep(.el-textarea__inner::placeholder) {
    color: var(--tf-text-dim);
}

.publish-list-shell :deep(.el-table) {
    --el-table-header-bg-color: rgba(13, 34, 60, 0.95);
    --el-table-tr-bg-color: rgba(8, 22, 38, 0.84);
    --el-table-striped-bg-color: rgba(15, 38, 63, 0.66);
    --el-table-row-hover-bg-color: rgba(31, 164, 255, 0.14);
    --el-table-border-color: rgba(74, 195, 255, 0.24);
    --el-table-text-color: var(--tf-text);
    --el-table-header-text-color: #bfe8ff;
    --el-table-bg-color: rgba(6, 14, 26, 0.84);
    color: var(--tf-text);
    border-radius: 10px;
    overflow: hidden;
}

.publish-list-shell :deep(.el-table__header-wrapper th.el-table__cell) {
    font-weight: 600;
    letter-spacing: 0.02em;
}

.publish-list-shell :deep(.el-table__body tr td.el-table__cell) {
    border-bottom-color: rgba(74, 195, 255, 0.18);
}

.publish-list-shell :deep(.el-table__body tr.el-table__row > td.el-table__cell) {
    background: rgba(6, 18, 32, 0.86);
}

.publish-list-shell :deep(.el-table--striped .el-table__body tr.el-table__row--striped > td.el-table__cell) {
    background: rgba(13, 31, 52, 0.82);
}

.publish-list-shell :deep(.el-table__body tr.el-table__row:hover > td.el-table__cell) {
    background: rgba(31, 164, 255, 0.16) !important;
}

.publish-list-shell :deep(.el-switch__label) {
    color: var(--tf-text-soft);
}

:deep(.publish-editor-dialog.el-dialog) {
    background: linear-gradient(160deg, rgba(4, 14, 26, 0.96), rgba(9, 24, 42, 0.97));
    border: 1px solid rgba(74, 195, 255, 0.3);
    box-shadow: 0 20px 44px rgba(0, 0, 0, 0.5);
}

:deep(.publish-editor-dialog .el-dialog__header) {
    border-bottom: 1px solid rgba(74, 195, 255, 0.2);
    margin-right: 0;
    padding: 16px 20px;
}

:deep(.publish-editor-dialog .el-dialog__title),
:deep(.publish-editor-dialog .el-dialog__close),
:deep(.publish-editor-dialog .el-form-item__label),
:deep(.publish-editor-dialog .el-radio-button__inner) {
    color: var(--tf-text);
}

:deep(.publish-editor-dialog .el-dialog__body) {
    color: var(--tf-text-soft);
    padding-top: 14px;
}

:deep(.publish-editor-dialog .publish-source-mode.el-radio-group) {
    display: inline-flex;
    align-items: center;
    padding: 4px;
    border-radius: 12px;
    border: 1px solid rgba(74, 195, 255, 0.34);
    background: linear-gradient(145deg, rgba(6, 16, 30, 0.88), rgba(9, 24, 42, 0.86));
    box-shadow: inset 0 0 0 1px rgba(103, 240, 255, 0.08);
}

:deep(.publish-editor-dialog .publish-source-mode .el-radio-button__inner) {
    min-width: 128px;
    padding: 10px 14px;
    border: 0;
    border-radius: 8px;
    color: var(--tf-text-soft);
    background: transparent;
    font-weight: 600;
    transition: all 0.2s ease;
    box-shadow: none;
}

:deep(.publish-editor-dialog .el-form-item) {
    margin-bottom: 18px;
}

:deep(.publish-editor-dialog .publish-source-mode .el-radio-button__original-radio:checked + .el-radio-button__inner) {
    background: linear-gradient(135deg, var(--tf-accent-strong), var(--tf-accent));
    border-color: transparent;
    color: #001621;
    box-shadow: 0 8px 16px rgba(18, 120, 211, 0.32);
}

:deep(.publish-editor-dialog .publish-source-mode .el-radio-button__original-radio:not(:checked) + .el-radio-button__inner:hover) {
    color: var(--tf-text);
    background: rgba(31, 164, 255, 0.16);
}

:deep(.publish-editor-dialog .el-switch) {
    --el-switch-on-color: var(--tf-accent-strong);
    --el-switch-off-color: rgba(74, 195, 255, 0.34);
}

@media (max-width: 960px) {
    .publish-table-actions {
        flex-wrap: wrap;
    }

    .path-field {
        flex-direction: column;
        align-items: stretch;
    }
}
</style>

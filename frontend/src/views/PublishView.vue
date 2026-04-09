<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';

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
const currentPage = ref(1);
const pageSize = ref(10);
const totalPublications = ref(0);
let loadTimer = null;

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
    ]
};

const publishTypeLabelMap = {
    imagery: '地图 / 遥感',
    'electronic-map': '地图 / 电子地图',
    terrain: '地形',
    '3dtiles': '3DTiles'
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

async function copyText(text) {
    const value = String(text || '').trim();
    if (!value) return false;

    if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
        return true;
    }

    const textArea = document.createElement('textarea');
    textArea.value = value;
    textArea.setAttribute('readonly', 'readonly');
    textArea.style.position = 'absolute';
    textArea.style.left = '-9999px';
    document.body.appendChild(textArea);
    textArea.select();
    const copied = document.execCommand('copy');
    document.body.removeChild(textArea);
    return copied;
}

async function copyPublicationUrl(url) {
    try {
        const copied = await copyText(url);
        if (!copied) {
            throw new Error('复制失败');
        }
        pushToast('发布地址已复制', 'success');
    } catch (error) {
        pushToast(`复制失败: ${error.message}`, 'error', 4000);
    }
}

function resetForm() {
    form.sourceMode = 'task';
    form.taskId = '';
    form.workspacePath = '';
    form.alias = '';
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
            sourceMode: item.metadata?.taskId ? 'task' : 'manual',
            taskId: item.metadata?.taskId || undefined,
            workspacePath: item.metadata?.taskId ? undefined : normalizedWorkspacePath,
            publishPath: normalizedWorkspacePath,
            alias: item.alias,
            publishType: item.publishType,
            publishMethod: item.metadata?.publishMethod,
            enabled: nextEnabled,
            visibility: item.metadata?.visibility,
            note: item.metadata?.note
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
        const response = await api.listPublications({
            page: currentPage.value,
            pageSize: pageSize.value,
            keyword: String(keyword.value || '').trim() || undefined
        });
        const data = response?.data || {};
        publications.value = data.publications || [];
        totalPublications.value = Number(data.total || 0);
        currentPage.value = Number(data.page || currentPage.value);
        pageSize.value = Number(data.pageSize || pageSize.value);
    } catch (error) {
        pushToast(`发布记录加载失败: ${error.message}`, 'error', 4500);
    }
}

async function loadTasks() {
    try {
        const response = await api.getAllTasks({
            page: 1,
            pageSize: 500,
            status: 'completed'
        });
        tasks.value = Object.values(response?.data?.tasks || {});
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
        sourceMode: form.sourceMode,
        taskId: form.sourceMode === 'task' ? form.taskId : undefined,
        workspacePath: form.sourceMode === 'manual' ? normalizedWorkspacePath : undefined,
        publishPath: form.sourceMode === 'manual' ? normalizedWorkspacePath : undefined,
        alias: form.alias || undefined,
        publishType: form.publishType,
        publishMethod: form.publishMethod || undefined,
        enabled: form.enabled,
        visibility: form.visibility,
        note: form.note || undefined
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

function handlePageChange(page) {
    currentPage.value = page;
    loadPublications();
}

function handlePageSizeChange(size) {
    pageSize.value = size;
    currentPage.value = 1;
    loadPublications();
}

function scheduleLoad() {
    if (loadTimer) {
        window.clearTimeout(loadTimer);
    }
    loadTimer = window.setTimeout(() => {
        loadTimer = null;
        loadPublications();
    }, 250);
}

watch(keyword, () => {
    currentPage.value = 1;
    scheduleLoad();
});

onBeforeUnmount(() => {
    if (loadTimer) {
        window.clearTimeout(loadTimer);
        loadTimer = null;
    }
});
</script>

<template>
    <section class="app-view">
        <div class="section-header section-header-product">
            <div>
                <h2>发布中心</h2>
                <p class="section-subtitle">统一管理发布记录，支持按任务生成发布、手动目录发布、启停切换与生命周期维护。</p>
            </div>
            <div class="tool-actions publish-header-actions">
                <el-button @click="loadPublications">刷新</el-button>
                <el-button type="primary" @click="openCreateModal">创建发布</el-button>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack">
                <div class="card publish-list-shell data-panel">
                    <div class="card-header task-filter-panel task-filter-panel-simple data-toolbar">
                        <el-input v-model="keyword" clearable placeholder="发布名称 / 路径 / 任务 / 发布方式" />
                    </div>

                    <div class="card-body publish-table data-table-shell">
                        <el-table class="publish-data-table" :data="publications" stripe border height="100%">
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
                                    <div v-if="row.accessUrl" class="publish-address-cell">
                                        <a
                                            class="publish-address-link"
                                            :href="row.accessUrl"
                                            :title="row.accessUrl"
                                            target="_blank"
                                            rel="noreferrer"
                                        >{{ row.accessUrl }}</a>
                                        <button
                                            class="publish-copy-button"
                                            type="button"
                                            :title="`复制地址: ${row.accessUrl}`"
                                            @click="copyPublicationUrl(row.accessUrl)"
                                        >
                                            <svg viewBox="0 0 24 24" aria-hidden="true">
                                                <path d="M9 9a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-8a2 2 0 0 1-2-2z" />
                                                <path d="M5 15H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1" />
                                            </svg>
                                        </button>
                                    </div>
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
                        <div class="publish-list-pagination">
                            <el-pagination
                                :current-page="currentPage"
                                :page-size="pageSize"
                                :page-sizes="[10, 20, 50, 100]"
                                :total="totalPublications"
                                background
                                layout="total, sizes, prev, pager, next, jumper"
                                @current-change="handlePageChange"
                                @size-change="handlePageSizeChange"
                            />
                        </div>
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

                <el-form-item label="发布类型">
                    <el-select v-model="form.publishType">
                        <el-option label="地图 / 遥感" value="imagery" />
                        <el-option label="地图 / 电子地图" value="electronic-map" />
                        <el-option label="地形" value="terrain" />
                        <el-option label="3DTiles" value="3dtiles" />
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

.publish-list-pagination {
    display: flex;
    justify-content: flex-end;
    padding: 16px 18px 18px;
    border-top: 1px solid rgba(145, 160, 180, 0.12);
}

.publish-table-actions {
    display: flex;
    align-items: center;
    gap: 8px;
}

.publish-list-shell {
    border: 1px solid rgba(145, 160, 180, 0.14);
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent),
        linear-gradient(160deg, rgba(8, 16, 28, 0.92), rgba(10, 19, 32, 0.96));
    box-shadow: 0 18px 38px rgba(0, 0, 0, 0.16);
}

.publish-list-shell.data-panel {
    border-radius: 30px;
    border-color: rgba(129, 150, 181, 0.16);
    background:
        radial-gradient(circle at top right, rgba(92, 132, 190, 0.1), transparent 26%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.03), transparent 22%),
        linear-gradient(160deg, rgba(7, 14, 24, 0.98), rgba(8, 15, 26, 0.95));
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.04),
        0 26px 54px rgba(0, 0, 0, 0.22);
}

.publish-list-shell :deep(.el-input__wrapper) {
    background: rgba(6, 14, 24, 0.9) !important;
    border-radius: 14px !important;
    box-shadow:
        inset 0 0 0 1px rgba(82, 112, 147, 0.3) !important,
        0 10px 24px rgba(0, 0, 0, 0.08) !important;
}

.publish-list-shell :deep(.el-input__wrapper.is-focus) {
    box-shadow:
        inset 0 0 0 1px rgba(103, 240, 255, 0.26) !important,
        0 0 0 4px rgba(31, 164, 255, 0.08) !important;
}

.publish-list-shell :deep(.el-input__inner),
.publish-list-shell :deep(.el-input__icon) {
    color: var(--tf-text) !important;
}

.publish-list-shell :deep(.el-input__inner::placeholder) {
    color: var(--tf-text-dim) !important;
}

.publish-list-shell :deep(.el-table) {
    color: var(--tf-text) !important;
    border: 1px solid rgba(108, 134, 168, 0.14) !important;
    border-radius: 26px !important;
    overflow: hidden !important;
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent),
        linear-gradient(150deg, rgba(10, 17, 29, 0.96), rgba(9, 15, 25, 0.92)) !important;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.03),
        0 16px 30px rgba(0, 0, 0, 0.14) !important;
}

.publish-list-shell :deep(.el-table::before),
.publish-list-shell :deep(.el-table__inner-wrapper::before) {
    display: none !important;
}

.publish-list-shell :deep(.el-table__header-wrapper) {
    background: linear-gradient(180deg, rgba(31, 43, 63, 0.96), rgba(25, 35, 52, 0.92)) !important;
}

.publish-list-shell :deep(.el-table__header-wrapper th.el-table__cell) {
    background: transparent !important;
    border-bottom-color: rgba(108, 134, 168, 0.16) !important;
    color: #dbe7f4 !important;
    font-weight: 700 !important;
    letter-spacing: 0.02em !important;
    padding-top: 18px !important;
    padding-bottom: 18px !important;
}

.publish-list-shell :deep(.el-table__body td.el-table__cell) {
    border-bottom-color: rgba(108, 134, 168, 0.1) !important;
    padding-top: 18px !important;
    padding-bottom: 18px !important;
}

.publish-list-shell :deep(.el-table__body tr.el-table__row > td.el-table__cell),
.publish-list-shell :deep(.el-table__fixed-body-wrapper tr.el-table__row > td.el-table__cell) {
    background: rgba(11, 20, 33, 0.82) !important;
}

.publish-list-shell :deep(.el-table--striped .el-table__body tr.el-table__row--striped > td.el-table__cell) {
    background: rgba(15, 25, 40, 0.86) !important;
}

.publish-list-shell :deep(.el-table__body tr.el-table__row:hover > td.el-table__cell),
.publish-list-shell :deep(.el-table__fixed-body-wrapper tr.el-table__row:hover > td.el-table__cell) {
    background: rgba(20, 33, 50, 0.94) !important;
}

.publish-list-shell :deep(.el-table__fixed),
.publish-list-shell :deep(.el-table__fixed-right),
.publish-list-shell :deep(.el-table__fixed-right-patch) {
    background: rgba(11, 19, 31, 0.96) !important;
}

.publish-list-shell :deep(.el-table__fixed-right::before),
.publish-list-shell :deep(.el-table__fixed::before) {
    background: linear-gradient(180deg, rgba(108, 134, 168, 0.16), rgba(108, 134, 168, 0.04)) !important;
}

.publish-table-actions :deep(.el-button),
.publish-header-actions :deep(.el-button) {
    min-width: 62px;
    padding-inline: 14px;
    border-radius: 10px;
    font-weight: 700;
}

.publish-header-actions :deep(.el-button--primary),
.publish-table-actions :deep(.el-button--primary) {
    border-color: rgba(196, 205, 216, 0.16);
    background: linear-gradient(135deg, rgba(142, 169, 201, 0.96), rgba(88, 109, 137, 0.92));
    color: #08111b;
    box-shadow: 0 10px 24px rgba(44, 56, 74, 0.26);
}

.publish-table-actions :deep(.el-button--danger) {
    border-color: rgba(233, 171, 183, 0.16);
    background: linear-gradient(135deg, rgba(201, 103, 120, 0.94), rgba(138, 59, 76, 0.9));
}

.publish-header-actions :deep(.el-button:not(.el-button--primary):not(.el-button--danger)),
.publish-table-actions :deep(.el-button:not(.el-button--primary):not(.el-button--danger)) {
    border-color: rgba(156, 170, 188, 0.16);
    background: linear-gradient(135deg, rgba(34, 44, 58, 0.96), rgba(22, 29, 39, 0.94));
    color: #dce6f1;
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

.publish-address-cell {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 10px;
}

.publish-address-link {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
}

.publish-copy-button {
    flex: 0 0 auto;
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid rgba(103, 240, 255, 0.16);
    border-radius: 10px;
    background: rgba(10, 24, 39, 0.72);
    color: var(--tf-text-soft);
    cursor: pointer;
    transition:
        background 0.18s ease,
        border-color 0.18s ease,
        color 0.18s ease,
        transform 0.18s ease;
}

.publish-copy-button:hover {
    background: rgba(19, 38, 58, 0.94);
    border-color: rgba(103, 240, 255, 0.26);
    color: var(--tf-text);
    transform: translateY(-1px);
}

.publish-copy-button svg {
    width: 15px;
    height: 15px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.9;
    stroke-linecap: round;
    stroke-linejoin: round;
}
.publish-editor-form :deep(.el-input__wrapper),
.publish-editor-form :deep(.el-textarea__inner),
.publish-editor-form :deep(.el-select__wrapper) {
    background: rgba(3, 12, 24, 0.72);
    box-shadow: 0 0 0 1px rgba(74, 195, 255, 0.22) inset;
}

.publish-editor-form :deep(.el-input__inner),
.publish-editor-form :deep(.el-textarea__inner),
.publish-editor-form :deep(.el-select__selected-item) {
    color: var(--tf-text);
}

.publish-editor-form :deep(.el-input__inner::placeholder),
.publish-editor-form :deep(.el-textarea__inner::placeholder) {
    color: var(--tf-text-dim);
}

.publish-list-shell :deep(.el-switch__label) {
    color: var(--tf-text-soft);
}

.publish-list-shell :deep(.el-tag) {
    border-radius: 999px;
    font-weight: 700;
    padding-inline: 10px;
}

.publish-list-pagination :deep(.el-pagination) {
    gap: 8px;
}

.publish-list-pagination :deep(.btn-prev),
.publish-list-pagination :deep(.btn-next),
.publish-list-pagination :deep(.el-pager li) {
    min-width: 38px;
    height: 38px;
    border: 1px solid rgba(108, 134, 168, 0.14) !important;
    border-radius: 12px;
    background: rgba(16, 27, 42, 0.92) !important;
    color: var(--tf-text) !important;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
}

.publish-list-pagination :deep(.el-pager li.is-active) {
    border-color: rgba(103, 240, 255, 0.2) !important;
    background: linear-gradient(135deg, rgba(75, 133, 214, 0.96), rgba(62, 111, 176, 0.92)) !important;
    color: #f5fbff !important;
}

.publish-list-pagination :deep(.el-pagination__total),
.publish-list-pagination :deep(.el-pagination__jump),
.publish-list-pagination :deep(.el-pagination__sizes),
.publish-list-pagination :deep(.el-pagination__goto) {
    color: var(--tf-text-soft) !important;
}

.publish-list-pagination :deep(.el-select .el-select__wrapper),
.publish-list-pagination :deep(.el-input .el-input__wrapper) {
    min-height: 38px;
    border-radius: 12px;
    background: rgba(16, 27, 42, 0.92) !important;
    box-shadow: inset 0 0 0 1px rgba(108, 134, 168, 0.18) !important;
}

.publish-list-pagination :deep(.el-select__selected-item),
.publish-list-pagination :deep(.el-input__inner),
.publish-list-pagination :deep(.el-select__caret),
.publish-list-pagination :deep(.el-input__icon) {
    color: var(--tf-text) !important;
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

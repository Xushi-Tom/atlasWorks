<script setup>
import { computed, onMounted, ref } from 'vue';

import { api } from '../services/api';
import { formatBytes, formatDateTime } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const ARCHIVE_EXTENSIONS = ['.zip', '.tar', '.tgz', '.tar.gz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz', '.7z'];

const browser = ref({ directories: [], files: [] });
const currentPath = ref('');
const selectedFile = ref(null);
const detailVisible = ref(false);
const previewLoadFailed = ref(false);
const uploadVisible = ref(false);
const folderVisible = ref(false);
const newFolderName = ref('');
const uploadState = ref({
    overwrite: false
});
const uploadResult = ref('');
const singleInput = ref(null);

const breadcrumbSegments = computed(() => {
    const segments = String(currentPath.value || '')
        .split('/')
        .filter(Boolean);

    return segments.map((segment, index) => ({
        label: segment,
        path: segments.slice(0, index + 1).join('/')
    }));
});

function isArchiveName(name = '') {
    const lower = String(name || '').toLowerCase();
    return ARCHIVE_EXTENSIONS.some(ext => lower.endsWith(ext));
}

async function loadDirectory(path = currentPath.value) {
    try {
        const response = await api.browseResults(path);
        const data = response?.data || {};
        browser.value = data || { directories: [], files: [] };
        currentPath.value = data?.currentPath || path || '';
    } catch (error) {
        pushToast(`工作空间加载失败: ${error.message}`, 'error', 4500);
    }
}

async function showFileDetails(file) {
    try {
        const response = await api.getWorkspaceFileInfo(file.path);
        selectedFile.value = response?.data || null;
        previewLoadFailed.value = false;
        detailVisible.value = true;
    } catch (error) {
        pushToast(`文件详情加载失败: ${error.message}`, 'error', 4500);
    }
}

function closeDetailModal() {
    detailVisible.value = false;
    previewLoadFailed.value = false;
}

function resolvePreviewUrl(fileInfo) {
    const previewUrl = String(fileInfo?.previewUrl || '').trim();
    if (previewUrl) {
        return previewUrl.startsWith('http') ? previewUrl : `${window.location.origin}${previewUrl}`;
    }
    const extension = String(fileInfo?.extension || '').toLowerCase();
    if (extension === '.png' || extension === '.jpg' || extension === '.jpeg') {
        return api.getWorkspaceFileUrl(fileInfo?.path || '');
    }
    return '';
}

function openUploadModal() {
    uploadState.value.overwrite = false;
    uploadResult.value = '';
    uploadVisible.value = true;
}

function closeUploadModal() {
    uploadVisible.value = false;
}

function openFolderModal() {
    newFolderName.value = '';
    folderVisible.value = true;
}

function closeFolderModal() {
    folderVisible.value = false;
}

function triggerSingleUpload() {
    singleInput.value?.click();
}

async function handleSingleUpload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    uploadResult.value = '上传中...';
    try {
        const response = await api.uploadDataSourceFile(file, currentPath.value, uploadState.value.overwrite, 'workspace');
        uploadResult.value = response?.message || '上传完成';
        pushToast(uploadResult.value, 'success');
        await loadDirectory(currentPath.value);
        uploadVisible.value = false;
    } catch (error) {
        uploadResult.value = error.message;
        pushToast(`上传失败: ${error.message}`, 'error', 5000);
    } finally {
        event.target.value = '';
    }
}

async function createFolder() {
    const name = String(newFolderName.value || '').trim();
    if (!name) {
        pushToast('请输入文件夹名称', 'warning');
        return;
    }
    try {
        const folderPath = currentPath.value ? `${currentPath.value}/${name}` : name;
        await api.createWorkspaceFolder(folderPath);
        newFolderName.value = '';
        pushToast('文件夹创建成功', 'success');
        folderVisible.value = false;
        await loadDirectory(currentPath.value);
    } catch (error) {
        pushToast(`创建文件夹失败: ${error.message}`, 'error', 4500);
    }
}

function navigateToRoot() {
    loadDirectory('');
}

function navigateUp() {
    if (!currentPath.value) return;
    const parentPath = currentPath.value.includes('/') ? currentPath.value.split('/').slice(0, -1).join('/') : '';
    loadDirectory(parentPath);
}

async function deleteItem(item, type) {
    const label = type === 'directory' ? '目录' : '文件';
    if (!window.confirm(`确认删除${label}“${item.name}”吗？该操作不可恢复。`)) return;
    try {
        if (type === 'directory') {
            await api.deleteWorkspaceFolder(item.path);
        } else {
            await api.deleteWorkspaceFile(item.path);
        }
        pushToast(`${label}删除成功`, 'success');
        await loadDirectory(currentPath.value);
    } catch (error) {
        pushToast(`删除${label}失败: ${error.message}`, 'error', 5000);
    }
}

async function extractArchive(file) {
    if (!window.confirm(`确认解压“${file.name}”到当前目录吗？`)) return;
    const extractFolderName = window.prompt('解压后文件夹名称（可选，留空使用默认）', '');
    if (extractFolderName === null) return;
    try {
        await api.extractArchive(file.path, 'workspace', false, extractFolderName);
        pushToast('压缩文件解压完成', 'success');
        await loadDirectory(currentPath.value);
    } catch (error) {
        pushToast(`解压失败: ${error.message}`, 'error', 5000);
    }
}

onMounted(async () => {
    await loadDirectory('');
});
</script>

<template>
    <section class="app-view">
        <div class="section-header section-header-product">
            <div>
                <h2>工作空间</h2>
                <p class="section-subtitle">面向交付资产目录进行归档、补充上传与发布前整理，确保外部成果也能纳入统一交付体系。</p>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack">
                <div class="card datasource-browser-shell">
                    <div class="card-header directory-shell-head">
                        <div class="directory-shell-toolbar">
                            <div class="directory-path-row">
                                <button class="directory-root-badge directory-root-button" type="button" @click="navigateToRoot">根目录</button>
                                <div v-if="breadcrumbSegments.length" class="directory-path-text">
                                    <template v-for="(segment, index) in breadcrumbSegments" :key="segment.path">
                                        <span v-if="index" class="directory-path-divider">/</span>
                                        <button class="directory-path-link" type="button" @click="loadDirectory(segment.path)">{{ segment.label }}</button>
                                    </template>
                                </div>
                            </div>
                            <div class="directory-shell-actions">
                                <button v-if="currentPath" class="btn btn-secondary" type="button" @click="navigateUp">上一级</button>
                                <button class="btn btn-secondary" type="button" @click="loadDirectory(currentPath)">刷新</button>
                                <button class="btn btn-secondary" type="button" @click="openFolderModal">新建文件夹</button>
                                <button class="btn btn-primary" type="button" @click="openUploadModal">上传到当前目录</button>
                            </div>
                        </div>
                    </div>
                    <div class="card-body file-list datasource-file-list datasource-file-list-compact">
                        <div
                            v-for="dir in browser.directories"
                            :key="`dir-${dir.path}`"
                            class="file-item file-item-button file-item-row"
                        >
                            <button type="button" class="file-item-main" @click="loadDirectory(dir.path)">
                                <div class="file-info">
                                    <div class="file-name">{{ dir.name }}</div>
                                    <div class="file-details">{{ dir.dirCount }} 个目录 / {{ dir.fileCount }} 个文件</div>
                                </div>
                            </button>
                            <div class="file-actions">
                                <button class="btn btn-ghost-danger" type="button" @click="deleteItem(dir, 'directory')">删除</button>
                            </div>
                        </div>

                        <div
                            v-for="file in browser.files"
                            :key="`file-${file.path}`"
                            class="file-item file-item-button file-item-row"
                        >
                            <button type="button" class="file-item-main" @click="showFileDetails(file)">
                                <div class="file-info">
                                    <div class="file-name">{{ file.name }}</div>
                                    <div class="file-details">{{ file.sizeFormatted || formatBytes(file.size) }}</div>
                                </div>
                            </button>
                            <div class="file-actions">
                                <button
                                    v-if="isArchiveName(file.name)"
                                    class="btn btn-secondary"
                                    type="button"
                                    @click="extractArchive(file)"
                                >
                                    解压
                                </button>
                                <button class="btn btn-ghost-danger" type="button" @click="deleteItem(file, 'file')">删除</button>
                            </div>
                        </div>

                        <div v-if="!browser.directories?.length && !browser.files?.length" class="message info">当前目录为空</div>
                    </div>
                </div>
            </div>
        </div>

        <Teleport to="body">
            <div v-if="detailVisible" class="modal modal-overlay modal-overlay-active" @click.self="closeDetailModal">
                <div class="modal-content datasource-detail-content">
                    <div class="modal-header">
                        <h3>工作空间文件详情</h3>
                        <button class="message-close" type="button" @click="closeDetailModal">×</button>
                    </div>
                    <div class="modal-body">
                        <div v-if="selectedFile" class="info-list">
                            <div class="info-row">
                                <span class="info-label">文件</span>
                                <span class="info-value">{{ selectedFile.name || selectedFile.path || '-' }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">大小</span>
                                <span class="info-value">{{ formatBytes(selectedFile.size) }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">更新时间</span>
                                <span class="info-value">{{ formatDateTime(selectedFile.lastModified || selectedFile.modifiedTime) || '-' }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">元数据</span>
                                <span class="info-value">{{ selectedFile.metadata?.bandCount ? `${selectedFile.metadata.bandCount} 波段` : '普通文件' }}</span>
                            </div>
                        </div>
                        <div v-if="resolvePreviewUrl(selectedFile)" class="datasource-preview-card workspace-preview-card">
                            <div class="datasource-preview-head">图片预览</div>
                            <div class="datasource-preview-frame workspace-preview-frame">
                                <img
                                    v-if="!previewLoadFailed"
                                    :src="resolvePreviewUrl(selectedFile)"
                                    :alt="selectedFile?.name || 'preview'"
                                    class="datasource-preview-image workspace-preview-image"
                                    @error="previewLoadFailed = true"
                                >
                                <div v-else class="message warning">图片加载失败</div>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" type="button" @click="closeDetailModal">关闭</button>
                    </div>
                </div>
            </div>
        </Teleport>

        <Teleport to="body">
            <div v-if="uploadVisible" class="modal modal-overlay modal-overlay-active" @click.self="closeUploadModal">
                <div class="modal-content datasource-import-content">
                    <div class="modal-header">
                        <h3>上传到工作空间当前目录</h3>
                        <button class="message-close" type="button" @click="closeUploadModal">×</button>
                    </div>
                    <div class="modal-body">
                        <div class="form-group">
                            <label class="checkbox-label">
                                <input v-model="uploadState.overwrite" type="checkbox">
                                覆盖同名文件
                            </label>
                        </div>
                        <div class="tool-actions">
                            <button class="btn btn-primary" type="button" @click="triggerSingleUpload">选择单文件</button>
                        </div>
                        <input ref="singleInput" hidden type="file" accept=".zip,.tar,.tgz,.tar.gz,.7z,.json,.png,.jpg,.jpeg,.terrain,.b3dm,.glb,.gltf,.geojson,.tif,.tiff" @change="handleSingleUpload">
                        <div class="simple-info datasource-upload-note">
                            <div class="placeholder-text">{{ uploadResult || '文件会直接上传到当前目录，压缩包上传后可在列表中单独执行解压。' }}</div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" type="button" @click="closeUploadModal">关闭</button>
                    </div>
                </div>
            </div>
        </Teleport>

        <Teleport to="body">
            <div v-if="folderVisible" class="modal modal-overlay modal-overlay-active" @click.self="closeFolderModal">
                <div class="modal-content datasource-import-content">
                    <div class="modal-header">
                        <h3>新建工作空间文件夹</h3>
                        <button class="message-close" type="button" @click="closeFolderModal">×</button>
                    </div>
                    <div class="modal-body">
                        <div class="form-group">
                            <label>文件夹名称</label>
                            <input v-model="newFolderName" type="text" placeholder="例如 publish/project-a">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" type="button" @click="closeFolderModal">取消</button>
                        <button class="btn btn-primary" type="button" @click="createFolder">创建</button>
                    </div>
                </div>
            </div>
        </Teleport>

    </section>
</template>

<style scoped>
.workspace-preview-card {
    margin-top: 18px;
}

.workspace-preview-frame {
    min-height: 320px;
}

.workspace-preview-image {
    max-height: 520px;
}
</style>

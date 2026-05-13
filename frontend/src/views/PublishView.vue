<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import {
    Clock,
    CopyDocument,
    Delete,
    EditPen,
    MoreFilled,
    Plus,
    Refresh,
    Search,
    View
} from '@element-plus/icons-vue';

import PathPickerModal from '../components/PathPickerModal.vue';
import ResizableDrawer from '../components/ResizableDrawer.vue';
import { api } from '../services/api';
import { formatDateTime, normalizeListInput } from '../utils/formatters';
import { pushToast } from '../composables/useToast';

const PublicationPreviewModal = defineAsyncComponent(() => import('../components/PublicationPreviewModal.vue'));

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
    seedEnabled: true,
    seedMinZoom: 0,
    seedMaxZoom: 16,
    enabled: true,
    visibility: 'public',
    note: ''
});

const createVisible = ref(false);
const detailVisible = ref(false);
const detailPublication = ref(null);
const detailLoading = ref(false);
const previewVisible = ref(false);
const keyword = ref('');
const statusFilter = ref('');
const publishTypeFilter = ref('');
const publications = ref([]);
const tasks = ref([]);
const tasksLoaded = ref(false);
const tasksLoading = ref(false);
const editingPublicationId = ref('');
const currentPage = ref(1);
const pageSize = ref(10);
const totalPublications = ref(0);
const publicationDetails = ref({});
let publicationRefreshTimer = null;

const DATASOURCE_PUBLISH_TYPE = 'imagery';
const DATASOURCE_PUBLISH_METHOD = 'geoserver-wmts';
const DATASOURCE_PUBLISH_TYPE_LABEL = '地图';
const DATASOURCE_PUBLISH_METHOD_LABEL = '数据源影像发布';

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
    vector: [
        { value: 'mvt', label: 'MVT 矢量瓦片' },
        { value: 'geojson-tile', label: 'GeoJSON 瓦片' }
    ]
};

const publishTypeLabelMap = {
    imagery: '地图',
    'electronic-map': '地图',
    terrain: '地形',
    '3dtiles': '3DTiles',
    vector: '二维矢量'
};

const visibilityLabelMap = {
    private: '私有',
    internal: '内部',
    public: '公开'
};

const publicationStatusLabelMap = {
    enabled: '已启动',
    disabled: '未启动',
    published: '已启动',
    draft: '构建中',
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
const DATASOURCE_BASE_PATH = '/app/dataSource';
const GEOSERVER_METHODS = ['geoserver-wms', 'geoserver-wmts'];
const VECTOR_MVT_METHODS = ['mvt', 'vector-tile', 'vector-tiles'];
const VECTOR_GEOJSON_METHODS = ['geojson-tile', 'geojson-tiles'];

const isDatasourceMode = computed(() => form.sourceMode === 'datasource');
const publishMethodOptions = computed(() => {
    if (isDatasourceMode.value) {
        return [{ value: DATASOURCE_PUBLISH_METHOD, label: DATASOURCE_PUBLISH_METHOD_LABEL }];
    }
    return publishMethodCatalog[form.publishType] || [];
});
const isGeoserverPublish = computed(() => GEOSERVER_METHODS.includes(String(form.publishMethod || '').toLowerCase()));
const isDatasourcePublish = computed(() => isGeoserverPublish.value);
const dataSourceAllowedExtensions = computed(() => {
    if (isDatasourcePublish.value) return ['.tif', '.tiff'];
    return [];
});
const dataSourcePlaceholder = computed(() => {
    return '选择单个影像文件，或选择包含影像的目录';
});

const publishableTasks = computed(() => {
    return [...tasks.value]
        .filter(task => task?.status === 'completed' && (task?.result?.mergedOutputPath || task?.result?.outputPath || task?.result?.artifactId))
        .sort((a, b) => String(b.startTime || '').localeCompare(String(a.startTime || '')));
});

const selectedTask = computed(() => publishableTasks.value.find(task => task.taskId === form.taskId) || null);
const modalTitle = computed(() => editingPublicationId.value ? '编辑发布' : '创建发布');

function normalizeDisplayUrl(url) {
    const value = String(url || '').trim();
    if (!value) return '';
    return value
        .replace(/^((?:https?):\/\/)([^/?#]+)/i, (_, protocol, hostPart) => {
            const portMatch = String(hostPart || '').match(/:(\d+)$/);
            return `${protocol}localhost${portMatch ? `:${portMatch[1]}` : ''}`;
        })
        .replace(/%7B/ig, '{')
        .replace(/%7D/ig, '}');
}

function resolveInteractiveUrl(url) {
    const value = String(url || '').trim();
    if (!value) return '';
    return value
        .replace(/^((?:https?):\/\/)([^/?#]+)/i, (_, protocol, hostPart) => {
            const portMatch = String(hostPart || '').match(/:(\d+)$/);
            const nextHost = window.location.hostname || 'localhost';
            return `${protocol}${nextHost}${portMatch ? `:${portMatch[1]}` : ''}`;
        })
        .replace(/%7B/ig, '{')
        .replace(/%7D/ig, '}');
}

function toPreviewPublication(item) {
    if (!item) return null;
    return {
        ...item,
        browserUrl: resolveInteractiveUrl(item.browserUrl),
        launchUrl: resolveInteractiveUrl(item.launchUrl),
        accessUrl: resolveInteractiveUrl(item.accessUrl),
        sampleUrl: resolveInteractiveUrl(item.sampleUrl),
        wmsUrl: resolveInteractiveUrl(item.wmsUrl),
        wmtsCapabilitiesUrl: resolveInteractiveUrl(item.wmtsCapabilitiesUrl),
        wmtsTileUrl: resolveInteractiveUrl(item.wmtsTileUrl)
    };
}

function getMergedPublication(item) {
    if (!item) return null;
    const publicationId = String(item?.publicationId || item?.id || '').trim();
    const detail = publicationId ? publicationDetails.value[publicationId] : null;
    return detail ? { ...item, ...detail } : item;
}

function isPublicationEnabled(item) {
    return Boolean(item?.metadata?.enabled ?? (item?.status === 'enabled' || item?.status === 'published'));
}

function getPublicationSourceSummary(item) {
    const entryCount = Number(item?.sourceEntryCount ?? item?.metadata?.sourceEntryCount ?? 0);
    return entryCount ? `${entryCount} 项` : '-';
}

function getPrimaryPublicationUrl(item) {
    if (!item) return '';
    const method = String(item?.metadata?.publishMethod || item?.publishMethod || '').toLowerCase();
    if (method.includes('geoserver')) {
        return normalizeDisplayUrl(item?.sampleUrl || item?.accessUrl || '');
    }
    return normalizeDisplayUrl(item?.accessUrl || item?.browserUrl || item?.launchUrl || '');
}

function getPrimaryPublicationHref(item) {
    if (!item) return '';
    const method = String(item?.metadata?.publishMethod || item?.publishMethod || '').toLowerCase();
    if (method.includes('geoserver')) {
        return resolveInteractiveUrl(item?.sampleUrl || item?.accessUrl || '');
    }
    return resolveInteractiveUrl(item?.accessUrl || item?.browserUrl || item?.launchUrl || '');
}

function getPrimaryPublicationUrlLabel(item) {
    if (!item) return '访问地址';
    const method = String(item?.metadata?.publishMethod || item?.publishMethod || '').toLowerCase();
    if (method.includes('geoserver')) {
        return '示例瓦片';
    }
    return '访问地址';
}

function getSecondaryPublicationUrl(item) {
    return '';
}

function getSecondaryPublicationHref(item) {
    return '';
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

function normalizeDataSourcePath(pathValue) {
    let path = String(pathValue || '').trim().replace(/\\/g, '/');
    if (!path) return '';

    const lowerPath = path.toLowerCase();
    const lowerBase = DATASOURCE_BASE_PATH.toLowerCase();
    if (lowerPath === lowerBase) return '';
    if (lowerPath.startsWith(`${lowerBase}/`)) {
        path = path.slice(DATASOURCE_BASE_PATH.length + 1);
    }
    return path.replace(/^\/+|\/+$/g, '');
}

function getNormalizedSourcePath() {
    return form.sourceMode === 'datasource'
        ? getNormalizedDataSourcePaths()[0] || ''
        : normalizeWorkspacePath(form.workspacePath);
}

function getNormalizedDataSourcePaths() {
    return normalizeListInput(form.workspacePath)
        .map(item => normalizeDataSourcePath(item))
        .filter(Boolean);
}

function getPublicationDataSourcePaths(item) {
    const rawSourcePaths = Array.isArray(item?.metadata?.sourcePaths) && item.metadata.sourcePaths.length
        ? item.metadata.sourcePaths
        : normalizeListInput(item?.metadata?.sourcePath || item?.metadata?.workspacePath || item?.publishPath || '');
    return rawSourcePaths
        .map(item => normalizeDataSourcePath(item))
        .filter(Boolean);
}

function getPublicationSourceTarget(item) {
    const sourceMode = item?.metadata?.sourceMode || (item?.metadata?.taskId ? 'task' : 'manual');
    if (sourceMode === 'datasource') {
        const paths = getPublicationDataSourcePaths(item);
        return paths.length ? paths.join(', ') : '-';
    }
    return normalizeWorkspacePath(item?.metadata?.workspacePath || item?.publishPath || '') || '-';
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

function getPublicationStatusBadgeClass(item) {
    const status = String(item?.status || '').toLowerCase();
    if (status === 'failed') return 'is-danger';
    if (status === 'draft') return 'is-warning';
    return isPublicationEnabled(item) ? 'is-success' : 'is-muted';
}

function getPublicationVisibilityBadgeClass(item) {
    return String(item?.metadata?.visibility || '').toLowerCase() === 'private' ? 'is-private' : 'is-shared';
}

function getPublicationVisibilityBadgeLabel(item) {
    return String(item?.metadata?.visibility || '').toLowerCase() === 'private' ? '私有' : '公共';
}

function getPublishMethodLabel(publishType, publishMethod) {
    const normalized = String(publishMethod || '').trim().toLowerCase();
    if (GEOSERVER_METHODS.includes(normalized)) {
        return '数据源影像发布';
    }
    if (normalized === 'nginx-static') {
        if (publishType === 'terrain') return 'Quantized Mesh';
        if (publishType === '3dtiles') return '3D Tiles 服务';
        if (publishType === 'vector') return 'XYZ 服务';
        return 'XYZ 服务';
    }
    const option = (publishMethodCatalog[publishType] || []).find(item => item.value === publishMethod);
    return option?.label || publishMethod || '-';
}

function getPublicationCategoryLine(item) {
    return [
        getPublishTypeLabel(item?.publishType),
        getPublishMethodLabel(item?.publishType, item?.metadata?.publishMethod || item?.publishMethod)
    ].filter(Boolean).join(' / ');
}

function getPublicationUpdatedTime(item) {
    return formatDateTime(item?.updatedAt || item?.publishedAt || item?.createdAt);
}

function getPublicationPublishedTime(item) {
    return formatDateTime(item?.publishedAt || item?.createdAt);
}

function getPublicationTileSchemeLabel(item) {
    const method = String(item?.metadata?.publishMethod || item?.publishMethod || '').trim().toLowerCase();
    if (method === 'wmts' || method === 'xyz') return 'XYZ';
    if (method === 'tms') return 'TMS';
    return getSourceTileScheme(item);
}

function getPublicationCopyUrl(item) {
    const merged = getMergedPublication(item);
    return getPrimaryPublicationUrl(merged) || getSecondaryPublicationUrl(merged) || '';
}

function getDefaultPublishMethodForType(publishType) {
    const options = publishMethodCatalog[publishType] || [];
    return options[0]?.value || 'wmts';
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

function handlePublicationMenu(command, item) {
    if (command === 'edit') {
        editPublication(item);
        return;
    }

    if (command === 'toggle') {
        togglePublicationStatus(item, !isPublicationEnabled(item));
        return;
    }

    if (command === 'delete') {
        removePublication(item);
    }
}

function openPublicationDetail(item) {
    detailPublication.value = item || null;
    detailVisible.value = true;
    loadPublicationDetail(item?.publicationId);
}

function closePublicationDetail() {
    detailVisible.value = false;
    detailPublication.value = null;
    detailLoading.value = false;
}

function openPublicationPreview(item) {
    const merged = getMergedPublication(item || detailPublication.value);
    detailPublication.value = toPreviewPublication(merged || item || detailPublication.value);
    previewVisible.value = true;
    if (item?.publicationId && !(merged?.accessUrl || merged?.launchUrl || merged?.browserUrl)) {
        loadPublicationDetail(item.publicationId);
    }
}

async function loadPublicationDetail(publicationId) {
    const normalizedId = String(publicationId || '').trim();
    if (!normalizedId) return;
    detailLoading.value = true;
    try {
        const response = await api.getPublication(normalizedId);
        const publication = response?.data?.publication || detailPublication.value;
        if (publication) {
            publicationDetails.value = {
                ...publicationDetails.value,
                [normalizedId]: publication
            };
        }
        detailPublication.value = publication;
    } catch (error) {
        pushToast(`发布详情加载失败: ${error.message}`, 'error', 4500);
    } finally {
        detailLoading.value = false;
    }
}

function getVectorPublicationKind(publishMethod) {
    const normalizedMethod = String(publishMethod || '').trim().toLowerCase();
    if (VECTOR_MVT_METHODS.includes(normalizedMethod)) return 'mvt';
    if (VECTOR_GEOJSON_METHODS.includes(normalizedMethod)) return 'geojson';
    return '';
}

function getVectorSourceLayerHint(item) {
    const vectorLayers = item?.vectorPublication?.vectorLayers || item?.metadata?.vectorLayers || item?.customMetadata?.vectorLayers || [];
    if (Array.isArray(vectorLayers) && vectorLayers.length && vectorLayers[0]?.id) {
        return String(vectorLayers[0].id).trim();
    }
    return 'source-layer-name';
}

function getSourceTileScheme(item) {
    const raw = String(
        item?.metadata?.sourceTileScheme
        || item?.customMetadata?.sourceTileScheme
        || item?.sourceTileScheme
        || ''
    ).trim().toLowerCase();
    if (raw === 'google' || raw === 'xyz') return 'XYZ';
    return 'TMS';
}

function formatBounds(bounds) {
    if (!Array.isArray(bounds) || bounds.length !== 4) return '-';
    return bounds.map(value => Number(value).toFixed(6)).join(', ');
}

function getPublicationGuide(item) {
    if (!item) {
        return {
            endpoints: [],
            notes: [],
            concepts: []
        };
    }

    const publishMethod = String(item?.publishMethod || item?.metadata?.publishMethod || '').toLowerCase();
    const vectorKind = getVectorPublicationKind(publishMethod);
    const endpoints = [];
    const notes = [];
    const concepts = [];
    const metadataRows = [];

    if (item.browserUrl) {
        endpoints.push({
            key: 'browser',
            label: '浏览器预览',
            url: normalizeDisplayUrl(item.browserUrl),
            href: resolveInteractiveUrl(item.browserUrl),
            description: '直接在浏览器打开，用于查看已发布内容或入口文件。'
        });
    }

    if (vectorKind) {
        const vectorPublication = item?.vectorPublication || {};
        metadataRows.push({
            key: 'vector-kind',
            label: '矢量格式',
            value: vectorKind === 'mvt' ? 'MVT / PBF' : 'GeoJSON Tile'
        });
        metadataRows.push({
            key: 'vector-zoom',
            label: '层级范围',
            value: vectorPublication.minzoom !== undefined && vectorPublication.maxzoom !== undefined
                ? `${vectorPublication.minzoom} - ${vectorPublication.maxzoom}`
                : '-'
        });
        metadataRows.push({
            key: 'vector-bounds',
            label: '数据范围',
            value: formatBounds(vectorPublication.bounds)
        });
        metadataRows.push({
            key: 'vector-layer',
            label: 'source-layer',
            value: getVectorSourceLayerHint(item)
        });
        metadataRows.push({
            key: 'vector-scheme',
            label: '行号规则',
            value: getSourceTileScheme(item)
        });

        if (item.launchUrl) {
            endpoints.push({
                key: 'tilejson',
                label: 'TileJSON',
                url: normalizeDisplayUrl(item.launchUrl),
                href: resolveInteractiveUrl(item.launchUrl),
                description: vectorKind === 'mvt'
                    ? '矢量发布入口。MapLibre 优先使用这个地址。'
                    : '矢量瓦片描述文件，可用于查看层级、范围和模板地址。'
            });
        }
        if (item.accessUrl) {
            endpoints.push({
                key: 'xyz',
                label: 'XYZ 模板',
                url: normalizeDisplayUrl(item.accessUrl),
                href: resolveInteractiveUrl(item.accessUrl),
                description: vectorKind === 'mvt'
                    ? '按 {z}/{x}/{y} 请求 PBF 瓦片。OpenLayers 常直接使用这个地址。'
                    : '按 {z}/{x}/{y} 请求 GeoJSON 瓦片，适合调试或小数据量使用。'
            });
        }
        if (item.sampleUrl && item.sampleUrl !== item.launchUrl && item.sampleUrl !== item.accessUrl && item.sampleUrl !== item.browserUrl) {
            endpoints.push({
                key: 'sample',
                label: '示例瓦片',
                url: normalizeDisplayUrl(item.sampleUrl),
                href: resolveInteractiveUrl(item.sampleUrl),
                description: '用于直接验证某一级某一块瓦片是否可访问。'
            });
        }

        if (vectorKind === 'mvt') {
            notes.push('二维矢量正式发布优先使用 MVT。');
            notes.push('程序接入时可直接使用 TileJSON，或按 XYZ 模板请求 PBF 瓦片。');
            notes.push('预览按钮可直接检查当前发布是否能正常出图。');
            concepts.push({
                title: 'MVT 是什么',
                text: 'MVT 是二进制矢量瓦片格式，体积更小、客户端支持更广，适合正式发布。'
            });
        } else {
            notes.push('GeoJSON 瓦片更适合调试、小数据量或兼容用途。');
            notes.push('正式发布如需更高性能，建议改发 MVT。');
            notes.push('预览按钮可直接检查 GeoJSON 瓦片是否按层级正常返回。');
            concepts.push({
                title: 'GeoJSON 瓦片适用场景',
                text: 'GeoJSON 瓦片可读性高，但体积和客户端生态都不如 MVT，更适合调试和小规模数据。'
            });
        }
    } else if (publishMethod === 'wmts' || publishMethod.includes('geoserver')) {
        if (item.launchUrl) {
            endpoints.push({
                key: 'capabilities',
                label: 'Capabilities',
                url: normalizeDisplayUrl(item.launchUrl),
                href: resolveInteractiveUrl(item.launchUrl),
                description: '地图服务元数据入口，GIS 客户端一般先读取这个地址。'
            });
        }
        if (item.sampleUrl) {
            endpoints.push({
                key: 'tiles',
                label: '示例瓦片',
                url: normalizeDisplayUrl(item.sampleUrl),
                href: resolveInteractiveUrl(item.sampleUrl),
                description: '用于直接验证服务是否能稳定返回瓦片。'
            });
        }
        if (item.accessUrl && item.accessUrl !== item.launchUrl) {
            endpoints.push({
                key: 'service',
                label: '服务地址',
                url: normalizeDisplayUrl(item.accessUrl),
                href: resolveInteractiveUrl(item.accessUrl),
                description: '服务访问入口。'
            });
        }

        notes.push('GIS 客户端优先加载 Capabilities。');
        notes.push('浏览器直接验证时，可先打开“示例瓦片”。');
        metadataRows.push({
            key: 'wmts-scheme',
            label: '行号规则',
            value: 'XYZ / EPSG:3857'
        });
    } else {
        if (item.launchUrl && item.launchUrl !== item.browserUrl && item.launchUrl !== item.accessUrl) {
            endpoints.push({
                key: 'launch',
                label: '程序入口',
                url: normalizeDisplayUrl(item.launchUrl),
                href: resolveInteractiveUrl(item.launchUrl),
                description: '给客户端或前端程序使用的入口地址。'
            });
        }
        if (item.accessUrl) {
            endpoints.push({
                key: 'access',
                label: '访问地址',
                url: normalizeDisplayUrl(item.accessUrl),
                href: resolveInteractiveUrl(item.accessUrl),
                description: '这是当前发布记录的主要访问地址。'
            });
        }
        if (item.sampleUrl && item.sampleUrl !== item.accessUrl && item.sampleUrl !== item.browserUrl) {
            endpoints.push({
                key: 'sample',
                label: '示例地址',
                url: normalizeDisplayUrl(item.sampleUrl),
                href: resolveInteractiveUrl(item.sampleUrl),
                description: '用于快速验证发布内容。'
            });
        }
    }

    return { endpoints, notes, concepts, metadataRows };
}

const detailGuide = computed(() => getPublicationGuide(detailPublication.value));

function resetForm() {
    form.sourceMode = 'task';
    form.taskId = '';
    form.workspacePath = '';
    form.alias = '';
    form.publishType = 'imagery';
    form.publishMethod = 'wmts';
    form.seedEnabled = true;
    form.seedMinZoom = 0;
    form.seedMaxZoom = 16;
    form.enabled = true;
    form.visibility = 'public';
    form.note = '';
}

async function ensureTasksLoaded(force = false) {
    if (tasksLoading.value) return;
    if (tasksLoaded.value && !force) return;
    tasksLoading.value = true;
    try {
        const response = await api.getAllTasks({
            page: 1,
            pageSize: 500,
            status: 'completed'
        });
        tasks.value = Object.values(response?.data?.tasks || {});
        tasksLoaded.value = true;
    } catch (error) {
        pushToast(`可发布任务加载失败: ${error.message}`, 'error', 4500);
    } finally {
        tasksLoading.value = false;
    }
}

function openCreateModal() {
    editingPublicationId.value = '';
    resetForm();
    createVisible.value = true;
    ensureTasksLoaded();
}

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

function editPublication(item) {
    editingPublicationId.value = item.publicationId;
    form.sourceMode = item.metadata?.sourceMode || (item.metadata?.taskId ? 'task' : 'manual');
    form.taskId = item.metadata?.taskId || '';
    form.workspacePath = form.sourceMode === 'datasource'
        ? getPublicationDataSourcePaths(item).join(', ')
        : normalizeWorkspacePath(item.metadata?.workspacePath || item.publishPath || '');
    form.alias = item.alias || '';
    form.publishType = item.publishType || 'imagery';
    form.publishMethod = item.metadata?.publishMethod || 'wmts';
    form.seedEnabled = Boolean(item.metadata?.customMetadata?.seedEnabled ?? true);
    form.seedMinZoom = Number(item.metadata?.customMetadata?.minZoom ?? 0);
    form.seedMaxZoom = Number(item.metadata?.customMetadata?.maxZoom ?? 16);
    form.enabled = isPublicationEnabled(item);
    form.visibility = item.metadata?.visibility || 'private';
    form.note = item.metadata?.note || '';
    if (form.sourceMode === 'datasource') {
        form.publishType = DATASOURCE_PUBLISH_TYPE;
        form.publishMethod = item.metadata?.publishMethod || DATASOURCE_PUBLISH_METHOD;
    }
    createVisible.value = true;
    if (form.sourceMode === 'task') {
        ensureTasksLoaded();
    }
}

async function togglePublicationStatus(item, explicitEnabled = null) {
    const nextEnabled = explicitEnabled === null ? !isPublicationEnabled(item) : Boolean(explicitEnabled);
    try {
        await api.togglePublicationEnabled(item.publicationId, nextEnabled);
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
    if (isDatasourceMode.value) {
        form.publishType = DATASOURCE_PUBLISH_TYPE;
        form.publishMethod = DATASOURCE_PUBLISH_METHOD;
        return;
    }
    const options = publishMethodCatalog[value] || [];
    if (!options.some(item => item.value === form.publishMethod)) {
        form.publishMethod = options[0]?.value || '';
    }
}, { immediate: true });

watch(() => form.publishMethod, value => {
    const normalizedValue = String(value || '').toLowerCase();
    if (isDatasourceMode.value) {
        if (!GEOSERVER_METHODS.includes(normalizedValue)) {
            form.publishMethod = DATASOURCE_PUBLISH_METHOD;
        }
        form.publishType = DATASOURCE_PUBLISH_TYPE;
        form.taskId = '';
        return;
    }
    if (GEOSERVER_METHODS.includes(normalizedValue)) {
        form.sourceMode = 'datasource';
        form.taskId = '';
    }
});

watch(() => form.sourceMode, value => {
    if (value === 'task') {
        form.workspacePath = '';
    } else {
        form.taskId = '';
    }
    if (value === 'datasource') {
        form.publishType = DATASOURCE_PUBLISH_TYPE;
        if (!GEOSERVER_METHODS.includes(String(form.publishMethod || '').toLowerCase())) {
            form.publishMethod = DATASOURCE_PUBLISH_METHOD;
        }
    } else if (GEOSERVER_METHODS.includes(String(form.publishMethod || '').toLowerCase())) {
        form.publishMethod = getDefaultPublishMethodForType(form.publishType);
    }
});

watch(() => form.taskId, value => {
    const task = publishableTasks.value.find(item => item.taskId === value);
    if (!task) return;
    const publishHints = task.result?.publishHints || {};
    const hintedPublishType = publishHints.publishType === 'geo' ? 'vector' : publishHints.publishType;
    if (hintedPublishType && publishMethodCatalog[hintedPublishType]) {
        form.publishType = hintedPublishType;
    }
    const methodOptions = publishMethodCatalog[form.publishType] || [];
    if (publishHints.publishMethod && methodOptions.some(item => item.value === publishHints.publishMethod)) {
        form.publishMethod = publishHints.publishMethod;
    }
    if (form.alias) return;
    const path = getTaskResultPath(task);
    const pathParts = String(path || '').split('/').filter(Boolean);
    form.alias = pathParts[pathParts.length - 1] || task.taskId;
});

async function loadPublications() {
    try {
        const response = await api.listPublications({
            page: currentPage.value,
            pageSize: pageSize.value,
            includeDetails: false,
            keyword: String(keyword.value || '').trim() || undefined,
            status: String(statusFilter.value || '').trim() || undefined,
            publishType: String(publishTypeFilter.value || '').trim() || undefined
        });
        const data = response?.data || {};
        publications.value = [...(data.publications || [])].sort((a, b) => {
            const left = String(a?.publishedAt || a?.createdAt || '');
            const right = String(b?.publishedAt || b?.createdAt || '');
            return right.localeCompare(left);
        });
        totalPublications.value = Number(data.total || 0);
        currentPage.value = Number(data.page || currentPage.value);
        pageSize.value = Number(data.pageSize || pageSize.value);
    } catch (error) {
        pushToast(`发布记录加载失败: ${error.message}`, 'error', 4500);
    }
}

async function loadTasks() {
    await ensureTasksLoaded(true);
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
    if (form.sourceMode === 'datasource' && !form.workspacePath) {
        pushToast('请先选择数据源文件或目录', 'warning');
        return;
    }

    const normalizedWorkspacePath = getNormalizedSourcePath();
    const normalizedDataSourcePaths = form.sourceMode === 'datasource' ? getNormalizedDataSourcePaths() : [];
    if (form.sourceMode === 'datasource' && !normalizedDataSourcePaths.length) {
        pushToast('请至少选择一个有效的 GeoTIFF 文件或目录', 'warning');
        return;
    }
    const payload = {
        sourceMode: form.sourceMode,
        taskId: form.sourceMode === 'task' ? form.taskId : undefined,
        workspacePath: form.sourceMode === 'manual' ? normalizedWorkspacePath : undefined,
        sourcePath: form.sourceMode === 'datasource' ? normalizedWorkspacePath : undefined,
        sourcePaths: form.sourceMode === 'datasource' ? normalizedDataSourcePaths : undefined,
        publishPath: form.sourceMode === 'manual' ? normalizedWorkspacePath : undefined,
        alias: form.alias || undefined,
        publishType: form.sourceMode === 'datasource' ? DATASOURCE_PUBLISH_TYPE : form.publishType,
        publishMethod: form.sourceMode === 'datasource' ? (form.publishMethod || DATASOURCE_PUBLISH_METHOD) : (form.publishMethod || undefined),
        enabled: form.enabled,
        visibility: form.visibility,
        note: form.note || undefined,
        customMetadata: form.sourceMode === 'datasource'
            ? {
                seedEnabled: Boolean(form.seedEnabled),
                minZoom: Number(form.seedMinZoom || 0),
                maxZoom: Number(form.seedMaxZoom || 16)
            }
            : undefined
    };

    try {
        if (editingPublicationId.value) {
            await api.updatePublication(editingPublicationId.value, payload);
            pushToast('发布记录已更新', 'success');
        } else {
            await api.createPublication(payload);
            currentPage.value = 1;
            pushToast(form.sourceMode === 'datasource' ? '发布记录已创建，后台正在构建缓存' : '发布记录已创建', 'success');
        }

        createVisible.value = false;
        editingPublicationId.value = '';
        await Promise.all([loadPublications(), loadTasks()]);
    } catch (error) {
        pushToast(`${editingPublicationId.value ? '更新' : '创建'}发布记录失败: ${error.message}`, 'error', 5000);
    }
}

onMounted(async () => {
    await loadPublications();
    publicationRefreshTimer = window.setInterval(() => {
        loadPublications();
    }, 15000);
});

onBeforeUnmount(() => {
    if (publicationRefreshTimer) {
        window.clearInterval(publicationRefreshTimer);
        publicationRefreshTimer = null;
    }
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

function applyFilters() {
    currentPage.value = 1;
    loadPublications();
}
</script>

<template>
    <section class="app-view standard-page">
        <div class="page-banner">
            <div class="page-banner__meta">
                <div class="page-banner__title">发布中心</div>
                <div class="page-banner__desc">统一管理发布记录，支持按任务生成发布、手动目录发布、启停切换与生命周期维护。</div>
            </div>
            <div class="page-banner__actions publish-header-actions">
                <el-button :icon="Refresh" @click="loadPublications">刷新</el-button>
                <el-button type="primary" :icon="Plus" @click="openCreateModal">创建发布</el-button>
            </div>
        </div>

        <div class="app-scroll">
            <el-card class="standard-panel publish-panel" shadow="never">
                <div class="publish-toolbar" @keydown.capture.enter.prevent="applyFilters">
                    <el-form class="publish-filter-form" @submit.prevent="applyFilters">
                        <div class="publish-filter-item">
                            <span class="publish-filter-label">状态：</span>
                            <el-select v-model="statusFilter" clearable placeholder="全部状态" class="publish-filter-control publish-filter-status">
                                <el-option label="已启动" value="enabled" />
                                <el-option label="未启动" value="disabled" />
                                <el-option label="构建中" value="draft" />
                                <el-option label="失败" value="failed" />
                            </el-select>
                        </div>
                        <div class="publish-filter-item">
                            <span class="publish-filter-label">类型：</span>
                            <el-select v-model="publishTypeFilter" clearable placeholder="全部类型" class="publish-filter-control publish-filter-type">
                                <el-option label="地图" value="imagery" />
                                <el-option label="地形" value="terrain" />
                                <el-option label="3DTiles" value="3dtiles" />
                                <el-option label="二维矢量" value="vector" />
                            </el-select>
                        </div>
                        <div class="publish-filter-item publish-filter-item-keyword">
                            <span class="publish-filter-label">检索：</span>
                            <el-input
                                v-model="keyword"
                                clearable
                                :prefix-icon="Search"
                                placeholder="发布名称 / 路径 / 任务 / 发布方式"
                                class="publish-filter-control publish-filter-keyword"
                            />
                        </div>
                        <el-button type="primary" native-type="submit">搜索</el-button>
                    </el-form>
                </div>

                <div v-if="publications.length" class="publication-card-grid">
                    <el-card
                        v-for="row in publications"
                        :key="row.id || row.alias || row.publishPath"
                        class="publication-card"
                        shadow="never"
                    >
                        <div class="publication-card-header">
                            <button class="publication-card-title-button" type="button" @click="openPublicationDetail(row)">
                                <div class="publication-card-title">{{ row.alias || '-' }}</div>
                            </button>
                            <el-dropdown trigger="click" placement="bottom-end" @command="command => handlePublicationMenu(command, row)">
                                <button class="publication-card-more publication-card-more-inline publication-card-more-top" type="button" aria-label="更多操作">
                                    <el-icon><MoreFilled /></el-icon>
                                </button>
                                <template #dropdown>
                                    <el-dropdown-menu class="publication-card-menu">
                                        <el-dropdown-item command="edit">
                                            <el-icon><EditPen /></el-icon>
                                            <span>编辑</span>
                                        </el-dropdown-item>
                                        <el-dropdown-item command="delete" class="is-danger">
                                            <el-icon><Delete /></el-icon>
                                            <span>删除</span>
                                        </el-dropdown-item>
                                    </el-dropdown-menu>
                                </template>
                            </el-dropdown>
                        </div>

                        <div class="publication-card-summary">
                            <span class="publication-inline-text" :class="getPublicationStatusBadgeClass(row)">{{ getPublicationStatusLabel(row.status) }}</span>
                            <span class="publication-summary-separator">|</span>
                            <span class="publication-inline-text" :class="getPublicationVisibilityBadgeClass(row)">{{ getPublicationVisibilityBadgeLabel(row) }}</span>
                            <span class="publication-summary-separator">|</span>
                            <span class="publication-inline-text is-type">{{ getPublishTypeLabel(row?.publishType) }}</span>
                            <span class="publication-summary-separator">|</span>
                            <span class="publication-inline-text is-method">{{ getPublishMethodLabel(row?.publishType, row?.metadata?.publishMethod || row?.publishMethod) }}</span>
                        </div>

                        <div class="publication-card-meta">
                            <span class="publication-card-meta-item">
                                <el-icon><Clock /></el-icon>
                                <span>发布时间：{{ getPublicationPublishedTime(row) }}</span>
                                <span class="publication-meta-separator">|</span>
                                <span>更新时间：{{ getPublicationUpdatedTime(row) }}</span>
                            </span>
                        </div>

                        <div class="publication-card-toolbar">
                            <el-button size="default" class="publication-action-button" :icon="View" @click="openPublicationPreview(row)">
                                预览
                            </el-button>
                            <el-button size="default" class="publication-action-button" :icon="CopyDocument" :disabled="!getPublicationCopyUrl(row)" @click="copyPublicationUrl(getPublicationCopyUrl(row))">
                                复制地址
                            </el-button>
                            <div class="publication-card-switch-inline">
                                <span class="publication-card-switch-label">启用状态</span>
                                <el-switch
                                    :model-value="isPublicationEnabled(row)"
                                    @change="value => togglePublicationStatus(row, value)"
                                />
                            </div>
                        </div>
                    </el-card>
                </div>
                <el-empty v-else description="暂无发布记录" />

                <div class="standard-pagination">
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
            </el-card>
        </div>

        <ResizableDrawer v-model="createVisible" :title="modalTitle" :width="860" :min-width="520" :max-width="1200" destroy-on-close>
            <el-form class="publish-editor-form" label-width="110px">
                <el-form-item label="发布来源">
                    <el-radio-group v-model="form.sourceMode">
                        <el-radio-button label="task">按任务发布</el-radio-button>
                        <el-radio-button label="manual">手动目录</el-radio-button>
                        <el-radio-button label="datasource">数据源文件</el-radio-button>
                    </el-radio-group>
                </el-form-item>

                <el-form-item v-if="form.sourceMode === 'task'" label="任务结果">
                    <el-select v-model="form.taskId" filterable placeholder="请选择已完成任务" :loading="tasksLoading" :teleported="false">
                        <el-option v-for="task in publishableTasks" :key="task.taskId" :label="`${task.taskId} / ${getTaskResultPath(task)}`" :value="task.taskId" />
                    </el-select>
                    <div v-if="selectedTask" class="publish-source-preview">
                        <span>结果目录：{{ getTaskResultPath(selectedTask) }}</span>
                        <span>产物 ID：{{ selectedTask.result?.artifactId || '-' }}</span>
                        <span>开始时间：{{ formatDateTime(selectedTask.startTime) }}</span>
                    </div>
                </el-form-item>

                <el-form-item v-else-if="form.sourceMode === 'datasource'" label="数据源">
                    <div class="path-field">
                        <el-input v-model="form.workspacePath" :placeholder="dataSourcePlaceholder" />
                        <div class="path-field-actions">
                            <el-button @click="openPicker({ title: '选择影像文件', source: 'datasource', selectionMode: 'file', multiple: false, field: 'workspacePath', allowedExtensions: dataSourceAllowedExtensions })">选择文件</el-button>
                            <el-button @click="openPicker({ title: '选择影像目录', source: 'datasource', selectionMode: 'folder', multiple: false, field: 'workspacePath', allowedExtensions: [] })">选择目录</el-button>
                            <el-button @click="form.workspacePath = ''">清空</el-button>
                        </div>
                    </div>
                    <div class="publish-source-preview">
                        <span>已选项数：{{ getNormalizedDataSourcePaths().length }}</span>
                        <span>发布模式：数据源影像发布</span>
                        <span>支持单文件或整个目录，发布细节由系统自动处理。</span>
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
                    <div v-if="isDatasourceMode" class="publish-fixed-field">{{ DATASOURCE_PUBLISH_TYPE_LABEL }}</div>
                    <el-select v-else v-model="form.publishType" :teleported="false">
                        <el-option label="地图" value="imagery" />
                        <el-option label="地形" value="terrain" />
                        <el-option label="3DTiles" value="3dtiles" />
                        <el-option label="二维矢量" value="vector" />
                    </el-select>
                </el-form-item>

                <el-form-item label="发布方式">
                    <el-select v-model="form.publishMethod" :teleported="false">
                        <el-option v-for="option in publishMethodOptions" :key="option.value" :label="option.label" :value="option.value" />
                    </el-select>
                </el-form-item>

                <template v-if="isDatasourceMode">
                    <el-form-item label="发布后预热">
                        <el-switch v-model="form.seedEnabled" active-text="启动 GWC Seed" inactive-text="仅发布服务" />
                    </el-form-item>
                    <el-form-item label="Seed 层级">
                        <div class="publish-seed-range">
                            <el-input-number v-model="form.seedMinZoom" :min="0" :max="24" />
                            <span class="publish-seed-range-separator">至</span>
                            <el-input-number v-model="form.seedMaxZoom" :min="0" :max="24" />
                        </div>
                    </el-form-item>
                </template>

                <el-form-item label="可见性">
                    <div class="publish-fixed-field">公开</div>
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
        </ResizableDrawer>

        <ResizableDrawer
            v-model="detailVisible"
            title="发布详情"
            :width="920"
            :min-width="560"
            :max-width="1320"
            destroy-on-close
            @closed="closePublicationDetail"
        >
            <div v-if="detailPublication" class="detail-content">
                <div class="detail-field-list">
                    <div class="detail-field">
                        <span class="detail-field-label">发布名称</span>
                        <span class="detail-field-value">{{ detailPublication.alias || '-' }}</span>
                    </div>
                    <div class="detail-field">
                        <span class="detail-field-label">发布类型</span>
                        <span class="detail-field-value">{{ getPublishTypeLabel(detailPublication.publishType) }} / {{ getPublishMethodLabel(detailPublication.publishType, detailPublication.metadata?.publishMethod) }}</span>
                    </div>
                    <div class="detail-field">
                        <span class="detail-field-label">状态</span>
                        <span class="detail-field-value">
                            <span class="detail-status-dot" :class="getPublicationStatusBadgeClass(detailPublication)"></span>
                            {{ getPublicationStatusLabel(detailPublication.status) }}
                        </span>
                    </div>
                    <div class="detail-field">
                        <span class="detail-field-label">数据源</span>
                        <span class="detail-field-value">{{ getPublicationSourceSummary(detailPublication) || (detailPublication.publishPath || '-') }}</span>
                    </div>
                    <div v-if="(detailPublication?.metadata?.sourceMode || 'manual') === 'manual'" class="detail-field">
                        <span class="detail-field-label">手动目录路径</span>
                        <span class="detail-field-value detail-field-value-mono">{{ normalizeWorkspacePath(detailPublication?.metadata?.workspacePath || detailPublication?.publishPath || '') || '-' }}</span>
                    </div>
                    <div class="detail-field">
                        <span class="detail-field-label">切片文件/文件夹</span>
                        <span class="detail-field-value detail-field-value-mono">{{ getPublicationSourceTarget(detailPublication) }}</span>
                    </div>
                </div>

                <div v-if="detailGuide.metadataRows.length" class="detail-section">
                    <div class="detail-section-title">接入参数</div>
                    <div class="detail-field-list">
                        <div
                            v-for="row in detailGuide.metadataRows"
                            :key="row.key"
                            class="detail-field"
                        >
                            <span class="detail-field-label">{{ row.label }}</span>
                            <span class="detail-field-value">{{ row.value || '-' }}</span>
                        </div>
                    </div>
                </div>

                <div class="detail-section">
                    <div class="detail-section-head">
                        <div class="detail-section-title">地址</div>
                        <el-button size="small" type="primary" plain @click="openPublicationPreview(detailPublication)">预览</el-button>
                    </div>
                    <div class="detail-endpoint-list">
                        <div
                            v-for="endpoint in detailGuide.endpoints"
                            :key="endpoint.key"
                            class="detail-endpoint"
                        >
                            <div class="detail-endpoint-head">
                                <span class="detail-endpoint-label">{{ endpoint.label }}</span>
                                <el-button size="small" text @click="copyPublicationUrl(endpoint.url)">复制</el-button>
                            </div>
                            <a class="detail-endpoint-url" :href="endpoint.href || endpoint.url" target="_blank" rel="noreferrer">{{ endpoint.url }}</a>
                            <p class="detail-endpoint-desc">{{ endpoint.description }}</p>
                        </div>
                    </div>
                </div>

                <div v-if="detailLoading" class="dialog-loading-text">详情刷新中...</div>
            </div>
        </ResizableDrawer>

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

        <PublicationPreviewModal
            v-model="previewVisible"
            :publication="detailPublication"
        />
    </section>
</template>

<style scoped>
.page-banner {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    padding: 20px 22px;
    border: 1px solid var(--tf-border);
    border-radius: 16px;
    background: var(--tf-surface);
}

.page-banner__title {
    color: var(--tf-text-primary);
    font-size: 18px;
    font-weight: 700;
}

.page-banner__desc {
    margin-top: 6px;
    color: var(--tf-text-secondary);
    font-size: 13px;
    line-height: 1.7;
}

.page-banner__actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.standard-panel {
    border-radius: 12px;
}

.publish-toolbar {
    margin-bottom: 18px;
}

.publish-filter-form {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    align-items: center;
}

.publish-panel {
    border-radius: 20px;
    border-color: var(--tf-border);
}

.publish-panel :deep(.el-card__body) {
    padding: 22px;
}

.publish-filter-item {
    display: flex;
    align-items: center;
    gap: 8px;
}

.publish-filter-item-keyword {
    flex: 1 1 360px;
}

.publish-filter-label {
    color: var(--tf-text-secondary);
    font-size: 13px;
    white-space: nowrap;
}

.publish-filter-control {
    min-width: 160px;
}

.publish-filter-keyword {
    width: 100%;
}

.publish-filter-keyword :deep(.el-input__wrapper),
.publish-filter-status :deep(.el-input__wrapper),
.publish-filter-type :deep(.el-input__wrapper) {
    min-height: 44px;
    border-radius: 14px;
    box-shadow: 0 0 0 1px var(--tf-border-strong) inset;
}

.publish-filter-keyword :deep(.el-input__wrapper.is-focus),
.publish-filter-status :deep(.el-input__wrapper.is-focus),
.publish-filter-type :deep(.el-input__wrapper.is-focus) {
    box-shadow: 0 0 0 1px var(--tf-accent) inset;
}

.publish-filter-form :deep(.el-button) {
    min-width: 92px;
    height: 44px;
    border-radius: 14px;
    padding: 0 18px;
    font-weight: 600;
}

.standard-pagination {
    display: flex;
    justify-content: flex-end;
    margin-top: 24px;
}

.publication-card-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
}

.publication-card {
    height: 100%;
    border-radius: 18px;
    border: 1px solid var(--tf-border);
    background: var(--tf-surface);
    transition:
        border-color 0.2s ease,
        box-shadow 0.2s ease,
        transform 0.2s ease;
}

.publication-card:hover {
    transform: translateY(-2px);
    border-color: var(--tf-border-strong);
    box-shadow: 0 14px 30px rgba(46, 84, 134, 0.08);
}

.publication-card :deep(.el-card__body) {
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 22px 24px 20px;
}

.publication-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.publication-card-summary {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    flex-wrap: nowrap;
}

.publication-inline-text {
    display: inline-block;
    font-size: 15px;
    font-weight: 700;
    line-height: 1.2;
    white-space: nowrap;
    flex: 0 0 auto;
}

.publication-summary-separator {
    color: var(--tf-border-strong);
    font-size: 14px;
    line-height: 1;
    flex: 0 0 auto;
}

.publication-inline-text.is-success {
    color: #2fa84f;
}

.publication-inline-text.is-warning {
    color: #d9911a;
}

.publication-inline-text.is-danger {
    color: #e34d59;
}

.publication-inline-text.is-muted {
    color: #8a94a6;
}

.publication-inline-text.is-private {
    color: #4a8ef7;
}

.publication-inline-text.is-shared {
    color: #ed9a1a;
}

.publication-inline-text.is-type {
    color: #2563eb;
}

.publication-inline-text.is-method {
    color: var(--tf-text-secondary);
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
}

.publication-card-more {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
}

.publication-card-title {
    font-size: 20px;
    font-weight: 700;
    line-height: 1.3;
    color: #2f6bff;
    word-break: break-word;
    text-decoration: underline;
    text-decoration-thickness: 2px;
    text-underline-offset: 4px;
    transition: color 0.18s ease, text-decoration-color 0.18s ease;
}

.publication-card-title-button {
    padding: 0;
    border: 0;
    background: transparent;
    text-align: left;
    cursor: pointer;
    align-self: flex-start;
}

.publication-card-title-button:hover .publication-card-title {
    color: #1f57e7;
    text-decoration-color: #1f57e7;
}

.publication-card-title-button:focus-visible {
    outline: 2px solid rgba(47, 107, 255, 0.28);
    outline-offset: 4px;
    border-radius: 8px;
}

.publication-card-meta {
    display: flex;
    align-items: center;
    min-height: 28px;
}

.publication-card-meta-item {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--tf-text-muted);
    font-size: 14px;
    flex-wrap: wrap;
}

.publication-card-meta-item .el-icon {
    font-size: 18px;
}

.publication-meta-separator {
    color: var(--tf-border-strong);
    font-size: 13px;
    line-height: 1;
}

.publication-card-toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--tf-border);
    flex-wrap: nowrap;
}

.publication-action-button {
    min-width: 0;
    height: 50px;
    padding: 0 22px;
    margin: 0;
    border-radius: 16px;
    border: 1px solid var(--tf-border-strong);
    color: var(--tf-text-secondary);
    background: var(--tf-surface-soft);
    font-size: 15px;
    font-weight: 600;
    box-shadow: none;
}

.publication-action-button:hover {
    border-color: var(--tf-accent);
    color: var(--tf-accent);
    background: var(--tf-accent-soft);
    box-shadow: none;
}

.publication-action-button :deep(.el-icon) {
    font-size: 18px;
}

.publication-card-menu :deep(.el-dropdown-menu__item) {
    gap: 8px;
}

.publication-card-menu :deep(.el-dropdown-menu__item.is-danger) {
    color: #ef4444;
}

.publication-card-menu :deep(.el-dropdown-menu__item.is-danger:not(.is-disabled):focus) {
    background: rgba(239, 68, 68, 0.08);
    color: #ef4444;
}

.publication-card-footer :deep(.el-switch) {
    --el-switch-on-color: #2f87f6;
    --el-switch-off-color: #d5deeb;
}

.publish-header-actions :deep(.el-button) {
    height: 46px;
    padding: 0 18px;
    border-radius: 12px;
    font-weight: 600;
}

.publish-header-actions :deep(.el-button--primary) {
    box-shadow: 0 12px 24px rgba(47, 135, 246, 0.18);
}

.publish-header-actions :deep(.el-button .el-icon) {
    font-size: 16px;
}

.publication-card-switch-inline {
    min-height: 50px;
    padding: 0 0 0 18px;
    display: inline-flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    border-left: 1px solid var(--tf-border);
    margin-left: 8px;
    flex: 0 0 auto;
}

.publication-card-switch-label {
    font-size: 15px;
    font-weight: 600;
    color: var(--tf-text-secondary);
    white-space: nowrap;
}

.publication-card-switch-inline :deep(.el-switch) {
    --el-switch-on-color: #409eff;
    --el-switch-off-color: #d5deeb;
}

.publication-card-more-inline {
    width: 50px;
    height: 50px;
    padding: 0;
    border: 1px solid var(--tf-border-strong);
    border-radius: 16px;
    background: var(--tf-surface-soft);
    color: var(--tf-text-muted);
    cursor: pointer;
    transition: all 0.18s ease;
    flex: 0 0 auto;
    box-shadow: none;
}

.publication-card-more-top {
    margin-left: auto;
}

.publication-card-more-inline:hover {
    border-color: var(--tf-accent);
    color: var(--tf-accent);
    background: var(--tf-accent-soft);
}

.publication-card-more-inline .el-icon {
    font-size: 20px;
}

.publish-panel :deep(.el-pagination) {
    width: 100%;
    justify-content: flex-end;
}

.publish-fixed-field {
    width: 100%;
    min-height: 40px;
    display: flex;
    align-items: center;
    padding: 0 12px;
    border: 1px solid var(--tf-border-strong);
    border-radius: 10px;
    background: var(--tf-surface);
    color: var(--tf-text-primary);
}

.path-field {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
}

.standard-table-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}

.publish-source-preview {
    margin-top: 10px;
    padding: 10px 12px;
    border-radius: 8px;
    border: 1px solid var(--tf-border);
    background: var(--tf-surface-soft);
    display: flex;
    flex-direction: column;
    gap: 4px;
    color: var(--tf-text-secondary);
}

.detail-content {
    display: flex;
    flex-direction: column;
    gap: 24px;
}

.detail-field-list {
    display: flex;
    flex-direction: column;
    gap: 0;
    border: 1px solid var(--tf-border);
    border-radius: 12px;
    overflow: hidden;
    background: var(--tf-surface);
}

.detail-field {
    display: flex;
    align-items: baseline;
    gap: 16px;
    padding: 13px 18px;
    border-bottom: 1px solid var(--tf-border);
}

.detail-field:last-child {
    border-bottom: none;
}

.detail-field-label {
    flex: 0 0 120px;
    font-size: 13px;
    color: var(--tf-text-muted);
    white-space: nowrap;
}

.detail-field-value {
    flex: 1;
    min-width: 0;
    font-size: 14px;
    color: var(--tf-text-primary);
    line-height: 1.6;
    word-break: break-all;
    display: flex;
    align-items: center;
    gap: 8px;
}

.detail-field-value-mono {
    font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace;
    font-size: 13px;
    color: var(--tf-text-secondary);
}

.detail-status-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}

.detail-status-dot.is-success {
    background: #2fa84f;
}

.detail-status-dot.is-warning {
    background: #d9911a;
}

.detail-status-dot.is-danger {
    background: #e34d59;
}

.detail-status-dot.is-muted {
    background: #8a94a6;
}

.detail-section {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.detail-section-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.detail-section-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--tf-text-primary);
}

.detail-endpoint-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.detail-endpoint {
    padding: 14px 18px;
    border: 1px solid var(--tf-border);
    border-radius: 12px;
    background: var(--tf-surface);
    transition: border-color 0.18s ease;
}

.detail-endpoint:hover {
    border-color: var(--tf-border-strong);
}

.detail-endpoint-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 8px;
}

.detail-endpoint-label {
    font-size: 14px;
    font-weight: 600;
    color: var(--tf-text-primary);
}

.detail-endpoint-url {
    display: inline-block;
    color: var(--tf-accent);
    text-decoration: none;
    font-size: 13px;
    line-break: anywhere;
    transition: color 0.2s ease;
}

.detail-endpoint-url:hover,
.publish-address-link:hover {
    filter: brightness(0.92);
}

.detail-endpoint-desc {
    margin: 8px 0 0;
    color: var(--tf-text-muted);
    font-size: 13px;
    line-height: 1.6;
}

.publish-address-cell {
    min-width: 0;
    display: flex;
    align-items: flex-start;
    gap: 10px;
}

.publish-address-stack {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.publish-address-line {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
}

.publish-address-line-secondary {
    opacity: 0.92;
}

.publish-address-type {
    font-size: 12px;
    color: var(--tf-text-muted);
}

.publish-address-link {
    flex: 1;
    min-width: 0;
    line-break: anywhere;
    font-size: 14px;
    line-height: 1.6;
}

.dialog-loading-text {
    color: var(--tf-text-muted);
    font-size: 12px;
}


.publish-editor-form :deep(.el-input__wrapper),
.publish-editor-form :deep(.el-textarea__inner),
.publish-editor-form :deep(.el-select__wrapper) {
    background: var(--tf-surface);
}

.publish-editor-form :deep(.el-select) {
    width: 100%;
}

.publish-editor-form :deep(.el-select__popper) {
    z-index: 3600 !important;
}

:deep(.el-textarea__inner) {
    background: var(--tf-surface);
    color: var(--tf-text-primary);
}

@media (max-width: 768px) {
    .page-banner {
        flex-direction: column;
        align-items: stretch;
    }

    .publication-card-grid {
        grid-template-columns: 1fr;
    }

    .publication-card :deep(.el-card__body) {
        min-height: unset;
    }
}

:deep(.publish-editor-dialog .el-form-item) {
    margin-bottom: 18px;
}

:deep(.publish-editor-dialog .el-switch) {
    --el-switch-on-color: #409eff;
    --el-switch-off-color: var(--tf-border-strong);
}

@media (max-width: 960px) {
    .path-field {
        flex-direction: column;
        align-items: stretch;
    }
}

@media (max-width: 760px) {
    .publication-card-summary {
        flex-wrap: wrap;
        white-space: normal;
    }

    .publication-card-toolbar {
        flex-wrap: wrap;
    }

    .publication-card-switch-inline {
        width: 100%;
        margin-left: 0;
        padding-left: 0;
        border-left: 0;
        border-top: 1px solid var(--tf-border);
        padding-top: 12px;
    }
}
</style>

<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import './styles/standard-theme.css';

import AppSidebar from './components/AppSidebar.vue';
import AppToastStack from './components/AppToastStack.vue';
import { useToastState } from './composables/useToast';
import { emitNavigationIntent, setNavigationIntent } from './utils/navigationIntent';

const DashboardView = defineAsyncComponent(() => import('./views/DashboardView.vue'));
const DatasourceView = defineAsyncComponent(() => import('./views/DatasourceView.vue'));
const MapTilesView = defineAsyncComponent(() => import('./views/MapTilesView.vue'));
const PublishView = defineAsyncComponent(() => import('./views/PublishView.vue'));
const SystemView = defineAsyncComponent(() => import('./views/SystemView.vue'));
const TasksView = defineAsyncComponent(() => import('./views/TasksView.vue'));
const TerrainTilesView = defineAsyncComponent(() => import('./views/TerrainTilesView.vue'));
const Tiles3DView = defineAsyncComponent(() => import('./views/Tiles3DView.vue'));
const ToolsView = defineAsyncComponent(() => import('./views/ToolsView.vue'));
const VectorTilesView = defineAsyncComponent(() => import('./views/VectorTilesView.vue'));
const WorkspaceView = defineAsyncComponent(() => import('./views/WorkspaceView.vue'));

const toasts = useToastState();

const sidebarCollapsed = ref(localStorage.getItem('atlasworks-sidebar-collapsed') === '1');
const themeMode = ref(localStorage.getItem('atlasworks-theme') === 'dark' ? 'dark' : 'light');
const currentSection = ref(localStorage.getItem('atlasworks-current-section') || 'dashboard');
const currentTool = ref(localStorage.getItem('atlasworks-current-tool') || 'toolNodataTiles');
const currentSystem = ref(localStorage.getItem('atlasworks-current-system') || 'systemUpdates');
const tilingGroupExpanded = ref(localStorage.getItem('atlasworks-group-tiling') !== '0');
const toolsGroupExpanded = ref(localStorage.getItem('atlasworks-group-tools') !== '0');
const systemGroupExpanded = ref(localStorage.getItem('atlasworks-group-system') !== '0');
let injectedOverlayObserver = null;

const viewMap = {
    dashboard: DashboardView,
    datasource: DatasourceView,
    'map-tiles': MapTilesView,
    'vector-tiles': VectorTilesView,
    'terrain-tiles': TerrainTilesView,
    'tiles-3d': Tiles3DView,
    workspace: WorkspaceView,
    tasks: TasksView,
    publish: PublishView,
    tools: ToolsView,
    system: SystemView
};

const currentView = computed(() => viewMap[currentSection.value] || DashboardView);
const currentViewKey = computed(() => {
    if (currentSection.value === 'tools') return `tools:${currentTool.value}`;
    if (currentSection.value === 'system') return `system:${currentSystem.value}`;
    return currentSection.value;
});
const expandedGroups = computed(() => ({
    tiling: tilingGroupExpanded.value,
    tools: toolsGroupExpanded.value,
    system: systemGroupExpanded.value
}));

const currentViewProps = computed(() => {
    if (currentSection.value === 'tools') {
        return {
            activeSubsection: currentTool.value === 'toolPreflight' ? 'toolNodataTiles' : currentTool.value,
            'onUpdate:activeSubsection': value => {
                currentTool.value = value;
            }
        };
    }

    if (currentSection.value === 'system') {
        return {
            activeSubsection: currentSystem.value,
            'onUpdate:activeSubsection': value => {
                currentSystem.value = value;
            }
        };
    }

    if (['map-tiles', 'vector-tiles', 'terrain-tiles', 'tiles-3d', 'datasource', 'workspace', 'tasks', 'publish'].includes(currentSection.value)) {
        return {
            onNavigate: navigate
        };
    }

    return {};
});

function applyThemeMode(mode) {
    document.body.classList.add('tf-app');
    document.body.classList.remove('tf-theme-light', 'tf-theme-dark');
    document.body.classList.add(mode === 'dark' ? 'tf-theme-dark' : 'tf-theme-light');
    document.documentElement.style.colorScheme = mode === 'dark' ? 'dark' : 'light';
}

function toggleThemeMode() {
    themeMode.value = themeMode.value === 'dark' ? 'light' : 'dark';
}

function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value;
}

function cleanupFloatingLayers() {
    if (typeof document === 'undefined') return;

    document.body.classList.remove('el-popup-parent--hidden');
    document.body.style.overflow = '';
    document.body.style.width = '';

    document.querySelectorAll('.modal-overlay-active').forEach(node => {
        node.remove();
    });

    document.querySelectorAll('.el-overlay').forEach(node => {
        node.remove();
    });
}

function removeInjectedOverlayNode(node) {
    if (!(node instanceof Element)) return;
    if (
        node.matches('doubao-ai-csui') ||
        node.matches('[id^="doubao-ai-translate-image-assistant"]')
    ) {
        node.remove();
        return;
    }

    node.querySelectorAll?.('doubao-ai-csui, [id^="doubao-ai-translate-image-assistant"]').forEach(child => {
        child.remove();
    });
}

function cleanupInjectedOverlays() {
    if (typeof document === 'undefined') return;
    document.querySelectorAll('doubao-ai-csui, [id^="doubao-ai-translate-image-assistant"]').forEach(node => {
        node.remove();
    });
}

function navigate(payload = {}) {
    const nextSection = payload.section || 'dashboard';
    const nextSubsection = payload.subsection || '';
    const sameSection = nextSection === currentSection.value;
    const hasIntentPayload = Boolean(
        payload?.sourceMode
        || payload?.taskId
        || payload?.workspacePath
        || payload?.alias
        || payload?.publishType
        || payload?.publishMethod
    );

    if (payload?.section && hasIntentPayload) {
        setNavigationIntent(payload);
    }

    if (nextSection !== currentSection.value) {
        cleanupFloatingLayers();
    }

    if (nextSection === 'tools') {
        currentTool.value = nextSubsection || currentTool.value || 'toolNodataTiles';
        if (currentTool.value === 'toolPreflight') {
            currentTool.value = 'toolNodataTiles';
        }
        toolsGroupExpanded.value = true;
    }

    if (nextSection === 'system') {
        currentSystem.value = nextSubsection || currentSystem.value || 'systemUpdates';
        systemGroupExpanded.value = true;
    }

    if (['map-tiles', 'vector-tiles', 'terrain-tiles', 'tiles-3d'].includes(nextSection)) {
        tilingGroupExpanded.value = true;
    }

    currentSection.value = viewMap[nextSection] ? nextSection : 'dashboard';
    if (sameSection && payload?.section && hasIntentPayload) {
        emitNavigationIntent(payload);
    }
}

function handleSidebarNavigate(payload = {}) {
    navigate(payload);
}

function handleSidebarToggleGroup(group, expanded) {
    if (group === 'tiling') {
        tilingGroupExpanded.value = typeof expanded === 'boolean' ? expanded : !tilingGroupExpanded.value;
    }
    if (group === 'tools') {
        toolsGroupExpanded.value = typeof expanded === 'boolean' ? expanded : !toolsGroupExpanded.value;
    }
    if (group === 'system') {
        systemGroupExpanded.value = typeof expanded === 'boolean' ? expanded : !systemGroupExpanded.value;
    }
}

function handleSidebarRequestExpand() {
    sidebarCollapsed.value = false;
}

function handleSidebarToggleCollapse() {
    toggleSidebar();
}

watch(sidebarCollapsed, value => {
    localStorage.setItem('atlasworks-sidebar-collapsed', value ? '1' : '0');
});

watch(themeMode, value => {
    localStorage.setItem('atlasworks-theme', value);
    applyThemeMode(value);
});

watch(currentSection, value => {
    localStorage.setItem('atlasworks-current-section', value);
});

watch(tilingGroupExpanded, value => {
    localStorage.setItem('atlasworks-group-tiling', value ? '1' : '0');
});

watch(toolsGroupExpanded, value => {
    localStorage.setItem('atlasworks-group-tools', value ? '1' : '0');
});

watch(systemGroupExpanded, value => {
    localStorage.setItem('atlasworks-group-system', value ? '1' : '0');
});

watch(currentTool, value => {
    localStorage.setItem('atlasworks-current-tool', value);
});

watch(currentSystem, value => {
    localStorage.setItem('atlasworks-current-system', value);
});

onMounted(() => {
    applyThemeMode(themeMode.value);
    cleanupFloatingLayers();
    cleanupInjectedOverlays();
    injectedOverlayObserver = new MutationObserver(mutations => {
        mutations.forEach(mutation => {
            mutation.addedNodes.forEach(node => {
                removeInjectedOverlayNode(node);
            });
        });
    });
    injectedOverlayObserver.observe(document.body, {
        childList: true,
        subtree: true
    });
    if (!viewMap[currentSection.value]) {
        currentSection.value = 'dashboard';
    }
    if (currentTool.value === 'toolPreflight') {
        currentTool.value = 'toolNodataTiles';
    }
});

onBeforeUnmount(() => {
    injectedOverlayObserver?.disconnect();
    injectedOverlayObserver = null;
});
</script>

<template>
    <el-container class="standard-shell">
        <el-aside class="standard-shell-aside" :width="sidebarCollapsed ? '72px' : '252px'">
            <AppSidebar
                :current-section="currentSection"
                :current-tool="currentTool"
                :current-system="currentSystem"
                :expanded-groups="expandedGroups"
                :collapsed="sidebarCollapsed"
                :theme-mode="themeMode"
                @navigate="handleSidebarNavigate"
                @toggle-group="handleSidebarToggleGroup"
                @request-expand="handleSidebarRequestExpand"
                @toggle-collapse="handleSidebarToggleCollapse"
                @toggle-theme="toggleThemeMode"
            />
        </el-aside>

        <el-container class="standard-shell-main">
            <el-main class="standard-shell-content">
                <div class="standard-shell-view">
                    <component :is="currentView" :key="currentViewKey" v-bind="currentViewProps" />
                </div>
            </el-main>
        </el-container>
    </el-container>

    <AppToastStack :toasts="toasts" />
</template>

<style scoped>
.standard-shell {
    height: 100vh;
    min-height: 100vh;
    background: var(--tf-shell-bg);
    overflow: hidden;
}

.standard-shell-aside {
    border-right: 1px solid var(--tf-border);
    background: var(--tf-sidebar-bg);
    overflow: hidden;
    display: flex;
    flex-direction: column;
}

.standard-shell-main {
    min-width: 0;
    min-height: 0;
    background: var(--tf-shell-bg);
    overflow: hidden;
}

.standard-shell-content {
    min-width: 0;
    min-height: 0;
    flex: 1;
    display: flex;
    flex-direction: column;
    padding: 0;
    overflow: hidden;
}

.standard-shell-view {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    padding: 16px;
    overflow: hidden;
}

.standard-shell-content :deep(.app-view) {
    flex: 1;
    min-height: 0;
}

.standard-shell-content :deep(.app-scroll) {
    overscroll-behavior: contain;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
}

@media (max-width: 860px) {
    .standard-shell-view {
        padding: 12px;
    }
}

</style>

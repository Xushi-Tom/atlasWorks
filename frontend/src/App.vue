<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';

import '../../backend/static/css/style.css';
import './styles/cosmic-theme.css';

import AppHeader from './components/AppHeader.vue';
import AppSidebar from './components/AppSidebar.vue';
import AppToastStack from './components/AppToastStack.vue';
import { useToastState } from './composables/useToast';
import DashboardView from './views/DashboardView.vue';
import DatasourceView from './views/DatasourceView.vue';
import MapTilesView from './views/MapTilesView.vue';
import TerrainTilesView from './views/TerrainTilesView.vue';
import WorkspaceView from './views/WorkspaceView.vue';
import TasksView from './views/TasksView.vue';
import PublishView from './views/PublishView.vue';
import ToolsView from './views/ToolsView.vue';
import SystemView from './views/SystemView.vue';

const currentSection = ref('dashboard');
const currentTool = ref('toolNodataTiles');
const currentSystem = ref('systemUpdates');
const sidebarCollapsed = ref(false);
const themeMode = ref(localStorage.getItem('atlasworks-theme-mode') || 'dark');
const expandedGroups = reactive({
    tools: true,
    system: false
});

const toasts = useToastState();

const sectionMeta = computed(() => {
    const catalog = {
        dashboard: {
            label: '系统仪表盘',
            caption: '统一查看平台健康、任务吞吐与资源水位。'
        },
        datasource: {
            label: '数据接入中心',
            caption: '围绕源数据目录、导入通道与元数据核验组织接入能力。'
        },
        'map-tiles': {
            label: '地图切片工位',
            caption: '面向二维地图生产组织切片构建、质量控制与任务下发。'
        },
        'terrain-tiles': {
            label: '地形切片工位',
            caption: '聚焦 terrain 构建、元数据治理与交付准备。'
        },
        workspace: {
            label: '工作空间',
            caption: '围绕交付目录组织上传补充、归档整理与发布承接。'
        },
        tasks: {
            label: '任务列表',
            caption: '追踪执行中的作业状态、阶段信息与处理日志。'
        },
        publish: {
            label: '发布中心',
            caption: '按工作空间资产组织发布记录与服务出口配置。'
        },
        tools: {
            label: '分析工具',
            caption: '围绕质量治理、结构修复、构建预检与成果整理组织生产支撑能力。'
        },
        system: {
            label: '系统管理',
            caption: '统一查看平台健康、接口清单与运行配置。'
        }
    };
    return catalog[currentSection.value] || catalog.dashboard;
});

const currentView = computed(() => {
    switch (currentSection.value) {
        case 'datasource': return DatasourceView;
        case 'map-tiles': return MapTilesView;
        case 'terrain-tiles': return TerrainTilesView;
        case 'workspace': return WorkspaceView;
        case 'tasks': return TasksView;
        case 'publish': return PublishView;
        case 'tools': return ToolsView;
        case 'system': return SystemView;
        default: return DashboardView;
    }
});

const viewProps = computed(() => {
    if (currentSection.value === 'tools') {
        return {
            activeSubsection: currentTool.value,
            'onUpdate:activeSubsection': value => {
                currentTool.value = value;
                expandedGroups.tools = true;
            }
        };
    }
    if (currentSection.value === 'system') {
        return {
            activeSubsection: currentSystem.value,
            'onUpdate:activeSubsection': value => {
                currentSystem.value = value;
                expandedGroups.system = true;
            }
        };
    }
    if (currentSection.value === 'map-tiles' || currentSection.value === 'terrain-tiles') {
        return {
            onNavigate: navigate
        };
    }
    return {};
});

function toggleGroup(group) {
    expandedGroups[group] = !expandedGroups[group];
}

function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value;
}

function expandSidebar() {
    sidebarCollapsed.value = false;
}

function applyThemeMode(mode) {
    document.body.classList.toggle('tf-theme-light', mode === 'light');
}

function toggleTheme() {
    themeMode.value = themeMode.value === 'light' ? 'dark' : 'light';
}

function navigate({ section, subsection } = {}) {
    if (!section) return;
    currentSection.value = section;
    if (section === 'tools') {
        currentTool.value = subsection || currentTool.value;
        expandedGroups.tools = true;
    }
    if (section === 'system') {
        currentSystem.value = subsection || currentSystem.value;
        expandedGroups.system = true;
    }
}

onMounted(() => {
    document.body.classList.add('tf-app');
    applyThemeMode(themeMode.value);
});

onBeforeUnmount(() => {
    document.body.classList.remove('tf-app');
    document.body.classList.remove('tf-theme-light');
});

watch(themeMode, value => {
    localStorage.setItem('atlasworks-theme-mode', value);
    applyThemeMode(value);
}, { immediate: false });
</script>

<template>
    <AppHeader
        :section-label="sectionMeta.label"
        :section-caption="sectionMeta.caption"
        :sidebar-collapsed="sidebarCollapsed"
        :theme-mode="themeMode"
        @toggle-sidebar="toggleSidebar"
        @toggle-theme="toggleTheme"
    />
    <div class="console-shell" :class="{ 'console-shell-collapsed': sidebarCollapsed }">
        <AppSidebar
            :current-section="currentSection"
            :current-tool="currentTool"
            :current-system="currentSystem"
            :expanded-groups="expandedGroups"
            :collapsed="sidebarCollapsed"
            @navigate="navigate"
            @toggle-group="toggleGroup"
            @request-expand="expandSidebar"
        />
        <main class="console-stage">
            <component :is="currentView" v-bind="viewProps" />
        </main>
    </div>
    <AppToastStack :toasts="toasts" />
</template>

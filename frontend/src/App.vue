<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import './styles/style.css';
import './styles/cosmic-theme.css';

import AppToastStack from './components/AppToastStack.vue';
import { pushToast, useToastState } from './composables/useToast';
import DashboardView from './views/DashboardView.vue';
import DatasourceView from './views/DatasourceView.vue';
import MapTilesView from './views/MapTilesView.vue';
import TerrainTilesView from './views/TerrainTilesView.vue';
import Tiles3DView from './views/Tiles3DView.vue';
import WorkspaceView from './views/WorkspaceView.vue';
import TasksView from './views/TasksView.vue';
import PublishView from './views/PublishView.vue';
import ToolsView from './views/ToolsView.vue';
import SystemView from './views/SystemView.vue';
import GameGuessNumberView from './views/GameGuessNumberView.vue';
import GameRpsView from './views/GameRpsView.vue';
import GameMemoryView from './views/GameMemoryView.vue';
import GameReactionView from './views/GameReactionView.vue';
import GameTicTacToeView from './views/GameTicTacToeView.vue';

const toasts = useToastState();
const themeMode = ref(localStorage.getItem('atlasworks-theme-mode') || 'dark');
const currentTool = ref('toolNodataTiles');
const currentSystem = ref('systemUpdates');
const windows = ref([]);
const activeWindowId = ref('');
const canvasRef = ref(null);
const startMenuHostRef = ref(null);
const zCounter = ref(100);
const windowCounter = ref(1);
const now = ref(new Date());
const startMenuOpen = ref(false);
const bgDashboardKey = ref(0);
const bgDashboardVisible = ref(false);
const eggUnlocked = ref(localStorage.getItem('atlasworks-egg-unlocked') === '1');
const eggPanelVisible = ref(false);
const eggPassword = ref('');
const eggError = ref('');
let clockTimer = null;
const WINDOW_MIN_WIDTH = 520;
const WINDOW_MIN_HEIGHT = 360;
const resizeHandleDirections = ['n', 'e', 's', 'w', 'ne', 'nw', 'se', 'sw'];

const dragState = ref({
    windowId: '',
    originX: 0,
    originY: 0,
    startX: 0,
    startY: 0
});

const resizeState = ref({
    windowId: '',
    direction: '',
    startX: 0,
    startY: 0,
    startLeft: 0,
    startTop: 0,
    startWidth: 0,
    startHeight: 0
});

const toolWindowMap = {
    'tool-nodata': 'toolNodataTiles',
    'tool-layer-json': 'toolLayerJson',
    'tool-terrain-decompress': 'toolTerrainDecompress',
    'tool-preflight': 'toolPreflight',
    'tool-tile-converter': 'toolTileConverter',
    'tool-split': 'toolSplit',
    'tool-artifacts': 'toolArtifacts'
};

const systemWindowMap = {
    'system-updates': 'systemUpdates',
    'system-routes': 'systemRoutes',
    'system-config': 'systemConfig'
};

const gameWindowMap = {
    'game-guess': GameGuessNumberView,
    'game-rps': GameRpsView,
    'game-memory': GameMemoryView,
    'game-reaction': GameReactionView,
    'game-tictactoe': GameTicTacToeView
};

const hiddenSections = new Set();

const desktopApps = [
    { section: 'dashboard', label: '系统仪表盘', subtitle: '平台状态总览', token: 'DB', tone: 'violet' },
    { section: 'datasource', label: '数据源管理', subtitle: '目录与接入', token: 'DS', tone: 'teal' },
    { section: 'map-tiles', label: '地图切片', subtitle: '二维生产工位', token: 'MP', tone: 'amber' },
    { section: 'terrain-tiles', label: '地形切片', subtitle: '地形生产工位', token: 'TR', tone: 'emerald' },
    { section: 'tiles-3d', label: '3D Tiles', subtitle: '三维生产工位', token: '3D', tone: 'indigo' },
    { section: 'workspace', label: '工作空间', subtitle: '产物目录管理', token: 'WS', tone: 'cyan' },
    { section: 'tasks', label: '任务列表', subtitle: '任务调度追踪', token: 'TK', tone: 'rose' },
    { section: 'publish', label: '发布中心', subtitle: '服务地址发布', token: 'PB', tone: 'orange' },
    { section: 'tool-nodata', label: '透明瓦片治理', subtitle: '透明瓦片识别与清理', token: 'ND', tone: 'teal' },
    { section: 'tool-layer-json', label: '地形元数据修复', subtitle: '修复 terrain 元数据', token: 'LJ', tone: 'violet' },
    { section: 'tool-terrain-decompress', label: '地形数据解压', subtitle: '解压 terrain 数据', token: 'TD', tone: 'emerald' },
    { section: 'tool-preflight', label: '生产预检', subtitle: '生产前一致性核验', token: 'PF', tone: 'amber' },
    { section: 'tool-tile-converter', label: '瓦片结构转换', subtitle: '目录结构迁移转换', token: 'CV', tone: 'indigo' },
    { section: 'tool-split', label: '大文件切分', subtitle: '超大栅格拆分', token: 'SP', tone: 'orange' },
    { section: 'tool-artifacts', label: '成果索引', subtitle: '查看已登记成果', token: 'AR', tone: 'rose' },
    { section: 'system-updates', label: '系统更新', subtitle: '容器状态与健康信息', token: 'SU', tone: 'slate' },
    { section: 'system-routes', label: 'API 路由', subtitle: '接口清单与分类', token: 'RT', tone: 'cyan' },
    { section: 'system-config', label: '系统配置', subtitle: '目录与运行配置', token: 'CF', tone: 'teal' },
    { section: 'game-guess', label: '猜数字', subtitle: '1 到 100 的热身游戏', token: 'GN', tone: 'amber' },
    { section: 'game-rps', label: '石头剪刀布', subtitle: '三局两胜快节奏对战', token: 'RPS', tone: 'rose' },
    { section: 'game-memory', label: '记忆翻牌', subtitle: '翻出所有配对卡片', token: 'MEM', tone: 'indigo' },
    { section: 'game-reaction', label: '反应测速', subtitle: '变绿瞬间立刻点击', token: 'SPD', tone: 'emerald' },
    { section: 'game-tictactoe', label: '井字棋', subtitle: '和电脑下三连棋', token: 'TTT', tone: 'violet' }
];

const startMenuSections = [
    { key: 'overview', title: '总览', sections: ['dashboard'] },
    { key: 'data', title: '数据管理', sections: ['datasource', 'workspace'] },
    { key: 'processing', title: '数据处理', sections: ['map-tiles', 'terrain-tiles', 'tiles-3d'] },
    { key: 'flow', title: '流程管理', sections: ['publish', 'tasks'] },
    { key: 'analysis', title: '分析工具', sections: ['tool-nodata', 'tool-layer-json', 'tool-terrain-decompress', 'tool-preflight', 'tool-tile-converter', 'tool-split', 'tool-artifacts'] },
    { key: 'platform', title: '平台能力', sections: ['system-updates', 'system-routes', 'system-config'] }
];

const eggGameSections = ['game-guess', 'game-rps', 'game-memory', 'game-reaction', 'game-tictactoe'];

const desktopShortcuts = [
    'dashboard',
    'tasks',
    'publish',
    'tiles-3d',
    'terrain-tiles',
    'map-tiles',
    'workspace'
];

const viewMap = {
    dashboard: DashboardView,
    datasource: DatasourceView,
    'map-tiles': MapTilesView,
    'terrain-tiles': TerrainTilesView,
    'tiles-3d': Tiles3DView,
    workspace: WorkspaceView,
    tasks: TasksView,
    publish: PublishView,
    tools: ToolsView,
    system: SystemView
};

const visibleWindows = computed(() => {
    return [...windows.value]
        .filter(windowItem => !windowItem.minimized)
        .sort((a, b) => a.zIndex - b.zIndex);
});

const taskbarWindows = computed(() => {
    return [...windows.value].sort((a, b) => (a.taskbarOrder ?? 0) - (b.taskbarOrder ?? 0));
});

const groupedStartMenuApps = computed(() => {
    return startMenuSections
        .map(group => ({
            ...group,
            apps: group.sections.map(section => appMeta(section)).filter(Boolean)
        }))
        .filter(group => group.apps.length > 0);
});

const eggGames = computed(() => {
    if (!eggUnlocked.value) return [];
    return eggGameSections
        .map(section => desktopApps.find(item => item.section === section))
        .filter(Boolean);
});

const shortcutApps = computed(() => {
    return desktopShortcuts
        .map(section => desktopApps.find(item => item.section === section))
        .filter(Boolean);
});

const currentDate = computed(() => now.value.toLocaleDateString('zh-CN'));
const currentTime = computed(() => now.value.toLocaleTimeString('zh-CN', { hour12: false }));

function resolveView(section) {
    if (toolWindowMap[section]) {
        return ToolsView;
    }
    if (systemWindowMap[section]) {
        return SystemView;
    }
    if (gameWindowMap[section]) {
        return gameWindowMap[section];
    }
    return viewMap[section] || DashboardView;
}

function getViewProps(section) {
    if (toolWindowMap[section]) {
        return {
            activeSubsection: toolWindowMap[section],
            standaloneMode: true
        };
    }
    if (systemWindowMap[section]) {
        return {
            activeSubsection: systemWindowMap[section],
            standaloneMode: true
        };
    }
    if (section === 'tools') {
        return {
            activeSubsection: currentTool.value,
            'onUpdate:activeSubsection': value => {
                currentTool.value = value;
            }
        };
    }
    if (section === 'system') {
        return {
            activeSubsection: currentSystem.value,
            'onUpdate:activeSubsection': value => {
                currentSystem.value = value;
            }
        };
    }
    if (section === 'map-tiles' || section === 'terrain-tiles' || section === 'tiles-3d') {
        return {
            onNavigate: navigateFromView
        };
    }
    return {};
}

function applyThemeMode(mode) {
    document.body.classList.toggle('tf-theme-light', mode === 'light');
}

function toggleThemeMode() {
    themeMode.value = themeMode.value === 'light' ? 'dark' : 'light';
}

function appMeta(section) {
    return desktopApps.find(item => item.section === section) || {
        section,
        label: section,
        subtitle: '',
        tone: 'cyan'
    };
}

function toneClass(section) {
    return `tone-${appMeta(section).tone || 'cyan'}`;
}

function appToken(section) {
    return appMeta(section).token || 'AW';
}

function nextZIndex() {
    zCounter.value += 1;
    return zCounter.value;
}

function clampWindowBounds(windowItem) {
    if (!canvasRef.value || windowItem.maximized) return;
    const canvasBounds = canvasRef.value.getBoundingClientRect();
    const minWidth = Math.min(WINDOW_MIN_WIDTH, canvasBounds.width);
    const minHeight = Math.min(WINDOW_MIN_HEIGHT, canvasBounds.height);
    windowItem.width = Math.min(Math.max(windowItem.width, minWidth), canvasBounds.width);
    windowItem.height = Math.min(Math.max(windowItem.height, minHeight), canvasBounds.height);
    const maxX = Math.max(0, canvasBounds.width - windowItem.width);
    const maxY = Math.max(0, canvasBounds.height - windowItem.height);
    windowItem.x = Math.min(Math.max(0, windowItem.x), maxX);
    windowItem.y = Math.min(Math.max(0, windowItem.y), maxY);
}

function focusWindow(windowId) {
    const target = windows.value.find(item => item.id === windowId);
    if (!target) return;
    activeWindowId.value = target.id;
    target.zIndex = nextZIndex();
}

function openWindow(section, subsection = '') {
    if (hiddenSections.has(section)) {
        return;
    }

    startMenuOpen.value = false;
    if (section === 'tools' && subsection) currentTool.value = subsection;
    if (section === 'system' && subsection) currentSystem.value = subsection;

    const existing = windows.value.find(item => item.section === section);
    if (existing) {
        existing.minimized = false;
        focusWindow(existing.id);
        return;
    }

    const meta = appMeta(section);
    const index = windows.value.length;
    const viewWidth = Math.max(860, window.innerWidth - 420);
    const viewHeight = Math.max(620, window.innerHeight - 220);

    const newWindow = {
        id: `window-${windowCounter.value++}`,
        section,
        title: meta.label,
        subtitle: meta.subtitle,
        x: 28 + (index % 5) * 34,
        y: 24 + (index % 4) * 28,
        width: Math.min(1200, viewWidth),
        height: Math.min(820, viewHeight),
        minimized: false,
        maximized: false,
        restoreBounds: null,
        taskbarOrder: windows.value.length ? Math.max(...windows.value.map(item => item.taskbarOrder ?? 0)) + 1 : 1,
        zIndex: nextZIndex()
    };
    windows.value.push(newWindow);
    activeWindowId.value = newWindow.id;
    clampWindowBounds(newWindow);
}

function closeWindow(windowId) {
    const index = windows.value.findIndex(item => item.id === windowId);
    if (index < 0) return;
    windows.value.splice(index, 1);
    if (activeWindowId.value === windowId) {
        const next = [...visibleWindows.value].pop();
        activeWindowId.value = next?.id || '';
    }
}

function minimizeWindow(windowId) {
    const target = windows.value.find(item => item.id === windowId);
    if (!target) return;
    target.minimized = true;
    if (activeWindowId.value === windowId) {
        const next = [...visibleWindows.value].filter(item => item.id !== windowId).pop();
        activeWindowId.value = next?.id || '';
    }
}

function toggleMaximize(windowId) {
    const target = windows.value.find(item => item.id === windowId);
    if (!target) return;
    if (!target.maximized) {
        target.restoreBounds = {
            x: target.x,
            y: target.y,
            width: target.width,
            height: target.height
        };
        target.maximized = true;
    } else {
        if (target.restoreBounds) {
            target.x = target.restoreBounds.x;
            target.y = target.restoreBounds.y;
            target.width = target.restoreBounds.width;
            target.height = target.restoreBounds.height;
        }
        target.maximized = false;
        target.restoreBounds = null;
        clampWindowBounds(target);
    }
    focusWindow(windowId);
}

function restoreWindow(windowId) {
    const target = windows.value.find(item => item.id === windowId);
    if (!target) return;
    target.minimized = false;
    focusWindow(windowId);
}

function handleTaskbarWindow(windowId) {
    const target = windows.value.find(item => item.id === windowId);
    if (!target) return;
    if (target.minimized) {
        restoreWindow(windowId);
        return;
    }
    if (activeWindowId.value === windowId) {
        minimizeWindow(windowId);
        return;
    }
    focusWindow(windowId);
}

function toggleStartMenu() {
    startMenuOpen.value = !startMenuOpen.value;
    if (!startMenuOpen.value) {
        eggPanelVisible.value = false;
        eggPassword.value = '';
        eggError.value = '';
    }
}

function handleGlobalPointerDown(event) {
    const host = startMenuHostRef.value;
    if (!host) return;
    if (host.contains(event.target)) return;
    startMenuOpen.value = false;
    eggPanelVisible.value = false;
    eggPassword.value = '';
    eggError.value = '';
}

function toggleEggPanel() {
    eggPanelVisible.value = !eggPanelVisible.value;
    eggPassword.value = '';
    eggError.value = '';
}

function unlockEgg() {
    if (eggPassword.value === 'xs666') {
        eggUnlocked.value = true;
        eggPanelVisible.value = true;
        eggPassword.value = '';
        eggError.value = '';
        localStorage.setItem('atlasworks-egg-unlocked', '1');
        pushToast('彩蛋已解锁', 'success');
        return;
    }
    eggError.value = '密码不对';
}

function isAppOpened(section) {
    return windows.value.some(item => item.section === section);
}

function windowStyle(windowItem) {
    if (windowItem.maximized) {
        return { zIndex: windowItem.zIndex };
    }
    return {
        left: `${windowItem.x}px`,
        top: `${windowItem.y}px`,
        width: `${windowItem.width}px`,
        height: `${windowItem.height}px`,
        zIndex: windowItem.zIndex
    };
}

function beginDrag(event, windowId) {
    const target = windows.value.find(item => item.id === windowId);
    if (!target || target.maximized || target.minimized) return;
    focusWindow(windowId);
    dragState.value = {
        windowId,
        originX: target.x,
        originY: target.y,
        startX: event.clientX,
        startY: event.clientY
    };
    window.addEventListener('mousemove', onDragMove);
    window.addEventListener('mouseup', endDrag);
}

function onDragMove(event) {
    const dragging = dragState.value;
    if (!dragging.windowId) return;
    const target = windows.value.find(item => item.id === dragging.windowId);
    if (!target || target.maximized) return;
    target.x = dragging.originX + (event.clientX - dragging.startX);
    target.y = dragging.originY + (event.clientY - dragging.startY);
    clampWindowBounds(target);
}

function endDrag() {
    dragState.value = { windowId: '', originX: 0, originY: 0, startX: 0, startY: 0 };
    window.removeEventListener('mousemove', onDragMove);
    window.removeEventListener('mouseup', endDrag);
}

function beginResize(event, windowId, direction) {
    event.stopPropagation();
    const target = windows.value.find(item => item.id === windowId);
    if (!target || target.maximized) return;
    focusWindow(windowId);
    resizeState.value = {
        windowId,
        direction,
        startX: event.clientX,
        startY: event.clientY,
        startLeft: target.x,
        startTop: target.y,
        startWidth: target.width,
        startHeight: target.height
    };
    window.addEventListener('mousemove', onResizeMove);
    window.addEventListener('mouseup', endResize);
}

function onResizeMove(event) {
    const state = resizeState.value;
    if (!state.windowId || !state.direction) return;
    const target = windows.value.find(item => item.id === state.windowId);
    const canvasBounds = canvasRef.value?.getBoundingClientRect();
    if (!target || !canvasBounds) return;

    const deltaX = event.clientX - state.startX;
    const deltaY = event.clientY - state.startY;
    const minWidth = Math.min(WINDOW_MIN_WIDTH, canvasBounds.width);
    const minHeight = Math.min(WINDOW_MIN_HEIGHT, canvasBounds.height);
    const direction = state.direction;

    let nextX = state.startLeft;
    let nextY = state.startTop;
    let nextWidth = state.startWidth;
    let nextHeight = state.startHeight;

    if (direction.includes('e')) {
        nextWidth = Math.min(Math.max(minWidth, state.startWidth + deltaX), canvasBounds.width - state.startLeft);
    }

    if (direction.includes('s')) {
        nextHeight = Math.min(Math.max(minHeight, state.startHeight + deltaY), canvasBounds.height - state.startTop);
    }

    if (direction.includes('w')) {
        const maxLeft = state.startLeft + state.startWidth - minWidth;
        nextX = Math.min(Math.max(0, state.startLeft + deltaX), maxLeft);
        nextWidth = state.startWidth + (state.startLeft - nextX);
    }

    if (direction.includes('n')) {
        const maxTop = state.startTop + state.startHeight - minHeight;
        nextY = Math.min(Math.max(0, state.startTop + deltaY), maxTop);
        nextHeight = state.startHeight + (state.startTop - nextY);
    }

    target.x = nextX;
    target.y = nextY;
    target.width = nextWidth;
    target.height = nextHeight;
}

function endResize() {
    resizeState.value = {
        windowId: '',
        direction: '',
        startX: 0,
        startY: 0,
        startLeft: 0,
        startTop: 0,
        startWidth: 0,
        startHeight: 0
    };
    window.removeEventListener('mousemove', onResizeMove);
    window.removeEventListener('mouseup', endResize);
}

function navigateFromView({ section, subsection } = {}) {
    if (!section) return;
    openWindow(section, subsection);
}

function handleResize() {
    windows.value.forEach(windowItem => {
        clampWindowBounds(windowItem);
    });
}

onMounted(() => {
    document.body.classList.add('tf-app');
    applyThemeMode(themeMode.value);
    clockTimer = window.setInterval(() => {
        now.value = new Date();
    }, 1000);
    window.addEventListener('resize', handleResize);
    document.addEventListener('mousedown', handleGlobalPointerDown);
});

onBeforeUnmount(() => {
    document.body.classList.remove('tf-app');
    document.body.classList.remove('tf-theme-light');
    if (clockTimer) window.clearInterval(clockTimer);
    endDrag();
    endResize();
    window.removeEventListener('resize', handleResize);
    document.removeEventListener('mousedown', handleGlobalPointerDown);
});

watch(themeMode, value => {
    localStorage.setItem('atlasworks-theme-mode', value);
    applyThemeMode(value);
});
</script>

<template>
    <div class="desktop-shell">
        <div class="desktop-workspace">
            <main ref="canvasRef" class="desktop-canvas">
                <div class="desktop-watermark">AtlasWorks</div>

                <!-- 右侧背景仪表盘 -->
                <aside v-show="bgDashboardVisible" class="desktop-bg-dashboard">
                    <DashboardView :key="bgDashboardKey" />
                </aside>
                <div class="desktop-bg-controls">
                    <button class="desktop-bg-refresh" type="button" title="刷新仪表盘" @click="bgDashboardKey++">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                        </svg>
                    </button>
                    <button class="desktop-bg-refresh" type="button" :title="bgDashboardVisible ? '收起仪表盘' : '展开仪表盘'" @click="bgDashboardVisible = !bgDashboardVisible">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="3" y="3" width="18" height="18" rx="2"/><path v-if="bgDashboardVisible" d="M9 12h6"/><path v-else d="M12 9v6M9 12h6"/>
                        </svg>
                    </button>
                </div>

                <section class="desktop-shortcuts">
                    <button
                        v-for="app in shortcutApps"
                        :key="app.section"
                        class="desktop-shortcut"
                        :class="[toneClass(app.section), { opened: isAppOpened(app.section) }]"
                        type="button"
                        @dblclick="openWindow(app.section)"
                    >
                        <span class="desktop-shortcut-token">{{ app.token }}</span>
                        <span class="desktop-shortcut-label">{{ app.label }}</span>
                    </button>
                </section>

                <article
                    v-for="windowItem in visibleWindows"
                    :key="windowItem.id"
                    class="desktop-window"
                    :class="{
                        [toneClass(windowItem.section)]: true,
                        active: activeWindowId === windowItem.id,
                        maximized: windowItem.maximized
                    }"
                    :style="windowStyle(windowItem)"
                    @mousedown="focusWindow(windowItem.id)"
                >
                    <header class="desktop-window-titlebar" @mousedown="beginDrag($event, windowItem.id)" @dblclick="toggleMaximize(windowItem.id)">
                        <div class="desktop-window-title">
                            <span class="desktop-window-appicon">{{ appToken(windowItem.section) }}</span>
                            <span class="desktop-window-title-copy">
                                <strong>{{ windowItem.title }}</strong>
                                <small>{{ windowItem.subtitle }}</small>
                            </span>
                        </div>
                        <div class="desktop-window-controls">
                            <button type="button" class="is-minimize" title="最小化" @click.stop="minimizeWindow(windowItem.id)">_</button>
                            <button type="button" class="is-maximize" :title="windowItem.maximized ? '还原' : '最大化'" @click.stop="toggleMaximize(windowItem.id)">
                                {{ windowItem.maximized ? '❐' : '□' }}
                            </button>
                            <button type="button" title="关闭" class="danger" @click.stop="closeWindow(windowItem.id)">×</button>
                        </div>
                    </header>
                    <div class="desktop-window-body">
                        <component :is="resolveView(windowItem.section)" v-bind="getViewProps(windowItem.section)" />
                    </div>
                    <template v-if="!windowItem.maximized">
                        <div
                            v-for="direction in resizeHandleDirections"
                            :key="direction"
                            class="desktop-window-resize"
                            :class="`is-${direction}`"
                            @mousedown.stop="beginResize($event, windowItem.id, direction)"
                        />
                    </template>
                </article>
            </main>
        </div>

        <footer class="desktop-taskbar">
            <div ref="startMenuHostRef" class="desktop-start-host">
                <button
                    class="desktop-start"
                    :class="{ opened: startMenuOpen }"
                    type="button"
                    @click.stop="toggleStartMenu"
                >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>
                    </svg>
                </button>
                <div v-if="startMenuOpen" class="desktop-start-menu">
                    <div class="desktop-start-groups">
                        <section
                            v-for="group in groupedStartMenuApps"
                            :key="group.key"
                            class="desktop-start-group"
                        >
                            <div class="desktop-start-group-title">{{ group.title }}</div>
                            <div class="desktop-start-group-grid">
                                <button
                                    v-for="app in group.apps"
                                    :key="app.section"
                                    class="desktop-start-item"
                                    :class="[toneClass(app.section), { opened: isAppOpened(app.section) }]"
                                    type="button"
                                    @click="openWindow(app.section)"
                                >
                                    <span class="desktop-start-item-token">{{ app.token }}</span>
                                    <span class="desktop-start-item-copy">
                                        <strong>{{ app.label }}</strong>
                                        <small>{{ app.subtitle }}</small>
                                    </span>
                                </button>
                            </div>
                        </section>
                        <section class="desktop-start-group">
                            <div class="desktop-start-group-head">
                                <div class="desktop-start-group-title">系统菜单</div>
                                <div class="desktop-egg-row">
                                    <button class="desktop-egg-trigger" type="button" @click="toggleEggPanel">{{ eggUnlocked ? '已解锁' : '解锁' }}</button>
                                </div>
                            </div>
                            <div v-if="!eggUnlocked && eggPanelVisible" class="desktop-egg-lock">
                                <input
                                    v-model="eggPassword"
                                    class="desktop-egg-input"
                                    type="password"
                                    placeholder="输入密码"
                                    @keyup.enter="unlockEgg"
                                >
                                <button class="desktop-egg-submit" type="button" @click="unlockEgg">解锁</button>
                            </div>
                            <div v-if="!eggUnlocked && eggError" class="desktop-egg-error">{{ eggError }}</div>
                            <div v-if="eggUnlocked" class="desktop-start-group-grid">
                                <button
                                    v-for="game in eggGames"
                                    :key="game.section"
                                    class="desktop-start-item"
                                    :class="[toneClass(game.section), { opened: isAppOpened(game.section) }]"
                                    type="button"
                                    @click="openWindow(game.section)"
                                >
                                    <span class="desktop-start-item-token">{{ game.token }}</span>
                                    <span class="desktop-start-item-copy">
                                        <strong>{{ game.label }}</strong>
                                        <small>{{ game.subtitle }}</small>
                                    </span>
                                </button>
                            </div>
                        </section>
                    </div>
                </div>
            </div>
            <div class="desktop-taskbar-windows">
                <button
                    v-for="windowItem in taskbarWindows"
                    :key="windowItem.id"
                    class="desktop-taskbar-window"
                    :class="{
                        [toneClass(windowItem.section)]: true,
                        active: activeWindowId === windowItem.id && !windowItem.minimized,
                        minimized: windowItem.minimized
                    }"
                    type="button"
                    @click="handleTaskbarWindow(windowItem.id)"
                >
                    <span class="desktop-taskbar-window-token">{{ appToken(windowItem.section) }}</span>
                    <span class="desktop-taskbar-window-label">{{ windowItem.title }}</span>
                </button>
            </div>
            <div class="desktop-taskbar-clock">
                {{ currentDate }} {{ currentTime }}
            </div>
        </footer>
    </div>
    <AppToastStack :toasts="toasts" />
</template>

<style scoped>
.desktop-shell {
    height: 100vh;
    min-height: 100vh;
    display: grid;
    grid-template-rows: minmax(0, 1fr) 46px;
    background:
        radial-gradient(circle at 15% 12%, rgba(72, 205, 255, 0.24), transparent 25%),
        radial-gradient(circle at 84% 12%, rgba(35, 134, 236, 0.22), transparent 27%),
        linear-gradient(165deg, #020916 0%, #041427 44%, #041124 100%);
}

.desktop-workspace {
    min-height: 0;
    display: flex;
    min-width: 0;
}

.desktop-canvas {
    flex: 1 1 auto;
    position: relative;
    overflow: hidden;
    min-width: 0;
    min-height: 0;
    padding: 10px;
}

.desktop-watermark {
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    font-size: clamp(34px, 6.2vw, 92px);
    letter-spacing: 3px;
    font-weight: 700;
    text-transform: lowercase;
    color: rgba(210, 241, 255, 0.08);
    text-shadow: 0 2px 18px rgba(0, 0, 0, 0.35);
    pointer-events: none;
    user-select: none;
    z-index: 1;
    white-space: nowrap;
}

/* 右侧背景仪表盘 */
.desktop-bg-dashboard {
    position: absolute;
    top: 40px;
    right: 0;
    width: 520px;
    bottom: 0;
    z-index: 1;
    opacity: 0.38;
    overflow-y: auto;
    overflow-x: hidden;
}

.desktop-bg-refresh {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 3;
    width: 28px;
    height: 28px;
    border-radius: 8px;
    border: 1px solid rgba(74, 195, 255, 0.28);
    background: rgba(8, 21, 38, 0.72);
    color: var(--tf-accent);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    opacity: 0.6;
    transition: opacity 0.2s;
}

.desktop-bg-refresh:hover {
    opacity: 1;
    border-color: rgba(103, 240, 255, 0.5);
}

.desktop-bg-controls {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 3;
    display: flex;
    gap: 4px;
}

.desktop-bg-dashboard :deep(.product-grid-2) {
    grid-template-columns: 1fr;
}

.desktop-bg-dashboard :deep(.app-view) {
    height: 100%;
}

.desktop-bg-dashboard :deep(.section-header),
.desktop-bg-dashboard :deep(.tool-actions),
.desktop-bg-dashboard :deep(.btn) {
    display: none;
}

.desktop-shortcuts {
    position: absolute;
    left: 14px;
    top: 14px;
    z-index: 2;
    display: grid;
    gap: 10px;
    width: 118px;
}

.desktop-shortcut {
    --window-accent-rgb: 103, 240, 255;
    --window-accent-soft: rgba(var(--window-accent-rgb), 0.2);
    --window-accent-strong: rgba(var(--window-accent-rgb), 0.5);
    --window-glow: rgba(var(--window-accent-rgb), 0.18);
    min-height: 82px;
    border-radius: 12px;
    border: 1px solid var(--window-accent-soft);
    background: rgba(5, 16, 30, 0.54);
    display: grid;
    grid-template-rows: 38px auto;
    justify-items: center;
    align-content: center;
    gap: 6px;
    padding: 8px;
    text-align: center;
    color: var(--tf-text-soft);
    cursor: pointer;
}

.desktop-shortcut:hover {
    border-color: var(--window-accent-strong);
    background: rgba(11, 29, 49, 0.68);
}

.desktop-shortcut.opened {
    border-color: var(--window-accent-strong);
    box-shadow: 0 0 0 1px var(--window-glow) inset;
}

.desktop-shortcut-token {
    width: 38px;
    height: 38px;
    border-radius: 11px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid rgba(var(--window-accent-rgb), 0.32);
    color: rgb(var(--window-accent-rgb));
    background: rgba(13, 33, 56, 0.86);
    font-size: 12px;
    font-weight: 700;
}

.desktop-shortcut-label {
    font-size: 12px;
    line-height: 1.25;
}

.desktop-window {
    --window-accent-rgb: 103, 240, 255;
    --window-accent-soft: rgba(var(--window-accent-rgb), 0.26);
    --window-accent-strong: rgba(var(--window-accent-rgb), 0.44);
    --window-glow: rgba(var(--window-accent-rgb), 0.14);
    position: absolute;
    border-radius: 16px;
    border: 1px solid var(--window-accent-soft);
    background: linear-gradient(170deg, rgba(5, 16, 30, 0.95), rgba(9, 23, 40, 0.94));
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.45);
    overflow: hidden;
    backdrop-filter: blur(10px);
}

.desktop-window.active {
    border-color: var(--window-accent-strong);
    box-shadow:
        0 20px 46px rgba(0, 0, 0, 0.5),
        0 0 0 1px var(--window-glow) inset,
        0 0 24px rgba(var(--window-accent-rgb), 0.12);
}

.desktop-window.maximized {
    left: 8px !important;
    top: 8px !important;
    width: calc(100% - 16px) !important;
    height: calc(100% - 16px) !important;
}

.desktop-window-titlebar {
    height: 44px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 10px 0 14px;
    border-bottom: 1px solid rgba(var(--window-accent-rgb), 0.18);
    background: linear-gradient(90deg, rgba(9, 23, 40, 0.98), rgba(var(--window-accent-rgb), 0.12));
    cursor: move;
    user-select: none;
}

.desktop-window-title {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 10px;
}

.desktop-window-appicon {
    width: 24px;
    height: 24px;
    flex: 0 0 auto;
    border-radius: 7px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid rgba(var(--window-accent-rgb), 0.28);
    background: linear-gradient(180deg, rgba(var(--window-accent-rgb), 0.2), rgba(10, 23, 37, 0.78));
    color: rgb(var(--window-accent-rgb));
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.04em;
}

.desktop-window-title-copy {
    min-width: 0;
    display: grid;
    gap: 2px;
}

.desktop-window-title-copy strong {
    color: #f2fbff;
    font-size: 14px;
    line-height: 1.1;
}

.desktop-window-title-copy small {
    display: block;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    color: var(--tf-text-dim);
    font-size: 11px;
}

.desktop-window-controls {
    display: flex;
    align-items: center;
    gap: 6px;
}

.desktop-window-controls button {
    width: 30px;
    height: 26px;
    border-radius: 8px;
    border: 1px solid rgba(var(--window-accent-rgb), 0.2);
    background: rgba(8, 20, 36, 0.86);
    color: var(--tf-text);
    cursor: pointer;
}

.desktop-window-controls button:hover {
    border-color: var(--window-accent-strong);
    background: rgba(16, 39, 66, 0.92);
}

.desktop-window-controls button.is-minimize:hover,
.desktop-window-controls button.is-maximize:hover {
    color: #f8fbff;
}

.desktop-window-controls button.danger:hover {
    color: #ffe9ed;
    border-color: rgba(255, 103, 134, 0.56);
    background: rgba(118, 23, 45, 0.82);
}

.desktop-window-body {
    height: calc(100% - 44px);
    overflow: hidden;
}

.desktop-window-body :deep(.app-view) {
    height: 100%;
}

/* 缩放手柄 */
.desktop-window-resize {
    position: absolute;
    z-index: 10;
}

.desktop-window-resize.is-n,
.desktop-window-resize.is-s {
    left: 14px;
    right: 14px;
    height: 8px;
}

.desktop-window-resize.is-n {
    top: -2px;
    cursor: n-resize;
}

.desktop-window-resize.is-s {
    bottom: -2px;
    cursor: s-resize;
}

.desktop-window-resize.is-e,
.desktop-window-resize.is-w {
    top: 14px;
    bottom: 14px;
    width: 8px;
}

.desktop-window-resize.is-e {
    right: -2px;
    cursor: e-resize;
}

.desktop-window-resize.is-w {
    left: -2px;
    cursor: w-resize;
}

.desktop-window-resize.is-ne,
.desktop-window-resize.is-nw,
.desktop-window-resize.is-se,
.desktop-window-resize.is-sw {
    width: 16px;
    height: 16px;
}

.desktop-window-resize.is-ne {
    top: -2px;
    right: -2px;
    cursor: ne-resize;
}

.desktop-window-resize.is-nw {
    top: -2px;
    left: -2px;
    cursor: nw-resize;
}

.desktop-window-resize.is-se {
    right: -2px;
    bottom: -2px;
    cursor: se-resize;
}

.desktop-window-resize.is-sw {
    left: -2px;
    bottom: -2px;
    cursor: sw-resize;
}

.desktop-window-resize.is-se::after,
.desktop-window-resize.is-sw::after {
    content: '';
    position: absolute;
    bottom: 4px;
    width: 8px;
    height: 8px;
    border-bottom: 2px solid rgba(var(--window-accent-rgb), 0.35);
    border-radius: 1px;
}

.desktop-window-resize.is-se::after {
    right: 4px;
    border-right: 2px solid rgba(var(--window-accent-rgb), 0.35);
}

.desktop-window-resize.is-sw::after {
    left: 4px;
    border-left: 2px solid rgba(var(--window-accent-rgb), 0.35);
}

.desktop-taskbar {
    position: relative;
    display: grid;
    grid-template-columns: 80px minmax(0, 1fr) auto;
    align-items: center;
    gap: 10px;
    padding: 0 10px;
    border-top: 1px solid rgba(142, 157, 176, 0.18);
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent),
        linear-gradient(90deg, rgba(12, 17, 24, 0.98), rgba(20, 26, 36, 0.96));
}

.desktop-start-host {
    position: relative;
}

.desktop-start {
    width: 40px;
    height: 32px;
    border-radius: 9px;
    border: 1px solid rgba(154, 168, 187, 0.18);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: #d9e5f2;
    font-size: 12px;
    font-weight: 700;
    background: rgba(28, 37, 49, 0.82);
    cursor: pointer;
}

.desktop-start.opened,
.desktop-start:hover {
    border-color: rgba(192, 202, 216, 0.24);
    background: rgba(39, 49, 63, 0.94);
}

.desktop-start-menu {
    position: absolute;
    bottom: 40px;
    left: 0;
    width: min(760px, calc(100vw - 24px));
    max-height: min(70vh, 560px);
    padding: 16px;
    border-radius: 14px;
    border: 1px solid rgba(140, 162, 189, 0.22);
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.03), transparent),
        linear-gradient(160deg, rgba(7, 18, 34, 0.98), rgba(9, 24, 43, 0.97));
    box-shadow: 0 18px 36px rgba(0, 0, 0, 0.5);
    overflow-y: auto;
    z-index: 1200;
}

.desktop-start-groups {
    display: grid;
    gap: 14px;
    padding-right: 6px;
}

.desktop-start-group {
    display: grid;
    gap: 10px;
}

.desktop-start-group-title {
    padding: 0 4px;
    color: var(--tf-text-soft);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.desktop-start-group-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
}

.desktop-start-item {
    --window-accent-rgb: 103, 240, 255;
    --window-accent-soft: rgba(var(--window-accent-rgb), 0.2);
    --window-accent-strong: rgba(var(--window-accent-rgb), 0.44);
    --window-glow: rgba(var(--window-accent-rgb), 0.14);
    width: 100%;
    min-height: 74px;
    padding: 12px;
    border-radius: 11px;
    border: 1px solid var(--window-accent-soft);
    background: rgba(7, 18, 33, 0.8);
    color: var(--tf-text);
    display: grid;
    grid-template-columns: 34px minmax(0, 1fr);
    gap: 10px;
    align-items: center;
    text-align: left;
    cursor: pointer;
}

.desktop-start-item:hover {
    border-color: var(--window-accent-strong);
    background: rgba(13, 33, 56, 0.86);
}

.desktop-start-item.opened {
    border-color: var(--window-accent-strong);
    box-shadow: 0 0 0 1px var(--window-glow) inset;
}

.desktop-start-item-token {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid rgba(var(--window-accent-rgb), 0.3);
    background: rgba(11, 28, 48, 0.9);
    color: rgb(var(--window-accent-rgb));
    font-size: 12px;
    font-weight: 700;
}

.desktop-start-item-copy {
    min-width: 0;
    display: grid;
    gap: 3px;
}

.desktop-start-item-copy strong {
    font-size: 13px;
    color: var(--tf-text);
}

.desktop-start-item-copy small {
    color: var(--tf-text-dim);
    font-size: 11px;
}

.desktop-egg-row {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}

.desktop-start-group-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.desktop-egg-trigger,
.desktop-egg-submit {
    height: 30px;
    border-radius: 10px;
    border: 1px solid rgba(154, 171, 192, 0.24);
    background: rgba(20, 31, 46, 0.86);
    color: #dde7f1;
    padding: 0 12px;
    cursor: pointer;
}

.desktop-egg-trigger:hover,
.desktop-egg-submit:hover {
    border-color: rgba(201, 214, 226, 0.3);
    background: rgba(33, 46, 64, 0.94);
}

.desktop-egg-state {
    color: rgba(105, 225, 127, 0.9);
    font-size: 12px;
    font-weight: 700;
}

.desktop-egg-lock {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.desktop-egg-input {
    width: min(220px, 100%);
    height: 32px;
    border-radius: 10px;
    border: 1px solid rgba(154, 171, 192, 0.22);
    background: rgba(7, 18, 33, 0.86);
    color: var(--tf-text);
    padding: 0 12px;
    outline: none;
}

.desktop-egg-input:focus {
    border-color: rgba(103, 240, 255, 0.42);
}

.desktop-egg-error {
    color: #ff8ea2;
    font-size: 12px;
}

.desktop-taskbar-windows {
    min-width: 0;
    display: flex;
    gap: 8px;
    overflow-x: auto;
    padding-bottom: 2px;
}

.desktop-taskbar-window {
    min-width: 140px;
    max-width: 220px;
    height: 32px;
    border-radius: 10px;
    border: 1px solid rgba(151, 165, 184, 0.14);
    background: linear-gradient(180deg, rgba(31, 39, 50, 0.92), rgba(21, 28, 38, 0.94));
    color: #c7d2df;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    cursor: pointer;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.desktop-taskbar-window-token {
    width: 18px;
    height: 18px;
    flex: 0 0 auto;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 9px;
    font-weight: 800;
    color: rgb(var(--window-accent-rgb));
    background: rgba(10, 23, 37, 0.88);
    border: 1px solid rgba(var(--window-accent-rgb), 0.22);
}

.desktop-taskbar-window-label {
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
}

.desktop-taskbar-window.active {
    color: #f4f7fb;
    border-color: rgba(196, 205, 216, 0.2);
    background:
        linear-gradient(180deg, rgba(96, 106, 121, 0.96), rgba(66, 75, 89, 0.94)),
        linear-gradient(135deg, rgba(255, 255, 255, 0.08), transparent);
    box-shadow:
        0 8px 18px rgba(0, 0, 0, 0.18),
        inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.desktop-taskbar-window.minimized {
    opacity: 0.66;
}

.desktop-taskbar-clock {
    color: #bcc8d6;
    font-size: 13px;
    padding-right: 2px;
    white-space: nowrap;
}

.tone-cyan {
    --window-accent-rgb: 103, 240, 255;
}

.tone-teal {
    --window-accent-rgb: 61, 217, 186;
}

.tone-emerald {
    --window-accent-rgb: 104, 225, 126;
}

.tone-amber {
    --window-accent-rgb: 255, 189, 89;
}

.tone-orange {
    --window-accent-rgb: 255, 144, 92;
}

.tone-rose {
    --window-accent-rgb: 255, 122, 146;
}

.tone-violet {
    --window-accent-rgb: 168, 141, 255;
}

.tone-indigo {
    --window-accent-rgb: 111, 153, 255;
}

.tone-slate {
    --window-accent-rgb: 154, 171, 192;
}

@media (max-width: 1100px) {
    .desktop-shortcuts {
        width: auto;
        max-width: calc(100% - 28px);
        grid-template-columns: repeat(auto-fill, minmax(86px, 1fr));
    }

    .desktop-taskbar-clock {
        font-size: 12px;
    }

    .desktop-bg-dashboard {
        display: none;
    }

    .desktop-start-menu {
        width: min(560px, calc(100vw - 24px));
    }
}

@media (max-width: 760px) {
    .desktop-start-group-grid {
        grid-template-columns: 1fr;
    }

    .desktop-start-group-head {
        flex-direction: column;
        align-items: flex-start;
    }
}
</style>

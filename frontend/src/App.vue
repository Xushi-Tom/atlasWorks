<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import '../../backend/static/css/style.css';
import './styles/cosmic-theme.css';

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
let clockTimer = null;

const dragState = ref({
    windowId: '',
    originX: 0,
    originY: 0,
    startX: 0,
    startY: 0
});

const desktopApps = [
    { section: 'dashboard', label: '系统仪表盘', subtitle: '平台状态总览', token: 'DB' },
    { section: 'datasource', label: '数据源管理', subtitle: '目录与接入', token: 'DS' },
    { section: 'map-tiles', label: '地图切片', subtitle: '二维生产工位', token: 'MP' },
    { section: 'terrain-tiles', label: '地形切片', subtitle: '地形生产工位', token: 'TR' },
    { section: 'workspace', label: '工作空间', subtitle: '产物目录管理', token: 'WS' },
    { section: 'tasks', label: '任务列表', subtitle: '任务调度追踪', token: 'TK' },
    { section: 'publish', label: '发布中心', subtitle: '服务地址发布', token: 'PB' },
    { section: 'tools', label: '分析工具', subtitle: '质量治理工具', token: 'TL' },
    { section: 'system', label: '系统管理', subtitle: '接口与配置', token: 'SY' }
];

const desktopShortcuts = [
    'dashboard',
    'tasks',
    'publish',
    'terrain-tiles',
    'map-tiles',
    'workspace'
];

const viewMap = {
    dashboard: DashboardView,
    datasource: DatasourceView,
    'map-tiles': MapTilesView,
    'terrain-tiles': TerrainTilesView,
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
    return [...windows.value].sort((a, b) => a.zIndex - b.zIndex);
});

const shortcutApps = computed(() => {
    return desktopShortcuts
        .map(section => desktopApps.find(item => item.section === section))
        .filter(Boolean);
});

const currentDate = computed(() => now.value.toLocaleDateString('zh-CN'));
const currentTime = computed(() => now.value.toLocaleTimeString('zh-CN', { hour12: false }));

function resolveView(section) {
    return viewMap[section] || DashboardView;
}

function getViewProps(section) {
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
    if (section === 'map-tiles' || section === 'terrain-tiles') {
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
        subtitle: ''
    };
}

function nextZIndex() {
    zCounter.value += 1;
    return zCounter.value;
}

function clampWindowBounds(windowItem) {
    if (!canvasRef.value || windowItem.maximized) return;
    const canvasBounds = canvasRef.value.getBoundingClientRect();
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
}

function handleGlobalPointerDown(event) {
    const host = startMenuHostRef.value;
    if (!host) return;
    if (host.contains(event.target)) return;
    startMenuOpen.value = false;
}

function isAppOpened(section) {
    return windows.value.some(item => item.section === section);
}

function windowStyle(windowItem) {
    if (windowItem.maximized) {
        return {
            zIndex: windowItem.zIndex
        };
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
    dragState.value = {
        windowId: '',
        originX: 0,
        originY: 0,
        startX: 0,
        startY: 0
    };
    window.removeEventListener('mousemove', onDragMove);
    window.removeEventListener('mouseup', endDrag);
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
    openWindow('dashboard');
    clockTimer = window.setInterval(() => {
        now.value = new Date();
    }, 1000);
    window.addEventListener('resize', handleResize);
    document.addEventListener('mousedown', handleGlobalPointerDown);
});

onBeforeUnmount(() => {
    document.body.classList.remove('tf-app');
    document.body.classList.remove('tf-theme-light');
    if (clockTimer) {
        window.clearInterval(clockTimer);
    }
    endDrag();
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
                <section class="desktop-shortcuts">
                    <button
                        v-for="app in shortcutApps"
                        :key="app.section"
                        class="desktop-shortcut"
                        :class="{ opened: isAppOpened(app.section) }"
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
                        active: activeWindowId === windowItem.id,
                        maximized: windowItem.maximized
                    }"
                    :style="windowStyle(windowItem)"
                    @mousedown="focusWindow(windowItem.id)"
                >
                    <header class="desktop-window-titlebar" @mousedown="beginDrag($event, windowItem.id)" @dblclick="toggleMaximize(windowItem.id)">
                        <div class="desktop-window-title">
                            <strong>{{ windowItem.title }}</strong>
                            <small>{{ windowItem.subtitle }}</small>
                        </div>
                        <div class="desktop-window-controls">
                            <button type="button" title="最小化" @click.stop="minimizeWindow(windowItem.id)">_</button>
                            <button type="button" :title="windowItem.maximized ? '还原' : '最大化'" @click.stop="toggleMaximize(windowItem.id)">
                                {{ windowItem.maximized ? '❐' : '□' }}
                            </button>
                            <button type="button" title="关闭" class="danger" @click.stop="closeWindow(windowItem.id)">×</button>
                        </div>
                    </header>
                    <div class="desktop-window-body">
                        <component :is="resolveView(windowItem.section)" v-bind="getViewProps(windowItem.section)" />
                    </div>
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
                    Start
                </button>
                <div v-if="startMenuOpen" class="desktop-start-menu">
                    <button
                        v-for="app in desktopApps"
                        :key="app.section"
                        class="desktop-start-item"
                        :class="{ opened: isAppOpened(app.section) }"
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
            </div>
            <div class="desktop-taskbar-windows">
                <button
                    v-for="windowItem in taskbarWindows"
                    :key="windowItem.id"
                    class="desktop-taskbar-window"
                    :class="{
                        active: activeWindowId === windowItem.id && !windowItem.minimized,
                        minimized: windowItem.minimized
                    }"
                    type="button"
                    @click="handleTaskbarWindow(windowItem.id)"
                >
                    <span>{{ windowItem.title }}</span>
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
    right: 34px;
    bottom: 24px;
    font-size: clamp(34px, 6.2vw, 92px);
    letter-spacing: 3px;
    font-weight: 700;
    text-transform: lowercase;
    color: rgba(210, 241, 255, 0.08);
    text-shadow: 0 2px 18px rgba(0, 0, 0, 0.35);
    pointer-events: none;
    user-select: none;
    z-index: 1;
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
    min-height: 82px;
    border-radius: 12px;
    border: 1px solid rgba(74, 195, 255, 0.2);
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
    border-color: rgba(103, 240, 255, 0.44);
    background: rgba(11, 29, 49, 0.68);
}

.desktop-shortcut.opened {
    border-color: rgba(103, 240, 255, 0.5);
    box-shadow: 0 0 0 1px rgba(103, 240, 255, 0.14) inset;
}

.desktop-shortcut-token {
    width: 38px;
    height: 38px;
    border-radius: 11px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid rgba(74, 195, 255, 0.32);
    color: var(--tf-accent);
    background: rgba(13, 33, 56, 0.86);
    font-size: 12px;
    font-weight: 700;
}

.desktop-shortcut-label {
    font-size: 12px;
    line-height: 1.25;
}

.desktop-window {
    position: absolute;
    border-radius: 16px;
    border: 1px solid rgba(74, 195, 255, 0.26);
    background: linear-gradient(170deg, rgba(5, 16, 30, 0.95), rgba(9, 23, 40, 0.94));
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.45);
    overflow: hidden;
}

.desktop-window.active {
    border-color: rgba(103, 240, 255, 0.44);
    box-shadow:
        0 20px 46px rgba(0, 0, 0, 0.5),
        0 0 0 1px rgba(103, 240, 255, 0.14) inset;
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
    border-bottom: 1px solid rgba(74, 195, 255, 0.18);
    background: linear-gradient(90deg, rgba(9, 23, 40, 0.98), rgba(13, 31, 54, 0.9));
    cursor: move;
    user-select: none;
}

.desktop-window-title {
    min-width: 0;
    display: flex;
    align-items: baseline;
    gap: 8px;
}

.desktop-window-title strong {
    color: #f2fbff;
    font-size: 14px;
}

.desktop-window-title small {
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
    border: 1px solid rgba(74, 195, 255, 0.22);
    background: rgba(8, 20, 36, 0.86);
    color: var(--tf-text);
    cursor: pointer;
}

.desktop-window-controls button:hover {
    border-color: rgba(103, 240, 255, 0.44);
    background: rgba(16, 39, 66, 0.92);
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

.desktop-taskbar {
    position: relative;
    display: grid;
    grid-template-columns: 80px minmax(0, 1fr) auto;
    align-items: center;
    gap: 10px;
    padding: 0 10px;
    border-top: 1px solid rgba(74, 195, 255, 0.24);
    background: linear-gradient(90deg, rgba(4, 12, 24, 0.96), rgba(8, 21, 39, 0.94));
}

.desktop-start-host {
    position: relative;
}

.desktop-start {
    width: 70px;
    height: 32px;
    border-radius: 9px;
    border: 1px solid rgba(74, 195, 255, 0.26);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--tf-accent);
    font-size: 12px;
    font-weight: 700;
    background: rgba(8, 21, 38, 0.8);
    cursor: pointer;
}

.desktop-start.opened,
.desktop-start:hover {
    border-color: rgba(103, 240, 255, 0.42);
    background: rgba(14, 36, 60, 0.92);
}

.desktop-start-menu {
    position: absolute;
    bottom: 40px;
    left: 0;
    width: 280px;
    max-height: min(70vh, 560px);
    padding: 10px;
    border-radius: 14px;
    border: 1px solid rgba(74, 195, 255, 0.26);
    background: linear-gradient(160deg, rgba(7, 18, 34, 0.98), rgba(9, 24, 43, 0.97));
    box-shadow: 0 18px 36px rgba(0, 0, 0, 0.5);
    overflow-y: auto;
    display: grid;
    gap: 8px;
    z-index: 1200;
}

.desktop-start-item {
    width: 100%;
    min-height: 58px;
    padding: 9px 10px;
    border-radius: 11px;
    border: 1px solid rgba(74, 195, 255, 0.2);
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
    border-color: rgba(103, 240, 255, 0.44);
    background: rgba(13, 33, 56, 0.86);
}

.desktop-start-item.opened {
    border-color: rgba(103, 240, 255, 0.44);
}

.desktop-start-item-token {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid rgba(74, 195, 255, 0.3);
    background: rgba(11, 28, 48, 0.9);
    color: var(--tf-accent);
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
    border: 1px solid rgba(74, 195, 255, 0.22);
    background: rgba(8, 21, 38, 0.78);
    color: var(--tf-text-soft);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0 12px;
    cursor: pointer;
}

.desktop-taskbar-window span {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
}

.desktop-taskbar-window.active {
    color: #001827;
    border-color: transparent;
    background: linear-gradient(135deg, var(--tf-accent), var(--tf-accent-strong));
}

.desktop-taskbar-window.minimized {
    opacity: 0.72;
}

.desktop-taskbar-clock {
    color: var(--tf-text-soft);
    font-size: 13px;
    padding-right: 2px;
    white-space: nowrap;
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
}
</style>

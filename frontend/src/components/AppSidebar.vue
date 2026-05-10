<script setup>
import {
    DataAnalysis,
    Files,
    FolderOpened,
    Grid,
    Histogram,
    List,
    Location,
    Monitor,
    Picture,
    SetUp
} from '@element-plus/icons-vue';
import { computed } from 'vue';

const props = defineProps({
    currentSection: { type: String, required: true },
    currentTool: { type: String, required: true },
    currentSystem: { type: String, required: true },
    expandedGroups: { type: Object, required: true },
    collapsed: { type: Boolean, required: true }
});

const emit = defineEmits(['navigate', 'toggle-group', 'request-expand', 'toggle-collapse']);

const primaryItems = [
    { id: 'dashboard', label: '系统仪表盘', icon: Monitor },
    { id: 'datasource', label: '数据源管理', icon: FolderOpened },
    { id: 'workspace', label: '工作空间', icon: Files },
    { id: 'tasks', label: '任务列表', icon: List },
    { id: 'publish', label: '发布中心', icon: DataAnalysis }
];

const tilingItems = [
    { id: 'map-tiles', label: '地图切片', icon: Picture },
    { id: 'vector-tiles', label: '二维矢量切片', icon: Grid },
    { id: 'terrain-tiles', label: '地形切片', icon: Histogram },
    { id: 'tiles-3d', label: '3D Tiles', icon: Location }
];

const toolItems = [
    { id: 'toolNodataTiles', label: '透明瓦片治理' },
    { id: 'toolLayerJson', label: '地形元数据修复' },
    { id: 'toolTerrainDecompress', label: '地形数据解压' }
];

const systemItems = [
    { id: 'systemUpdates', label: '系统更新' },
    { id: 'systemRoutes', label: 'API 文档' }
];

const activeKey = computed(() => {
    if (props.currentSection === 'tools') return `tools:${props.currentTool}`;
    if (props.currentSection === 'system') return `system:${props.currentSystem}`;
    return props.currentSection;
});

const openedKeys = computed(() => {
    const keys = [];
    if (props.expandedGroups?.tiling) keys.push('tiling');
    if (props.expandedGroups?.tools) keys.push('tools');
    if (props.expandedGroups?.system) keys.push('system');
    return keys;
});

const menuKey = computed(() => `${props.collapsed ? '1' : '0'}:${openedKeys.value.join(',')}:${activeKey.value}`);

function onSelect(index) {
    if (index.startsWith('tools:')) {
        emit('navigate', { section: 'tools', subsection: index.slice(6) });
        return;
    }
    if (index.startsWith('system:')) {
        emit('navigate', { section: 'system', subsection: index.slice(7) });
        return;
    }
    emit('navigate', { section: index });
}

function onOpen(index) {
    emit('toggle-group', index, true);
}

function onClose(index) {
    emit('toggle-group', index, false);
}

function requestExpand() {
    if (props.collapsed) {
        emit('request-expand');
    }
}
</script>

<template>
    <div class="admin-sidebar">
        <div class="admin-sidebar__brand">
            <div class="brand-mark">AW</div>
            <div v-if="!collapsed" class="brand-copy">
                <strong>AtlasWorks</strong>
            </div>
        </div>

        <el-scrollbar class="admin-sidebar__scroll">
            <el-menu
                :key="menuKey"
                class="admin-sidebar__menu"
                :default-active="activeKey"
                :default-openeds="openedKeys"
                :collapse="collapsed"
                :collapse-transition="false"
                @select="onSelect"
                @open="onOpen"
                @close="onClose"
            >
                <el-menu-item
                    v-for="item in primaryItems"
                    :key="item.id"
                    :index="item.id"
                    @click="requestExpand"
                >
                    <el-icon><component :is="item.icon" /></el-icon>
                    <template #title>{{ item.label }}</template>
                </el-menu-item>

                <el-sub-menu index="tiling">
                    <template #title>
                        <el-icon><Picture /></el-icon>
                        <span>切片生产</span>
                    </template>
                    <el-menu-item
                        v-for="item in tilingItems"
                        :key="item.id"
                        :index="item.id"
                    >
                        <el-icon><component :is="item.icon" /></el-icon>
                        <template #title>{{ item.label }}</template>
                    </el-menu-item>
                </el-sub-menu>

                <el-sub-menu index="tools">
                    <template #title>
                        <el-icon><SetUp /></el-icon>
                        <span>分析工具</span>
                    </template>
                    <el-menu-item
                        v-for="item in toolItems"
                        :key="item.id"
                        :index="`tools:${item.id}`"
                    >
                        {{ item.label }}
                    </el-menu-item>
                </el-sub-menu>

                <el-sub-menu index="system">
                    <template #title>
                        <el-icon><SetUp /></el-icon>
                        <span>系统管理</span>
                    </template>
                    <el-menu-item
                        v-for="item in systemItems"
                        :key="item.id"
                        :index="`system:${item.id}`"
                    >
                        {{ item.label }}
                    </el-menu-item>
                </el-sub-menu>
            </el-menu>
        </el-scrollbar>

        <div class="admin-sidebar__footer">
            <el-button class="admin-sidebar__collapse" text @click="$emit('toggle-collapse')">
                {{ collapsed ? '展开菜单' : '收起菜单' }}
            </el-button>
        </div>
    </div>
</template>

<style scoped>
.admin-sidebar {
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: #ffffff;
}

.admin-sidebar__brand {
    height: 72px;
    padding: 14px 16px;
    display: flex;
    align-items: center;
    gap: 12px;
    border-bottom: 1px solid #ebeef5;
}

.brand-mark {
    width: 36px;
    height: 36px;
    border-radius: 12px;
    background: #2f87f6;
    color: #ffffff;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 700;
    flex: 0 0 36px;
}

.brand-copy {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 3px;
}

.brand-copy strong {
    color: #303133;
    font-size: 20px;
    line-height: 1.15;
}

.brand-copy span {
    color: #909399;
    font-size: 11px;
    line-height: 1.2;
}

.admin-sidebar__scroll {
    flex: 1;
    min-height: 0;
}

.admin-sidebar__menu {
    border-right: 0;
}

.admin-sidebar__footer {
    padding: 12px;
    border-top: 1px solid #ebeef5;
}

.admin-sidebar__collapse {
    width: 100%;
    justify-content: center;
    color: #606266;
}

.admin-sidebar__collapse:hover {
    color: #409eff;
}

:deep(.admin-sidebar__menu .el-menu-item),
:deep(.admin-sidebar__menu .el-sub-menu__title) {
    height: 44px;
    line-height: 44px;
    border-radius: 10px;
    margin: 4px 10px;
    width: auto;
}

:deep(.admin-sidebar__menu .el-menu-item:hover),
:deep(.admin-sidebar__menu .el-sub-menu__title:hover) {
    background: #f5f9ff;
}

:deep(.admin-sidebar__menu .el-menu-item.is-active) {
    background: #ecf5ff;
    color: #409eff;
}

:deep(.admin-sidebar__menu .el-sub-menu .el-menu-item) {
    margin-left: 18px;
    font-size: 13px;
}

:deep(.admin-sidebar__menu.el-menu--collapse .el-menu-item),
:deep(.admin-sidebar__menu.el-menu--collapse .el-sub-menu__title) {
    margin-left: 6px;
    margin-right: 6px;
}
</style>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue';

const props = defineProps({
    modelValue: { type: Boolean, required: true },
    title: { type: String, default: '' },
    width: { type: Number, default: 820 },
    minWidth: { type: Number, default: 420 },
    maxWidth: { type: Number, default: 1280 },
    destroyOnClose: { type: Boolean, default: false },
    subtitle: { type: String, default: '' }
});

const emit = defineEmits(['update:modelValue', 'closed']);

const drawerWidth = ref(props.width);
const dragging = ref(false);

let startX = 0;
let startWidth = 0;

const widthStyle = computed(() => `${drawerWidth.value}px`);
const shouldRender = computed(() => props.modelValue || !props.destroyOnClose);

function close() {
    emit('update:modelValue', false);
}

function clampWidth(nextWidth) {
    const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : props.maxWidth;
    const safeMax = Math.min(props.maxWidth, Math.max(props.minWidth, viewportWidth - 120));
    return Math.max(props.minWidth, Math.min(safeMax, nextWidth));
}

function stopDragging() {
    if (!dragging.value) return;
    dragging.value = false;
    window.removeEventListener('mousemove', handleMouseMove);
    window.removeEventListener('mouseup', stopDragging);
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
}

function handleMouseMove(event) {
    const delta = startX - event.clientX;
    drawerWidth.value = clampWidth(startWidth + delta);
}

function startDragging(event) {
    dragging.value = true;
    startX = event.clientX;
    startWidth = drawerWidth.value;
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', stopDragging);
}

watch(() => props.width, value => {
    drawerWidth.value = clampWidth(value);
}, { immediate: true });

watch(() => props.modelValue, value => {
    if (!value) {
        stopDragging();
        emit('closed');
    }
});

onBeforeUnmount(() => {
    stopDragging();
});
</script>

<template>
    <Teleport to="body">
        <div v-if="shouldRender" v-show="modelValue" class="drawer-overlay" @click.self="close">
            <aside class="drawer-shell" :style="{ width: widthStyle }" @click.stop>
                <div class="drawer-resize-handle" @mousedown.prevent="startDragging"></div>
                <header class="drawer-header">
                    <div class="drawer-header-copy">
                        <h3>{{ title }}</h3>
                        <span v-if="subtitle">{{ subtitle }}</span>
                    </div>
                    <button class="drawer-close" type="button" @click="close">×</button>
                </header>

                <section class="drawer-body">
                    <slot />
                </section>

                <footer v-if="$slots.footer" class="drawer-footer">
                    <slot name="footer" />
                </footer>
            </aside>
        </div>
    </Teleport>
</template>

<style scoped>
.drawer-overlay {
    position: fixed;
    inset: 0;
    z-index: 3000;
    background: rgba(15, 23, 42, 0.18);
    display: flex;
    justify-content: flex-end;
}

.drawer-shell {
    position: relative;
    height: 100%;
    max-width: calc(100vw - 32px);
    display: flex;
    flex-direction: column;
    background: #ffffff;
    border-left: 1px solid #e4e7ed;
    box-shadow: -12px 0 32px rgba(15, 23, 42, 0.14);
}

.drawer-resize-handle {
    position: absolute;
    left: 0;
    top: 0;
    width: 8px;
    height: 100%;
    cursor: col-resize;
    transform: translateX(-50%);
}

.drawer-header {
    padding: 16px 20px;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    border-bottom: 1px solid #ebeef5;
}

.drawer-header-copy {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.drawer-header-copy h3 {
    margin: 0;
    color: #303133;
    font-size: 18px;
    line-height: 1.3;
}

.drawer-header-copy span {
    color: #909399;
    font-size: 12px;
    line-height: 1.5;
}

.drawer-close {
    width: 32px;
    height: 32px;
    border: 1px solid #dcdfe6;
    border-radius: 8px;
    background: #ffffff;
    color: #606266;
    font-size: 18px;
    line-height: 1;
    cursor: pointer;
}

.drawer-close:hover {
    border-color: #c0d7ff;
    color: #409eff;
    background: #f5f9ff;
}

.drawer-body {
    flex: 1;
    min-height: 0;
    padding: 18px 20px;
    overflow: auto;
}

.drawer-footer {
    padding: 14px 20px 18px;
    border-top: 1px solid #ebeef5;
    display: flex;
    justify-content: flex-end;
    gap: 10px;
}
</style>

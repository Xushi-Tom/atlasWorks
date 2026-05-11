<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';

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
const visible = ref(props.modelValue);
const animating = ref(false);

let startX = 0;
let startWidth = 0;
let closeTimer = null;

const widthStyle = computed(() => `${drawerWidth.value}px`);
const shouldRender = computed(() => visible.value || !props.destroyOnClose);

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

function stopCloseTimer() {
    if (closeTimer) {
        window.clearTimeout(closeTimer);
        closeTimer = null;
    }
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
    stopCloseTimer();
    if (value) {
        visible.value = true;
        nextTick(() => {
            animating.value = true;
        });
        return;
    }
    animating.value = false;
    closeTimer = window.setTimeout(() => {
        visible.value = false;
        stopDragging();
        emit('closed');
    }, 220);
});

onBeforeUnmount(() => {
    stopCloseTimer();
    stopDragging();
});
</script>

<template>
    <Teleport to="body">
        <div v-if="shouldRender" class="drawer-overlay" :class="{ 'is-open': animating }" @click.self="close">
            <aside class="drawer-shell" :class="{ 'is-open': animating }" :style="{ width: widthStyle }" @click.stop>
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
    background: var(--tf-overlay, rgba(15, 23, 42, 0.18));
    display: flex;
    justify-content: flex-end;
    opacity: 0;
    transition: opacity 0.22s ease;
}

.drawer-overlay.is-open {
    opacity: 1;
}

.drawer-shell {
    position: relative;
    height: 100%;
    max-width: calc(100vw - 32px);
    display: flex;
    flex-direction: column;
    background: var(--tf-surface);
    border-left: 1px solid var(--tf-border);
    box-shadow: -12px 0 32px rgba(15, 23, 42, 0.14);
    transform: translateX(32px);
    opacity: 0;
    transition:
        transform 0.22s ease,
        opacity 0.22s ease;
}

.drawer-shell.is-open {
    transform: translateX(0);
    opacity: 1;
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
    border-bottom: 1px solid var(--tf-border);
}

.drawer-header-copy {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.drawer-header-copy h3 {
    margin: 0;
    color: var(--tf-text-primary);
    font-size: 18px;
    line-height: 1.3;
}

.drawer-header-copy span {
    color: var(--tf-text-muted);
    font-size: 12px;
    line-height: 1.5;
}

.drawer-close {
    width: 32px;
    height: 32px;
    border: 1px solid var(--tf-border-strong);
    border-radius: 8px;
    background: var(--tf-surface);
    color: var(--tf-text-secondary);
    font-size: 18px;
    line-height: 1;
    cursor: pointer;
}

.drawer-close:hover {
    border-color: var(--tf-accent);
    color: var(--tf-accent);
    background: var(--tf-accent-soft);
}

.drawer-body {
    flex: 1;
    min-height: 0;
    padding: 18px 20px;
    overflow: auto;
}

.drawer-footer {
    padding: 14px 20px 18px;
    border-top: 1px solid var(--tf-border);
    display: flex;
    justify-content: flex-end;
    gap: 10px;
}
</style>

<script setup>
import { computed, ref } from 'vue';

const status = ref('idle');
const message = ref('点击开始，等待面板变绿后再点击。');
const startedAt = ref(0);
const timerId = ref(null);
const bestTime = ref(null);
const currentTime = ref(null);

const padClass = computed(() => ({
    waiting: status.value === 'waiting',
    ready: status.value === 'ready',
    result: status.value === 'result'
}));

function clearRoundTimer() {
    if (timerId.value) {
        window.clearTimeout(timerId.value);
        timerId.value = null;
    }
}

function startRound() {
    clearRoundTimer();
    status.value = 'waiting';
    currentTime.value = null;
    message.value = '等待变绿，抢跑会判失败。';
    const delay = 1800 + Math.floor(Math.random() * 2200);
    timerId.value = window.setTimeout(() => {
        startedAt.value = performance.now();
        status.value = 'ready';
        message.value = '现在点。';
        timerId.value = null;
    }, delay);
}

function handlePadClick() {
    if (status.value === 'waiting') {
        clearRoundTimer();
        status.value = 'idle';
        message.value = '抢跑了，重新开始。';
        return;
    }
    if (status.value !== 'ready') return;

    const elapsed = Math.round(performance.now() - startedAt.value);
    currentTime.value = elapsed;
    bestTime.value = bestTime.value === null ? elapsed : Math.min(bestTime.value, elapsed);
    status.value = 'result';
    message.value = `这次反应 ${elapsed} ms。`;
}
</script>

<template>
    <section class="app-view">
        <div class="section-header section-header-product">
            <div>
                <h2>反应测速</h2>
                <p class="section-subtitle">等到面板变绿后立即点击，越快越好。</p>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack">
                <div class="card">
                    <div class="card-header">
                        <h3>测速区</h3>
                    </div>
                    <div class="card-body">
                        <div class="tool-actions">
                            <button class="btn btn-primary" type="button" @click="startRound">开始</button>
                        </div>
                        <button class="reaction-pad" :class="padClass" type="button" @click="handlePadClick">
                            {{ message }}
                        </button>
                        <div class="info-list game-stats">
                            <div class="info-row">
                                <span class="info-label">当前成绩</span>
                                <span class="info-value">{{ currentTime === null ? '-' : `${currentTime} ms` }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">最好成绩</span>
                                <span class="info-value">{{ bestTime === null ? '-' : `${bestTime} ms` }}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>
</template>

<style scoped>
.reaction-pad {
    width: 100%;
    min-height: 260px;
    margin-top: 18px;
    border-radius: 22px;
    border: 1px solid rgba(148, 163, 184, 0.18);
    background: linear-gradient(180deg, rgba(36, 49, 66, 0.92), rgba(20, 28, 39, 0.94));
    color: #e6eef8;
    font-size: 24px;
    font-weight: 700;
    cursor: pointer;
}

.reaction-pad.waiting {
    background: linear-gradient(180deg, rgba(144, 52, 74, 0.94), rgba(87, 24, 41, 0.94));
}

.reaction-pad.ready {
    background: linear-gradient(180deg, rgba(45, 132, 71, 0.94), rgba(27, 88, 46, 0.94));
}

.reaction-pad.result {
    background: linear-gradient(180deg, rgba(40, 90, 146, 0.94), rgba(24, 56, 95, 0.94));
}

.game-stats {
    margin-top: 18px;
}
</style>

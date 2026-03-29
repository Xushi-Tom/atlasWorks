<script setup>
import { ref } from 'vue';

const baseIcons = ['A', 'B', 'C', 'D', 'E', 'F'];

function shuffle(list) {
    const next = [...list];
    for (let index = next.length - 1; index > 0; index -= 1) {
        const target = Math.floor(Math.random() * (index + 1));
        [next[index], next[target]] = [next[target], next[index]];
    }
    return next;
}

function createBoard() {
    return shuffle([...baseIcons, ...baseIcons]).map((icon, index) => ({
        id: `${icon}-${index}`,
        icon,
        flipped: false,
        matched: false
    }));
}

const cards = ref(createBoard());
const openIndexes = ref([]);
const moves = ref(0);
const finished = ref(false);
const busy = ref(false);

function resetGame() {
    cards.value = createBoard();
    openIndexes.value = [];
    moves.value = 0;
    finished.value = false;
    busy.value = false;
}

function flipCard(index) {
    const card = cards.value[index];
    if (!card || busy.value || card.flipped || card.matched || finished.value) return;

    card.flipped = true;
    openIndexes.value.push(index);

    if (openIndexes.value.length < 2) return;

    moves.value += 1;
    const [firstIndex, secondIndex] = openIndexes.value;
    const firstCard = cards.value[firstIndex];
    const secondCard = cards.value[secondIndex];

    if (firstCard.icon === secondCard.icon) {
        firstCard.matched = true;
        secondCard.matched = true;
        openIndexes.value = [];
        finished.value = cards.value.every(item => item.matched);
        return;
    }

    busy.value = true;
    window.setTimeout(() => {
        firstCard.flipped = false;
        secondCard.flipped = false;
        openIndexes.value = [];
        busy.value = false;
    }, 650);
}
</script>

<template>
    <section class="app-view">
        <div class="section-header section-header-product">
            <div>
                <h2>记忆翻牌</h2>
                <p class="section-subtitle">找出 6 组相同卡片，步数越少越好。</p>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack">
                <div class="card">
                    <div class="card-header">
                        <h3>牌面</h3>
                    </div>
                    <div class="card-body">
                        <div class="memory-board">
                            <button
                                v-for="(card, index) in cards"
                                :key="card.id"
                                class="memory-card"
                                :class="{ flipped: card.flipped || card.matched, matched: card.matched }"
                                type="button"
                                @click="flipCard(index)"
                            >
                                <span>{{ card.flipped || card.matched ? card.icon : '?' }}</span>
                            </button>
                        </div>
                        <div class="info-list game-stats">
                            <div class="info-row">
                                <span class="info-label">步数</span>
                                <span class="info-value">{{ moves }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">已配对</span>
                                <span class="info-value">{{ cards.filter(item => item.matched).length / 2 }} / 6</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">状态</span>
                                <span class="info-value">{{ finished ? '通关' : '进行中' }}</span>
                            </div>
                        </div>
                        <div class="tool-actions game-actions">
                            <button class="btn btn-secondary" type="button" @click="resetGame">重新洗牌</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>
</template>

<style scoped>
.memory-board {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
}

.memory-card {
    min-height: 84px;
    border-radius: 16px;
    border: 1px solid rgba(111, 153, 255, 0.22);
    background: linear-gradient(180deg, rgba(18, 29, 48, 0.96), rgba(10, 18, 31, 0.94));
    color: #d7e3f4;
    font-size: 24px;
    font-weight: 700;
    cursor: pointer;
}

.memory-card.flipped {
    background: linear-gradient(180deg, rgba(29, 49, 80, 0.96), rgba(16, 28, 45, 0.94));
    border-color: rgba(111, 153, 255, 0.4);
}

.memory-card.matched {
    color: #9ff0b2;
    border-color: rgba(104, 225, 126, 0.42);
}

.game-stats,
.game-actions {
    margin-top: 18px;
}

@media (max-width: 720px) {
    .memory-board {
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }
}
</style>

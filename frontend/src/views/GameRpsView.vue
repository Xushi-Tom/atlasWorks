<script setup>
import { computed, ref } from 'vue';

const choices = [
    { id: 'rock', label: '石头' },
    { id: 'paper', label: '布' },
    { id: 'scissors', label: '剪刀' }
];

const resultMatrix = {
    rock: { rock: 'draw', paper: 'lose', scissors: 'win' },
    paper: { rock: 'win', paper: 'draw', scissors: 'lose' },
    scissors: { rock: 'lose', paper: 'win', scissors: 'draw' }
};

const playerChoice = ref('');
const computerChoice = ref('');
const roundText = ref('点击任意手势开始。');
const score = ref({ win: 0, lose: 0, draw: 0 });
const history = ref([]);

const totalRounds = computed(() => score.value.win + score.value.lose + score.value.draw);

function playRound(choice) {
    const randomChoice = choices[Math.floor(Math.random() * choices.length)].id;
    const outcome = resultMatrix[choice][randomChoice];
    playerChoice.value = choice;
    computerChoice.value = randomChoice;

    if (outcome === 'win') {
        score.value.win += 1;
        roundText.value = '这回你赢了。';
    } else if (outcome === 'lose') {
        score.value.lose += 1;
        roundText.value = '这回电脑赢了。';
    } else {
        score.value.draw += 1;
        roundText.value = '平局，再来。';
    }

    history.value.unshift(`${choices.find(item => item.id === choice)?.label} vs ${choices.find(item => item.id === randomChoice)?.label}`);
    history.value = history.value.slice(0, 8);
}

function resetGame() {
    playerChoice.value = '';
    computerChoice.value = '';
    roundText.value = '点击任意手势开始。';
    score.value = { win: 0, lose: 0, draw: 0 };
    history.value = [];
}
</script>

<template>
    <section class="app-view">
        <div class="section-header section-header-product">
            <div>
                <h2>石头剪刀布</h2>
                <p class="section-subtitle">标准三选一，适合在等待任务的时候打发半分钟。</p>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack">
                <div class="card">
                    <div class="card-header">
                        <h3>对局</h3>
                    </div>
                    <div class="card-body">
                        <div class="game-choice-row">
                            <button
                                v-for="choice in choices"
                                :key="choice.id"
                                class="btn btn-secondary game-choice-button"
                                type="button"
                                @click="playRound(choice.id)"
                            >
                                {{ choice.label }}
                            </button>
                        </div>
                        <div class="simple-info game-note">
                            <div class="placeholder-text">{{ roundText }}</div>
                        </div>
                        <div class="info-list game-stats">
                            <div class="info-row">
                                <span class="info-label">你的手势</span>
                                <span class="info-value">{{ choices.find(item => item.id === playerChoice)?.label || '-' }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">电脑手势</span>
                                <span class="info-value">{{ choices.find(item => item.id === computerChoice)?.label || '-' }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">比分</span>
                                <span class="info-value">{{ score.win }} 胜 / {{ score.lose }} 负 / {{ score.draw }} 平</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">总局数</span>
                                <span class="info-value">{{ totalRounds }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">最近对局</span>
                                <span class="info-value">{{ history.length ? history.join(' ｜ ') : '-' }}</span>
                            </div>
                        </div>
                        <div class="tool-actions game-actions">
                            <button class="btn btn-secondary" type="button" @click="resetGame">清空比分</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>
</template>

<style scoped>
.game-choice-row {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
}

.game-choice-button {
    min-width: 116px;
}

.game-note,
.game-stats,
.game-actions {
    margin-top: 18px;
}
</style>

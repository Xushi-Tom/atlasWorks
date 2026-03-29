<script setup>
import { computed, ref } from 'vue';

const board = ref(Array(9).fill(''));
const winner = ref('');
const statusText = ref('你先手，使用 X。');
const playerMark = 'X';
const computerMark = 'O';

const lines = [
    [0, 1, 2],
    [3, 4, 5],
    [6, 7, 8],
    [0, 3, 6],
    [1, 4, 7],
    [2, 5, 8],
    [0, 4, 8],
    [2, 4, 6]
];

const filledCount = computed(() => board.value.filter(Boolean).length);

function evaluateWinner() {
    for (const [a, b, c] of lines) {
        if (board.value[a] && board.value[a] === board.value[b] && board.value[a] === board.value[c]) {
            return board.value[a];
        }
    }
    return '';
}

function availableIndexes() {
    return board.value
        .map((value, index) => ({ value, index }))
        .filter(item => !item.value)
        .map(item => item.index);
}

function finishRound(mark) {
    winner.value = mark;
    if (mark === playerMark) {
        statusText.value = '你赢了。';
    } else if (mark === computerMark) {
        statusText.value = '电脑赢了。';
    } else {
        statusText.value = '平局。';
    }
}

function tryComplete(mark) {
    for (const [a, b, c] of lines) {
        const line = [board.value[a], board.value[b], board.value[c]];
        const markCount = line.filter(item => item === mark).length;
        const emptyIndex = [a, b, c].find(index => !board.value[index]);
        if (markCount === 2 && emptyIndex !== undefined) {
            return emptyIndex;
        }
    }
    return -1;
}

function computerMove() {
    if (winner.value) return;

    const winIndex = tryComplete(computerMark);
    const blockIndex = tryComplete(playerMark);
    const candidates = [
        winIndex,
        blockIndex,
        board.value[4] ? -1 : 4,
        ...[0, 2, 6, 8].filter(index => !board.value[index]),
        ...availableIndexes()
    ].filter(index => index >= 0);

    const nextIndex = candidates[0];
    if (nextIndex === undefined) {
        finishRound('draw');
        return;
    }

    board.value[nextIndex] = computerMark;
    const nextWinner = evaluateWinner();
    if (nextWinner) {
        finishRound(nextWinner);
        return;
    }
    if (availableIndexes().length === 0) {
        finishRound('draw');
        return;
    }
    statusText.value = '轮到你了。';
}

function placeMark(index) {
    if (board.value[index] || winner.value) return;
    board.value[index] = playerMark;

    const nextWinner = evaluateWinner();
    if (nextWinner) {
        finishRound(nextWinner);
        return;
    }
    if (availableIndexes().length === 0) {
        finishRound('draw');
        return;
    }

    statusText.value = '电脑思考中。';
    window.setTimeout(computerMove, 220);
}

function resetGame() {
    board.value = Array(9).fill('');
    winner.value = '';
    statusText.value = '你先手，使用 X。';
}
</script>

<template>
    <section class="app-view">
        <div class="section-header section-header-product">
            <div>
                <h2>井字棋</h2>
                <p class="section-subtitle">你是 X，电脑是 O，先连成三子获胜。</p>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack">
                <div class="card">
                    <div class="card-header">
                        <h3>棋盘</h3>
                    </div>
                    <div class="card-body">
                        <div class="simple-info">
                            <div class="placeholder-text">{{ statusText }}</div>
                        </div>
                        <div class="ttt-board">
                            <button
                                v-for="(cell, index) in board"
                                :key="index"
                                class="ttt-cell"
                                type="button"
                                @click="placeMark(index)"
                            >
                                {{ cell || '·' }}
                            </button>
                        </div>
                        <div class="info-list game-stats">
                            <div class="info-row">
                                <span class="info-label">已落子</span>
                                <span class="info-value">{{ filledCount }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">胜负</span>
                                <span class="info-value">
                                    {{ winner === 'draw' ? '平局' : (winner || '-') }}
                                </span>
                            </div>
                        </div>
                        <div class="tool-actions game-actions">
                            <button class="btn btn-secondary" type="button" @click="resetGame">重新开始</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>
</template>

<style scoped>
.ttt-board {
    margin-top: 18px;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
}

.ttt-cell {
    min-height: 96px;
    border-radius: 18px;
    border: 1px solid rgba(168, 141, 255, 0.24);
    background: linear-gradient(180deg, rgba(25, 19, 49, 0.94), rgba(15, 12, 30, 0.94));
    color: #eee7ff;
    font-size: 30px;
    font-weight: 700;
    cursor: pointer;
}

.game-stats,
.game-actions {
    margin-top: 18px;
}
</style>

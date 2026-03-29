<script setup>
import { ref } from 'vue';

function createSecret() {
    return Math.floor(Math.random() * 100) + 1;
}

const secret = ref(createSecret());
const guess = ref('');
const attempts = ref([]);
const hint = ref('输入 1 到 100 的整数开始。');
const solved = ref(false);

function resetGame() {
    secret.value = createSecret();
    guess.value = '';
    attempts.value = [];
    hint.value = '新的一局开始了。';
    solved.value = false;
}

function submitGuess() {
    const value = Number.parseInt(String(guess.value).trim(), 10);
    if (!Number.isInteger(value) || value < 1 || value > 100) {
        hint.value = '请输入 1 到 100 的整数。';
        return;
    }

    attempts.value.unshift(value);
    if (value === secret.value) {
        solved.value = true;
        hint.value = `猜中了，答案就是 ${secret.value}。`;
        return;
    }

    hint.value = value > secret.value ? '偏大了，再往下试。' : '偏小了，再往上试。';
    guess.value = '';
}
</script>

<template>
    <section class="app-view">
        <div class="section-header section-header-product">
            <div>
                <h2>猜数字</h2>
                <p class="section-subtitle">在 1 到 100 之间找到目标数字，看看几次能收敛。</p>
            </div>
        </div>

        <div class="app-scroll">
            <div class="content-stack">
                <div class="card">
                    <div class="card-header">
                        <h3>游戏面板</h3>
                    </div>
                    <div class="card-body">
                        <div class="tool-form">
                            <div class="form-group">
                                <label>当前猜测</label>
                                <input v-model="guess" type="number" min="1" max="100" placeholder="例如 42" @keyup.enter="submitGuess">
                            </div>
                            <div class="tool-actions">
                                <button class="btn btn-primary" type="button" @click="submitGuess">提交</button>
                                <button class="btn btn-secondary" type="button" @click="resetGame">重开</button>
                            </div>
                        </div>
                        <div class="simple-info game-note">
                            <div class="placeholder-text">{{ hint }}</div>
                        </div>
                        <div class="info-list game-stats">
                            <div class="info-row">
                                <span class="info-label">状态</span>
                                <span class="info-value">{{ solved ? '已命中' : '进行中' }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">尝试次数</span>
                                <span class="info-value">{{ attempts.length }}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">最近记录</span>
                                <span class="info-value">{{ attempts.length ? attempts.join(' / ') : '-' }}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>
</template>

<style scoped>
.game-note {
    margin-top: 18px;
}

.game-stats {
    margin-top: 18px;
}
</style>

<script setup>
import { ref } from 'vue'

import { API_BASE } from '@/api/client.js'
import { login, session, switchToDemo } from '@/stores/session.js'

const loginName = ref('')
const password = ref('')

async function submit() {
  if (!loginName.value || !password.value) return
  await login(loginName.value.trim(), password.value)
}
</script>

<template>
  <div class="page" style="max-width: 520px; margin: 0 auto">
    <div class="card" style="margin-top: 40px">
      <div class="card-head"><h3>连接本机后端</h3></div>
      <div class="card-body">
        <p class="note">
          后端地址 <span class="code">{{ API_BASE }}</span>，由 <span class="code">VITE_API_BASE</span> 配置。
        </p>

        <div class="field" style="margin-top: 14px">
          <label>学号 / 登录名</label>
          <input
            v-model="loginName"
            type="text"
            placeholder="000000003"
            autocomplete="username"
            @keyup.enter="submit"
          />
        </div>

        <div class="field" style="margin-top: 12px">
          <label>密码</label>
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            @keyup.enter="submit"
          />
        </div>

        <div class="row" style="margin-top: 16px; justify-content: flex-end">
          <button class="btn ghost" @click="switchToDemo">返回演示模式</button>
          <button class="btn" :disabled="session.loggingIn" @click="submit">
            {{ session.loggingIn ? '登录中…' : '登录' }}
          </button>
        </div>

        <p class="note" style="margin: 14px 0 0">
          账号由本机 <span class="code">python -m app.cli seed-students</span> 初始化，
          初始密码与学号相同；学号按字符串处理，保留前导零。
        </p>
      </div>
    </div>
  </div>
</template>

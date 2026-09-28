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
      <div class="card-head"><h3>登录项目平台</h3></div>
      <div class="card-body">
        <p class="note">
          后端地址 <span class="code">{{ API_BASE }}</span>，由 <span class="code">VITE_API_BASE</span> 配置。
        </p>

        <div class="field" style="margin-top: 14px">
          <label>学号 / 登录名</label>
          <input
            v-model="loginName"
            type="text"
            placeholder="输入登录名"
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
          本地开发账号由初始化脚本创建；独立演示账号为 demo1—demo6，使用初始化时设置的密码。
          跨设备访问时请使用运行服务的电脑地址。
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AboutDialog from '@/components/AboutDialog.vue'
import SourceDialog from '@/components/SourceDialog.vue'
import LoginView from '@/views/LoginView.vue'
import ProjectSetup from '@/components/ProjectSetup.vue'
import { NAV } from '@/router.js'
import { isLive, session } from '@/stores/session.js'
import { workspace, load, clearWorkspace } from '@/stores/workspace.js'
import { toasts, dismiss } from '@/stores/toasts.js'

const route = useRoute()
const drawerOpen = ref(false)
const aboutOpen = ref(false)
const sourceOpen = ref(false)

const needsLogin = computed(() => session.mode === 'live' && !session.token)
const needsProject = computed(() => session.mode === 'live' && !!session.token && !session.projectId)
const projectName = computed(() => (workspace.project ? workspace.project.name : '未选择项目'))
const currentLabel = computed(() => (route.meta && route.meta.label) || '')

// 切换数据源、账号或项目时清空旧数据，不能把演示记录显示为真实项目。
watch(() => [session.mode, session.token, session.projectId], () => {
  clearWorkspace()
  if (!needsLogin.value && !needsProject.value) load()
}, { immediate: true })

// 窄屏抽屉：给 body 加类，用于遮罩与侧栏滑出。
watch(drawerOpen, (open) => {
  document.body.classList.toggle('drawer', open)
})
</script>

<template>
  <LoginView v-if="needsLogin" />

  <ProjectSetup v-else-if="needsProject" />

  <div v-else class="app">
    <aside class="sidebar">
      <div class="sidebar-inner">
        <div class="brand">
          <h1>企业项目<br />智能协作平台</h1>
          <div class="sub">PROJECT · KNOWLEDGE · AI</div>
        </div>
        <nav class="nav">
          <RouterLink
            v-for="item in NAV"
            :key="item.name"
            :to="{ name: item.name }"
            @click="drawerOpen = false"
          >
            <span class="ico">{{ item.icon }}</span>{{ item.label }}
          </RouterLink>
        </nav>
        <div class="sidebar-foot">
          <b>六人协作 · PC Web</b><br />
          <template v-if="isLive">已连接项目后端<br />数据来自真实接口</template>
          <template v-else>演示数据，不连接后端<br />切换数据源可联调</template>
        </div>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <button class="menu-btn" aria-label="菜单" @click="drawerOpen = !drawerOpen">☰</button>
        <div class="crumb">
          <b>{{ projectName }}</b>
          <span class="sep">/</span>{{ currentLabel }}
          <template v-if="isLive"><span class="sep">/</span>已连接项目后端</template>
        </div>
        <span v-if="isLive" class="badge badge-live">
          已连接 · {{ session.user ? session.user.display_name : '' }}
        </span>
        <span v-else class="badge badge-demo">演示数据 · 非实际运行结果</span>
        <button class="btn ghost small" @click="aboutOpen = true">原型说明</button>
        <button class="btn ghost small" @click="sourceOpen = true">数据源</button>
      </header>

      <main class="page">
        <RouterView v-if="workspace.loaded" :key="`${session.mode}:${session.projectId}`" />
        <p v-else class="note">{{ workspace.loading ? '正在加载项目…' : '项目加载失败，请检查后端或重新选择数据源。' }}</p>
      </main>
    </div>

    <div class="toasts">
      <div
        v-for="t in toasts.items"
        :key="t.id"
        class="toast"
        :class="t.kind === 'err' ? 'err' : t.kind === 'ok' ? 'ok' : ''"
        @click="dismiss(t.id)"
      >
        {{ t.message }}
      </div>
    </div>

    <AboutDialog v-if="aboutOpen" @close="aboutOpen = false" />
    <SourceDialog v-if="sourceOpen" @close="sourceOpen = false" />
  </div>
</template>

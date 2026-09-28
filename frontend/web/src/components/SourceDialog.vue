<script setup>
import ModalDialog from './ModalDialog.vue'
import ProjectSetup from './ProjectSetup.vue'
import { API_BASE } from '@/api/client.js'
import { isLive, logout, switchToDemo, switchToLive, session } from '@/stores/session.js'
import { toast } from '@/stores/toasts.js'

defineEmits(['close'])

function useDemo() {
  switchToDemo()
  toast('已切回演示数据')
}
</script>

<template>
  <ModalDialog title="数据源" @close="$emit('close')">
    <p class="note">
      演示模式使用内置示例数据，无后端也能完整走完页面；连接本机后端后改为调用真实接口。
      真实 AI 能力需要后端接入组员模块并启动 Worker；后端 demo 模式仅返回固定示例。
    </p>

    <div class="row" style="margin-top: 14px">
      <button class="btn" :class="{ ghost: isLive }" @click="useDemo">使用演示数据</button>
      <button class="btn" :class="{ ghost: !isLive }" @click="switchToLive">连接本机后端</button>
    </div>

    <hr class="hr" />
    <ProjectSetup v-if="isLive" />

    <dl class="kv">
      <dt>API 地址</dt>
      <dd><span class="code">{{ API_BASE }}</span></dd>
      <dt>当前状态</dt>
      <dd>
        <template v-if="isLive">
          已登录 · {{ session.user ? session.user.display_name : '' }} ·
          项目 #{{ session.projectId }}
        </template>
        <template v-else>内置演示数据</template>
      </dd>
    </dl>

    <p class="note" style="margin-top: 12px">
      令牌只保存在内存中，不写入 localStorage，也不提交到代码仓库。
    </p>

    <template #footer>
      <button v-if="isLive" class="btn ghost" @click="logout(); $emit('close')">退出登录</button>
      <button class="btn" @click="$emit('close')">关闭</button>
    </template>
  </ModalDialog>
</template>

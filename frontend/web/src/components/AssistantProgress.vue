<script setup>
defineProps({ progress: Object })
</script>
<template>
  <div v-if="progress" class="src" role="status" aria-live="polite">
    <b>{{ progress.events?.at(-1)?.message || '等待后端记录' }}</b>
    <span class="note"> · 已用 {{ (progress.elapsed_ms / 1000).toFixed(1) }} 秒</span>
    <details><summary>查看实际执行阶段</summary>
      <ol><li v-for="event in progress.events" :key="event.seq">
        {{ event.message }} · {{ event.state === 'running' ? '执行中' : event.state === 'failed' ? '失败' : '完成' }}
        <span v-if="event.state !== 'running'"> · {{ (event.elapsed_ms / 1000).toFixed(1) }} 秒</span>
      </li></ol>
    </details>
    <p v-if="progress.error" class="note">{{ progress.error }}；再次发送会创建新请求。</p>
  </div>
</template>

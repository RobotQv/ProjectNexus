<script setup>
import { ref, watch } from 'vue'

const props = defineProps({ progress: Object, pending: Boolean, answered: Boolean })
const expanded = ref(true)
// 仅新请求/正式回答改变默认展开状态，轮询更新不覆盖用户的手动切换。
watch([() => props.progress?.run_id, () => props.pending, () => props.answered], ([, pending, answered]) => {
  if (answered) expanded.value = false
  else if (pending) expanded.value = true
}, { immediate: true })
</script>
<template>
  <div v-if="progress" class="src assistant-progress">
    <div role="status" aria-live="polite">
      <b>{{ progress.events?.at(-1)?.message || '等待后端记录' }}</b>
      <span class="note"> · 已用 {{ ((progress.elapsed_ms || 0) / 1000).toFixed(1) }} 秒</span>
    </div>
    <details :open="expanded" @toggle="expanded = $event.target.open"><summary>{{ expanded ? '收起实际执行阶段' : '查看实际执行阶段' }}</summary>
      <ol><li v-for="event in progress.events" :key="event.seq">
        {{ event.message }} · {{ event.state === 'running' ? '执行中' : event.state === 'failed' ? '失败' : '完成' }}
        <span v-if="event.state !== 'running'"> · {{ (event.elapsed_ms / 1000).toFixed(1) }} 秒</span>
      </li></ol>
    </details>
    <p v-if="progress.error" class="note">{{ progress.error }}；再次发送会创建新请求。</p>
  </div>
</template>

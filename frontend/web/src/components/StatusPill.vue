<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: { type: String, default: '' },
  kind: { type: String, default: 'task' }, // task | document | review
})

const TASK_TEXT = { not_started: '未开始', in_progress: '进行中', done: '已完成', cancelled: '已取消' }
const TASK_TONE = { not_started: 'gray', in_progress: 'teal', done: 'done', cancelled: 'gray' }
const DOC_TEXT = { pending: '排队中', running: '处理中', ready: '已入库', failed: '失败' }
const DOC_TONE = { pending: 'gray', running: 'teal', ready: 'ok', failed: 'danger' }
const REVIEW_TEXT = { draft: '草稿', pending: '待审核', approved: '已通过', rejected: '已驳回' }
const REVIEW_TONE = { draft: 'gray', pending: 'warn', approved: 'ok', rejected: 'gray' }

const MAPS = {
  task: [TASK_TEXT, TASK_TONE],
  document: [DOC_TEXT, DOC_TONE],
  review: [REVIEW_TEXT, REVIEW_TONE],
}

const text = computed(() => {
  const [texts] = MAPS[props.kind] || MAPS.task
  return texts[props.value] || props.value || '—'
})
const tone = computed(() => {
  const [, tones] = MAPS[props.kind] || MAPS.task
  return tones[props.value] || 'gray'
})
</script>

<template>
  <span class="pill" :class="tone">{{ text }}</span>
</template>

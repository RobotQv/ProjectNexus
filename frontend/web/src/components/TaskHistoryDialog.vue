<script setup>
/** 任务历史快照：只读，按版本倒序，不提供回滚。 */
import { onMounted, ref } from 'vue'

import ModalDialog from './ModalDialog.vue'
import { memberName, taskHistory } from '@/stores/workspace.js'

const props = defineProps({
  task: { type: Object, required: true },
})
defineEmits(['close'])

const items = ref([])
const loading = ref(true)
const expanded = ref(null)
function changes(index) {
  const current = items.value[index]?.snapshot || {}
  const previous = items.value[index + 1]?.snapshot
  if (!previous) return ['最早可查快照（不补造此前历史）']
  return Object.keys(current).filter(key => !['updated_at', 'version'].includes(key) &&
    JSON.stringify(current[key]) !== JSON.stringify(previous[key]))
    .map(key => `${key}：${JSON.stringify(previous[key])} → ${JSON.stringify(current[key])}`)
}

onMounted(async () => {
  items.value = await taskHistory(props.task.id)
  loading.value = false
})
</script>

<template>
  <ModalDialog :title="`任务历史快照 · TASK-${task.id}`" wide @close="$emit('close')">
    <p class="note">
      按版本倒序的完整快照，只读，不提供回滚。来源列区分手工修改与建议确认。
    </p>

    <div v-if="loading" class="empty">载入中…</div>
    <div v-else-if="!items.length" class="empty">暂无历史记录。</div>
    <div v-else class="scroll-x" style="margin-top: 12px">
      <table>
        <thead>
          <tr><th>版本</th><th>操作人</th><th>来源</th><th>记录时间</th><th>当时状态</th></tr>
        </thead>
        <tbody>
          <template v-for="(h, index) in items" :key="h.id">
          <tr>
            <td style="white-space: nowrap">v{{ h.version }}</td>
            <td>{{ h.actor_id == null ? '—' : memberName(h.actor_id) }}</td>
            <td>{{ h.source }}<span v-if="h.suggestion_id"> · 建议 #{{ h.suggestion_id }}</span></td>
            <td><span class="note">{{ h.recorded_at }}</span></td>
            <td>
              <span class="note">
                {{ h.snapshot.status }} · {{ h.snapshot.progress }}%
                <template v-if="h.snapshot.assignee_id"> · {{ memberName(h.snapshot.assignee_id) }}</template>
              </span>
              <button class="btn ghost small" @click="expanded = expanded === h.id ? null : h.id">字段变化与完整快照</button>
            </td>
          </tr>
          <tr v-if="expanded === h.id">
            <td colspan="5">
                <p v-for="change in changes(index)" :key="change" class="note">{{ change }}</p>
              <details><summary>完整 JSON 快照</summary>
                <pre style="white-space: pre-wrap; overflow: auto; max-height: 240px">{{ JSON.stringify(h.snapshot, null, 2) }}</pre>
              </details>
            </td>
          </tr>
          </template>
        </tbody>
      </table>
    </div>
  </ModalDialog>
</template>

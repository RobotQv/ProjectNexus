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
          <tr v-for="h in items" :key="h.id">
            <td>v{{ h.version }}</td>
            <td>{{ h.actor_id == null ? '—' : memberName(h.actor_id) }}</td>
            <td>{{ h.source }}</td>
            <td><span class="note">{{ h.recorded_at }}</span></td>
            <td>
              <span class="note">
                {{ h.snapshot.status }} · {{ h.snapshot.progress }}%
                <template v-if="h.snapshot.assignee_id"> · {{ memberName(h.snapshot.assignee_id) }}</template>
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </ModalDialog>
</template>

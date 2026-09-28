<script setup>
/**
 * 手工新建 / 编辑任务。
 *
 * 进度与状态必须成对：done 配 100、not_started 配 0，后端不会自动纠正。
 * 编辑时带 expected_version，409 提示刷新而不是静默覆盖。
 */
import { computed, reactive, ref } from 'vue'

import ModalDialog from './ModalDialog.vue'
import { createTask, taskById, updateTask, workspace } from '@/stores/workspace.js'

const props = defineProps({
  taskId: { type: Number, default: null },
})
const emit = defineEmits(['close', 'saved'])

const existing = computed(() => (props.taskId ? taskById(props.taskId) : null))
const busy = ref(false)
const errors = reactive({})

const form = reactive({
  title: existing.value ? existing.value.title : '',
  description: (existing.value && existing.value.description) || '',
  assignee_id: existing.value && existing.value.assignee_id != null ? String(existing.value.assignee_id) : '',
  module_name: (existing.value && existing.value.module_name) || '',
  status: existing.value ? existing.value.status : 'not_started',
  progress: existing.value ? existing.value.progress : 0,
  planned_start: (existing.value && existing.value.planned_start) || '',
  planned_end: (existing.value && existing.value.planned_end) || '',
  forecast_end: (existing.value && existing.value.forecast_end) || '',
  deadline: (existing.value && existing.value.deadline) || '',
})

// 状态与进度联动，避免提交后端必然 422 的组合。
function onStatusChange() {
  if (form.status === 'done') form.progress = 100
  else if (form.status === 'not_started') form.progress = 0
}
function onProgressChange() {
  if (form.progress >= 100) form.status = 'done'
  else if (form.progress > 0 && form.status === 'not_started') form.status = 'in_progress'
  else if (form.progress === 0 && form.status === 'done') form.status = 'not_started'
}

async function save() {
  for (const key of Object.keys(errors)) delete errors[key]
  if (!form.title.trim()) {
    errors.title = '任务标题不能为空'
    return
  }
  busy.value = true
  const payload = {
    title: form.title.trim(),
    description: form.description || null,
    assignee_id: form.assignee_id === '' ? null : Number(form.assignee_id),
    module_name: form.module_name || null,
    status: form.status,
    progress: Number(form.progress),
    planned_start: form.planned_start || null,
    planned_end: form.planned_end || null,
    forecast_end: form.forecast_end || null,
    deadline: form.deadline || null,
  }

  let out
  if (existing.value) {
    out = await updateTask(existing.value.id, { ...payload, expected_version: existing.value.version })
  } else {
    out = await createTask(payload)
  }
  busy.value = false
  if (!out) return
  emit('saved')
  emit('close')
}

</script>

<template>
  <ModalDialog :title="existing ? `编辑任务 · TASK-${existing.id}` : '新建任务'" @close="emit('close')">
    <div class="grid-2">
      <div class="field">
        <label>任务标题</label>
        <input v-model="form.title" type="text" />
        <span v-if="errors.title" class="note" style="color: var(--danger)">{{ errors.title }}</span>
      </div>
      <div class="field">
        <label>负责人</label>
        <select v-model="form.assignee_id">
          <option value="">未指定</option>
          <option v-for="m in workspace.members" :key="m.user_id" :value="String(m.user_id)">
            {{ m.display_name }}
          </option>
        </select>
      </div>
      <div class="field">
        <label>所属模块</label>
        <input v-model="form.module_name" type="text" />
      </div>
      <div class="field">
        <label>状态</label>
        <select v-model="form.status" @change="onStatusChange">
          <option value="not_started">未开始</option>
          <option value="in_progress">进行中</option>
          <option value="done">已完成</option>
          <option value="cancelled">已取消</option>
        </select>
      </div>
      <div class="field">
        <label>进度（%）</label>
        <input v-model.number="form.progress" type="number" min="0" max="100" @change="onProgressChange" />
      </div>
      <div class="field">
        <label>计划完成</label>
        <input v-model="form.planned_end" type="date" />
      </div>
      <div class="field">
        <label>最新人工预计完成</label>
        <input v-model="form.forecast_end" type="date" />
      </div>
      <div class="field">
        <label>最终截止</label>
        <input v-model="form.deadline" type="date" />
      </div>
    </div>

    <div class="field" style="margin-top: 12px">
      <label>任务描述</label>
      <textarea v-model="form.description" placeholder="可留空" />
    </div>

    <div class="alert warn" style="margin-top: 14px">
      <h4>成对校验</h4>
      <p>done 必须配 100%，not_started 必须配 0%；冲突会返回 422 并逐字段提示。</p>
    </div>

    <p v-if="existing" class="note" style="margin-top: 12px">
      提交带 <span class="code">expected_version: {{ existing.version }}</span>；
      版本不一致返回 409，请刷新后重新核对，不会静默覆盖。
    </p>

    <template #footer>
      <button class="btn ghost" @click="emit('close')">取消</button>
      <button class="btn" :disabled="busy" @click="save">
        {{ busy ? '保存中…' : existing ? '保存修改' : '创建任务' }}
      </button>
    </template>
  </ModalDialog>
</template>

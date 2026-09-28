<script setup>
import { computed, reactive, ref, watch } from 'vue'

import { memberName, workspace } from '@/stores/workspace.js'

const props = defineProps({
  suggestion: { type: Object, required: true },
  // draft：对话草稿，只有提交者可见，核对后提交审核；
  // review：已进入正式审核（含资料提取直接 pending），逐条通过或驳回。
  mode: { type: String, default: 'review' },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['submit', 'drop', 'confirm', 'reject', 'view-source'])

const KIND_TEXT = {
  create_task: '新建任务',
  update_task: '更新任务',
  propose_dependency: '依赖建议',
  create_risk: '风险事项',
}
const SOURCE_TEXT = {
  document: '资料提取',
  task_assistant: '任务 AI 助理',
  project_assistant: '项目助手',
}

const form = reactive({
  title: '',
  assignee_id: '',
  module_name: '',
  planned_end: '',
  description: '',
})
const payloadText = ref('')
const payloadError = computed(() => {
  if (props.suggestion.suggestion_type === 'create_task') return ''
  try {
    const data = JSON.parse(payloadText.value)
    return data && typeof data === 'object' && !Array.isArray(data) ? '' : '请填写 JSON 对象'
  } catch { return '数据格式有误，请检查 JSON 的引号、逗号和括号' }
})

/** 用当前载荷初始化表单；载荷被后端修正后同步。 */
function reset() {
  const p = props.suggestion.proposed_payload || {}
  payloadText.value = JSON.stringify(p, null, 2)
  form.title = p.title || ''
  form.assignee_id = p.assignee_id == null ? '' : String(p.assignee_id)
  form.module_name = p.module_name || ''
  form.planned_end = p.planned_end || ''
  form.description = p.description || ''
}
reset()
watch(() => props.suggestion.version, reset)

const kindText = computed(() => KIND_TEXT[props.suggestion.suggestion_type] || props.suggestion.suggestion_type)
const sourceText = computed(() => SOURCE_TEXT[props.suggestion.source_kind] || props.suggestion.source_kind)
const warnings = computed(() => props.suggestion.validation_warnings || [])
const refs = computed(() => props.suggestion.source_refs || [])
const targetsTask = computed(() => props.suggestion.suggestion_type === 'create_task')
const isDraft = computed(() => props.mode === 'draft')

/** 只提交被修改过的字段，未改动的通过 overrides 留给后端合并。 */
function overrides() {
  if (!targetsTask.value) return JSON.parse(payloadText.value)
  const patch = {}
  const p = props.suggestion.proposed_payload || {}
  if (form.title !== (p.title || '')) patch.title = form.title
  const assignee = form.assignee_id === '' ? null : Number(form.assignee_id)
  if (assignee !== (p.assignee_id == null ? null : p.assignee_id)) patch.assignee_id = assignee
  if (form.module_name !== (p.module_name || '')) patch.module_name = form.module_name || null
  if (form.planned_end !== (p.planned_end || '')) patch.planned_end = form.planned_end || null
  if (form.description !== (p.description || '')) patch.description = form.description || null
  return patch
}

function fullPayload() {
  // 更新建议必须保留 task_id/expected_version/changes，不能混入新建任务表单字段。
  if (!targetsTask.value) return JSON.parse(payloadText.value)
  const p = props.suggestion.proposed_payload || {}
  return {
    ...p,
    title: form.title,
    assignee_id: form.assignee_id === '' ? null : Number(form.assignee_id),
    module_name: form.module_name || null,
    planned_end: form.planned_end || null,
    description: form.description || null,
  }
}

defineExpose({ overrides, fullPayload, reset })
</script>

<template>
  <div class="sg">
    <div class="sg-head">
      <span class="pill teal">{{ kindText }}</span>
      <span v-if="isDraft" class="pill gray">草稿 · 仅你可见</span>
      <span class="grow" />
      <span class="note">
        来源：{{ sourceText }} · 提交者 {{ memberName(suggestion.submitted_by) }} · v{{ suggestion.version }}
      </span>
    </div>

    <div class="sg-body">
      <div v-if="warnings.length" class="alert warn" style="margin-bottom: 12px">
        <h4>需要补充的信息</h4>
        <ul style="margin: 0; padding-left: 18px">
          <li v-for="(w, i) in warnings" :key="i">{{ w }}</li>
        </ul>
      </div>

      <div v-if="suggestion.review_status === 'approved'" class="alert ok" style="margin-bottom: 12px">
        <h4>已通过</h4>
        <p>
          正式目标：<b>{{ suggestion.target_type }} #{{ suggestion.target_id }}</b>。
          重复点击“通过”会返回同一个目标，不会重复创建。
        </p>
      </div>
      <div v-else-if="suggestion.review_status === 'rejected'" class="alert" style="margin-bottom: 12px">
        <h4>已驳回</h4>
        <p>{{ suggestion.review_note || '未创建任何正式任务。' }}</p>
      </div>

      <template v-if="targetsTask">
        <div class="grid-2">
          <div class="field">
            <label>任务标题</label>
            <input v-model="form.title" type="text" />
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
            <label>计划完成</label>
            <input v-model="form.planned_end" type="date" />
          </div>
        </div>
        <div class="field" style="margin-top: 12px">
          <label>任务描述</label>
          <textarea v-model="form.description" placeholder="可留空" />
        </div>
      </template>

      <div v-else class="field">
        <label>待确认数据（JSON）</label>
        <textarea v-model="payloadText" rows="10" aria-label="待确认数据" />
        <p class="note">可以修正任务更新、依赖或风险字段；最终由后端按统一格式校验。任务更新只在 changes 内填写需要修改的字段。</p>
        <p v-if="payloadError" role="alert">{{ payloadError }}</p>
      </div>

      <div v-for="(ref, i) in refs" :key="i" class="src">
        <b>[{{ i + 1 }}] {{ ref.filename || `文档 ${ref.document_id}` }}</b>
        <br />
        <span class="note">文档版本 {{ ref.version }} · 块 {{ ref.block_ids.join(', ') }}</span>
        <p class="q">{{ ref.quote }}</p>
        <button class="btn ghost small" style="margin-top: 8px" @click="emit('view-source', i)">
          查看来源原文
        </button>
      </div>

      <hr class="hr" />

      <div class="row wrap" style="justify-content: flex-end">
        <template v-if="isDraft">
          <button class="btn ghost small" :disabled="busy" @click="emit('drop')">放弃草稿</button>
          <button class="btn small" :disabled="busy || !!payloadError" @click="emit('submit', fullPayload())">
            {{ busy ? '提交中…' : '核对无误，提交审核' }}
          </button>
        </template>
        <template v-else>
          <button class="btn ghost small" :disabled="busy" @click="emit('reject')">驳回</button>
          <button class="btn small" :disabled="busy || !!payloadError" @click="emit('confirm', overrides())">
            {{ busy ? '处理中…' : '核对无误，通过' }}
          </button>
        </template>
      </div>

      <p class="note" style="margin: 10px 0 0">
        <template v-if="isDraft">
          这是<b>草稿</b>：只有你本人可见。提交后进入正式审核（pending），仍然不会直接写入任务。
        </template>
        <template v-else>
          确认前可修改字段；确认后展示正式 target_id，重复点击返回同一目标，不会重复创建。
        </template>
      </p>
    </div>
  </div>
</template>

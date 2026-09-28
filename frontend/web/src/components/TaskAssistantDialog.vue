<script setup>
/**
 * 任务管理里的“AI 助理”：用一句话新增任务。
 *
 * 与项目助手共用 POST /projects/{p}/assistant/messages，以 entry=task_assistant 区分。
 * 返回的是**草稿**：提交者核对后调用 /suggestions/{id}/submit 进入正式审核，
 * 在此之前不会创建任何正式任务 —— 这条链路不能用 POST /tasks 绕过。
 */
import { computed, ref } from 'vue'

import ChatMessages from './ChatMessages.vue'
import ModalDialog from './ModalDialog.vue'
import SuggestionCard from './SuggestionCard.vue'
import { newRequestKey } from '@/api/resources.js'
import { askAssistant, editSuggestion, submitSuggestion, workspace } from '@/stores/workspace.js'
import { toast } from '@/stores/toasts.js'

const emit = defineEmits(['close', 'goto-review'])

const text = ref('')
const sending = ref(false)
const busyId = ref(null)
const messages = ref([])
/** 同一次提问的网络重试复用 request_key；新提问换新的。 */
let requestKey = newRequestKey()
let requestText = ''

const drafts = computed(() => workspace.suggestions.filter((s) => s.review_status === 'draft'))
/** 打开面板时已有的草稿一并列出，不只显示本次会话新生成的。 */
const draftIds = ref(drafts.value.map((s) => s.id))

async function send() {
  const value = text.value.trim()
  if (!value || sending.value) return
  if (value !== requestText) requestKey = newRequestKey()
  requestText = value
  messages.value.push({ role: 'me', text: value })
  text.value = ''
  sending.value = true
  const out = await askAssistant('task_assistant', value, requestKey)
  sending.value = false
  if (!out) {
    // 网络失败时保留输入，用同一个 request_key 重试即可复用后端结果。
    messages.value.pop()
    text.value = value
    return
  }
  messages.value.push({ role: 'ai', ...out })
  requestKey = newRequestKey()
  requestText = ''
  for (const s of out.suggestions || []) draftIds.value.push(s.id)
  if (!out.suggestions || !out.suggestions.length) {
    toast('这次没有生成任务草稿；可以把要新增的任务说得再具体一点')
  }
}

async function submitDraft(suggestion, payload) {
  busyId.value = suggestion.id
  // 提交者修正后的载荷先落库（PATCH 是完整替换），再提交审核。
  const edited = payload ? await editSuggestion(suggestion.id, suggestion.version, payload) : suggestion
  if (payload && !edited) {
    busyId.value = null
    return
  }
  const base = edited || suggestion
  const out = await submitSuggestion(base.id, base.version)
  busyId.value = null
  if (out) toast('已进入正式审核队列', 'ok')
}

/** 契约没有删除草稿的接口，这里只是从本次面板里收起，不影响后端记录。 */
function dropDraft(suggestion) {
  draftIds.value = draftIds.value.filter((id) => id !== suggestion.id)
  toast('已从本面板收起该草稿；草稿记录仍保留')
}

const visibleDrafts = computed(() => drafts.value.filter((s) => draftIds.value.includes(s.id)))
</script>

<template>
  <ModalDialog title="任务 AI 助理" wide @close="emit('close')">
    <p class="note">
      入口与项目助手共用 <span class="code">POST /projects/{p}/assistant/messages</span>，
      以 <span class="code">entry=task_assistant</span> 区分。生成的是草稿：
      <b>核对提交前不会改变任何正式任务</b>。
    </p>

    <div style="margin-top: 14px">
      <ChatMessages
        v-if="messages.length"
        :messages="messages"
        who="任务 AI 助理"
        @pick="(c) => { text = `TASK-${c.entity_id} 补充说明` }"
      />
      <div v-else class="empty">
        <span class="big">✦</span>
        用一句话描述要新增的任务，例如：<br />
        “补一个支付回调失败重试任务，甲负责，9-23 前完成”
      </div>
    </div>

    <template v-if="visibleDrafts.length">
      <hr class="hr" />
      <div class="row">
        <h4 style="margin: 0; font-size: 13px">待核对草稿</h4>
        <span class="note">可逐条修改字段后提交审核</span>
      </div>
      <div style="margin-top: 12px">
        <SuggestionCard
          v-for="s in visibleDrafts"
          :key="s.id"
          :suggestion="s"
          mode="draft"
          :busy="busyId === s.id"
          @submit="(payload) => submitDraft(s, payload)"
          @drop="dropDraft(s)"
        />
      </div>
    </template>

    <div class="composer">
      <input
        v-model="text"
        type="text"
        placeholder="例如：补一个支付回调失败重试任务，甲负责，9-23 前完成"
        :disabled="sending"
        @keyup.enter="send"
      />
      <button class="btn" :disabled="sending || !text.trim()" @click="send">
        {{ sending ? '生成中…' : '发送' }}
      </button>
    </div>
    <p class="note" style="margin: 10px 0 0">
      正式实现由工作流抽取字段，缺失的负责人或日期保留待确认状态，不替你编造。
    </p>

    <template #footer>
      <button class="btn ghost" @click="emit('close')">关闭</button>
      <button class="btn" @click="emit('goto-review')">前往正式审核</button>
    </template>
  </ModalDialog>
</template>

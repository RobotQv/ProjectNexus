<script setup>
import { computed, ref } from 'vue'

import BlocksDialog from '@/components/BlocksDialog.vue'
import ChatMessages from '@/components/ChatMessages.vue'
import { newRequestKey } from '@/api/resources.js'
import { askAssistant } from '@/stores/workspace.js'
import { toast } from '@/stores/toasts.js'

const text = ref('')
const sending = ref(false)
const messages = ref([])
const sourceDialog = ref(null)
let requestKey = newRequestKey()
let requestText = ''

/** 右侧“事实与来源”取最近一次回答的内容。 */
const last = computed(() => [...messages.value].reverse().find((m) => m.role === 'ai') || null)
const facts = computed(() => (last.value ? last.value.facts || [] : []))
const evidence = computed(() => (last.value ? last.value.evidence || [] : []))
const routes = computed(() => (last.value ? last.value.routes || [] : []))

async function send() {
  const value = text.value.trim()
  if (!value || sending.value) return
  if (value !== requestText) requestKey = newRequestKey()
  requestText = value
  messages.value.push({ role: 'me', text: value })
  text.value = ''
  sending.value = true
  const out = await askAssistant('project_assistant', value, requestKey)
  sending.value = false
  if (!out) {
    messages.value.pop()
    text.value = value
    return
  }
  messages.value.push({ role: 'ai', ...out })
  requestKey = newRequestKey()
  requestText = ''
}

/** 澄清分支：带入明确 ID 重新提问，而不是让助手猜。 */
function pickCandidate(candidate) {
  text.value = `TASK-${candidate.entity_id} 现在进度怎样`
  toast('已带入明确任务，按回车或“发送”重新提问')
}

function openEvidence(index) {
  const ref0 = evidence.value[index]
  if (!ref0) return
  sourceDialog.value = {
    documentId: ref0.document_id,
    version: ref0.version,
    filename: ref0.filename || `文档 ${ref0.document_id}`,
    onlyIds: ref0.block_ids || [],
    title: `来源原文 · 文档版本 ${ref0.version}`,
  }
}
</script>

<template>
  <div class="page-head">
    <div class="grow">
      <h2 class="title">AI 项目助手</h2>
      <p>先定位实体、再读取当前事实；需要解释时补充文档依据。</p>
    </div>
  </div>

  <div class="split">
    <div class="card">
      <div class="card-body">
        <ChatMessages
          v-if="messages.length"
          :messages="messages"
          who="AI 项目助手"
          @cite="openEvidence"
          @pick="pickCandidate"
        />
        <div v-else class="empty">
          <span class="big">◇</span>
          先定位实体，再读取当前事实；需要解释时补充文档依据。
        </div>

        <div v-if="routes.length" class="routes">
          <span v-for="(r, i) in routes" :key="i" class="chip">
            {{ r.src }} <b>→ {{ r.dst }}</b>
          </span>
        </div>

        <div class="composer">
          <input
            v-model="text"
            type="text"
            placeholder="试试：支付那块进度怎样，为什么卡住？"
            :disabled="sending"
            @keyup.enter="send"
          />
          <button class="btn" :disabled="sending || !text.trim()" @click="send">
            {{ sending ? '思考中…' : '发送' }}
          </button>
        </div>
        <p class="note" style="margin: 10px 0 0">
          提问调用 <span class="code">POST /projects/{p}/assistant/messages</span>，
          <span class="code">entry=project_assistant</span>。每次新提问生成新的 request_key，
          网络重试复用原值。
        </p>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h3>事实与来源</h3></div>
      <div class="card-body">
        <template v-if="facts.length">
          <div v-for="f in facts" :key="f.id" class="src">
            <b>当前任务记录</b><br />
            TASK-{{ f.id }} · {{ f.title }}<br />
            进度：{{ f.progress }}%
            <br />
            <span class="note">正式系统将显示更新时间与任务链接</span>
          </div>
        </template>

        <div v-for="(e, i) in evidence" :key="`e${i}`" class="src">
          <b>[{{ i + 1 }}] {{ e.filename || `文档 ${e.document_id}` }}</b><br />
          <span class="note">第 {{ e.locator || '—' }} · 文档版本 {{ e.version }}</span>
          <p class="q">{{ e.quote }}</p>
          <button class="btn ghost small" style="margin-top: 8px" @click="openEvidence(i)">展开证据</button>
        </div>

        <p v-if="!facts.length && !evidence.length" class="note" style="margin: 0">
          提问后会在这里分开展示：业务库的当前任务记录、文档中的原文引用，以及规则判断的边界。
        </p>

        <div class="src">
          <b>判断边界</b><br />
          当前进度、历史解释与规则风险分别标注；没有依据时明确说明。
          模型即使给出额外来源文字，也不会被当作证据。
        </div>
      </div>
    </div>
  </div>

  <BlocksDialog
    v-if="sourceDialog"
    :document-id="sourceDialog.documentId"
    :version="sourceDialog.version"
    :filename="sourceDialog.filename"
    :only-ids="sourceDialog.onlyIds"
    :title="sourceDialog.title"
    @close="sourceDialog = null"
  />
</template>

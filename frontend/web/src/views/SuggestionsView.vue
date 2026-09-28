<script setup>
import { computed, ref } from 'vue'

import BlocksDialog from '@/components/BlocksDialog.vue'
import ModalDialog from '@/components/ModalDialog.vue'
import StatusPill from '@/components/StatusPill.vue'
import SuggestionCard from '@/components/SuggestionCard.vue'
import { memberName, reviewSuggestion, suggestionSource, workspace } from '@/stores/workspace.js'

const busyId = ref(null)
const sourceDialog = ref(null)
const rejectTarget = ref(null)
const rejectNote = ref('')
const lastResult = ref(null)

const pending = computed(() => workspace.suggestions.filter((s) => s.review_status === 'pending'))
const handled = computed(() =>
  workspace.suggestions.filter((s) => s.review_status === 'approved' || s.review_status === 'rejected'),
)
const drafts = computed(() => workspace.suggestions.filter((s) => s.review_status === 'draft'))

/**
 * 确认：expected_version 是**建议**的版本，overrides 只带被改动的字段。
 * 重复同结果确认由后端返回原目标，不会重复创建。
 */
async function confirm(suggestion, overrides) {
  busyId.value = suggestion.id
  const out = await reviewSuggestion(suggestion.id, {
    action: 'confirm',
    expected_version: suggestion.version,
    overrides,
  })
  busyId.value = null
  if (out) lastResult.value = out
}

async function reject() {
  const suggestion = rejectTarget.value
  if (!suggestion) return
  busyId.value = suggestion.id
  await reviewSuggestion(suggestion.id, {
    action: 'reject',
    expected_version: suggestion.version,
    note: rejectNote.value || null,
  })
  busyId.value = null
  rejectTarget.value = null
  rejectNote.value = ''
}

async function viewSource(suggestion, index) {
  const detail = await suggestionSource(suggestion.id)
  if (!detail) return
  const doc = (detail.documents || [])[index]
  if (!doc) return
  sourceDialog.value = {
    documentId: doc.document_id,
    version: doc.version,
    filename: doc.filename,
    onlyIds: (doc.blocks || []).map((b) => b.id),
    title: `来源原文 · 建议 #${suggestion.id}`,
  }
}
</script>

<template>
  <div class="page-head">
    <div class="grow">
      <h2 class="title">提取结果确认</h2>
      <p>每条建议独立一条记录，独立确认或驳回；不把多条任务打包成一次审核。</p>
    </div>
  </div>

  <div v-if="drafts.length" class="alert warn">
    <h4>还有 {{ drafts.length }} 条对话草稿未提交</h4>
    <p>
      草稿只有提交者可见，需要先在“AI 助理”里核对并提交，才会进入正式审核。
    </p>
  </div>

  <template v-if="pending.length">
    <SuggestionCard
      v-for="s in pending"
      :key="s.id"
      :suggestion="s"
      mode="review"
      :busy="busyId === s.id"
      @confirm="(overrides) => confirm(s, overrides)"
      @reject="rejectTarget = s"
      @view-source="(i) => viewSource(s, i)"
    />
  </template>
  <div v-else class="card">
    <div class="card-body">
      <div class="empty">
        <span class="big">☑</span>
        当前没有待确认的建议。
      </div>
    </div>
  </div>

  <div v-if="handled.length" class="card" style="margin-top: 18px">
    <div class="card-head">
      <h3>已处理</h3>
      <span class="note">审核后不能再次编辑；重复同结果审核返回原结果</span>
    </div>
    <div class="card-body tight scroll-x">
      <table>
        <thead>
          <tr><th>建议</th><th>结果</th><th>正式目标</th><th>审核</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in handled" :key="s.id">
            <td>
              <div class="tname">{{ s.proposed_payload.title || `建议 #${s.id}` }}</div>
              <div class="tmeta">
                来源 {{
                  { document: '资料提取', task_assistant: '任务 AI 助理', project_assistant: '项目助手' }[s.source_kind]
                    || s.source_kind
                }}
              </div>
            </td>
            <td><StatusPill :value="s.review_status" kind="review" /></td>
            <td>
              <span class="note">
                {{ s.target_id ? `${s.target_type} #${s.target_id}` : '—' }}
              </span>
            </td>
            <td>
              <span class="note">
                {{ s.reviewed_by != null ? memberName(s.reviewed_by) : '—' }}
                <template v-if="s.reviewed_at"><br />{{ s.reviewed_at }}</template>
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <ModalDialog v-if="rejectTarget" title="驳回建议" @close="rejectTarget = null">
    <div class="field">
      <label>审核备注（可选）</label>
      <textarea v-model="rejectNote" placeholder="说明驳回原因，便于提交者复核" />
    </div>
    <p class="note" style="margin-top: 12px">
      reject 请求无需 overrides，该建议不会写入任何正式任务。
    </p>
    <template #footer>
      <button class="btn ghost" @click="rejectTarget = null">取消</button>
      <button class="btn danger" @click="reject">确认驳回</button>
    </template>
  </ModalDialog>

  <ModalDialog v-if="lastResult" title="审核结果" @close="lastResult = null">
    <div class="alert ok">
      <h4>已通过</h4>
      <p>
        正式目标已创建：<b>{{ lastResult.target_type }} #{{ lastResult.target_id }}</b>。
        再次点击“通过”会返回同一个目标，不会重复创建。
      </p>
    </div>
    <dl class="kv" style="margin-top: 14px">
      <dt>建议编号</dt><dd>#{{ lastResult.id }}</dd>
      <dt>来源</dt>
      <dd>
        {{
          { document: '资料提取', task_assistant: '任务 AI 助理', project_assistant: '项目助手' }[lastResult.source_kind]
            || lastResult.source_kind
        }}
      </dd>
      <dt>提交者</dt><dd>{{ memberName(lastResult.submitted_by) }}</dd>
      <dt>审核版本</dt><dd>v{{ lastResult.version }}</dd>
    </dl>
    <p class="note" style="margin-top: 12px">
      正式前端调用 <span class="code">POST /suggestions/{id}/review</span>，
      body 为 <span class="code">{{ JSON.stringify({ action: 'confirm', expected_version: lastResult.version }) }}</span>。
    </p>
    <template #footer>
      <button class="btn" @click="lastResult = null">知道了</button>
    </template>
  </ModalDialog>

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

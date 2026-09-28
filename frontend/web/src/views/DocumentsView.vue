<script setup>
import { computed, ref } from 'vue'

import BlocksDialog from '@/components/BlocksDialog.vue'
import ModalDialog from '@/components/ModalDialog.vue'
import StatusPill from '@/components/StatusPill.vue'
import UploadDialog from '@/components/UploadDialog.vue'
import { API_BASE, getToken } from '@/api/client.js'
import { useJobPolling } from '@/composables/useJobPolling.js'
import { isDemo } from '@/stores/session.js'
import { deleteDocument, extractDocument, retryDocument, sourceUrl, workspace } from '@/stores/workspace.js'
import { toast } from '@/stores/toasts.js'

const uploadOpen = ref(false)
const blocksDoc = ref(null)
const confirmDoc = ref(null)

// 离开本页时 useJobPolling 会自动停表。
const { jobs, watch } = useJobPolling()

const documents = computed(() =>
  workspace.documents.filter((d) => !d.deleted_at).slice().sort((a, b) => b.id - a.id),
)

function jobOf(documentId) {
  return Object.values(jobs.value).find((j) => j && j.resource_id === documentId) || null
}

function onUploaded(jobId) {
  watch(jobId, (job) => {
    if (job.status === 'failed') {
      toast(`后台任务失败：${job.error_message || '未知原因'}，可点击重试`, 'err')
    } else {
      toast('解析与索引均已就绪，可以提问了', 'ok')
    }
  })
}

async function retry(doc) {
  const jobId = await retryDocument(doc.id)
  if (!jobId) return
  toast(`已重新排队，job_id=${jobId}`)
  watch(jobId, (job) => {
    if (job.status === 'failed') toast(`重试仍失败：${job.error_message || '未知原因'}`, 'err')
    else toast('重试成功，解析与索引均已就绪', 'ok')
  })
}

async function extract(doc) {
  if (doc.index_status !== 'ready') {
    toast('索引尚未就绪，暂不能提取', 'err')
    return
  }
  const out = await extractDocument(doc.id, 'extract')
  if (out) toast('文档提取结果直接进入正式审核，不经过草稿', 'ok')
}

async function remove(doc) {
  confirmDoc.value = null
  await deleteDocument(doc.id)
}

/** 原文件下载不是 JSON，要带 Authorization 用 blob，不能裸链接依赖 Cookie。 */
async function download(doc) {
  if (isDemo.value) {
    toast('演示模式没有真实原文件；连接本机后端后可下载')
    return
  }
  try {
    const response = await fetch(`${API_BASE}${sourceUrl(doc.id, doc.version)}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    if (!response.ok) throw new Error('下载失败')
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = doc.filename
    link.click()
    URL.revokeObjectURL(url)
  } catch {
    toast('原文件下载失败，请确认登录状态与存储配置', 'err')
  }
}

function jobLabel(job) {
  return { queued: '排队中', running: '处理中', succeeded: '已完成', failed: '失败' }[job.status] || job.status
}
</script>

<template>
  <div class="page-head">
    <div class="grow">
      <h2 class="title">项目资料库</h2>
      <p>上传只表示排队。解析与索引状态分别判定，202 不等于处理成功。</p>
    </div>
    <button class="btn" @click="uploadOpen = true">上传资料</button>
  </div>

  <div class="card">
    <div class="card-head">
      <h3>资料列表</h3>
      <span class="note">删除、重试与新版本会同步维护派生索引</span>
    </div>
    <div class="card-body tight scroll-x">
      <table>
        <thead>
          <tr><th>文件</th><th>资料日期</th><th>解析</th><th>索引</th><th>切片</th><th>后台任务</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="d in documents" :key="d.id">
            <td>
              <div class="tname">{{ d.filename }}</div>
              <div class="tmeta">
                DOC-{{ d.id }} · v{{ d.version }}<template v-if="d.document_type"> · {{ d.document_type }}</template>
                · {{ Math.round(d.size_bytes / 1024) }} KB
              </div>
              <div v-if="d.error_message" class="note" style="color: var(--danger)">{{ d.error_message }}</div>
            </td>
            <td><span class="note">{{ d.document_date || '—' }}</span></td>
            <td><StatusPill :value="d.parse_status" kind="document" /></td>
            <td><StatusPill :value="d.index_status" kind="document" /></td>
            <td>
              <span class="note">
                {{ d.chunk_count == null ? '—' : `${d.chunk_count} 块` }}
                <template v-if="d.index_version"><br />{{ d.index_version }}</template>
              </span>
            </td>
            <td>
              <span v-if="jobOf(d.id)" class="note">
                #{{ jobOf(d.id).id }} · {{ jobLabel(jobOf(d.id)) }}
              </span>
              <span v-else class="note">—</span>
            </td>
            <td style="text-align: right; white-space: nowrap">
              <button class="btn ghost small" @click="blocksDoc = d">正文块</button>
              <button class="btn ghost small" style="margin-left: 6px" @click="download(d)">原文件</button>
              <button
                v-if="d.parse_status === 'ready'"
                class="btn ghost small"
                style="margin-left: 6px"
                @click="extract(d)"
              >
                提取任务
              </button>
              <button
                v-if="d.parse_status === 'failed'"
                class="btn small"
                style="margin-left: 6px"
                @click="retry(d)"
              >
                重试入库
              </button>
              <button class="btn ghost small" style="margin-left: 6px" @click="confirmDoc = d">移除</button>
            </td>
          </tr>
          <tr v-if="!documents.length">
            <td colspan="7" class="empty">还没有资料，先上传一份会议纪要试试。</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="card-head"><h3>处理状态说明</h3></div>
    <div class="card-body">
      <ol class="steps">
        <li>
          上传返回 <span class="code">202</span> 与 <span class="code">job_id</span>，
          页面每约 2 秒轮询一次后台任务，离开页面即停止。
        </li>
        <li>
          <span class="code">queued</span> / <span class="code">running</span> 继续等待；
          <span class="code">failed</span> 展示错误原因与重试按钮。
        </li>
        <li>
          <span class="code">succeeded</span> 后刷新解析与索引状态。
          <span class="code">parse_status=ready</span> 不等于 <span class="code">index_status=ready</span>。
        </li>
        <li>
          索引未就绪时不做检索问答；演示模式的 <span class="code">demo-no-vector-index</span>
          不会被当作真实索引。
        </li>
      </ol>
    </div>
  </div>

  <UploadDialog v-if="uploadOpen" @close="uploadOpen = false" @uploaded="onUploaded" />

  <BlocksDialog
    v-if="blocksDoc"
    :document-id="blocksDoc.id"
    :version="blocksDoc.version"
    :filename="blocksDoc.filename"
    @close="blocksDoc = null"
  />

  <ModalDialog v-if="confirmDoc" title="移除资料" @close="confirmDoc = null">
    <p>确定移除《{{ confirmDoc.filename }}》？</p>
    <div class="alert warn" style="margin-top: 12px">
      <h4>派生索引同步维护</h4>
      <p>
        删除返回 202 与清理任务；引用该版本的旧建议在审核时会提示来源失效，不会静默通过。
      </p>
    </div>
    <template #footer>
      <button class="btn ghost" @click="confirmDoc = null">取消</button>
      <button class="btn danger" @click="remove(confirmDoc)">确认移除</button>
    </template>
  </ModalDialog>
</template>

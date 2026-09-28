<script setup>
/**
 * 上传资料。上传只返回 202 与 job_id；处理结果由资料页轮询 Job 得到，
 * 页面离开就停表。演示模式可勾选“模拟一次失败”走失败与重试分支。
 */
import { ref } from 'vue'

import ModalDialog from './ModalDialog.vue'
import { isDemo } from '@/stores/session.js'
import { uploadDocument } from '@/stores/workspace.js'
import { toast } from '@/stores/toasts.js'

const emit = defineEmits(['close', 'uploaded'])

const file = ref(null)
const documentType = ref('会议纪要')
const documentDate = ref('') // 由提交者填写真实文档日期，不能默认为示例日期。
const willFail = ref(false)
const busy = ref(false)
const fileInput = ref(null)

function onFileChange(event) {
  file.value = event.target.files && event.target.files[0] ? event.target.files[0] : null
}

async function upload() {
  if (!file.value) {
    toast('请先选择要上传的文件', 'err')
    return
  }
  busy.value = true
  const out = await uploadDocument(file.value, documentType.value, documentDate.value, willFail.value)
  busy.value = false
  if (!out) return
  toast(`已上传，返回 202 与 job_id=${out.jobId}（排队中）`)
  emit('uploaded', out.jobId)
  emit('close')
}
</script>

<template>
  <ModalDialog title="上传项目资料" @close="emit('close')">
    <div class="field">
      <label>资料文件</label>
      <input ref="fileInput" type="file" accept=".txt,.md,.docx,.pdf" @change="onFileChange" />
      <span class="hint">首版支持 TXT、Markdown、DOCX 和可提取文本的 PDF。</span>
    </div>

    <div class="grid-2" style="margin-top: 12px">
      <div class="field">
        <label>资料类型</label>
        <select v-model="documentType">
          <option value="会议纪要">会议纪要</option>
          <option value="需求说明">需求说明</option>
          <option value="接口规范">接口规范</option>
          <option value="其他">其他</option>
        </select>
      </div>
      <div class="field">
        <label>资料日期</label>
        <input v-model="documentDate" type="date" />
      </div>
    </div>

    <div class="alert warn" style="margin-top: 14px">
      <h4>上传只表示排队</h4>
      <p>
        返回 202 与 job_id 后，页面每约 2 秒轮询一次后台任务，离开页面即停止。
        解析成功不等于索引成功。
      </p>
    </div>

    <div v-if="isDemo" class="row wrap" style="margin-top: 12px">
      <button class="btn ghost small" :class="{ danger: willFail }" @click="willFail = !willFail">
        {{ willFail ? '已开启：本次将失败' : '模拟一次失败' }}
      </button>
      <span class="note">演示模式下勾选后，本次上传会走到 failed 并展示重试。</span>
    </div>

    <template #footer>
      <button class="btn ghost" @click="emit('close')">取消</button>
      <button class="btn" :disabled="busy || !file" @click="upload">
        {{ busy ? '上传中…' : '上传' }}
      </button>
    </template>
  </ModalDialog>
</template>

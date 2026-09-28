<script setup>
/** 正文块：建议的来源定位与原文回看都用它。 */
import { onMounted, ref } from 'vue'

import ModalDialog from './ModalDialog.vue'
import { loadBlocks } from '@/stores/workspace.js'

const props = defineProps({
  documentId: { type: Number, required: true },
  version: { type: Number, default: 1 },
  filename: { type: String, default: '' },
  /** 只展示这些块（用于建议的来源引用）；为空则展示全部。 */
  onlyIds: { type: Array, default: () => [] },
  title: { type: String, default: '' },
})
defineEmits(['close'])

const blocks = ref([])
const loading = ref(true)

onMounted(async () => {
  const all = await loadBlocks(props.documentId, props.version)
  blocks.value = props.onlyIds.length ? all.filter((b) => props.onlyIds.includes(b.id)) : all
  loading.value = false
})
</script>

<template>
  <ModalDialog :title="title || `正文块 · ${filename || `文档 ${documentId}`}`" wide @close="$emit('close')">
    <p class="note">
      文档版本 {{ version }} · 块 {{ onlyIds.length ? onlyIds.join(', ') : '全部' }}。
      引用必须是正文块的连续原文，后端会逐条核验。
    </p>

    <div v-if="loading" class="empty">载入中…</div>
    <div v-else-if="!blocks.length" class="empty">该版本没有可展示的正文块。</div>
    <div
      v-for="b in blocks"
      v-else
      :key="b.id"
      class="src"
    >
      <b>块 {{ b.id }} · {{ b.heading || '' }}</b>
      <span class="note">
        （{{ b.locator || '' }}<template v-if="b.page"> · 第 {{ b.page }} 页</template>）
      </span>
      <p class="q">{{ b.text }}</p>
    </div>
  </ModalDialog>
</template>

<script setup>
/** 两个助手共用固定视窗。新内容默认跟随底部，手动上翻后可阅读历史。 */
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({ pending: Boolean })
const viewport = ref(null)
const content = ref(null)
const following = ref(true)
let resizeObserver
let mutationObserver
let frame = 0

function scrollToLatest() {
  following.value = true
  scheduleScroll()
}

function scheduleScroll() {
  cancelAnimationFrame(frame)
  frame = requestAnimationFrame(() => {
    const element = viewport.value
    if (element && following.value) element.scrollTop = element.scrollHeight
  })
}

function onScroll() {
  const element = viewport.value
  if (element) following.value = element.scrollHeight - element.clientHeight - element.scrollTop < 48
}

// 新请求回到底部；轮询、折叠及长回答引起的布局变化在DOM更新后跟随。
watch(() => props.pending, async (pending) => {
  if (pending) following.value = true
  await nextTick()
  scheduleScroll()
})

onMounted(() => {
  resizeObserver = new ResizeObserver(scheduleScroll)
  resizeObserver.observe(content.value)
  resizeObserver.observe(viewport.value)
  mutationObserver = new MutationObserver(scheduleScroll)
  mutationObserver.observe(content.value, { childList: true, subtree: true, characterData: true, attributes: true })
  scheduleScroll()
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  mutationObserver?.disconnect()
  cancelAnimationFrame(frame)
})
</script>

<template>
  <section class="assistant-shell" aria-label="助手对话">
    <div ref="viewport" class="assistant-scroll" tabindex="0" aria-label="对话内容" @scroll="onScroll">
      <div ref="content" class="assistant-scroll-content"><slot /></div>
    </div>
    <div class="assistant-input-area">
      <button v-if="!following" class="btn ghost small latest-message" @click="scrollToLatest">回到最新消息 ↓</button>
      <slot name="composer" />
    </div>
  </section>
</template>

<style scoped>
.assistant-shell {
  display: flex;
  flex-direction: column;
  height: clamp(440px, calc(100vh - 210px), 760px);
  height: clamp(440px, calc(100dvh - 210px), 760px);
  min-width: 0;
  overflow: hidden;
}
.assistant-scroll { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; overflow-anchor: none; padding: 16px; }
.assistant-scroll-content { min-width: 0; }
.assistant-input-area { flex: 0 0 auto; min-width: 0; border-top: 1px solid var(--line-soft); padding: 12px 16px 16px; overflow-wrap: anywhere; }
.assistant-input-area :deep(.composer) { margin-top: 0; }
.assistant-input-area :deep(.composer input) { min-width: 0; }
.latest-message { display: block; margin: 0 auto 10px; }
</style>

<script setup>
defineProps({
  messages: { type: Array, default: () => [] },
  who: { type: String, default: '助手' },
})
const emit = defineEmits(['cite', 'pick'])
const OUTCOME = {
  answered: ['已依据当前数据回答', 'ok'],
  clarify: ['需要澄清目标', 'warn'],
  insufficient: ['资料不足', 'warn'],
  partial: ['仅部分数据可用', 'warn'],
}

/** 把答案里的 [1] 变成可点击的引用标记。 */
function segments(text) {
  const parts = []
  const pattern = /\[(\d+)\]|\*\*([^*]+)\*\*/g
  let last = 0
  let match
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index) })
    parts.push(match[1] ? { cite: Number(match[1]) } : { strong: match[2] })
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push({ text: text.slice(last) })
  return parts
}
</script>

<template>
  <div class="chat">
    <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role === 'me' ? 'me' : 'ai'">
      <div class="who">{{ m.role === 'me' ? '我' : who }}</div>
      <div class="bubble">
        <template v-if="m.role === 'me'">{{ m.text }}</template>
        <template v-else>
          <template v-for="(seg, j) in segments(m.answer)" :key="j">
            <span v-if="seg.cite && m.evidence?.[seg.cite - 1]" class="cite" @click="emit('cite', seg.cite - 1, m)">[{{ seg.cite }}] 查看原文</span>
            <span v-else-if="seg.cite">[{{ seg.cite }}]</span>
            <strong v-else-if="seg.strong">{{ seg.strong }}</strong>
            <template v-else>{{ seg.text }}</template>
          </template>
        </template>
      </div>

      <template v-if="m.role === 'ai'">
        <div class="row wrap" style="margin-top: 9px">
          <span class="pill" :class="(OUTCOME[m.outcome] || OUTCOME.answered)[1]">
            {{ (OUTCOME[m.outcome] || OUTCOME.answered)[0] }}
          </span>
          <span class="pill gray">{{ m.model_id || 'demo' }}</span>
          <span v-if="m.is_demo" class="pill warn">DEMO</span>
        </div>

        <div v-if="m.warnings && m.warnings.length" class="alert warn" style="margin-top: 10px">
          <h4>提示</h4>
          <p v-for="(w, k) in m.warnings" :key="k">{{ w }}</p>
        </div>

        <div v-if="m.outcome === 'clarify' && m.candidates && m.candidates.length" class="alert warn" style="margin-top: 10px">
          <h4>需要你确认目标</h4>
          <p>问题指向多个对象，请选择后再提问，助手不会自己猜一个 ID。</p>
          <div class="row wrap">
            <button
              v-for="c in m.candidates"
              :key="c.entity_id"
              class="chip clickable"
              @click="emit('pick', c)"
            >
              {{ c.title }} <b>#{{ c.entity_id }}</b>
            </button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

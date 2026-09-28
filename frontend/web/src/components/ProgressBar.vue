<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: { type: Number, default: 0 },
  // 低于一半时用琥珀色，和原型一致。
  markLow: { type: Boolean, default: false },
})
const tone = computed(() => (props.markLow && props.value < 50 ? 'warn' : ''))
</script>

<template>
  <div class="bar" :class="tone"><i :style="{ width: `${value}%` }" /></div>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: 0 },
  sub: { type: String, default: '' },
})
</script>

<template>
  <div class="stat">
    <div class="k">{{ label }}</div>
    <div class="v">{{ value }}</div>
    <div class="s">{{ sub }}</div>
  </div>
</template>

<script setup>
defineProps({
  tone: { type: String, default: '' }, // '' | warn | danger | ok
  title: { type: String, default: '' },
  linkText: { type: String, default: '' },
})
const emit = defineEmits(['link'])
</script>

<template>
  <div class="alert" :class="tone">
    <h4 v-if="title">{{ title }}</h4>
    <p><slot /></p>
    <button v-if="linkText" class="btn link" @click="emit('link')">{{ linkText }}</button>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { projectApi } from '@/api/resources.js'
import { describeError } from '@/api/client.js'
import { session, switchToDemo } from '@/stores/session.js'

const name = ref('')
const busy = ref(false)
const error = ref('')
async function create() {
  if (!name.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const project = await projectApi.create({ name: name.value.trim() })
    session.projects.push(project)
    session.projectId = project.id
    name.value = ''
  } catch (e) { error.value = describeError(e) }
  finally { busy.value = false }
}
</script>

<template>
  <div class="card" style="max-width: 560px; margin: 30px auto">
    <div class="card-body">
      <h3>选择本机项目</h3>
      <select v-if="session.projects.length" v-model="session.projectId" aria-label="当前项目">
        <option :value="null" disabled>请选择项目</option>
        <option v-for="p in session.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
      <p v-else class="note">当前账号还没有项目。可以创建一个，也可以请项目创建者将你的账号加入项目后重新登录。</p>
      <div class="row" style="margin-top: 12px">
        <input v-model="name" placeholder="新项目名称" maxlength="120" aria-label="新项目名称" @keyup.enter="create" />
        <button class="btn" :disabled="busy || !name.trim()" @click="create">创建项目</button>
      </div>
      <p v-if="error" role="alert">{{ error }}</p>
      <button class="btn ghost" style="margin-top: 12px" @click="switchToDemo">返回演示模式</button>
    </div>
  </div>
</template>

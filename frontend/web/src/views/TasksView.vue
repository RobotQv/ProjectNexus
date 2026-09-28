<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import NoteCard from '@/components/NoteCard.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import StatusPill from '@/components/StatusPill.vue'
import TaskAssistantDialog from '@/components/TaskAssistantDialog.vue'
import TaskFormDialog from '@/components/TaskFormDialog.vue'
import TaskHistoryDialog from '@/components/TaskHistoryDialog.vue'
import { memberName, workspace } from '@/stores/workspace.js'

const router = useRouter()

const formOpen = ref(false)
const editingId = ref(null)
const assistantOpen = ref(false)
const historyTask = ref(null)
const keyword = ref('')
const statusFilter = ref('')

const drafts = computed(() => workspace.suggestions.filter((s) => s.review_status === 'draft'))

const tasks = computed(() =>
  workspace.tasks.filter((t) => {
    if (t.deleted_at) return false
    if (statusFilter.value && t.status !== statusFilter.value) return false
    if (keyword.value && !t.title.includes(keyword.value)) return false
    return true
  }),
)

function openCreate() {
  editingId.value = null
  formOpen.value = true
}

function openEdit(task) {
  editingId.value = task.id
  formOpen.value = true
}

function gotoReview() {
  assistantOpen.value = false
  router.push({ name: 'suggestions' })
}
</script>

<template>
  <div class="page-head">
    <div class="grow">
      <h2 class="title">任务管理</h2>
      <p>进度与状态成对校验：done 配 100%，not_started 配 0%，后端不会自动纠正矛盾字段。</p>
    </div>
    <div class="row wrap">
      <button class="btn ghost" @click="assistantOpen = true">✦ AI 助理</button>
      <button class="btn" @click="openCreate">新建任务</button>
    </div>
  </div>

  <NoteCard
    v-if="drafts.length"
    tone="warn"
    :title="`有 ${drafts.length} 条 AI 草稿待你核对`"
    link-text="打开 AI 助理继续 →"
    @link="assistantOpen = true"
  >
    草稿只有你本人可见。核对并提交后进入正式审核，此时仍不会改变正式任务。
  </NoteCard>

  <div class="card" style="margin-top: 16px">
    <div class="card-head">
      <h3>任务列表</h3>
      <input v-model="keyword" type="text" placeholder="按标题筛选" style="max-width: 200px" />
      <select v-model="statusFilter" style="max-width: 140px">
        <option value="">全部状态</option>
        <option value="not_started">未开始</option>
        <option value="in_progress">进行中</option>
        <option value="done">已完成</option>
        <option value="cancelled">已取消</option>
      </select>
    </div>
    <div class="card-body tight scroll-x">
      <table>
        <thead>
          <tr>
            <th>任务</th><th>负责人</th><th>当前进度</th><th>状态</th><th>计划完成</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.id">
            <td>
              <div class="tname">{{ t.title }}</div>
              <div class="tmeta">
                TASK-{{ t.id }} · v{{ t.version }}<template v-if="t.module_name"> · {{ t.module_name }}</template>
              </div>
            </td>
            <td>{{ memberName(t.assignee_id) }}</td>
            <td>
              <div class="cellprog">
                <ProgressBar :value="t.progress" />
                <span>{{ t.progress }}%</span>
              </div>
            </td>
            <td><StatusPill :value="t.status" kind="task" /></td>
            <td><span class="note">{{ t.planned_end || '—' }}</span></td>
            <td style="text-align: right; white-space: nowrap">
              <button class="btn ghost small" @click="openEdit(t)">编辑</button>
              <button class="btn ghost small" style="margin-left: 6px" @click="historyTask = t">历史</button>
            </td>
          </tr>
          <tr v-if="!tasks.length">
            <td colspan="6" class="empty">没有符合条件的任务。</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <p class="note" style="margin-top: 12px">
    AI 助理只生成 <span class="code">create_task</span> / <span class="code">update_task</span> 建议草稿，
    不会直接写入任务；手工新建走 <span class="code">POST /projects/{p}/tasks</span>。
  </p>

  <TaskFormDialog v-if="formOpen" :task-id="editingId" @close="formOpen = false" @saved="formOpen = false" />
  <TaskHistoryDialog v-if="historyTask" :task="historyTask" @close="historyTask = null" />
  <TaskAssistantDialog v-if="assistantOpen" @close="assistantOpen = false" @goto-review="gotoReview" />
</template>

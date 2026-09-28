<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import NoteCard from '@/components/NoteCard.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import StatCard from '@/components/StatCard.vue'
import StatusPill from '@/components/StatusPill.vue'
import { evaluateDeps, memberName, taskById, workspace } from '@/stores/workspace.js'

const router = useRouter()

const tasks = computed(() => workspace.tasks.filter((t) => !t.deleted_at))
const doneCount = computed(() => tasks.value.filter((t) => t.status === 'done').length)
const indexedCount = computed(() => workspace.documents.filter((d) => d.index_status === 'ready').length)
const pendingCount = computed(() => workspace.suggestions.filter((s) => s.review_status === 'pending').length)

const recentTasks = computed(() =>
  tasks.value
    .slice()
    .sort((a, b) => b.progress - a.progress || a.id - b.id)
    .slice(0, 5),
)

/** 总览只展示首条依赖的结论；完整试算在“依赖与风险”页。 */
const primaryDependency = computed(() => workspace.dependencies[0] || null)

const dependencyVerdict = computed(() => {
  const d = primaryDependency.value
  if (!d) return null
  const a = taskById(d.predecessor_task_id)
  const b = taskById(d.successor_task_id)
  if (!a || !b) return null
  return evaluateDeps({
    a: a.progress,
    b: b.progress,
    gate: d.successor_gate_progress == null ? 100 : d.successor_gate_progress,
    gateKind: d.successor_gate,
    aRequired: d.predecessor_required_progress,
    neededOn: d.gate_needed_on,
    // 条件就绪日期是依赖自己的字段，不套用前置任务的整体完工日期。
    forecastOn: d.predecessor_forecast_ready_on,
  })
})
</script>

<template>
  <div class="page-head">
    <div class="grow">
      <h2 class="title">项目总览</h2>
      <p>把资料、任务和 AI 分析放在同一个工作空间。</p>
    </div>
    <button class="btn" @click="router.push({ name: 'documents' })">上传项目资料</button>
  </div>

  <div class="grid-4">
    <StatCard label="项目任务" :value="tasks.length" sub="结构化任务记录" />
    <StatCard label="已完成任务" :value="doneCount" sub="不按工时加权进度" />
    <StatCard label="已索引资料" :value="indexedCount" sub="为每次查询可溯源" />
    <StatCard label="待确认建议" :value="pendingCount" sub="确认前不改变任务库" />
  </div>

  <div class="split" style="margin-top: 16px">
    <div class="card">
      <div class="card-head">
        <h3>近期任务</h3>
        <button class="btn ghost small" @click="router.push({ name: 'tasks' })">管理任务</button>
      </div>
      <div class="card-body tight scroll-x">
        <table>
          <thead>
            <tr><th>任务</th><th>负责人</th><th>当前进度</th><th>状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="t in recentTasks" :key="t.id">
              <td>
                <div class="tname">{{ t.title }}</div>
                <div class="tmeta">TASK-{{ t.id }}</div>
              </td>
              <td>{{ memberName(t.assignee_id) }}</td>
              <td>
                <div class="cellprog">
                  <ProgressBar :value="t.progress" />
                  <span>{{ t.progress }}%</span>
                </div>
              </td>
              <td><StatusPill :value="t.status" kind="task" /></td>
            </tr>
            <tr v-if="!recentTasks.length">
              <td colspan="4" class="empty">暂无任务</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h3>需要关注</h3></div>
      <div class="card-body">
        <NoteCard
          v-if="dependencyVerdict"
          :tone="dependencyVerdict.tone"
          :title="`依赖与关卡 · ${dependencyVerdict.headline}`"
          link-text="查看依赖与依赖链 →"
          @link="router.push({ name: 'dependencies' })"
        >
          {{ dependencyVerdict.body }}
        </NoteCard>

        <NoteCard
          v-if="pendingCount > 0"
          title="待人工确认"
          link-text="前往提取结果确认 →"
          @link="router.push({ name: 'suggestions' })"
        >
          资料提取与对话共 {{ pendingCount }} 条建议仍在等待确认，确认后才会写入正式任务。
        </NoteCard>
        <NoteCard v-else title="待人工确认">当前没有等待确认的建议。</NoteCard>

        <NoteCard
          title="先试一句"
          link-text="打开 AI 助手 →"
          @link="router.push({ name: 'assistant' })"
        >
          “支付那块进度怎样，为什么卡住？” 助手会先定位任务，再区分当前记录、文档依据与规则判断。
        </NoteCard>
      </div>
    </div>
  </div>

  <p class="note" style="margin-top: 14px">
    页面指标依据当前数据源计算。演示模式下不连接后端，也不代表真实项目状态。
  </p>
</template>

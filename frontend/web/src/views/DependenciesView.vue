<script setup>
/**
 * 依赖与风险。
 *
 * 判断依据是关卡和日期，而不是比较两个任务的百分比。
 * 演示模式按 6.1 口径在前端试算并标注“演示规则”；
 * 连接后端后结论取自 POST /projects/{p}/analysis，前端不复制后端规则。
 */
import { computed, reactive, ref } from 'vue'

import ProgressBar from '@/components/ProgressBar.vue'
import { analysisApi } from '@/api/resources.js'
import { isDemo, session } from '@/stores/session.js'
import { describeError } from '@/api/client.js'
import {
  TIMING_TEXT,
  STATUS_TEXT,
  dependencyGate,
  evaluateDeps,
  taskById,
  taskLabel,
  workspace,
} from '@/stores/workspace.js'
import { toast } from '@/stores/toasts.js'

const evaluationDate = ref('') // 留空由后端按项目时区选择今天，不固定为示例日期。
const manualResult = ref(null)
const liveResult = computed(() => manualResult.value || workspace.riskStatus?.analysis || null)
const running = ref(false)

/** 主依赖：驱动顶部链路与试算卡片。 */
const primary = computed(() => workspace.dependencies[0] || null)
const downstream = computed(() => workspace.dependencies[1] || null)

const predecessor = computed(() => (primary.value ? taskById(primary.value.predecessor_task_id) : null))
const successor = computed(() => (primary.value ? taskById(primary.value.successor_task_id) : null))
const farTask = computed(() => (downstream.value ? taskById(downstream.value.successor_task_id) : null))

/** 输入面板：初值取自当前依赖记录，改动后立即重算。 */
const input = reactive({
  a: 0,
  b: 0,
  gate: 90,
  aRequired: 100,
  neededOn: '',
  forecastOn: '',
  gateKind: 'progress',
})

function resetFromData() {
  const d = primary.value
  if (!d) return
  input.a = predecessor.value ? predecessor.value.progress : 0
  input.b = successor.value ? successor.value.progress : 0
  input.gate = d.successor_gate_progress == null ? 100 : d.successor_gate_progress
  input.aRequired = d.predecessor_required_progress
  input.gateKind = d.successor_gate
  input.neededOn = d.gate_needed_on || ''
  // 条件就绪日期是依赖自己的字段，不套用前置任务的整体完工日期。
  input.forecastOn = d.predecessor_forecast_ready_on || ''
  manualResult.value = null
}

resetFromData()

const verdict = computed(() =>
  evaluateDeps({
    a: Number(input.a) || 0,
    b: Number(input.b) || 0,
    gate: Number(input.gate) || 0,
    gateKind: input.gateKind,
    aRequired: Number(input.aRequired) || 0,
    neededOn: input.neededOn,
    forecastOn: input.forecastOn,
  }),
)

function clamp(value) {
  const n = parseInt(value, 10)
  if (Number.isNaN(n)) return 0
  return Math.max(0, Math.min(100, n))
}

function apply() {
  input.a = clamp(input.a)
  input.b = clamp(input.b)
  input.gate = clamp(input.gate)
  toast(verdict.value.headline, verdict.value.status === 'blocked_now' ? 'err' : 'ok')
}

function clearForecast() {
  input.forecastOn = ''
  toast('已清空前置任务的条件就绪日期：时间信息不足，不等于低风险', 'err')
}

/** 连接后端时，正式结论必须来自 /analysis。 */
async function runAnalysis() {
  running.value = true
  try {
    const out = await analysisApi.run(session.projectId, evaluationDate.value || null)
    manualResult.value = out
    toast(`已重新计算（rule_version=${out.rule_version}）`, 'ok')
  } catch (error) {
    toast(describeError(error), 'err')
  } finally {
    running.value = false
  }
}

const findings = computed(() => (liveResult.value ? liveResult.value.findings || [] : []))
const openRisks = computed(() => workspace.risks.filter((r) => r.status === 'open'))
</script>

<template>
  <div class="page-head">
    <div class="grow">
      <h2 class="title">任务依赖与风险</h2>
      <p>判断依据是关卡和日期，而不是比较两个任务的百分比。</p>
    </div>
    <div class="row wrap">
      <input v-if="!isDemo" v-model="evaluationDate" type="date" style="max-width: 160px" />
      <button class="btn ghost" :disabled="running" @click="isDemo ? resetFromData() : runAnalysis()">
        {{ running ? '计算中…' : '重新计算' }}
      </button>
    </div>
  </div>

  <div v-if="!primary" class="card">
    <div class="card-body"><div class="empty">当前项目还没有依赖记录。</div></div>
  </div>

  <section>
    <div v-if="primary && isDemo" class="card">
      <div class="card-head">
        <h3>
          {{ predecessor ? predecessor.title : '前置任务' }} →
          {{ successor ? successor.title : '后置任务' }}
          <template v-if="farTask"> → {{ farTask.title }}</template>
        </h3>
        <span class="pill warn">{{ isDemo ? '演示规则 · 人工录入数据' : '规则分析结果' }}</span>
      </div>
      <div class="card-body">
        <div class="chain">
          <div v-if="predecessor" class="node">
            <div class="nid">A · TASK-{{ predecessor.id }}</div>
            <div class="nt">{{ predecessor.title }}</div>
            <div class="np">
              <ProgressBar :value="Number(input.a) || 0" mark-low />
              <span>{{ Number(input.a) || 0 }}%</span>
            </div>
            <div class="nn">前置要求：完成 {{ input.aRequired }}%</div>
          </div>

          <div class="arrow">
            <span class="a">→</span>{{ dependencyGate(primary) }}时需要
          </div>

          <div v-if="successor" class="node" :class="{ on: verdict.status === 'blocked_now' }">
            <div class="nid">B · TASK-{{ successor.id }}</div>
            <div class="nt">{{ successor.title }}</div>
            <div class="np">
              <ProgressBar :value="Number(input.b) || 0" mark-low />
              <span>{{ Number(input.b) || 0 }}%</span>
            </div>
            <div class="nn">后置关卡：{{ dependencyGate(primary) }}</div>
          </div>

          <div class="arrow"><span class="a">→</span>下游影响范围</div>

          <div v-if="farTask" class="node dim">
            <div class="nid">C · TASK-{{ farTask.id }}</div>
            <div class="nt">{{ farTask.title }}</div>
            <div class="np">
              <ProgressBar :value="farTask.progress" mark-low />
              <span>{{ farTask.progress }}%</span>
            </div>
            <div class="nn">潜在受影响，不等于已受阻</div>
          </div>
        </div>

        <div class="grid-4" style="margin-top: 16px">
          <div class="field">
            <label>A 当前进度（%）</label>
            <input v-model="input.a" type="number" min="0" max="100" @change="apply" />
          </div>
          <div class="field">
            <label>B 当前进度（%）</label>
            <input v-model="input.b" type="number" min="0" max="100" @change="apply" />
          </div>
          <div class="field">
            <label>B 的依赖关卡（%）</label>
            <input v-model="input.gate" type="number" min="0" max="100" @change="apply" />
          </div>
          <div class="field">
            <label>B 需要前置成果的日期</label>
            <input v-model="input.neededOn" type="date" @change="apply" />
          </div>
        </div>

        <div class="row wrap" style="margin-top: 14px">
          <div class="field" style="flex: 0 0 250px">
            <label>A 条件就绪日期（最新人工预计）</label>
            <input v-model="input.forecastOn" type="date" @change="apply" />
          </div>
          <button class="btn ghost small" @click="clearForecast">演示缺失日期</button>
          <span class="note">
            关卡 90 改成 80 会从“尚未到关卡”变为“当前关卡受阻”。
          </span>
        </div>

        <div class="alert" :class="verdict.tone" style="margin-top: 16px">
          <h4>{{ verdict.headline }}</h4>
          <p>{{ verdict.body }}</p>
          <p>{{ verdict.timingText }}</p>
          <div class="row wrap">
            <span class="chip">依赖状态 <b>{{ STATUS_TEXT[verdict.status] || verdict.status }}</b></span>
            <span class="chip">时间状态 <b>{{ TIMING_TEXT[verdict.timing] || verdict.timing }}</b></span>
            <span class="chip">关卡需要日期 <b>{{ input.neededOn || '缺失' }}</b></span>
          </div>
        </div>

        <p class="note" style="margin-top: 14px">
          试算：A={{ input.a }}、B={{ input.b }}、关卡 {{ input.gate }}。
          下游节点仅展示潜在影响路径，不能自动把全部任务标红。
          <template v-if="isDemo">演示模式下的结论由前端按 6.1 口径试算，正式结论请连接后端。</template>
        </p>
      </div>
    </div>

    <div v-if="!isDemo && liveResult" class="card">
      <div class="card-head">
        <h3>规则分析结果</h3>
        <span class="note">
          rule_version {{ liveResult.rule_version }} · {{ liveResult.evaluated_at }}
          <template v-if="liveResult.is_demo"> · DEMO</template>
        </span>
      </div>
      <div class="card-body">
        <p v-if="!manualResult && workspace.riskStatus?.is_stale" class="alert warn">以下为旧结果，项目数据已变化，请重新计算。</p>
        <div v-if="liveResult.warnings && liveResult.warnings.length" class="alert warn" style="margin-bottom: 12px">
          <h4>提示</h4>
          <p v-for="(w, i) in liveResult.warnings" :key="i">{{ w }}</p>
        </div>
        <div v-for="(f, i) in findings" :key="i" class="alert" :class="f.timing_status === 'future_risk' ? 'warn' : ''">
          <h4>{{ f.explanation || '规则结论' }}</h4>
          <p>
            依赖状态：{{ STATUS_TEXT[f.dependency_status] || f.dependency_status || '—' }} ·
            时间状态：{{ TIMING_TEXT[f.timing_status] || f.timing_status || '—' }}
          </p>
          <p class="note">reason_codes：{{ (f.reason_codes || []).join('、') || '—' }}</p>
        </div>
        <div v-if="!findings.length" class="empty">本次分析没有产生结论项。</div>
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        <h3>依赖记录</h3>
        <span class="note">PUT 提交完整依赖字段与 expected_version</span>
      </div>
      <div class="card-body tight scroll-x">
        <table>
          <thead>
            <tr><th>前置</th><th>后置</th><th>前置要求</th><th>后置关卡</th><th>需要日期</th><th>版本</th></tr>
          </thead>
          <tbody>
            <tr v-for="d in workspace.dependencies" :key="d.id">
              <td>{{ taskLabel(d.predecessor_task_id) }}</td>
              <td>{{ taskLabel(d.successor_task_id) }}</td>
              <td>{{ d.predecessor_required_progress }}%</td>
              <td>{{ dependencyGate(d) }}</td>
              <td><span class="note">{{ d.gate_needed_on || '缺失' }}</span></td>
              <td><span class="note">v{{ d.version }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        <h3>人工登记风险</h3>
        <span class="note">与规则分析分开展示</span>
      </div>
      <div class="card-body">
        <p class="note" style="margin: 0 0 10px">
          规则分析与人工登记的风险分开展示；未运行或运行失败不能解释为“无风险”。
          <template v-if="workspace.riskStatus">
            当前检查：{{ workspace.riskStatus.job ? workspace.riskStatus.job.status : '未运行' }}
            <template v-if="workspace.riskStatus.is_stale"> · 结果已过期</template>
          </template>
        </p>
        <div v-for="r in openRisks" :key="r.id" class="alert warn">
          <h4>{{ r.title }}</h4>
          <p>
            {{ r.description }}
            <template v-if="r.related_task_id"><br />关联 {{ taskLabel(r.related_task_id) }}</template>
          </p>
          <p class="note">
            严重度 {{ r.severity }} · 来源 {{ r.origin === 'extracted' ? '资料提取' : '人工登记' }}
            <template v-if="r.source_suggestion_id"> · 建议 #{{ r.source_suggestion_id }}</template>
          </p>
        </div>
        <div v-if="!openRisks.length" class="empty">当前没有未解决的人工风险。</div>
      </div>
    </div>
  </section>
</template>

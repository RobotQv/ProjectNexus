/**
 * 演示模式下的依赖关卡试算。
 *
 * 只在 demo 模式下使用，页面会标注“演示规则”。live 模式的结论必须来自
 * POST /projects/{p}/analysis 的 findings —— 前端不复制后端判断规则当作最终结论。
 * 口径对齐开题报告 2.4 与 docs/DATA_CONTRACTS.md 第 6 节。
 */

export const GATE_TEXT = {
  start: '开始即需要',
  finish: '完成时',
}

export function gateLabel(dependency) {
  if (!dependency) return '—'
  if (dependency.successor_gate === 'start') return GATE_TEXT.start
  if (dependency.successor_gate === 'finish') return GATE_TEXT.finish
  return `到 ${dependency.successor_gate_progress}%`
}

/**
 * @param {object} input
 *   a            前置任务当前进度
 *   b            后置任务当前进度
 *   gate         后置关卡百分比（gateKind 为 progress 时使用）
 *   gateKind     start | progress | finish
 *   aRequired    前置任务需要达到的进度
 *   neededOn     后置任务需要前置成果的日期
 *   forecastOn   前置任务最新人工预计完成日期
 */
export function evaluateDependency(input) {
  const { a, b, gate, aRequired, neededOn, forecastOn } = input
  const gateKind = input.gateKind || 'progress'

  const gateReached =
    gateKind === 'start' ? b > 0 : gateKind === 'finish' ? b >= 100 : b >= gate

  let status
  let title
  let body
  if (!gateReached) {
    status = 'condition_unmet'
    title = '尚未到关卡'
    body =
      `后置任务当前 ${b}%，还没有到关卡 ${gate}%。` +
      '前置任务尚未满足时先不判定受阻，等后置任务推进到关卡再复核。'
  } else if (a >= aRequired) {
    status = 'satisfied'
    title = '条件已满足'
    body = `前置任务当前 ${a}%，已达到要求的 ${aRequired}%，后置任务可以继续推进。`
  } else {
    status = 'blocked_now'
    title = '当前关卡受阻'
    body =
      `后置任务已到关卡 ${gate}%，但前置任务当前 ${a}%，未达到要求的 ${aRequired}%。` +
      '当前关卡受阻，需要先推进前置任务或调整关卡。'
  }

  let timing
  let timingText
  if (!neededOn || !forecastOn) {
    timing = 'timing_unknown'
    const missing = !neededOn ? '后置任务需要前置成果的日期' : '前置任务最新人工预计完成'
    timingText = `时间信息不足：缺少“${missing}”，无法判断时间风险，不等于低风险。`
  } else if (forecastOn > neededOn) {
    timing = 'future_risk'
    timingText =
      `前置任务人工预估 ${forecastOn} 完成，晚于后置任务的需要日期 ${neededOn}。` +
      '这是预警，不是确定延期。'
  } else {
    timing = 'on_time'
    timingText = `前置任务人工预估 ${forecastOn} 完成，不晚于需要日期 ${neededOn}，时间上暂未见冲突。`
  }

  // 标题同时体现关卡与时间两类判断，避免“信息不足”被藏进正文当成低风险。
  const parts = []
  if (timing === 'future_risk') parts.push('未来关卡存在风险')
  else if (timing === 'timing_unknown') parts.push('时间信息不足')
  if (status === 'blocked_now') parts.unshift('当前关卡受阻')
  else if (!parts.length) parts.push(title)

  const tone =
    status === 'blocked_now' ? 'danger'
    : timing === 'future_risk' || timing === 'timing_unknown' ? 'warn'
    : 'ok'

  return { status, timing, title, body, timingText, tone, headline: parts.join(' · ') }
}

export const STATUS_TEXT = {
  satisfied: '条件已满足',
  condition_unmet: '尚未到关卡',
  blocked_now: '当前关卡受阻',
  finish_condition_unmet: '完成条件未满足',
  data_conflict: '数据冲突',
}

export const TIMING_TEXT = {
  on_time: '时间未见冲突',
  future_risk: '未来关卡风险',
  timing_unknown: '时间信息不足',
}

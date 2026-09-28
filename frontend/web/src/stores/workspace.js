/**
 * 当前项目的工作区数据与业务操作。
 *
 * demo 与 live 两种数据源在这里合流：页面只调用本模块的方法，
 * 不去关心底层是内存演示后端还是真实 HTTP 接口。
 */
import { computed, reactive } from 'vue'

import { describeError } from '@/api/client.js'
import {
  analysisApi,
  assistantApi,
  dependencyApi,
  documentApi,
  jobApi,
  newRequestKey,
  projectApi,
  suggestionApi,
  taskApi,
} from '@/api/resources.js'
import { createDemoBackend } from '@/demo/backend.js'
import {
  STATUS_TEXT,
  TIMING_TEXT,
  evaluateDependency,
  gateLabel,
} from '@/demo/risk.js'
import { isLive, session } from './session.js'
import { toast } from './toasts.js'

const demo = createDemoBackend()

export const workspace = reactive({
  project: null,
  members: [],
  tasks: [],
  documents: [],
  suggestions: [],
  dependencies: [],
  risks: [],
  blocks: {},
  riskStatus: null,
  loading: false,
  loaded: false,
})

const pid = () => {
  if (!session.projectId) throw new Error('请先选择项目')
  return session.projectId
}
let generation = 0
export function clearWorkspace() {
  generation += 1
  Object.assign(workspace, {
    project: null, members: [], tasks: [], documents: [], suggestions: [],
    dependencies: [], risks: [], blocks: {}, riskStatus: null, loading: false, loaded: false,
  })
}

export const membersById = computed(() => {
  const map = {}
  for (const m of workspace.members) map[m.user_id] = m
  return map
})

export function memberName(id) {
  if (id == null) return '—'
  const m = membersById.value[id]
  return m ? m.display_name : `用户 ${id}`
}

export function taskById(id) {
  return workspace.tasks.find((t) => t.id === id) || null
}

export function taskLabel(id) {
  const t = taskById(id)
  return t ? `TASK-${t.id} · ${t.title}` : `TASK-${id}`
}

export const dependencyGate = gateLabel

/** 规则状态文案，供依赖与风险页展示 findings 时复用。 */
export { STATUS_TEXT, TIMING_TEXT }

/** demo 模式下按 6.1 口径试算；live 模式下结论取自 /analysis，这里只做兜底展示。 */
export function evaluateDeps(input) {
  return evaluateDependency(input)
}

function handle(error) {
  toast(describeError(error), 'err')
  return null
}

// ------------------------------------------------------------------ 载入
export async function load() {
  const current = ++generation
  workspace.loading = true
  try {
    if (isLive.value) {
      const projectId = pid()
      const [project, members, tasks, documents, suggestions, dependencies, risks, riskStatus] =
        await Promise.all([
          projectApi.get(projectId),
          projectApi.members(projectId),
          taskApi.list(projectId, { limit: 200 }),
          documentApi.list(projectId, { limit: 200 }),
          suggestionApi.list(projectId, { limit: 200 }),
          dependencyApi.list(projectId, { limit: 500 }),
          analysisApi.risks(projectId, { limit: 200 }),
          analysisApi.riskStatus(projectId),
        ])
      if (current !== generation) return
      workspace.project = project
      workspace.members = members.items
      workspace.tasks = tasks.items
      workspace.documents = documents.items
      workspace.suggestions = suggestions.items
      workspace.dependencies = dependencies.items
      workspace.risks = risks.items
      workspace.riskStatus = riskStatus
    } else {
      const snap = await demo.snapshot()
      if (current !== generation) return
      workspace.project = snap.project
      workspace.members = snap.members
      workspace.tasks = snap.tasks
      workspace.documents = snap.documents
      workspace.suggestions = snap.suggestions
      workspace.dependencies = snap.dependencies
      workspace.risks = snap.risks
      workspace.riskStatus = await demo.riskStatus()
    }
    workspace.loaded = true
    session.ready = true
  } catch (error) {
    handle(error)
  } finally {
    if (current === generation) workspace.loading = false
  }
}

export async function reloadTasks() {
  try {
    workspace.tasks = isLive.value
      ? (await taskApi.list(pid(), { limit: 200 })).items
      : (await demo.snapshot()).tasks
  } catch (error) {
    handle(error)
  }
}

export async function reloadDocuments() {
  try {
    workspace.documents = isLive.value
      ? (await documentApi.list(pid(), { limit: 200 })).items
      : (await demo.snapshot()).documents
  } catch (error) {
    handle(error)
  }
}

export async function reloadSuggestions() {
  try {
    workspace.suggestions = isLive.value
      ? (await suggestionApi.list(pid(), { limit: 200 })).items
      : (await demo.snapshot()).suggestions
  } catch (error) {
    handle(error)
  }
}

// ------------------------------------------------------------------ 资料
export async function uploadDocument(file, documentType, documentDate, willFail = false) {
  try {
    if (isLive.value) {
      const form = new FormData()
      form.append('file', file)
      if (documentType) form.append('document_type', documentType)
      if (documentDate) form.append('document_date', documentDate)
      const out = await documentApi.upload(pid(), form)
      workspace.documents.push(out.document)
      return { document: out.document, jobId: out.job_id }
    }
    const out = await demo.uploadDocument({
      filename: file ? file.name : '新上传资料.txt',
      size_bytes: file ? file.size : 2048,
      document_type: documentType,
      document_date: documentDate,
      willFail,
    })
    workspace.documents.push(out.document)
    return { document: out.document, jobId: out.job_id }
  } catch (error) {
    handle(error)
    return null
  }
}

/** 轮询一次后台任务；调用方负责停表与离开页面时清理。 */
export async function pollJob(jobId) {
  try {
    const job = isLive.value ? await jobApi.get(pid(), jobId) : await demo.job(jobId)
    if (isLive.value) await reloadDocuments()
    else workspace.documents = (await demo.snapshot()).documents
    return job
  } catch (error) {
    handle(error)
    return null
  }
}

export async function retryDocument(documentId) {
  try {
    const out = isLive.value
      ? await documentApi.retry(pid(), documentId)
      : await demo.retryDocument(documentId)
    await reloadDocuments()
    return out.job_id
  } catch (error) {
    handle(error)
    return null
  }
}

export async function deleteDocument(documentId) {
  try {
    if (isLive.value) await documentApi.remove(pid(), documentId)
    else await demo.deleteDocument(documentId)
    workspace.documents = workspace.documents.filter((d) => d.id !== documentId)
    toast('已移除资料，派生索引将同步清理', 'ok')
    return true
  } catch (error) {
    handle(error)
    return false
  }
}

export async function extractDocument(documentId, kind = 'extract') {
  try {
    const out = isLive.value
      ? await documentApi.extract(pid(), documentId, kind)
      : await demo.extract(documentId, kind)
    toast(`已发起${kind === 'summary' ? '摘要' : '提取'}，workflow_run_id=${out.workflow_run_id}`)
    return out
  } catch (error) {
    handle(error)
    return null
  }
}

export async function loadBlocks(documentId, version = null) {
  try {
    if (isLive.value) {
      const doc = workspace.documents.find((d) => d.id === documentId)
      const selectedVersion = version ?? (doc ? doc.version : 1)
      const blocks = []
      // 来源可能在长文的后半部分，不能只取第一页的 500 个块。
      for (let offset = 0; ; offset += 500) {
        const page = await documentApi.blocks(pid(), documentId, selectedVersion, { limit: 500, offset })
        blocks.push(...page.items)
        if (page.items.length < 500) break
      }
      return blocks
    }
    return await demo.documentBlocks(documentId)
  } catch (error) {
    handle(error)
    return []
  }
}

export function sourceUrl(documentId, version) {
  return documentApi.sourceUrl(pid(), documentId, version)
}

// ------------------------------------------------------------------ 任务
export async function createTask(payload) {
  try {
    const task = isLive.value ? await taskApi.create(pid(), payload) : await demo.createTask(payload)
    workspace.tasks.push(task)
    toast('已创建任务', 'ok')
    return task
  } catch (error) {
    handle(error)
    return null
  }
}

export async function updateTask(taskId, payload) {
  try {
    const task = isLive.value
      ? await taskApi.patch(pid(), taskId, payload)
      : await demo.updateTask(taskId, payload)
    const index = workspace.tasks.findIndex((t) => t.id === taskId)
    if (index >= 0) workspace.tasks.splice(index, 1, task)
    toast('已保存任务', 'ok')
    return task
  } catch (error) {
    handle(error)
    return null
  }
}

export async function deleteTask(taskId, expectedVersion) {
  try {
    if (isLive.value) await taskApi.remove(pid(), taskId, expectedVersion)
    else await demo.deleteTask(taskId, expectedVersion)
    workspace.tasks = workspace.tasks.filter((t) => t.id !== taskId)
    toast('已删除任务', 'ok')
    return true
  } catch (error) {
    handle(error)
    return false
  }
}

export async function taskHistory(taskId) {
  try {
    return isLive.value
      ? (await taskApi.history(pid(), taskId, { limit: 50 })).items
      : (await demo.taskHistory(taskId)).items
  } catch (error) {
    handle(error)
    return []
  }
}

// ------------------------------------------------------------------ 建议
export async function submitSuggestion(suggestionId, expectedVersion) {
  try {
    const out = isLive.value
      ? await suggestionApi.submit(pid(), suggestionId, expectedVersion)
      : await demo.submitSuggestion(suggestionId, expectedVersion)
    replaceSuggestion(out)
    toast('已提交正式审核；此时仍不会改变正式任务', 'ok')
    return out
  } catch (error) {
    handle(error)
    return null
  }
}

export async function editSuggestion(suggestionId, expectedVersion, proposedPayload) {
  try {
    const out = isLive.value
      ? await suggestionApi.edit(pid(), suggestionId, expectedVersion, proposedPayload)
      : await demo.editSuggestion(suggestionId, expectedVersion, proposedPayload)
    replaceSuggestion(out)
    return out
  } catch (error) {
    handle(error)
    return null
  }
}

export async function reviewSuggestion(suggestionId, body) {
  try {
    const out = isLive.value
      ? await suggestionApi.review(pid(), suggestionId, body)
      : await demo.reviewSuggestion(suggestionId, body)
    replaceSuggestion(out)
    if (body.action === 'confirm') {
      await reloadTasks()
      toast(`已通过，正式目标 ${out.target_type} #${out.target_id}`, 'ok')
    } else {
      toast('已驳回，未创建任何正式任务', 'ok')
    }
    return out
  } catch (error) {
    handle(error)
    return null
  }
}

export async function suggestionSource(suggestionId) {
  try {
    return isLive.value
      ? await suggestionApi.source(pid(), suggestionId)
      : await demo.suggestionSource(suggestionId)
  } catch (error) {
    handle(error)
    return null
  }
}

function replaceSuggestion(out) {
  const index = workspace.suggestions.findIndex((s) => s.id === out.id)
  if (index >= 0) workspace.suggestions.splice(index, 1, out)
  else workspace.suggestions.push(out)
}

// ------------------------------------------------------------------ 助手
/**
 * 两处入口共用同一接口，以 entry 区分。
 * 每次主动提问生成新的 request_key；网络重试复用同一个值。
 */
export async function askAssistant(entry, text, requestKey) {
  const request_key = requestKey || newRequestKey()
  try {
    const out = isLive.value
      ? await assistantApi.send(pid(), entry, text, request_key)
      : await demo.assistant(entry, text)
    await reloadSuggestions()
    return out
  } catch (error) {
    handle(error)
    return null
  }
}

export async function retryAssistant(entry, text, requestKey) {
  return askAssistant(entry, text, requestKey)
}

export { newRequestKey }

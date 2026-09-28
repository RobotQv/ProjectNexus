/**
 * 演示模式的内存后端：方法签名与 src/api/resources.js 对齐，便于页面无差别调用。
 * 关键行为刻意与真实后端一致 —— 202 只表示排队、建议确认前不写任务、重复确认返回同一目标。
 */
import { ASK_FALLBACK, ASK_FIXTURES, clone, seed } from './data.js'

const POLL_STEPS = ['running', 'parsed', 'indexed']

export function createDemoBackend() {
  const db = seed()
  const jobs = new Map()
  let seq = 5000

  const nextId = () => ++seq
  const now = () => new Date().toISOString().slice(0, 19).replace('T', ' ')
  const today = '2026-09-15'
  const currentUser = 1

  function makeJob(kind, resourceId, resourceType, willFail = false) {
    const id = nextId()
    jobs.set(id, {
      id, project_id: 1, kind, resource_type: resourceType, resource_id: resourceId,
      resource_version: 1, status: 'queued', attempts: 0, dedup_key: `${kind}:${resourceId}`,
      error_message: null, created_at: now(), started_at: null, finished_at: null,
      _step: 0, _willFail: willFail,
    })
    return id
  }

  /** 每次轮询推进一步，模拟后台任务的三段式推进。 */
  function advanceJob(job) {
    if (!job || job.status === 'succeeded' || job.status === 'failed') return job
    job._step += 1
    job.status = 'running'
    if (job.started_at === null) job.started_at = now()

    if (job._willFail && job._step >= 2) {
      job.status = 'failed'
      job.attempts = 1
      job.error_message = '正文提取失败：该 PDF 无可提取文本层'
      job.finished_at = now()
      const doc = db.documents.find((d) => d.id === job.resource_id)
      if (doc) {
        doc.parse_status = 'failed'
        doc.error_message = job.error_message
      }
      return job
    }

    const doc = db.documents.find((d) => d.id === job.resource_id)
    if (doc) {
      if (job._step === 1) {
        doc.parse_status = 'running'
        doc.index_status = 'pending'
      } else if (job._step === 2) {
        doc.parse_status = 'ready'
        doc.index_status = 'running'
        doc.chunk_count = doc.chunk_count || 6
      } else {
        doc.index_status = 'ready'
        doc.index_version = `idx-${today.replace(/-/g, '')}`
      }
    }
    if (job._step >= 3) {
      job.status = 'succeeded'
      job.finished_at = now()
    }
    return job
  }

  function memberName(id) {
    const m = db.members.find((x) => x.user_id === id)
    return m ? m.display_name : id == null ? '—' : '未知成员'
  }

  return {
    isDemo: true,

    async snapshot() {
      return {
        project: clone(db.project),
        members: clone(db.members),
        tasks: clone(db.tasks),
        documents: clone(db.documents),
        suggestions: clone(db.suggestions),
        dependencies: clone(db.dependencies),
        risks: clone(db.risks),
      }
    },

    async documentBlocks(documentId) {
      return clone(db.blocks[documentId] || [])
    },

    // ---------------------------------------------------------------- 资料
    async uploadDocument({ filename, size_bytes = 2048, document_type = null, document_date = null, willFail = false }) {
      const doc = {
        id: nextId(), project_id: 1, filename,
        media_type: 'application/octet-stream', size_bytes,
        document_type, document_date, version: 1, content_hash: `demo-${nextId()}`,
        parse_status: 'pending', index_status: 'pending', index_version: null,
        chunk_count: null, error_message: null, created_by_demo: true,
        uploaded_by: currentUser, created_at: now(), updated_at: now(), deleted_at: null,
      }
      db.documents.push(doc)
      const job_id = makeJob('document_ingest', doc.id, 'document', willFail)
      // 与真实后端一致：上传返回 202，处理结果只能靠轮询 Job。
      return { document: clone(doc), job_id }
    },

    async job(jobId) {
      const job = jobs.get(jobId)
      if (!job) throw new Error('演示任务不存在')
      advanceJob(job)
      return clone(job)
    },

    async retryDocument(documentId) {
      const doc = db.documents.find((d) => d.id === documentId)
      if (!doc) throw new Error('资料不存在')
      doc.parse_status = 'pending'
      doc.index_status = 'pending'
      doc.error_message = null
      const job_id = makeJob('document_ingest', doc.id, 'document', false)
      return { document: clone(doc), job_id }
    },

    async deleteDocument(documentId) {
      db.documents = db.documents.filter((d) => d.id !== documentId)
      return { deleted: true, job_id: makeJob('document_delete', documentId, 'document') }
    },

    async extract(documentId, kind) {
      const doc = db.documents.find((d) => d.id === documentId)
      if (!doc) throw new Error('资料不存在')
      if (doc.index_status !== 'ready') throw new Error('索引尚未就绪，暂不能提取')
      const runId = nextId()
      // 文档提取直接进入正式待审，没有 draft 阶段。
      const pending = db.suggestions.filter((s) => s.source_kind === 'document' && s.review_status === 'pending')
      return { workflow_run_id: runId, job_id: makeJob('workflow', runId, 'workflow_run'), status: 'succeeded', extracted: pending.length }
    },

    // ---------------------------------------------------------------- 任务
    async createTask(payload) {
      const task = {
        id: nextId(), project_id: 1, tags: [], aliases: [], planned_start: null,
        forecast_end: null, deadline: null, description: null, module_name: null,
        ...payload, version: 1, progress_updated_at: today,
        forecast_updated_at: null, forecast_by: null,
        source_suggestion_id: payload.source_suggestion_id ?? null,
        created_at: now(), updated_at: now(), deleted_at: null,
      }
      db.tasks.push(task)
      return clone(task)
    },

    async updateTask(taskId, patch) {
      const task = db.tasks.find((t) => t.id === taskId)
      if (!task) throw new Error('任务不存在')
      const { expected_version, ...changes } = patch
      // 版本不一致必须报冲突，不能静默覆盖。
      if (expected_version !== undefined && expected_version !== task.version) {
        throw Object.assign(new Error('数据已发生变化，请刷新后重试'), { status: 409 })
      }
      for (const [k, v] of Object.entries(changes)) task[k] = v
      task.version += 1
      task.updated_at = now()
      return clone(task)
    },

    async deleteTask(taskId, expected_version) {
      const task = db.tasks.find((t) => t.id === taskId)
      if (!task) throw new Error('任务不存在')
      if (task.version !== expected_version) {
        throw Object.assign(new Error('数据已发生变化，请刷新后重试'), { status: 409 })
      }
      db.tasks = db.tasks.filter((t) => t.id !== taskId)
      return { deleted: true, task_id: taskId }
    },

    async taskHistory(taskId) {
      const task = db.tasks.find((t) => t.id === taskId)
      if (!task) return { items: [] }
      const base = [1, 2, 3].slice(0, Math.max(1, task.version))
      const sources = ['创建', '手工修改', '建议 #501', '手工修改']
      const items = base
        .map((v) => ({
          id: taskId * 100 + v, project_id: 1, task_id: taskId, version: v,
          snapshot: clone(task), actor_id: currentUser,
          source: sources[v] || '手工修改', suggestion_id: null,
          recorded_at: `2026-09-${String(13 + v).padStart(2, '0')} 10:20`,
        }))
        .reverse()
      return { items, limit: 50, offset: 0 }
    },

    // ---------------------------------------------------------------- 建议
    async editSuggestion(id, expected_version, proposed_payload) {
      const s = db.suggestions.find((x) => x.id === id)
      if (!s) throw new Error('建议不存在')
      if (s.review_status !== 'draft' && s.review_status !== 'pending') {
        throw Object.assign(new Error('建议已审核'), { status: 409 })
      }
      if (s.version !== expected_version) {
        throw Object.assign(new Error('建议版本已更新'), { status: 409 })
      }
      s.proposed_payload = clone(proposed_payload)
      s.version += 1
      return clone(s)
    },

    async submitSuggestion(id, expected_version) {
      const s = db.suggestions.find((x) => x.id === id)
      if (!s) throw new Error('建议不存在')
      if (s.submitted_by !== currentUser) {
        throw Object.assign(new Error('仅提交者可核对并提交对话建议'), { status: 403 })
      }
      if (s.source_kind === 'document') {
        throw Object.assign(new Error('文档提取已直接进入正式审核'), { status: 409 })
      }
      if (s.review_status === 'pending') return clone(s)
      if (s.review_status !== 'draft' || s.version !== expected_version) {
        throw Object.assign(new Error('建议状态或版本已变化'), { status: 409 })
      }
      s.review_status = 'pending'
      s.submitted_at = today
      s.version += 1
      return clone(s)
    },

    async reviewSuggestion(id, { action, expected_version, overrides = {}, note = null }) {
      const s = db.suggestions.find((x) => x.id === id)
      if (!s) throw new Error('建议不存在')
      const desired = action === 'confirm' ? 'approved' : 'rejected'

      // 同结果重试返回原目标，不重复创建。
      if (s.review_status === desired) return clone(s)
      if (s.review_status !== 'pending' || s.version !== expected_version) {
        throw Object.assign(new Error('该建议已被处理或版本已更新'), { status: 409 })
      }

      if (action === 'confirm') {
        const merged = { ...s.proposed_payload, ...overrides }
        if (s.suggestion_type === 'create_task') {
          const task = await this.createTask({ ...merged, source_suggestion_id: s.id })
          s.target_type = 'task'
          s.target_id = task.id
        } else if (s.suggestion_type === 'create_risk') {
          const risk = {
            id: nextId(), project_id: 1, title: merged.title, description: merged.description || '',
            related_task_id: merged.related_task_id ?? null, severity: merged.severity || 'unknown',
            origin: 'extracted', source_suggestion_id: s.id, status: 'open', version: 1,
          }
          db.risks.push(risk)
          s.target_type = 'risk'
          s.target_id = risk.id
        }
        s.proposed_payload = merged
      }

      s.review_status = desired
      s.reviewed_by = currentUser
      s.reviewed_by_name = memberName(currentUser)
      s.reviewed_at = today
      s.review_note = note
      s.version += 1
      return clone(s)
    },

    async suggestionSource(id) {
      const s = db.suggestions.find((x) => x.id === id)
      if (!s) throw new Error('建议不存在')
      return {
        source_kind: s.source_kind,
        submitted_by: s.submitted_by,
        input_text: null,
        documents: (s.source_refs || []).map((ref) => {
          const doc = db.documents.find((d) => d.id === ref.document_id)
          return {
            document_id: ref.document_id,
            version: ref.version,
            filename: doc ? doc.filename : `文档 ${ref.document_id}`,
            quote: ref.quote,
            blocks: (db.blocks[ref.document_id] || []).filter((b) => ref.block_ids.includes(b.id)),
          }
        }),
      }
    },

    // ---------------------------------------------------------------- 助手
    async assistant(entry, text) {
      const runId = nextId()
      const key = Object.keys(ASK_FIXTURES).find((k) => text.includes(k)) || ASK_FALLBACK
      const fx = clone(ASK_FIXTURES[key])
      const facts = (fx.task_ids || [])
        .map((id) => db.tasks.find((t) => t.id === id))
        .filter(Boolean)

      // 任务 AI 助理：把一句话变成草稿，缺失字段留待确认，不编造。
      let suggestions = []
      if (entry === 'task_assistant' && /(新增|添加|补|加)/.test(text)) {
        const guess = text
          .replace(/^(请|帮我|麻烦)?(新增|添加|补|加)(一个|一条)?/, '')
          .replace(/任务$/, '')
          .trim()
        const draft = {
          id: nextId(), run_id: runId, project_id: 1, suggestion_type: 'create_task',
          source_kind: 'task_assistant', review_status: 'draft', submitted_by: currentUser,
          version: 1, submitted_at: null, reviewed_by: null, reviewed_at: null,
          review_note: null, target_id: null, target_type: null,
          proposed_payload: {
            title: (guess || '未命名任务').slice(0, 60), assignee_id: null, module_name: null,
            tags: [], aliases: [], status: 'not_started', progress: 0, planned_end: null,
          },
          source_refs: [], entity_candidates: [],
          validation_warnings: ['未识别出负责人与计划完成日期，请核对后补充。'],
        }
        db.suggestions.push(draft)
        suggestions = [clone(draft)]
        fx.answer =
          `已生成 1 条新建任务草稿，标题为“${draft.proposed_payload.title}”。\n\n` +
          '负责人和计划完成日期没有从这句话里识别出来，已留待确认，没有替你编造。' +
          '请核对字段后提交正式审核；提交后进入 pending，仍然不会直接写入任务。'
        fx.task_ids = []
        fx.evidence = []
      }

      return {
        run_id: runId,
        answer: fx.answer,
        outcome: fx.outcome,
        suggestions,
        facts: clone(facts),
        evidence: clone(fx.evidence || []),
        candidates: clone(fx.candidates || []),
        warnings: [],
        risk_previews: [],
        routes: fx.routes || [],
        model_id: 'demo-workflow',
        prompt_version: 'demo-1',
        is_demo: true,
      }
    },

    async riskStatus() {
      return {
        job: { id: 900, status: 'succeeded', kind: 'risk_analysis' },
        analysis: { id: 901, rule_version: 'demo-1', evaluated_at: today, findings: [], warnings: [], is_demo: true },
        is_stale: false,
        notice: '仅标记和提示；未运行或失败不能解释为无风险',
      }
    },
  }
}

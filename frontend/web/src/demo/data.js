/**
 * 演示数据：全部为固定示例，与开题报告第六块的截图一致。
 * 只在 demo 模式下使用；live 模式的数据全部来自本机后端。
 */

export function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

export function seed() {
  return {
    project: {
      id: 1,
      name: '校园外卖平台',
      description: '示例项目，用于原型演示。',
      status: 'active',
      owner_id: 1,
      timezone: 'Asia/Shanghai',
    },
    members: [
      { user_id: 1, display_name: '示例成员甲', login_name: '示例账号甲', aliases: ['甲'] },
      { user_id: 2, display_name: '示例成员乙', login_name: '示例账号乙', aliases: ['乙'] },
      { user_id: 3, display_name: '示例成员丙', login_name: '示例账号丙', aliases: [] },
      { user_id: 4, display_name: '示例成员丁', login_name: '示例账号丁', aliases: [] },
    ],
    tasks: [
      {
        id: 17, title: '支付模块开发', assignee_id: 1, status: 'in_progress', progress: 70,
        module_name: '后端', tags: ['支付'], aliases: ['支付那块', '支付功能'],
        description: '完成支付下单与回调，覆盖异常分支。',
        planned_start: '2026-09-14', planned_end: '2026-09-22',
        forecast_end: '2026-09-20', deadline: '2026-09-25', version: 3,
      },
      {
        id: 18, title: '前端订单页面', assignee_id: 2, status: 'in_progress', progress: 80,
        module_name: '前端', tags: ['Vue'], aliases: ['订单页'],
        description: '订单列表与详情页，联调支付结果。',
        planned_start: '2026-09-15', planned_end: '2026-09-23',
        forecast_end: null, deadline: '2026-09-26', version: 2,
      },
      {
        id: 19, title: '接口联调与验收', assignee_id: 3, status: 'not_started', progress: 0,
        module_name: '联调', tags: [], aliases: ['联调'],
        description: '按验收用例逐条走查端到端链路。',
        planned_start: '2026-09-24', planned_end: '2026-09-26',
        forecast_end: null, deadline: '2026-09-27', version: 1,
      },
      {
        id: 20, title: '用户登录功能', assignee_id: 4, status: 'done', progress: 100,
        module_name: '后端', tags: ['FastAPI'], aliases: ['登录'],
        description: '学号登录与项目权限校验。',
        planned_start: '2026-09-14', planned_end: '2026-09-16',
        forecast_end: '2026-09-16', deadline: '2026-09-18', version: 4,
      },
    ],
    documents: [
      {
        id: 1, filename: '09-18 项目会议纪要.docx', document_type: '会议纪要',
        document_date: '2026-09-18', version: 1, size_bytes: 18422,
        media_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        parse_status: 'ready', index_status: 'ready', index_version: 'idx-20260918',
        chunk_count: 12, error_message: null, created_by_demo: true,
      },
      {
        id: 2, filename: '接口规范 v1.md', document_type: '接口规范',
        document_date: '2026-09-15', version: 1, size_bytes: 9310,
        media_type: 'text/markdown',
        parse_status: 'ready', index_status: 'ready', index_version: 'idx-20260918',
        chunk_count: 8, error_message: null, created_by_demo: true,
      },
    ],
    blocks: {
      1: [
        {
          id: 18, document_id: 1, document_version: 1, block_no: 2, page: 2,
          heading: '二、进度同步', locator: '第 3 段',
          text: '支付模块开发目前完成七成，负责人是示例成员甲。前端订单页面已经到八成，接口联调还没有开始。',
        },
        {
          id: 19, document_id: 1, document_version: 1, block_no: 3, page: 2,
          heading: '三、风险与依赖', locator: '第 4 段',
          text: '测试账号尚未开通，可能影响联调进度。订单页面到九成时需要支付模块完成，预计 09-19 就要用。',
        },
      ],
    },
    suggestions: [
      {
        id: 501, run_id: 11, project_id: 1, suggestion_type: 'create_task',
        source_kind: 'task_assistant', review_status: 'draft', submitted_by: 1,
        version: 1, submitted_at: null, reviewed_by: null, reviewed_at: null,
        review_note: null, target_id: null, target_type: null,
        proposed_payload: {
          title: '补充支付回调的失败重试', assignee_id: 1, module_name: '后端',
          tags: ['支付'], status: 'not_started', progress: 0, planned_end: '2026-09-23',
        },
        source_refs: [], entity_candidates: [], validation_warnings: [],
      },
      {
        id: 601, run_id: 21, project_id: 1, suggestion_type: 'create_task',
        source_kind: 'document', review_status: 'pending', submitted_by: 2,
        version: 1, submitted_at: '2026-09-18', reviewed_by: null, reviewed_at: null,
        review_note: null, target_id: null, target_type: null,
        proposed_payload: {
          title: '开通联调测试账号', assignee_id: 3, module_name: '联调',
          tags: ['环境'], status: 'not_started', progress: 0, planned_end: '2026-09-19',
        },
        source_refs: [
          { document_id: 1, version: 1, block_ids: [19], quote: '测试账号尚未开通，可能影响联调进度。' },
        ],
        entity_candidates: [],
        validation_warnings: ['未识别出确切负责人，已留待确认。'],
      },
      {
        id: 602, run_id: 21, project_id: 1, suggestion_type: 'create_task',
        source_kind: 'document', review_status: 'pending', submitted_by: 2,
        version: 1, submitted_at: '2026-09-18', reviewed_by: null, reviewed_at: null,
        review_note: null, target_id: null, target_type: null,
        proposed_payload: {
          title: '订单页面对接支付结果回调', assignee_id: 2, module_name: '前端',
          tags: ['Vue'], status: 'not_started', progress: 0, planned_end: '2026-09-23',
        },
        source_refs: [
          { document_id: 1, version: 1, block_ids: [18], quote: '前端订单页面已经到八成，接口联调还没有开始。' },
        ],
        entity_candidates: [], validation_warnings: [],
      },
    ],
    dependencies: [
      {
        id: 31, project_id: 1, predecessor_task_id: 17, successor_task_id: 18,
        predecessor_required_progress: 100, successor_gate: 'progress',
        successor_gate_progress: 90, gate_needed_on: '2026-09-19',
        predecessor_forecast_ready_on: '2026-09-20', version: 1, description: null,
        source_suggestion_id: null,
      },
      {
        id: 32, project_id: 1, predecessor_task_id: 18, successor_task_id: 19,
        predecessor_required_progress: 100, successor_gate: 'start',
        successor_gate_progress: null, gate_needed_on: null,
        predecessor_forecast_ready_on: null, version: 1, description: null,
        source_suggestion_id: null,
      },
    ],
    risks: [
      {
        id: 41, project_id: 1, title: '测试账号可能影响联调', origin: 'extracted',
        description: '资料提取到的风险，测试账号尚未开通。',
        related_task_id: 19, severity: 'medium', status: 'open', version: 1,
      },
    ],
  }
}

/** 演示问答：按关键词命中不同 outcome，覆盖 answered / clarify / insufficient。 */
export const ASK_FIXTURES = {
  支付: {
    outcome: 'answered',
    answer:
      '支付模块开发当前进度 70%，负责人是示例成员甲。这部分来自任务记录，而不是历史会议纪要。\n\n' +
      '会议纪要提到：测试账号尚未开通，可能影响联调。这是一条文档依据，不能直接当作当前阻塞的确定结论。[1]\n\n' +
      '依赖规则显示：前置任务当前 70%，到 90% 时才需要支付模块达到 100%。目前尚未到该关卡，存在后续风险但不能判定已经停工。',
    task_ids: [17],
    evidence: [
      {
        document_id: 1, version: 1, block_ids: [19], locator: '第 4 段',
        filename: '09-18 项目会议纪要.docx', quote: '测试账号尚未开通，可能影响联调进度。',
      },
    ],
    routes: [
      { src: '轻RAG', dst: 'TASK-17' },
      { src: '业务库', dst: '当前进度' },
      { src: '主RAG', dst: '会议纪要' },
    ],
  },
  登录: {
    outcome: 'answered',
    answer:
      '用户登录功能已经完成，当前进度 100%，负责人是示例成员丁。\n\n' +
      '该结论来自业务库的当前任务记录，没有引用文档；如需核对实现说明，可上传登录接口文档后重新提问。',
    task_ids: [20],
    evidence: [],
    routes: [
      { src: '轻RAG', dst: 'TASK-20' },
      { src: '业务库', dst: '当前进度' },
    ],
  },
  联调: {
    outcome: 'clarify',
    answer:
      '“联调”可能指向多个任务，请先确认你问的是哪一个。助手不会自己猜一个 ID，选定后可以带上明确的任务再问一次。',
    task_ids: [],
    evidence: [],
    candidates: [
      { entity_type: 'task', entity_id: 19, title: '接口联调与验收' },
      { entity_type: 'task', entity_id: 18, title: '前端订单页面' },
    ],
    routes: [{ src: '轻RAG', dst: '候选 2 条' }],
  },
  上线: {
    outcome: 'insufficient',
    answer:
      '现有资料不足以回答这个问题。项目内没有与“上线”相关的任务记录，已索引的两份资料中也没有对应段落。\n\n不展示推测的原因；补充相关资料后再提问。',
    task_ids: [],
    evidence: [],
    routes: [{ src: '主RAG', dst: '无命中' }],
  },
}

export const ASK_FALLBACK = '支付'

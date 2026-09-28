# 组员模块接入契约 v2

> v2 接口已接入后端，真实算法仍由对应负责人实现。任务与建议的精确格式、JSON 示例和审核状态见 [数据格式](DATA_CONTRACTS.md)。

## 已实现的接口边界

| 边界 | 需要支持的输入/输出 |
| --- | --- |
| 后端 → 工作流 | 项目范围、对话输入或带版本/锚点的清洗正文、业务读取与检索/风险工具；助手编排归工作流 |
| 工作流 → 后端 | 每条独立建议，支持新建任务与已有任务各业务字段更新、目标引用及版本、来源和缺失/歧义提示 |
| 建议流转 | 两个对话入口先由提交者核对；文档提取直接正式待审；正式审核逐条修正/通过/驳回，所有有效项目成员均可操作 |
| 来源与审计 | 后端从登录身份记录提交者/审核人、时间与结果；文档来源含版本/原文锚点，对话来源关联原始输入，不伪造 Evidence |
| 任务历史 | 新建和每次生效修改保存完整快照，记录版本、操作人、时间与来源；仅保留/查看，不做回滚 |
| 工作流 → 风险 | 当前状态＋未生效的候选任务/依赖变更，返回阻塞风险标记和解释，候选不必先正式写库 |
| 数据变更 → 风险 | 相关正式数据变化后检查，无定时检查、外部通知或自动任务状态写入 |

上述字段、状态枚举与方法已同步 shared 和 HTTP，不在各模块自行定义不兼容的替代版本。算法间用注入协议协作，不直接导入彼此实现。

以 `shared/contracts.py` 中 Pydantic 对象 / Protocol 为唯一代码基准，旧 app 路径仅作兼容转发。下文解释责任，具体字段以该文件及 OpenAPI 为准。整数 ID 由后端分配，同一次本机联调的模块必须使用同一套 ID；不同电脑各有独立数据，不要求 ID 相同。

## 1. 怎样把实现接进来

三个工作区已经固定为 team_modules/main_rag、team_modules/workflow、team_modules/risk，各有 README、适配器骨架和 tests。后端维护 team_modules/factory.py 统一装配，算法模块只依赖 shared，不导入 app 或彼此的实现。

```python
from shared.contracts import Modules
from team_modules.main_rag.adapter import MainRAGAdapter
from team_modules.workflow.adapters import WorkflowAdapter, EntityAdapter
from team_modules.risk.adapter import RiskAdapter

def build_modules(*, settings, llm):
    # 按你们选定的方案初始化向量库 / Embedding 客户端；不要在 import 时创建业务数据。
    return Modules(
        main_rag=MainRAGAdapter(),
        entities=EntityAdapter(),
        workflow=WorkflowAdapter(llm=llm),
        risk=RiskAdapter(),
        is_demo=False,
    )
```

上述类已提供明确抛出 module_unavailable 的方法骨架，不是完成的算法。各组员在自己目录实现对应方法，未实现部分继续明确报错，不用空结果伪装成功。

`.env`：

```dotenv
NEXUS_MODULE_FACTORY=team_modules.factory:build_modules
NEXUS_MODULE_MODE=disabled
```

重启自己电脑的 API 和 Worker。非空 MODULE_FACTORY 优先于 MODULE_MODE；切回 demo 时清空 MODULE_FACTORY。examples/team_factory.py 兼容转发到同一装配点，不维护第二份工厂。

工厂在 API、Worker 两个进程各创建一份实例；不能依赖进程内字典共享索引。必须使用团队确定的持久向量库/索引存储。模块对象可能由多个 API 线程并发使用，请保护客户端状态，不共享 SQLAlchemy Session。

## 2. 主 RAG 负责人

| 方法 | 输入 | 返回 / 责任 |
| --- | --- | --- |
| `parse(file)` | FileRef：项目、文档、版本、原始路径、文件名、哈希 | ParsedDocument，按正文顺序返回 ParsedBlock；不分配业务 Block ID |
| `ingest(document)` | DocumentRef，包含主干已保存、带 ID 的 Block | IngestResult(index_version, chunk_count)，发布完成后才返回 |
| `retrieve(scope, question, limit)` | 显式 Scope(project_id) | Evidence 列表；在向量查询层也加项目过滤 |
| `delete(scope, document_id, version)` | 指定项目、文档、版本 | 幂等清理该版本 Chunk / 向量，不删除业务表 |

要点：

- TXT、Markdown、DOCX、文本 PDF 属于首版范围；扫描 PDF 无 OCR 就明确失败，不能返回空成功。
- FileRef.path 只交给服务端模块，不向前端或模型发送服务器路径。DOCX 解压要限制解压总大小、条目数量，不能信任 ZIP 文件自报体积；PDF 解析也要约束资源。
- block_no 从 0 开始、同文档版本唯一；page 只有实际有分页时填写，DOCX 不伪造固定页码。
- `ingest` 必须基于传入 Block 生成 Chunk，不再另解析一份正文，防止引用错位。
- Chunk 记录 text、block_ids、token_count、content_hash、Embedding 模型/维度、index_version、vector_id。它们由主 RAG 的派生索引存储管理，不作为业务事实表。
- 推荐确定性向量 ID：`doc:{id}:v{version}:i{index_version}:c{chunk_no}`；upsert 同一 Job 重试不能重复追加。
- 模型/维度改变必须切换索引版本；构建完成后原子发布，不让半成品被查询。
- Evidence 必须包含 document_id、version、block_ids、quote。quote 是原文连续摘录或按照 block_ids 顺序用换行拼接后的连续子串，不是改写摘要。主干会再次核验。
- delete 重试应安全；旧任务延迟回写也不能让软删文档重新进入检索。主干仍做二次过滤，但模块应该维护自己的版本/删除隔离。

## 3. 轻 RAG / 实体索引

```text
sync(EntityRecord) → None
resolve(Scope, text, entity_type, limit) → Resolution
```

EntityRecord 字段：project_id、entity_type(task/member)、entity_id、source_version、search_text、is_active。

`member.entity_id` 是 User.id，不是 ProjectMember.id。以 `(project_id, entity_type, entity_id)` 为键；成员可属于多个项目，各项目别名不同。

任务的 search_text 包含标题、说明、模块、标签、别名，不含实时进度。新增或改文本时同步；只有状态/进度/截止日变化不会要求重新 Embedding。source_version 是取文本时的业务版本，不保证每个任务版本都产生索引 Job。

`is_active=false` 表示删除/移除，请清理索引。同步需要幂等并防止旧版本覆盖新版本。主干会回查有效业务实体，所以已经删除或跨项目候选即使向量库有残留也不能作为结果返回。

Resolution：outcome 为 resolved / ambiguous / not_found，包含 candidates 和 index_version。每个候选包括 entity_type、entity_id、title、score(可空)、match_reason。score 是算法匹配分，不是成功概率；不要随意写死“0.9 就一定正确”。

## 4. 工作流 / 轻量文档理解

```text
respond(AssistantRequest, AssistantTools) → AssistantResult
extract(DocumentRef, entity_catalog: list[EntityRecord], kind, *, tools=None) → ExtractionResult
```

kind 为 `extract` 或 `summary`。DocumentRef 中有 filename、document_date 和完整正文 Block；日期缺失时不能根据当前时间瞎猜会议日期。entity_catalog 用于映射已存在任务/成员，最终 ID 仍由主干在审核时验证。

长文档分批、实体歧义、抽取去重、提示词、模型 JSON 修复属于工作流实现。复用注入的 `llm.complete(messages, max_tokens=...)`；不要把整份大文件一次塞进预算之外的请求。

ExtractionResult 必须记录 model_id、prompt_version。extract 返回 SuggestionDraft 列表，summary 返回 summary 文本（一般不返回建议）。

v2 建议类型：

- `create_task`：候选 proposed_payload 对应 TaskChanges，正式确认按 TaskCreate 验证。
- `update_task`：proposed_payload 对应 UpdateTaskProposal(task_id, expected_version, changes)，确认时合并当前任务并验证版本；不能自动覆盖。
- `propose_dependency`：候选用 DependencyDraft，正式确认按 DependencyCreate 验证；原文未给前置要求或后置关卡时留待人补齐，不能默认造一条 100% / start 边。
- `create_risk`：候选用 RiskDraft，正式确认按 RiskCreate 验证；severity 可以 unknown。

当前文档建议必须有真实 source_refs，可附 entity_candidates 和 validation_warnings；对话的原始输入/提交者由后端记录，source_refs 可为空。缺失信息可以先保留在候选载荷里，让用户在 review.overrides 中补充；主干确认时才执行完整字段校验。不要填数据库中没有的人员/任务，也不要将“模型猜测”作为原文摘录。

审核接口的 overrides 是**字段补丁**，合并 proposed_payload 后重新校验。重复 confirm 返回第一次的 target_id，不会用新的 overrides 编辑已经创建的正式对象；要修改请走对应业务接口。

正式表的创建/更新和完整 TaskHistory 由 ReviewService 与业务服务在同一事务完成。模块不可 import `app.models` 或 `app.db` 绕过审核写入 Task / Dependency / RiskItem。

## 5. 依赖 / 风险负责人

```text
analyze(Snapshot) → AnalysisResult
analyze_candidates(RiskPreview(snapshot, changes)) → AnalysisResult
```

Snapshot 已包含同一事务读取的 tasks、dependencies、project_id、timezone、evaluation_date。任务/依赖含 id、version、更新时间与各项日期。不要再读业务表拼接另一个时刻的数据，也不要直接调用 LLM 替代确定性规则。

AnalysisResult：rule_version、findings、warnings。每个 Finding 有 task_ids、candidate_keys、可选 dependency_id、dependency_status、timing_status、reason_codes、explanation。正式分析的 candidate_keys 为空，预览只能引用本批候选 key。

dependency_status 允许 satisfied / condition_unmet / blocked_now / finish_condition_unmet / data_conflict；timing_status 允许 future_risk / timing_unknown / on_time。任务超期等非依赖发现可不填两个状态，通过明确的 reason_codes 表达。需要额外潜在下游路径等字段时，先和后端同步修改契约并补测试，不私自给 API 塞未知字段。

必须按架构预案冻结：

- A70、B80，B关卡90：未到关卡，不等于当前阻塞。
- A70、B80，B关卡80：当前无法越过关卡。
- finish 条件不满足但 B 尚未完成：只说明完成条件未满足。
- B 已完成却违反前置条件：数据冲突，不自动撤销状态。
- cancelled 前置任务不能自动满足条件。
- 日期当天不算已超期；要严格晚于 planned_end 且任务未完成。
- 条件要求小于100时，不能用 A 的整体 forecast_end 推断该条件就绪日期。
- 日期缺失返回 timing_unknown，不能判“低风险”。

主干已有查环/自依赖/跨项目校验和开始操作的阻止规则；完整规则矩阵和影响路径仍是你负责的算法，不是 demo 的空 findings。

## 6. 错误与测试约定

可预期、可展示的失败用 `AppError(code, 中文说明, status)`，说明里不要包含密钥、请求头、原始供应商错误或本地绝对路径。其他异常会被主干转成脱敏的模块执行失败。

模块超时、限流、空正文、索引失败都应是明确失败，不返回伪造的成功结构。Worker 会在无数据库事务的阶段调用模块，失败不影响 API 继续处理普通业务。

开发自测不作为专门交付物；各模块交付实现、运行/接口说明与必要脱敏样例，由测试负责人验收并继续集成和系统测试。已有 `tests/test_queries_llm.py` 与 Worker 测试可作为注入替身、上传和审核验证的参考，不代表新增需求已经实现。

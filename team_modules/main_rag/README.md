# 主 RAG 负责人工作区

## Alpha 接入变更

DOCX 按 XML 顺序读取段落和普通表格，每行保留 `table:N/row:N` 锚点；不承诺复杂合并表格或 OCR。`chunking.py` 在原始 Block 上建立独立检索块，默认最多 1200 字符、短块阈值 300、长块重叠 100，保留 block 内字符范围。原始 Block 不变。

`retrieve` 签名不变；`retrieve_ranked` 供评估使用，返回 chunk 排名、原始锚点与两路排名。非连续摘录分开返回 Evidence，不拼造原文。模式由后端设置 `NEXUS_RAG_RETRIEVAL_MODE=vector/bm25/hybrid_rrf`；索引策略为 `baseline/bounded/semantic`。切换分块策略须重建，详见根目录 `docs/ALPHA.md`。

课设规模下从同一份 Chroma 持久化快照计算余弦排名、BM25 与 RRF（c=60），避免进程间缓存过期；不适合直接扩展到海量语料。真实小样本对照见 `artifacts/alpha_handoff/`，下方旧整合说明只记录当时状态。

## 负责需求与边界

负责 TXT/Markdown/DOCX/文本 PDF 的真实解析、正文分块、Embedding、资料索引、检索及派生索引清理。依据既有审计保证项目隔离、版本一致、来源可回看、重试不重复。扫描 PDF 不承诺 OCR，无可提取正文时明确失败。

只在本目录编写实现。adapter.py 已接入 parsing/ 和 indexing/，配置由后端工厂传入；不移动后端文件。2026-09-22 整合验证使用模拟 Embedding 和真实临时 Chroma，尚未验证真实模型效果、表格解析与长文边界，见 docs/INTEGRATION_20260922.md。

不负责账号、HTTP、文件上传落盘、Document/Block ID 分配、工作流提取或正式任务写入。尤其不能为工作流另解析第二份正文：parse 输出由后端保存，ingest 与工作流都复用这些带 ID 的 Block。

资料库既有大部头资料，也允许新增文档和会议记录。“提取任务”的页面入口虽在资料库，但功能归工作流＋轻 RAG：你提供清洗正文和准确锚点，对方生成独立待审核建议，直接进入正式审核。审核页的“查看来源原文”依赖这些版本和锚点，不可用生成摘要替代原文。

## 必须实现的接口

从 shared.contracts 导入；方法签名以 adapter.py / 公共协议为准。

| 方法 | 输入 | 输出 |
| --- | --- | --- |
| parse(file) | FileRef：project_id、document_id、version、path、filename、content_hash | ParsedDocument(blocks)，每块 block_no、text，可选 page/heading/locator |
| ingest(document) | DocumentRef：项目/文档/版本、日期、filename、后端保存的 Block 列表 | IngestResult(index_version, chunk_count) |
| retrieve(scope, question, limit) | Scope(project_id)、问题、条数上限 | Evidence[] |
| delete(scope, document_id, version) | 指定项目、文档、版本 | None；只有成功清理或确认已清理才返回 |

Block ID 由后端分配；block_no 非负且同版本唯一。DOCX 不伪造页码。Chunk/向量元数据由你维护，须保存 document/version、block_ids、内容哈希、Embedding 模型/维度、index_version 和 vector_id。

Evidence 必填 document_id、version、block_ids、quote。quote 必须是指定原文块按顺序换行拼接后的连续摘录，不是模型改写；后端会校验范围、版本与原文一致性。

## 本地解耦和选型授权

- 你与轻 RAG 负责人自行决定 Embedding 模型和向量库；不要求后端先选好。协商共享客户端/模型维度和集合命名，资料索引与实体索引分开命名空间。
- 做出选择后，在此 README 记录模型、维度、索引版本、存储路径、安装/启动方式、离线/联网要求，再填本目录 requirements.txt。不要把未确定的包提前装到所有人环境。
- 模块仅导入 shared 和自己的内部模块/第三方依赖，不导入 app、workflow 或 risk 的实现。需要共享基础设施时与后端协商注入，不互相硬连。
- 单测可用临时文件构造 FileRef，不需要本机账号或数据库。完整联调才设置本机 MODULE_FACTORY 并启动 API/Worker。
- API 与 Worker 是同一电脑上的两个进程，不能只靠 Python 内存字典共享索引。存储放根 data/main_rag/ 或本目录 data/，不提交索引文件。

## 重试、安全和失败语义

同一文档/版本/索引版本的向量 ID 确定且 upsert 幂等；索引构建成功后原子发布。delete 可多次调用，失败抛共享 AppError，不能假成功。向量查询本身也要按 project_id 过滤，不依赖最后一道后端过滤兜底。

文件路径来自后端，但内容不可信。限制 DOCX 解压体积/条数、PDF 处理资源，空正文/格式不支持给出脱敏错误。资料里的指令只是文档内容，不赋予写数据库或访问其他项目的权限。

## 测试与交付

仓库根执行：

```powershell
.\.venv\Scripts\python.exe -m pytest team_modules/main_rag/tests
```

现有 smoke 测试仅证明骨架/契约可独立使用，不代表 RAG 完成；上面命令仅用于已有验证，不要求专门自测交付物。提交实现、必要脱敏样例、requirements、实际选型记录和启动步骤。测试负责人验收解析/清洗、锚点回看、入库、检索与项目隔离等功能；不提交密钥/真实项目资料。

新增 OCR、复杂表格语义、额外文件类型、业务查询含义等功能先向项目负责人确认。详细公共约定见[模块契约](../../../docs/MODULE_CONTRACTS.md)。


---


## 选型记录

- Embedding：智谱 embedding-3，维度 2048
- 向量库：Chroma 1.5.9
- 索引存储：data/main_rag/
- 集合名：main_rag_blocks
- 索引版本：embedding-3-2048
- Key 验证：已确认可调 Embedding 接口，状态码 200，维度 2048
- 依赖版本：chromadb==1.5.9, python-docx==1.2.0, pdfminer.six==20260107, httpx==0.28.1

## 实现说明

### 已完成

- `parse`：TXT / Markdown / DOCX / 文本 PDF，扫描件明确失败
- `ingest`：用后端保存的 Block 建索引，幂等 upsert
- `retrieve`：按 project_id 过滤，返回真实连续摘录
- `delete`：按 project_id + document_id + version 清理派生索引

### 目录结构

    main_rag/
    ├── adapter.py
    ├── parsing/
    │   ├── txt.py
    │   ├── markdown.py
    │   ├── docx.py
    │   └── pdf.py
    ├── indexing/
    │   ├── embedding.py
    │   └── store.py
    └── tests/

### 如何建立索引

1. 后端调用 `parse`，得到 `ParsedDocument`
2. 后端保存 blocks，分配 block.id
3. 后端构造 `DocumentRef`，调用 `ingest`
4. `ingest` 调用 Embedding，写入 Chroma

### 如何重建索引

1. 删除 `data/main_rag/` 目录
2. 对每个文档重新调用 `ingest`
3. 索引版本由 `EMBEDDING_MODEL + EMBEDDING_DIM` 决定

### 如何清理索引

调用 `delete(scope, document_id, version)`，只清理该文档版本的派生索引。

### 本地联调

在 `.env` 设置：

    NEXUS_MODULE_FACTORY=team_modules.factory:build_modules
    NEXUS_MODULE_MODE=disabled

重启 API 和 Worker。

### 联调验证记录

- 上传 TXT：parse 成功，3 个 block
- ingest：index_status=ready，chunk_count=3
- delete：文档列表为空，blocks 返回 404，Chroma 记录数 0
- retrieve：4 个单元测试覆盖

### 依赖

    chromadb==1.5.9
    python-docx==1.2.0
    pdfminer.six==20260107
    httpx==0.28.1
    python-dotenv

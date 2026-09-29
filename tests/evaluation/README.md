# 评估样例草稿

已完成的100题冻结结果与直接可用的离线复核命令见 [公开评估归档](../records/retrieval-100/README.md)。下方包含早期草稿和从头生成实验的命令，不能把旧草稿状态当作本次100题实测状态。

## 100题分批评估与指标审计

新增 `audit_batch_a.py` 从原始排名和原文锚点独立重算A集。A不是50道单锚点题，而是40道单锚点、10道双锚点；原95%是逐题平均锚点Recall，不是Hit。后续同时报告Hit@5、Recall@5（macro anchor recall）、MRR@5，另保留micro anchor recall和全证据覆盖率。

`batch_b_dataset.py` 为同一虚构维保项目设计50道新题：语义10、技术词10、混合10、相似干扰10、跨文件/项目5、无答案5。按问题需要标注1个或多个原文锚点，不以chunk_id作答案；无答案不指定伪证据。

```powershell
python -m tests.evaluation.audit_batch_a --source artifacts/rrf-title-50/<成功运行目录> --output artifacts/retrieval-100-audit
python -m tests.evaluation.run_retrieval_100 prepare --source-a artifacts/rrf-title-50/<成功运行目录> --output artifacts/retrieval-100-v1
python -m tests.evaluation.run_retrieval_100 run --output artifacts/retrieval-100-v1
```

`prepare`只审计并冻结，不访问模型；`run`检查数据及算法哈希后才执行。冻结后不得修改原文、标注、RRF常数60、分词、候选20或等权设置。新的真实Embedding调用只传虚构资料，沿用官方embedding-3，复用已保存的A向量；不读取业务数据库。每次运行结果独立保存于输出目录下`runs/`，不覆盖失败记录。

A、B在同一个扩展语料快照重跑，再分别报告A、B、合并；原80份语料下的A审计表另存，不能混拼。100题中95道有答案，5道无答案单列，因此主要指标分母为A=50、B=45、Total=95。有答案的失败记录按0计，不从分母移除。Hit是至少一个锚点命中，Recall是该题所有相关锚点的覆盖比例，MRR是最先命中的倒数且截断于5。

输出包含`retrieval_results_100.csv`、`retrieval_summary_100.csv`、`rrf_case_studies.json`、`no_answer_results.json`及完整原始排名。案例自动区分提高、相同、下降，保留全部记录；没有观察到的类型不得捏造。自检：`python -m pytest tests/test_retrieval_100.py`。

## 独立的 RRF 扩展实测（50 题）

`rrf_dataset_v2.py` 是新增合成压力样例，与下方旧 JSON 草稿分开：10 类企业协作场景、80 份原文、50 条问题（其中10条需要两份证据）。同时收录现行制度、旧版、相近业务及目录等干扰资料，运行前冻结题目与原文锚点，不按结果删题或调参。

```powershell
# 只导出题目、原文及哈希，不访问模型
python -m tests.evaluation.run_rrf_comparison --prepare-only
# 真实 Embedding 对照；需要本机官方 BigModel Key
python -m tests.evaluation.run_rrf_comparison
```

使用正式 `MainRAGAdapter`、bounded 分块、embedding-3/2048维、两路各20候选和等权 RRF（常数60）。三种检索分别运行同一组50题，不调用聊天模型。向量保存在独立 `data/rrf-v2-50/`，复跑使用缓存；不访问业务数据库或更改生产配置。

结果按运行时间写入 `artifacts/rrf-v2-50/`，包括 `REPORT.md`、80份原文 `materials.md`、冻结题目 `dataset.json`、完整前20名 `raw.json`、总体/分类指标 `summary.json` 和逐题差异 `differences.csv`。指标包含 Recall@1/3/5、MRR@5、nDCG@5，并保留 RRF 退步的题目。多来源题按目标数量计算 Recall，不把“找到一条”当作“全部找齐”。

计分自检：`python -m pytest tests/test_rrf_evaluation.py`。这套题由开发者构造，不是独立人工评测或生产随机样本；得分不能当作普遍模型能力，更不代表最终答案准确率。排序耗时不含预热阶段的网络 Embedding 调用。

## 标题检索与三路 RRF 对照

在上面的成功运行结果上执行：

```powershell
python -m tests.evaluation.run_title_rrf_comparison --baseline artifacts/rrf-v2-50/<运行目录>
```

脚本先校验原数据哈希、原文锚点和原双路RRF是否可复现，然后增加“标题BM25单路”和“向量＋正文BM25＋标题BM25三路RRF”。标题只使用原有文件名与章节标题，重复只计一次，不从答案标注补关键词或编号。每路20候选、常数60、等权，三路候选并集上限60，原双路上限40。

此实验复用已保存的真实向量与正文排名，不额外调用API，也不改生产默认检索。输出位于 `artifacts/rrf-title-50/`，保存五组共250条结果、全部50题差异、实际标题字段和可读报告。该数据集此前已被查看过，不属于新增盲测集；增加通道不保证提升效果。

自检：`python -m pytest tests/test_title_rrf_evaluation.py tests/test_rrf_evaluation.py`。

## 2026-09-28 提交的旧版草稿

这批 JSON 来自测试负责人的 2026-09-28 提交。当前仅完成材料合入和格式检查，**没有完成冻结，也没有真实模型评分结果**。

## 当前数量

- questions.json：24 条（资料问答 10、实体状态 8、混合 3、资料不足 3）。全部暂标为 test，尚无开发集。
- dependency-rules.json：8 条场景描述。
- extraction-samples.json：4 段文本及人工期望草稿。
- project-a、project-b 只有 README，没有配套资料和初始化脚本。

## 运行评分前需要补齐

1. 每个项目的原文、文档版本和准确段落锚点；当前“设计规范”等文字只是描述，不是可验证的证据地址。
2. 任务和成员初始化数据，以及逻辑样例 ID 到实际数据库 ID 的映射。不要把 expected_task_id 的 10、15 等直接当作另一台机器的业务 ID。
3. 依赖测试的完整 Snapshot：任务进度/状态、前后置关卡、阈值、需要日期、条件就绪日期及 evaluation_date。
4. 区分 dependency_status、timing_status 与 reason_codes。目前 expected_reason_code 混放了两类状态，不是协议里的 reason_codes。
5. 抽取样例的会议日期、时区和成员映射。“下周三”“10月10日”等不能无依据补成年月日；completed 也不是正式任务状态（正式枚举是 done）。字段请对照 shared/task_data.py 和 docs/DATA_CONTRACTS.md，输出仍是待审核建议。
6. 按既定课程要求划分开发/冻结集，记录数据版本及评审人，然后再运行主 RAG、实体定位和抽取评分。

上述信息涉及业务预期，保留提交方原始期望供复核，不在整合时猜测补齐。离线 JSON 检查只说明文件可读取、编号没有冲突，不说明 AI 效果通过。

# 主 RAG 100题检索评估

2026-09-29完成，100题×5种方法，共500条结果，0失败。材料、项目和人物均为虚构，不包含业务库、模型密钥或Embedding缓存。

[发布复核记录](../2026-09-29-retrieval-100-release.md)：239项测试通过、2项有条件跳过，说明浮点同分及换行约束。

## 结果与口径

Hit@5表示至少一条相关锚点进入前5。Recall@5为每题锚点覆盖比例的平均值。MRR@5为最先命中名次的倒数，超过5名计0。另保存micro recall和全证据覆盖率。

A有40道单锚点、10道双锚点题。B有37道单锚点、8道双锚点、5道无答案题。无答案单列，因此主指标分母分别为A=50、B=45、合并=95。

| 方法 | 合并 Hit@5 | 合并 Recall@5 | 合并 MRR@5 |
| --- | --- | --- | --- |
| Vector | 92/95=96.84% | 93.68% | 0.8691 |
| Body BM25 | 88/95=92.63% | 89.47% | 0.8021 |
| 双路 RRF | 92/95=96.84% | 94.21% | 0.8621 |
| Title BM25 | 58/95=61.05% | 58.42% | 0.3653 |
| 三路 RRF | 93/95=97.89% | 95.26% | 0.7795 |

双路与向量的命中题数相同，锚点覆盖略升、MRR略降。三路覆盖进一步提高，但排序代价更明显。双路补回A24、B45，同时丢失B06、B16，不删除负面样例。

- [完整A/B/合并对照表](runs/20260929T095508491040Z/D_100题对比.md)
- [旧50题审计与95%的解释](A_指标审计.md)：旧95%是多锚点macro recall，不是Hit。
- [Batch B设计](C_Batch_B设计.md)、[原文材料](materials.md)、[题目及锚点](dataset.json)
- [逐题CSV](runs/20260929T095508491040Z/retrieval_results_100.csv)、[汇总CSV](runs/20260929T095508491040Z/retrieval_summary_100.csv)
- [全部正反案例与Top5](runs/20260929T095508491040Z/rrf_case_studies.json)、[五个展示案例](E_PPT案例与结论.md)
- [冻结记录](frozen_manifest.json)、[完整排名](runs/20260929T095508491040Z/raw.json)

A、B使用相同101份扩展语料，历史A原80份语料结果另存，不能与新B混拼。B在评估前冻结，RRF常数60、候选20、等权，未根据结果调参。资料为开发者合成，非独立人工盲测或生产随机抽样。本轮只评价检索，不评价最终回答与拒答准确率。

## 离线复核

在项目根目录、安装README要求的依赖后执行，不需要API密钥：

```powershell
python -m tests.evaluation.audit_batch_a --source tests/records/retrieval-100/historical-a --output artifacts/retrieval-100-audit
python -m tests.evaluation.verify_retrieval_100 --dataset-dir tests/records/retrieval-100 --run-dir tests/records/retrieval-100/runs/20260929T095508491040Z
python -m pytest tests/test_retrieval_100.py tests/test_rrf_evaluation.py tests/test_title_rrf_evaluation.py -q
```

离线验证从原文锚点重算评分，并重算正文BM25、标题BM25及两种RRF。向量结果使用保存排名，本操作不会重新调用Embedding，因此不声称独立重算了向量模型。

发布复核发现：冻结版BM25按Python集合顺序累加，进程间可能出现约1e-15的浮点差异，使近乎同分的候选换位。验证器逐项重算得分，只容许绝对差不超过1e-12的同分换位，并在`floating_tie_reorderings`中明列。实际分差、缺失候选、重复候选或保存分数不符仍报错。RRF按归档候选顺序严格重算，指标按归档排名重算，未修改冻结算法或原结果。再次在线检索不保证同分项次序逐字一致。

冻结校验使用文件字节哈希，`.gitattributes`固定6个算法文件为LF，并保留Embedding适配文件冻结时的CRLF字节，避免系统换行转换造成假失败。不要修改冻结清单来绕过真实算法变更。

## 重新调用Embedding评估

先将整个记录目录复制到被Git忽略的本地工作目录，避免改动归档。配置自己的官方BigModel Embedding密钥后运行：

```powershell
New-Item -ItemType Directory -Path artifacts -Force
Copy-Item -LiteralPath tests/records/retrieval-100 -Destination artifacts/retrieval-100-replay -Recurse
python -m tests.evaluation.run_retrieval_100 run --output artifacts/retrieval-100-replay
```

无缓存时会产生Embedding调用，费用和可用性由账户决定。本次归档是固定历史结果，新运行单独保存，不能覆盖归档或将新结果称为本次结果。算法变化后的实验应建立新的评估版本。

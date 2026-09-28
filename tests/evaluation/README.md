# 评估样例草稿

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

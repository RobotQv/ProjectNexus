> 公开版账号说明：所有账号样例均为虚构演示数据，不是真实学号。登录方式以根 README 为准；仓库不附带 .env 或业务数据。

> 当前仅为项目资料预留目录，尚无配套资料或任务快照。问题位于上一级 questions.json，按 project 字段筛选；其余两个 JSON 也在上一级。不能直接运行模型评分。

# Project A - 冻结评估集隔离项目

本目录用于存放 Project A 的评估数据，与 Project B 隔离。

## 用途

- 存放 Project A 的测试问题、依赖规则和抽取样例
- 与 project-b/ 数据完全隔离，避免交叉污染
- 所有数据均为脱敏假数据，不包含真实人名、学号、企业资料

## 使用说明

评估执行时，测试人员应：
1. 选择一个项目目录（project-a 或 project-b）
2. 使用该目录下的 questions.json 执行问答测试
3. 使用 dependency-rules.json 执行依赖分析测试
4. 使用 extraction-samples.json 执行抽取测试

## 数据版本

- 创建日期：2026-09-28
- 版本：v1.0
- 维护人：测试负责人

# 公共契约（跨模块共享，不是第七人的算法任务）

由后端负责人协调维护，所有模块共同使用。只定义类型/协议/错误，不依赖 FastAPI、SQLAlchemy、app 或具体算法。

当前为 v2：contracts.py 已增加助手、工具、任务更新建议和候选风险协议；task_data.py 统一任务业务字段，structured.py 导出带类型分支的 JSON Schema。详见 [数据格式](../docs/DATA_CONTRACTS.md) 和 [模块接入](../docs/MODULE_CONTRACTS.md)。业务审核与历史由后端负责，不由算法直接操作。

- contracts.py：文件、正文块、证据、实体、建议、快照、分析结果和四个模块协议。
- llm.py：LLMProvider / LLMResult；工作流通过注入使用，不自行复制智谱连接代码。
- errors.py：AppError；错误说明不能包含密钥或供应商原始异常。

依赖方向：前端 → HTTP；app → shared；team_modules 各子模块 → shared。只有 team_modules/factory.py 装配三个算法工作区；算法之间不互相导入实现，shared 也不能反向导入任何一方。

旧的 app/integrations/contracts.py、app/core/errors.py、app/llm.py 保留公共类型的兼容导出，现有主干不需要立即改完导入；新算法代码统一从 shared 导入。两套路径指向同一个类，不是重复定义。

字段类型、日期语义、枚举、方法签名变化会影响所有人。先提交接口变更说明；业务含义不明确时先询问项目负责人，再同步修改契约、后端、模块、测试与文档。

独立模块单测可以构造这些对象，无须数据库、HTTP 服务或用户账号。单测中的 ID 是本地样例标识；完整联调时以本机后端实际分配的 ID 为准。

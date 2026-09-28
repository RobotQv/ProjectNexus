<script setup>
import ModalDialog from './ModalDialog.vue'
import { API_BASE } from '@/api/client.js'
import { isLive } from '@/stores/session.js'

defineEmits(['close'])
</script>

<template>
  <ModalDialog title="原型说明" wide @close="$emit('close')">
    <p class="note">
      页面按开题报告第六块的界面原型实现。当前为演示数据模式时，所有记录都是内置示例，
      不代表已实现的后端或真实项目状态。
    </p>

    <h4 style="font-size: 13px; margin: 16px 0 8px">可以验收的交互（6.1）</h4>
    <ol class="steps">
      <li>
        <b>新增资料</b>：项目资料库 → 上传资料。观察排队、处理中、成功；
        勾选“模拟一次失败”可看到失败原因与重试按钮。不能跳过入库。
      </li>
      <li>
        <b>资料问答</b>：AI 项目助手 → 输入“支付”看事实与来源；输入“联调”触发候选澄清；
        输入“上线”得到资料不足提示。
      </li>
      <li>
        <b>建议确认</b>：任务管理 → AI 助理生成草稿 → 提交审核 →
        提取结果确认逐条通过；重复点击“通过”返回同一个 target_id。
      </li>
      <li>
        <b>依赖比较</b>：依赖与风险 → 把关卡 90 改成 80，
        结果从“尚未到关卡”变为“当前关卡受阻”。
      </li>
      <li>
        <b>缺失日期</b>：点“演示缺失日期”清空前置任务的人工预计完成，
        返回“时间信息不足”，而不是低风险。
      </li>
    </ol>

    <hr class="hr" />

    <p class="note">
      “数据源”可切换到本机后端 <span class="code">{{ API_BASE }}</span> 做真实联调。
      账号由本机 <span class="code">python -m app.cli seed-students</span> 初始化，
      初始密码与学号相同；令牌只存在内存里。
    </p>
    <p class="note" style="margin-top: 8px">
      <template v-if="isLive">当前已连接后端，依赖与风险结论取自 <span class="code">POST /projects/{p}/analysis</span>。</template>
      <template v-else>
        演示模式下依赖与风险按 6.1 口径在前端试算并标注“演示规则”；
        正式结论必须取自 <span class="code">POST /projects/{p}/analysis</span>，前端不复制后端规则。
      </template>
    </p>
  </ModalDialog>
</template>

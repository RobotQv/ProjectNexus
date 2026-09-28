"""工程逻辑自测：在 JS 引擎里真实执行 frontend/web 的演示后端与依赖规则。

覆盖 6.1 的五条交互验收在 Vue 工程里的实现，以及依赖关卡的边界用例。
只测纯逻辑模块（demo/*.js），不依赖 Vue 与浏览器 API。

用法（需要 Node.js；不需要安装 QuickJS）：
    python frontend/tests/工程逻辑自测.py
"""
import io
import json
import pathlib
import re
import sys
import subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "web" / "src"


def load(rel):
    """把 ESM 源码降级成脚本可解析的形式：去掉 import/export。"""
    src = (SRC / rel).read_text(encoding="utf-8")
    out = re.sub(r"^\s*import\s+[^;]*?from\s*['\"][^'\"]+['\"]\s*;?\s*$", "", src, flags=re.M)
    out = re.sub(r"^\s*export\s*\{[^}]*\}\s*;?\s*$", "", out, flags=re.M)
    out = re.sub(r"^\s*export\s+(?=(const|let|var|function|class|async)\b)", "", out, flags=re.M)
    return out


BUNDLE = "\n".join([load("demo/data.js"), load("demo/risk.js"), load("demo/backend.js")])

TESTS = r"""
var out = { checks: [], errors: [] };
function ok(name, cond, extra) {
  out.checks.push({ name: name, pass: !!cond, extra: extra === undefined ? '' : String(extra) });
}

var backend = createDemoBackend();

// ---------- 1. 依赖规则：A70 / B80，关卡 90 → 80 ----------
function depCase(patch) {
  var base = { a: 70, b: 80, gate: 90, aRequired: 100, neededOn: '2026-09-19',
               forecastOn: '2026-09-20', gateKind: 'progress' };
  return evaluateDependency(Object.assign(base, patch || {}));
}
var c90 = depCase(), c80 = depCase({ gate: 80 });
ok('关卡90 → 尚未到关卡', c90.status === 'condition_unmet' && c90.body.indexOf('还没有到关卡') >= 0,
   c90.status + ' / ' + c90.headline);
ok('关卡80 → 当前关卡受阻', c80.status === 'blocked_now' && c80.headline.indexOf('当前关卡受阻') >= 0,
   c80.status + ' / ' + c80.headline);
ok('关卡80 判为 danger', c80.tone === 'danger', c80.tone);

// ---------- 2. 缺失日期 ----------
var cNo = depCase({ forecastOn: '' });
ok('缺失日期 → timing_unknown', cNo.timing === 'timing_unknown', cNo.timing);
ok('缺失日期 → 标题含时间信息不足', cNo.headline.indexOf('时间信息不足') >= 0, cNo.headline);
ok('缺失日期 → 明示不等于低风险', cNo.timingText.indexOf('不等于低风险') >= 0);
ok('缺失日期 → 不判为 on_time', cNo.timing !== 'on_time');
ok('预估早于需要日期 → on_time', depCase({ forecastOn: '2026-09-18' }).timing === 'on_time');
ok('A 达标 → satisfied', depCase({ gate: 80, a: 100 }).status === 'satisfied');

// ---------- 3. 关卡类型 ----------
ok('start 关卡：B 未开始即未到关卡',
   evaluateDependency({ a: 0, b: 0, gate: 100, aRequired: 100, gateKind: 'start',
     neededOn: '2026-09-20', forecastOn: '2026-09-18' }).status === 'condition_unmet');
ok('finish 关卡：B 到 100 才到关卡',
   evaluateDependency({ a: 50, b: 99, gate: 100, aRequired: 100, gateKind: 'finish',
     neededOn: '2026-09-20', forecastOn: '2026-09-18' }).status === 'condition_unmet');

// ---------- 4. 资料上传：排队 → 处理中 → 成功 ----------
async function uploadFlow(willFail) {
  var up = await backend.uploadDocument({ filename: '纪要.docx', document_type: '会议纪要',
    document_date: '2026-09-18', willFail: willFail });
  var steps = [];
  var j = await backend.job(up.job_id);
  steps.push(j.status);
  var d1 = (await backend.snapshot()).documents.find(function (d) { return d.id === up.document.id; });
  steps.push(d1.parse_status);
  j = await backend.job(up.job_id);
  var d2 = (await backend.snapshot()).documents.find(function (d) { return d.id === up.document.id; });
  steps.push(d2.parse_status + '/' + d2.index_status);
  j = await backend.job(up.job_id);
  var d3 = (await backend.snapshot()).documents.find(function (d) { return d.id === up.document.id; });
  steps.push(d3.parse_status + '/' + d3.index_status);
  return { job: j, doc: d3, steps: steps, jobId: up.job_id };
}

// ---------- 5. 建议确认幂等 ----------
async function suggestionFlow() {
  var snap = await backend.snapshot();
  var target = snap.suggestions.find(function (s) { return s.review_status === 'pending'; });
  var before = (await backend.snapshot()).tasks.length;
  var first = await backend.reviewSuggestion(target.id, { action: 'confirm',
    expected_version: target.version, overrides: { title: '已核对后的标题', assignee_id: 2 } });
  var afterFirst = (await backend.snapshot()).tasks.length;
  // 重复同结果确认：即使仍带旧版本，也必须返回原目标
  var second = await backend.reviewSuggestion(target.id, { action: 'confirm',
    expected_version: target.version, overrides: {} });
  var afterSecond = (await backend.snapshot()).tasks.length;
  var created = (await backend.snapshot()).tasks.filter(function (t) {
    return t.source_suggestion_id === target.id; });
  return { target: target, first: first, second: second, before: before,
           afterFirst: afterFirst, afterSecond: afterSecond, created: created };
}

// ---------- 6. 驳回 ----------
async function rejectFlow() {
  var snap = await backend.snapshot();
  var target = snap.suggestions.find(function (s) { return s.review_status === 'pending'; });
  var before = (await backend.snapshot()).tasks.length;
  var out = await backend.reviewSuggestion(target.id, { action: 'reject',
    expected_version: target.version, note: '依据不足' });
  return { status: out.review_status, added: (await backend.snapshot()).tasks.length - before };
}

// ---------- 7. 任务 AI 助理：草稿 → 提交 → 审核 ----------
async function assistantFlow() {
  var beforeTasks = (await backend.snapshot()).tasks.length;
  var res = await backend.assistant('task_assistant', '补一个支付回调失败重试任务，甲负责');
  var drafts = (await backend.snapshot()).suggestions.filter(function (s) {
    return s.review_status === 'draft' && s.source_kind === 'task_assistant'; });
  var afterAsk = (await backend.snapshot()).tasks.length;
  var draft = drafts[drafts.length - 1];
  var submitted = await backend.submitSuggestion(draft.id, draft.version);
  var afterSubmit = (await backend.snapshot()).tasks.length;
  var afterReview;
  try {
    afterReview = await backend.reviewSuggestion(submitted.id, { action: 'confirm',
      expected_version: submitted.version, overrides: { assignee_id: 1, planned_end: '2026-09-23' } });
  } catch (e) { afterReview = { error: e.message }; }
  var finalTasks = (await backend.snapshot()).tasks.length;
  return { res: res, draft: draft, submitted: submitted, approved: afterReview,
           beforeTasks: beforeTasks, afterAsk: afterAsk, afterSubmit: afterSubmit,
           finalTasks: finalTasks };
}

// ---------- 8. 项目助手四种 outcome ----------
async function assistantOutcomes() {
  var pay = await backend.assistant('project_assistant', '支付那块进度怎样');
  var clar = await backend.assistant('project_assistant', '联调做到哪了');
  var ins = await backend.assistant('project_assistant', '这个什么时候上线');
  return { pay: pay, clar: clar, ins: ins };
}

(async function () {
  try {
    var up = await uploadFlow(false);
    ok('上传后任务为 succeeded', up.job.status === 'succeeded', up.job.status);
    ok('轮询推进：处理中 → 解析就绪 → 索引就绪',
       up.steps[0] === 'running' && up.steps[1] === 'running' && up.steps[2] === 'ready/running'
       && up.steps[3] === 'ready/ready', up.steps.join(' → '));
    ok('解析与索引状态分开判定', up.steps[2] !== up.steps[3], up.steps[2]);

    var fail = await uploadFlow(true);
    ok('失败分支 → failed 且有原因',
       fail.job.status === 'failed' && !!fail.job.error_message, fail.job.error_message || 'none');
    ok('失败后文档标为 failed', fail.doc.parse_status === 'failed', fail.doc.parse_status);

    var retried = await backend.retryDocument(fail.doc.id);
    ok('重试后重新排队', retried.document.parse_status === 'pending' && !retried.document.error_message);
    await backend.job(retried.job_id);
    await backend.job(retried.job_id);
    await backend.job(retried.job_id);
    var afterRetry = (await backend.snapshot()).documents.find(function (d) { return d.id === fail.doc.id; });
    ok('重试后索引就绪', afterRetry.index_status === 'ready', afterRetry.index_status);

    var sug = await suggestionFlow();
    ok('首次通过创建一条正式任务', sug.afterFirst === sug.before + 1,
       sug.before + ' → ' + sug.afterFirst);
    ok('重复确认返回同一目标', sug.first.target_id === sug.second.target_id,
       sug.first.target_id + ' / ' + sug.second.target_id);
    ok('重复确认不重复创建', sug.afterSecond === sug.afterFirst,
       sug.before + ' → ' + sug.afterFirst + ' → ' + sug.afterSecond);
    ok('overrides 写入正式任务',
       sug.created.length === 1 && sug.created[0].title === '已核对后的标题'
       && sug.created[0].assignee_id === 2,
       sug.created.length ? sug.created[0].title : 'none');
    ok('正式任务可追溯来源建议',
       sug.created.length === 1 && sug.created[0].source_suggestion_id === sug.target.id);

    var rej = await rejectFlow();
    ok('驳回不创建任务', rej.status === 'rejected' && rej.added === 0, rej.status + ' +' + rej.added);

    var ai = await assistantFlow();
    ok('AI 助理生成草稿', !!ai.draft, ai.draft ? ai.draft.proposed_payload.title : 'none');
    ok('草稿阶段不写正式任务', ai.afterAsk === ai.beforeTasks,
       ai.beforeTasks + ' → ' + ai.afterAsk);
    ok('未识别的负责人留空而不编造', ai.draft.proposed_payload.assignee_id === null);
    ok('保留 validation_warnings', ai.draft.validation_warnings.length > 0,
       ai.draft.validation_warnings[0]);
    ok('提交后进入 pending', ai.submitted.review_status === 'pending', ai.submitted.review_status);
    ok('提交后仍不写正式任务', ai.afterSubmit === ai.beforeTasks,
       ai.beforeTasks + ' → ' + ai.afterSubmit);
    ok('审核通过后才创建任务',
       ai.approved.review_status === 'approved' && ai.finalTasks === ai.beforeTasks + 1,
       (ai.approved.review_status || ai.approved.error) + ' tasks=' + ai.finalTasks);
    ok('审核时可用 overrides 补字段',
       ai.approved.proposed_payload.assignee_id === 1
       && ai.approved.proposed_payload.planned_end === '2026-09-23',
       JSON.stringify(ai.approved.proposed_payload || {}));

    var oc = await assistantOutcomes();
    ok('支付 → answered 且有事实与来源',
       oc.pay.outcome === 'answered' && oc.pay.facts.length > 0 && oc.pay.evidence.length > 0,
       oc.pay.outcome + ' facts=' + oc.pay.facts.length + ' ev=' + oc.pay.evidence.length);
    ok('联调 → clarify 有候选',
       oc.clar.outcome === 'clarify' && oc.clar.candidates.length > 0,
       oc.clar.outcome + ' cand=' + oc.clar.candidates.length);
    ok('上线 → insufficient 且无证据',
       oc.ins.outcome === 'insufficient' && oc.ins.evidence.length === 0, oc.ins.outcome);
    ok('助手结果标记 is_demo', oc.pay.is_demo === true);
  } catch (e) {
    out.errors.push(String(e && e.stack ? e.stack : e));
  }
  out.done = true;
})();
"""


def main():
    # Node 自然执行 Promise 微任务；退出前确认所有异步断言都已执行。
    runner = BUNDLE + TESTS + "\nprocess.on('beforeExit', () => { if (!out.done) out.errors.push('异步检查未完成'); console.log(JSON.stringify(out)); });"
    run = subprocess.run(["node", "--input-type=commonjs", "-"], input=runner,
                         capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
    result = json.loads(run.stdout)

    if result["errors"]:
        print("=== 运行期异常 ===")
        for e in result["errors"]:
            print("  " + e)

    print("=== 验收检查 ===")
    failed = 0
    for c in result["checks"]:
        if not c["pass"]:
            failed += 1
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}"
              + (f"  ← {c['extra']}" if not c["pass"] and c["extra"] else ""))

    print(f"\n合计 {len(result['checks'])} 项，失败 {failed} 项")
    ok = failed == 0 and not result["errors"]
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

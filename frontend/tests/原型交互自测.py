"""原型交互自测：在 JS 引擎里真实执行《项目交互原型.html》，逐条核对 6.1 的交互验收。

不是只调函数 —— 用真实的 DOM 事件委托和假定时器驱动点击与轮询。

用法（需要 pip install dukpy）：
    python frontend/tests/原型交互自测.py
"""
import io
import json
import pathlib
import re
import sys

import dukpy

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROTOTYPE = ROOT / "frontend" / "prototype" / "项目交互原型.html"

STUB = r"""
var __els = {};
function mkEl(id){
  return { id:id, innerHTML:'', value:'', textContent:'', files:[], dataset:{}, style:{},
    classList:{ toggle:function(){}, add:function(){}, remove:function(){}, contains:function(){return false} },
    addEventListener:function(){}, appendChild:function(){}, remove:function(){},
    scrollIntoView:function(){}, closest:function(){ return null; } };
}
function reg(id, value){ if(!__els[id]) __els[id]=mkEl(id); if(value!==undefined) __els[id].value=value; return __els[id]; }
['page','nav','crumb','topActions','modals','toasts','menuBtn','chatBox'].forEach(function(i){ reg(i); });

var __docListeners = [];
var document = {
  getElementById: function(id){ return __els[id] || null; },
  addEventListener: function(type, fn){ if(type==='click') __docListeners.push(fn); },
  createElement: function(){ return mkEl('new'); },
  body: { classList:{ toggle:function(){}, add:function(){}, remove:function(){} } }
};

// 假定时器：手动 tick 驱动轮询
var __timers = {}, __timerSeq = 0;
function setInterval(fn){ __timerSeq++; __timers[__timerSeq] = fn; return __timerSeq; }
function clearInterval(id){ delete __timers[id]; }
function setTimeout(fn){ __timerSeq++; __timers[__timerSeq] = fn; return __timerSeq; }
function __tick(){ Object.keys(__timers).forEach(function(k){ var fn = __timers[k]; if(fn) fn(); }); }

// 精确模拟 CSS 属性选择器：只在与 data-act / data-nav 的值完全相等时命中
function __matches(sel, act, nav){
  if(sel === '[data-nav]') return !!nav;
  if(sel === '[data-act]') return !!act;
  var re = /\[data-act="([a-z\-]+)"\]/g, m;
  while((m = re.exec(sel))){ if(m[1] === act) return true; }
  return false;
}
function __click(act, id, opts){
  opts = opts || {};
  var nav = opts.nav || null;
  var target = {
    closest: function(sel){ return __matches(sel, nav ? null : act, nav) ? target : null; },
    classList:{ toggle:function(){}, add:function(){}, remove:function(){}, contains:function(){return false} },
    dataset:{ act:act, id:String(id) },
    textContent:'', value:''
  };
  var ev = { target: target, key:'', preventDefault:function(){} };
  __docListeners.forEach(function(fn){ fn(ev); });
}
function __listeners(){ return __docListeners.length; }
var window = {};
var fetch = function(){ return Promise.resolve({ ok:true, headers:{get:function(){return 'application/json'}}, json:function(){ return {}; } }); };
"""

TESTS = r"""
var out = { errors: [], checks: [] };
function ok(name, cond, extra){
  out.checks.push({ name:name, pass: !!cond, extra: extra===undefined ? '' : String(extra) });
}
function silent(fn){ var t = toast; toast = function(){}; try { return fn(); } finally { toast = t; } }

/* ---- 1. 六个页面都能渲染 ---- */
var VIEWS = ['viewOverview','viewTasks','viewDocuments','viewAssistant','viewSuggestions','viewDependencies'];
var rendered = {};
VIEWS.forEach(function(fn){
  try {
    var h = eval(fn + '()');
    rendered[fn] = h.length;
    ok('渲染 ' + fn, h.length > 400, h.length + ' 字符');
  } catch(e){ out.errors.push(fn + ': ' + e.message); ok('渲染 ' + fn, false, e.message); }
});
ok('事件委托已注册', __listeners() >= 4, __listeners() + ' 个 click 监听');

/* ---- 2. 6.1 依赖比较：A70 / B80，关卡 90 → 80 ---- */
function depCase(patch){
  state.deps = Object.assign({ a:70, b:80, gate:90, aRequired:100,
    neededOn:'2026-09-19', forecastOn:'2026-09-20', gateKind:'progress' }, patch);
  var r = evaluateDependency(state.deps);
  return { s:r.status, t:r.timing, h:r.headline, tone:r.tone, body:r.body, tt:r.timingText };
}
var c90 = depCase({}), c80 = depCase({ gate:80 });
ok('关卡90 → 尚未到关卡', c90.s === 'condition_unmet' && c90.body.indexOf('还没有到关卡') >= 0, c90.s+' / '+c90.h);
ok('关卡80 → 当前关卡受阻', c80.s === 'blocked_now' && c80.h.indexOf('当前关卡受阻') >= 0, c80.s+' / '+c80.h);
ok('关卡80 判为危险', c80.tone === 'danger', c80.tone);

/* ---- 3. 6.1 缺失日期 ---- */
var cNoDate = depCase({ forecastOn:'' });
ok('缺失日期 → timing_unknown', cNoDate.t === 'timing_unknown', cNoDate.t);
ok('缺失日期 → 标题为时间信息不足', cNoDate.h.indexOf('时间信息不足') >= 0, cNoDate.h);
ok('缺失日期 → 明示不等于低风险', cNoDate.tt.indexOf('不等于低风险') >= 0, cNoDate.tt);
ok('预估早于需要日期 → on_time', depCase({ forecastOn:'2026-09-18' }).t === 'on_time');
ok('A 达标 → satisfied', depCase({ gate:80, a:100 }).s === 'satisfied');

/* ---- 4. 依赖页交互：输入 + 应用（走真实点击路径） ---- */
state.deps = Object.assign({ a:70, b:80, gate:90, aRequired:100,
  neededOn:'2026-09-19', forecastOn:'2026-09-20', gateKind:'progress' });
ok('依赖页关卡90含尚未到关卡', viewDependencies().indexOf('尚未到关卡') >= 0);
reg('dep-a','70'); reg('dep-b','80'); reg('dep-gate','80');
reg('dep-needed','2026-09-19'); reg('dep-forecast','2026-09-20');
silent(function(){ __click('dep-apply'); });
ok('点击应用后关卡变为受阻', state.deps.gate === 80 && viewDependencies().indexOf('当前关卡受阻') >= 0,
   'gate='+state.deps.gate);
ok('B 任务进度同步到 80', taskOf(18).progress === 80, taskOf(18).progress);
silent(function(){ __click('dep-clear-forecast'); });
ok('演示缺失日期清空后为时间信息不足',
   state.deps.forecastOn === '' && viewDependencies().indexOf('时间信息不足') >= 0);

/* ---- 5. 6.1 新增资料：上传 → 轮询 → 成功 / 失败重试 ---- */
state.route = 'documents';
state.data.documents = [];
reg('up-file'); __els['up-file'].files = [{ name:'09-18 项目会议纪要.docx', size:18422 }];
reg('up-type','会议纪要'); reg('up-date','2026-09-18');
silent(function(){ __click('do-upload'); });
var doc0 = state.data.documents[0];
var jobId = Object.keys(state.jobs)[0];
ok('上传后进入排队', doc0 && doc0.parse_status === 'pending' && state.jobs[jobId].status === 'queued',
   doc0 ? doc0.parse_status : 'no doc');
__tick();
ok('轮询一次 → 处理中', doc0.parse_status === 'running' && state.jobs[jobId].status === 'running', doc0.parse_status);
__tick();
ok('轮询两次 → 解析就绪、索引处理中',
   doc0.parse_status === 'ready' && doc0.index_status === 'running', doc0.parse_status+'/'+doc0.index_status);
ok('解析就绪但索引未就绪（两者分开判定）', doc0.index_status !== 'ready');
__tick();
ok('轮询三次 → 索引就绪', doc0.index_status === 'ready' && doc0.index_version, doc0.index_version);
ok('资料页展示三态文案', viewDocuments().indexOf('已入库') >= 0 || viewDocuments().indexOf('处理中') >= 0);

// 失败分支
reg('up-file'); __els['up-file'].files = [{ name:'扫描件.pdf', size:900 }];
silent(function(){ __click('sim-fail'); });
silent(function(){ __click('do-upload'); });
var doc1 = state.data.documents[1];
var jobId1 = Object.keys(state.jobs).filter(function(k){ return k !== jobId; })[0];
__tick(); __tick();
ok('失败分支 → failed 且有错误原因',
   state.jobs[jobId1].status === 'failed' && !!doc1.error_message, doc1.error_message || 'none');
ok('失败后页面出现重试按钮', viewDocuments().indexOf('重试入库') >= 0);

silent(function(){ __click('doc-retry', doc1.id); });
ok('重试后重新排队', doc1.parse_status === 'pending' && !doc1.error_message, doc1.parse_status);
__tick(); __tick();
ok('重试后索引就绪', doc1.index_status === 'ready', doc1.index_status);

// 离开页面应停止轮询
state.data.documents = [];
reg('up-file'); __els['up-file'].files = [{ name:'a.txt', size:10 }];
silent(function(){ __click('do-upload'); });
var keys = Object.keys(state.jobs);
var jobId2 = keys[keys.length - 1];
ok('离开页面前该任务仍在排队', state.jobs[jobId2].status === 'queued', state.jobs[jobId2].status);
state.route = 'overview';
__tick(); __tick(); __tick();
ok('离开页面后停止轮询', state.jobs[jobId2].status === 'queued',
   '期望 queued，实际 ' + state.jobs[jobId2].status);
ok('离开页面的上传未继续改文档状态',
   state.data.documents[0].parse_status === 'pending', state.data.documents[0].parse_status);
state.route = 'documents';

/* ---- 6. 6.1 建议确认：编辑字段后确认，重复点击不重复创建 ---- */
function fill(sid, title){
  reg('sug-title-' + sid, title);
  reg('sug-assignee-' + sid, '2');
  reg('sug-module-' + sid, '前端');
  reg('sug-planned-' + sid, '2026-09-23');
  reg('sug-desc-' + sid, '');
}
fill(601, '订单页面对接支付结果回调（已核对）');
var tasksBefore = state.data.tasks.length;
silent(function(){ __click('sug-confirm', 601); });
var s601 = state.data.suggestions.filter(function(s){ return s.id===601; })[0];
ok('首次通过创建一条正式任务',
   state.data.tasks.length === tasksBefore + 1 && s601.review_status === 'approved',
   'target=' + s601.target_id);
var target1 = s601.target_id;
var tasksMid = state.data.tasks.length;
silent(function(){ __click('sug-confirm', 601); });
ok('重复点击返回同一目标且不重复创建',
   s601.target_id === target1 && state.data.tasks.length === tasksMid,
   'target=' + s601.target_id + ' tasks=' + state.data.tasks.length);
var made = state.data.tasks.filter(function(t){ return t.source_suggestion_id === 601; });
ok('编辑后的字段写入正式任务',
   made.length === 1 && made[0].title.indexOf('已核对') >= 0 && made[0].assignee_id === 2,
   made.length ? made[0].title : 'none');

var tasksB4Rej = state.data.tasks.length;
silent(function(){ __click('sug-reject', 602); });
reg('rj-note','依据不足');
silent(function(){ __click('do-reject', 602); });
var s602 = state.data.suggestions.filter(function(s){ return s.id===602; })[0];
ok('驳回不写入正式任务',
   state.data.tasks.length === tasksB4Rej && s602.review_status === 'rejected',
   s602.review_status);
ok('驳回后待审列表清空', viewSuggestions().split('data-sug="').length - 1 === 0,
   viewSuggestions().split('data-sug="').length - 1 + ' 张待审卡');
ok('驳回结果进入已处理表', viewSuggestions().indexOf('已驳回') >= 0);

/* ---- 7. AI 助理（新建任务）：草稿 → 核对 → 提交审核 ---- */
state.data.suggestions = state.data.suggestions.filter(function(s){ return s.review_status !== 'draft'; });
var tasksB4Ai = state.data.tasks.length;
silent(function(){ __click('ai-task'); });
ok('AI 助理面板打开', document.getElementById('modals').innerHTML.indexOf('任务 AI 助理') >= 0);

reg('ta-input', '补一个支付回调失败重试任务，甲负责');
silent(function(){ __click('ta-ask'); });
var drafts = state.data.suggestions.filter(function(s){ return s.review_status === 'draft'; });
ok('AI 助理生成草稿', drafts.length === 1, 'drafts=' + drafts.length);
ok('草稿阶段不写正式任务', state.data.tasks.length === tasksB4Ai, 'tasks=' + state.data.tasks.length);
var d0 = drafts[0];
ok('未识别的负责人留空而不编造', d0.proposed_payload.assignee_id === null);
ok('保留 validation_warnings 提醒补充', d0.validation_warnings.length > 0, d0.validation_warnings[0]);
ok('草稿卡片按钮是“提交审核”而不是“通过”',
   document.getElementById('modals').innerHTML.indexOf('提交审核') >= 0
   && document.getElementById('modals').innerHTML.indexOf('sug-confirm') < 0);

var did = d0.id;
fill(did, '支付回调失败重试');
reg('sug-desc-' + did, '失败后按退避重试三次');
silent(function(){ __click('ta-submit', did); });
var submitted = state.data.suggestions.filter(function(s){ return s.id===did; })[0];
ok('草稿提交后进入 pending（仍不写任务）',
   submitted.review_status === 'pending' && state.data.tasks.length === tasksB4Ai,
   submitted.review_status + ' / tasks=' + state.data.tasks.length);
ok('提交写入 submitted_at', !!submitted.submitted_at, String(submitted.submitted_at));
ok('提交者修正后的字段被保存', submitted.proposed_payload.title === '支付回调失败重试'
   && submitted.proposed_payload.assignee_id === 2,
   submitted.proposed_payload.title + ' / assignee=' + submitted.proposed_payload.assignee_id);
ok('提交后清空未识别字段的警告',
   submitted.validation_warnings.length === 0, submitted.validation_warnings.join(';'));

var tasksB4Review = state.data.tasks.length;
silent(function(){ __click('sug-confirm', did); });
var approved = state.data.suggestions.filter(function(s){ return s.id===did; })[0];
ok('审核通过后才创建正式任务',
   approved.review_status === 'approved' && state.data.tasks.length === tasksB4Review + 1,
   'target=' + approved.target_id);
ok('AI 助理新建的任务可追溯到来源建议',
   state.data.tasks.filter(function(t){ return t.source_suggestion_id === did; }).length === 1);

/* ---- 8. 问答四种 outcome ---- */
function ask(text){
  reg('askInput', text);
  state.chat.messages = [];
  silent(function(){ __click('ask'); });
  var ai = state.chat.messages.filter(function(m){ return m.role === 'ai'; })[0];
  return { outcome: ai ? ai.outcome : 'none',
           candidates: state.chat.candidates.length,
           facts: ai ? ai.facts.length : 0,
           evidence: ai ? ai.evidence.length : 0,
           html: viewAssistant() };
}
var rPay = ask('支付那块进度怎样');
ok('支付 → answered', rPay.outcome === 'answered', rPay.outcome);
ok('支付 → 给出当前事实与文档来源', rPay.facts > 0 && rPay.evidence > 0,
   'facts=' + rPay.facts + ' evidence=' + rPay.evidence);
ok('支付 → 展示路由链路', rPay.html.indexOf('轻RAG') >= 0);

var rClar = ask('联调做到哪了');
ok('联调 → clarify', rClar.outcome === 'clarify', rClar.outcome);
ok('澄清分支给出候选供选择', rClar.candidates > 0, rClar.candidates + ' 个候选');
ok('澄清时不编造事实', rClar.facts === 0, 'facts=' + rClar.facts);

var rIns = ask('这个什么时候上线');
ok('上线 → insufficient', rIns.outcome === 'insufficient', rIns.outcome);
ok('资料不足时明确说明而非编造原因',
   rIns.html.indexOf('资料不足') >= 0 && rIns.evidence === 0, 'evidence=' + rIns.evidence);

ok('登录 → answered', ask('登录做到哪了').outcome === 'answered');
ask('联调做到哪了');                              // 重新进入 clarify 分支
silent(function(){ __click('pick-candidate', 19); });
ok('澄清后可带入明确任务', state.chat.draftInput.indexOf('TASK-19') >= 0, state.chat.draftInput);

/* ---- 9. 转义 ---- */
ok('esc 处理尖括号', esc('<img src=x onerror=1>').indexOf('&lt;img') === 0);
ok('esc 处理引号', esc('a"b\'c').indexOf('&quot;') >= 0 && esc("a'b").indexOf('&#39;') >= 0);
ok('页面输出已转义用户标题',
   (function(){ state.data.tasks[0].title = '<script>x</script>';
     var h = viewTasks(); state.data.tasks[0].title = '支付模块开发';
     return h.indexOf('<script>x') < 0; })());

out.rendered = rendered;
JSON.stringify(out);
"""


def main():
    html = PROTOTYPE.read_text(encoding="utf-8")
    script = re.findall(r"<script>(.*?)</script>", html, re.S)[0]

    interp = dukpy.JSInterpreter()
    result = json.loads(interp.evaljs(STUB + script + TESTS))

    print("=== 渲染字符数 ===")
    for k, v in result["rendered"].items():
        print(f"  {k:20s} {v}")

    if result["errors"]:
        print("\n=== 运行期异常 ===")
        for e in result["errors"]:
            print("  " + e)

    print("\n=== 验收检查 ===")
    failed = []
    for c in result["checks"]:
        if not c["pass"]:
            failed.append(c)
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}"
              + (f"  ← {c['extra']}" if not c["pass"] and c["extra"] else ""))

    print(f"\n合计 {len(result['checks'])} 项，失败 {len(failed)} 项")
    print("RESULT:", "PASS" if not failed and not result["errors"] else "FAIL")
    return 0 if not failed and not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())

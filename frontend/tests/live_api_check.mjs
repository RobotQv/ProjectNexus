// 由 tests/test_frontend_live.py 使用临时后端调用，不连接开发者的业务数据库。
import assert from 'node:assert/strict'
import { session, login, switchToDemo } from '../web/src/stores/session.js'
import { workspace, load, clearWorkspace, createTask, updateTask, taskHistory } from '../web/src/stores/workspace.js'
import { projectApi, dependencyApi, analysisApi, taskApi, documentApi } from '../web/src/api/resources.js'

assert.equal(await login('web-test', 'test-password-123'), true)
assert.equal(session.projectId, null)
const project = await projectApi.create({ name: '前端真实接口联调' })
session.projectId = project.id
await load()
assert.equal(workspace.loaded, true)
assert.equal(workspace.project.id, project.id)
assert.equal(workspace.members.length, 1)
const task = await createTask({ title: '登录接口', status: 'in_progress', progress: 20 })
assert.ok(task?.id)
const edited = await updateTask(task.id, { expected_version: task.version, progress: 70 })
assert.equal(edited.progress, 70)
assert.equal((await taskHistory(task.id)).length, 2)
await assert.rejects(taskApi.patch(project.id, task.id, { expected_version: task.version, progress: 90 }),
  error => error.status === 409)
const next = await createTask({ title: '页面联调', status: 'in_progress', progress: 80 })
await dependencyApi.create(project.id, {
  predecessor_task_id: task.id, successor_task_id: next.id,
  predecessor_required_progress: 100, successor_gate: 'progress', successor_gate_progress: 80,
})
const result = await analysisApi.run(project.id)
assert.equal(result.rule_version, 'risk-v1')
assert.equal(result.findings[0].dependency_status, 'blocked_now')
const form = new FormData()
form.append('file', new Blob(['会议资料'], { type: 'text/plain' }), 'meeting.txt')
const uploaded = await documentApi.upload(project.id, form)
assert.ok(uploaded.document.id && uploaded.job_id)
clearWorkspace()
switchToDemo()
await load()
assert.equal(workspace.loaded, true)
assert.notEqual(workspace.project.name, project.name)
console.log('PASS: frontend live login, empty project, creation, task editing/history/conflict, risk, upload, demo switch')

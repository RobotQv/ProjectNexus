/**
 * 会话与数据源。
 *
 * - demo：使用内置示例数据，无后端也能完整演示，页面显示 DEMO 标识；
 * - live：登录本机后端，全部页面走真实 HTTP 接口。
 * 令牌只保存在内存里，不写入 localStorage，也不提交到代码仓库。
 */
import { computed, reactive } from 'vue'

import { ApiError, describeError, setToken, setUnauthorizedHandler } from '@/api/client.js'
import { authApi, projectApi } from '@/api/resources.js'
import { toast } from './toasts.js'

const DEFAULT_MODE = import.meta.env.VITE_DEFAULT_MODE === 'live' ? 'live' : 'demo'

export const session = reactive({
  mode: DEFAULT_MODE,
  user: null,
  token: '',
  projects: [],
  projectId: null,
  loggingIn: false,
  ready: false,
})

export const isLive = computed(() => session.mode === 'live' && !!session.token)
export const isDemo = computed(() => !isLive.value)

/** 令牌失效时统一回到登录，不保留半登录状态。 */
setUnauthorizedHandler(() => {
  if (!session.token) return
  clearSession()
  toast('登录已失效，请重新登录', 'err')
})

function clearSession() {
  session.token = ''
  session.user = null
  session.projects = []
  session.projectId = null
  setToken('')
}

export function switchToDemo() {
  clearSession()
  session.mode = 'demo'
  session.ready = false
}

export function switchToLive() {
  session.mode = 'live'
  session.ready = false
}

export async function login(loginName, password) {
  session.loggingIn = true
  try {
    const out = await authApi.login(loginName, password)
    session.token = out.access_token
    session.user = out.user
    setToken(out.access_token)
    const page = await projectApi.list({ limit: 200 })
    session.projects = page.items
    if (!page.items.length) {
      toast('该账号还没有项目，请先创建测试项目', 'err')
      session.projectId = null
    } else {
      session.projectId = page.items[0].id
      toast(`登录成功：${out.user.display_name}`, 'ok')
    }
    session.mode = 'live'
    return true
  } catch (error) {
    clearSession()
    toast(describeError(error), 'err')
    return false
  } finally {
    session.loggingIn = false
  }
}

export function logout() {
  clearSession()
  session.mode = 'demo'
  toast('已退出登录，回到演示数据')
}

export { ApiError }

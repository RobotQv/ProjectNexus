import { createRouter, createWebHashHistory } from 'vue-router'

import OverviewView from '@/views/OverviewView.vue'

/** 左侧导航与开题报告第六块的原型一致。 */
export const NAV = [
  { name: 'overview', label: '项目总览', icon: '◆' },
  { name: 'tasks', label: '任务管理', icon: '▤' },
  { name: 'documents', label: '项目资料库', icon: '▦' },
  { name: 'assistant', label: 'AI 项目助手', icon: '◇' },
  { name: 'suggestions', label: '提取结果确认', icon: '☑' },
  { name: 'dependencies', label: '依赖与风险', icon: '⇥' },
]

const routes = [
  { path: '/', redirect: '/overview' },
  { path: '/overview', name: 'overview', component: OverviewView, meta: { label: '项目总览' } },
  { path: '/tasks', name: 'tasks', component: () => import('@/views/TasksView.vue'), meta: { label: '任务管理' } },
  { path: '/documents', name: 'documents', component: () => import('@/views/DocumentsView.vue'), meta: { label: '项目资料库' } },
  { path: '/assistant', name: 'assistant', component: () => import('@/views/AssistantView.vue'), meta: { label: 'AI 项目助手' } },
  { path: '/suggestions', name: 'suggestions', component: () => import('@/views/SuggestionsView.vue'), meta: { label: '提取结果确认' } },
  { path: '/dependencies', name: 'dependencies', component: () => import('@/views/DependenciesView.vue'), meta: { label: '依赖与风险' } },
  { path: '/:pathMatch(.*)*', redirect: '/overview' },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

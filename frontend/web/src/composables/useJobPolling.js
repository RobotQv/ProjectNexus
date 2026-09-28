import { onUnmounted, ref } from 'vue'

import { pollJob } from '@/stores/workspace.js'

/**
 * 后台任务轮询。
 *
 * 上传返回 202 只表示排队，必须轮询到 succeeded / failed 才能下结论。
 * 组件卸载（离开页面）时自动停表，避免页面离开后继续请求。
 */
export function useJobPolling() {
  const timers = new Map()
  const jobs = ref({})

  function stop(jobId) {
    const timer = timers.get(jobId)
    if (timer) {
      clearInterval(timer)
      timers.delete(jobId)
    }
  }

  function stopAll() {
    for (const timer of timers.values()) clearInterval(timer)
    timers.clear()
  }

  /**
   * @param {number} jobId
   * @param {(job: object) => void} onSettled 任务终态回调
   */
  function watch(jobId, onSettled) {
    if (timers.has(jobId)) return
    jobs.value[jobId] = { id: jobId, status: 'queued' }
    const timer = setInterval(async () => {
      const job = await pollJob(jobId)
      if (!job) {
        stop(jobId)
        return
      }
      jobs.value[jobId] = job
      if (job.status === 'succeeded' || job.status === 'failed') {
        stop(jobId)
        if (onSettled) onSettled(job)
      }
    }, 2000)
    timers.set(jobId, timer)
  }

  onUnmounted(stopAll)

  return { jobs, watch, stop, stopAll }
}

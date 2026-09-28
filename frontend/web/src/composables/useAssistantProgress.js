/** 只轮询已执行阶段，不用计时器假造模型处理步骤；卸载后停止轮询。 */
import { onUnmounted, ref } from 'vue'
import { assistantApi } from '@/api/resources.js'
import { isLive, session } from '@/stores/session.js'
import { askAssistant } from '@/stores/workspace.js'

export function useAssistantProgress() {
  const progress = ref(null)
  let timer
  let generation = 0
  let disposed = false
  function stop() { generation++; clearTimeout(timer) }
  onUnmounted(() => { disposed = true; stop() })

  async function send(entry, text, key, onFailed) {
    stop()
    const active = generation
    const pid = session.projectId
    progress.value = null
    if (!isLive.value) return askAssistant(entry, text, key)
    let last = null
    async function poll() {
      if (disposed || active !== generation) return
      try {
        last = await assistantApi.progress(pid, key)
        if (disposed || active !== generation) return
        progress.value = last
      } catch (error) {
        if (error.status === 401 || error.status === 403) return
        // 首次 POST 尚未提交时允许 404；网络中断不能伪装为模型失败。
      }
      if (!last?.terminal && !disposed && active === generation) timer = setTimeout(poll, 900)
    }
    // 重试先找原 run：成功直接读取，运行中只恢复观察，不重复生成。
    try { last = await assistantApi.progress(pid, key) } catch (error) {
      if (error.status !== 404 && error.status !== 0) return null
    }
    if (last?.status === 'failed') {
      progress.value = last
      onFailed?.()
      return null
    }
    if (last?.status === 'succeeded') return assistantApi.run(pid, last.run_id)
    void poll()
    if (last?.status === 'running') {
      const deadline = Date.now() + 600000
      while (!disposed && active === generation && !last?.terminal && Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 500))
      }
      stop()
      if (last?.status === 'succeeded' && !disposed) return assistantApi.run(pid, last.run_id)
      if (last?.status === 'failed') onFailed?.()
      return null
    }
    const out = await askAssistant(entry, text, key)
    try { progress.value = await assistantApi.progress(pid, key) } catch { /* 保留最后已知阶段 */ }
    stop()
    if (progress.value?.status === 'failed') onFailed?.()
    return out
  }
  return { progress, send }
}

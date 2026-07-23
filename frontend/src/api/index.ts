import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

declare module 'axios' {
  interface AxiosRequestConfig {
    /** 为 true 时不弹出全局错误 toast（由调用方自行处理） */
    skipGlobalError?: boolean
  }
}

const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (resp) => resp,
  (err) => {
    let msg = err?.response?.data?.detail || err.message || '请求失败'
    if (err?.code === 'ECONNABORTED' || /timeout/i.test(err?.message || '')) {
      msg = '请求超时：教材拆分与索引耗时较长，请稍候再试；若后端正在重启请运行 backend\\dev.bat'
    } else if (!err?.response) {
      msg = '无法连接后端服务，请确认 backend 已在 8000 端口运行'
    }
    if (err?.response?.status === 401) {
      try {
        useAuthStore().logout()
      } catch {
        localStorage.removeItem('token')
      }
      const path = window.location.pathname
      if (path !== '/login' && path !== '/register' && path !== '/welcome') {
        import('@/router').then(({ default: router }) => {
          if (router.currentRoute.value.path !== '/welcome') {
            router.replace('/welcome')
          }
        })
      }
    }
    if (!err?.config?.skipGlobalError) {
      ElMessage.error(msg)
    }
    return Promise.reject(err)
  },
)

export default http

/**
 * SSE 流式请求：通过 fetch + ReadableStream 解析 text/event-stream。
 * - onChunk: message 事件文本增量回调
 * - onEvent: 任意 event 类型回调 (name, data)
 */
export async function sseStream(
  url: string,
  body: any,
  onChunk: (text: string) => void,
  opts: { signal?: AbortSignal; onEvent?: (name: string, data: string) => void } = {},
): Promise<void> {
  const { signal, onEvent } = opts
  const resp = await fetch(`/api${url}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!resp.ok || !resp.body) {
    const txt = await resp.text().catch(() => '请求失败')
    throw new Error(txt)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let curEvent = 'message'
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      const s = line.trim()
      if (!s) { curEvent = 'message'; continue }
      if (s.startsWith('event:')) {
        curEvent = s.slice(6).trim()
      } else if (s.startsWith('data:')) {
        const data = s.slice(5).trim()
        if (data === '[DONE]') return
        if (curEvent === 'message') {
          try {
            const obj = JSON.parse(data)
            onChunk(typeof obj === 'object' && obj && 'text' in obj ? obj.text : data)
          } catch {
            onChunk(data)
          }
        }
        if (onEvent) onEvent(curEvent, data)
      }
    }
  }
}

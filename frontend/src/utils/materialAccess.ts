/** 带认证访问资料文件（与课程问答附件一致：非视频一律下载，视频弹窗播放） */
import { ElMessage } from 'element-plus'

export interface MaterialRec {
  material_id?: number
  type?: string
  title?: string
  file_url?: string
  video_start_sec?: number | null
  chapter_title?: string
  page?: string | null
  pages?: string[]
}

export function resolveMaterialRec(rec: MaterialRec): MaterialRec {
  const file_url = rec.file_url || (rec.material_id ? `/api/materials/file/${rec.material_id}` : '')
  return { ...rec, file_url }
}

function normalizeUrl(url: string): string {
  if (!url) throw new Error('资料链接无效')
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  if (url.startsWith('/api/')) return url
  if (url.startsWith('/')) return `/api${url}`
  return `/api/${url}`
}

function parseErrorMessage(txt: string, status: number): string {
  try {
    const obj = JSON.parse(txt)
    if (typeof obj.detail === 'string') return obj.detail
  } catch { /* ignore */ }
  if (status === 401) return '登录已过期，请重新登录'
  if (status === 403) return '无权访问该资料'
  if (status === 404) return '文件不存在或已被删除'
  return txt || `无法获取文件 (${status})`
}

export async function fetchMaterialBlob(fileUrl: string): Promise<Blob> {
  const url = normalizeUrl(fileUrl)
  const resp = await fetch(url, {
    headers: {
      Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
    },
  })
  if (!resp.ok) {
    const txt = await resp.text().catch(() => '')
    throw new Error(parseErrorMessage(txt, resp.status))
  }
  return resp.blob()
}

function triggerDownload(blobUrl: string, filename: string) {
  const a = document.createElement('a')
  a.href = blobUrl
  a.download = filename || 'download'
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function guessFilename(rec: MaterialRec, blob: Blob): string {
  const base = (rec.title || '资料').replace(/[\\/:*?"<>|]/g, '_').slice(0, 100)
  if (/\.[a-z0-9]{2,5}$/i.test(base)) return base
  const extMap: Record<string, string> = {
    pdf: '.pdf', ppt: '.ppt', word: '.docx', video: '.mp4',
  }
  const type = rec.type || ''
  if (extMap[type]) return base + extMap[type]
  if (blob.type === 'application/pdf') return base + '.pdf'
  if (blob.type.includes('presentation')) return base + '.pptx'
  if (blob.type.includes('word')) return base + '.docx'
  if (blob.type.startsWith('video/')) return base + '.mp4'
  return base
}

function isVideoType(rec: MaterialRec): boolean {
  return rec.type === 'video'
}

/** 打开资料：视频返回 blob 供弹窗；其余文件触发下载（不在浏览器内阅读） */
export async function openMaterialFile(
  rec: MaterialRec,
): Promise<{ kind: 'video'; blobUrl: string; startSec: number } | { kind: 'downloaded' }> {
  const item = resolveMaterialRec(rec)
  if (!item.file_url) throw new Error('资料链接无效')

  const blob = await fetchMaterialBlob(item.file_url)
  const blobUrl = URL.createObjectURL(blob)

  if (isVideoType(item)) {
    return { kind: 'video', blobUrl, startSec: item.video_start_sec || 0 }
  }

  triggerDownload(blobUrl, guessFilename(item, blob))
  setTimeout(() => URL.revokeObjectURL(blobUrl), 15_000)
  return { kind: 'downloaded' }
}

export async function handleMaterialClick(
  rec: MaterialRec,
  onVideo: (blobUrl: string, startSec: number) => void,
) {
  try {
    const result = await openMaterialFile(rec)
    if (result.kind === 'video') {
      onVideo(result.blobUrl, result.startSec)
    } else {
      ElMessage.success('文件下载已开始，请使用本地应用打开')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '无法获取资料')
  }
}

export function materialActionLabel(type?: string): string {
  if (type === 'video') return '观看'
  return '下载'
}

export function fmtVideoTime(s: number) {
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${r.toString().padStart(2, '0')}`
}

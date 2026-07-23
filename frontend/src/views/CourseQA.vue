<script setup lang="ts">
import { ref, nextTick, onMounted, onUnmounted, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Paperclip, Close, Microphone } from '@element-plus/icons-vue'
import http, { sseStream } from '@/api'
import MarkdownView from '@/components/MarkdownView.vue'
import { useAuthStore } from '@/stores/auth'
import { useCourseAgentStore } from '@/stores/courseAgent'
import { useAgentBoundClasses } from '@/composables/useAgentBoundClasses'
import { handleMaterialClick, fmtVideoTime, type MaterialRec } from '@/utils/materialAccess'

interface Chapter { id: number; title: string }
interface Recommend {
  material_id: number; type: string; title: string
  chapter_id: number; chapter_title: string; score: number
  video_start_sec: number | null; video_end_sec: number | null
  page: string | null; pages?: string[]
  keywords?: string[]
  file_url: string
}
interface ChatAttachment {
  name: string
  type: string
  text: string
  truncated?: boolean
  size?: number
  file_id?: string
  blobUrl?: string
  mimeType?: string
  legacy?: boolean
}
interface Msg {
  role: 'user' | 'assistant'
  content: string
  recommends?: Recommend[]
  attachments?: ChatAttachment[]
}
interface LlmCfg {
  id: number
  provider: string
  model: string
  is_default: boolean
}
interface Prov { provider: string; label: string }
interface ClassItem { id: number; name: string }
interface Enrollment {
  class_id: number
  class_name: string
  course_id: number
  course_name: string
}
interface QaHistoryItem {
  id: number
  question: string
  answer: string
  has_full_answer?: boolean
  model_name: string
  attachments?: ChatAttachment[]
  created_at: string | null
}

const MAX_ATTACHMENTS = 5
const ACCEPT_TYPES = '.pdf,.doc,.docx,.ppt,.pptx,.txt,.md,.c,.h,.cpp,.java,.py,.js,.ts,.vue,.html,.css,.json,.xml,.csv,.jpg,.jpeg,.png,.gif,.webp'

const chapters = ref<Chapter[]>([])
const chapterId = ref<number | undefined>(undefined)
const classes = ref<ClassItem[]>([])
const selectedClassId = ref<number | undefined>(undefined)
const myEnrollments = ref<Enrollment[]>([])
const userStore = useAuthStore()
const agentStore = useCourseAgentStore()
const { loadScopedClasses, pickClassId, isSharedPreview } = useAgentBoundClasses()
const router = useRouter()
const needsAgentGuide = computed(() => !agentStore.current)
const agentPlanned = computed(() => agentStore.current && !agentStore.isActive())
const isStudent = computed(() => userStore.user?.role === 'student')
const isTeacher = computed(() => userStore.user?.role === 'teacher')
const classLabel = computed(() => {
  if (isStudent.value) {
    const cid = activeClassId.value
    const e = myEnrollments.value.find(x => x.class_id === cid)
    return e ? `${e.class_name}（${e.course_name}）` : ''
  }
  const c = classes.value.find(x => x.id === selectedClassId.value)
  return c?.name || ''
})
const activeClassId = computed(() => {
  if (isStudent.value) {
    const courseId = agentStore.current?.course_id
    if (!courseId) return undefined
    const e = myEnrollments.value.find(x => x.course_id === courseId)
    return e?.class_id
  }
  return selectedClassId.value
})
const studentNeedsEnrollment = computed(() =>
  isStudent.value && !!agentStore.current?.course_id && !activeClassId.value
)
const configs = ref<LlmCfg[]>([])
const providers = ref<Prov[]>([])
const selectedConfigId = ref<number | undefined>(undefined)
const messages = ref<Msg[]>([
  { role: 'assistant', content: '你好，我是课程智能体。可以问任何课程相关问题，我会从课程资料中检索并回答，同时推荐相关学习资源。也可上传文件或语音输入提问。' },
])
const input = ref('')
const loading = ref(false)
const fileParsing = ref(false)
const boxRef = ref<HTMLElement | null>(null)
const videoDialog = ref(false)
const videoBlobUrl = ref('')
const videoStart = ref(0)
const materialLoading = ref<string | null>(null)
const attachments = ref<ChatAttachment[]>([])

const qaHistory = ref<QaHistoryItem[]>([])
const historyLoading = ref(false)
const historyDrawer = ref(false)
const selectedHistory = ref<QaHistoryItem | null>(null)
const attachmentDrawer = ref(false)
const selectedAttachment = ref<ChatAttachment | null>(null)
const fetchedBlobUrl = ref<string | null>(null)

const voiceListening = ref(false)
const voiceTranscribing = ref(false)
const voiceSupported = ref(false)
const voiceEngine = ref<'whisper' | 'webspeech' | 'none'>('none')
const voiceHint = ref('')
let speechRecognition: SpeechRecognition | null = null
let voiceBaseText = ''
let mediaRecorder: MediaRecorder | null = null
let mediaStream: MediaStream | null = null
let audioChunks: Blob[] = []

const VOICE_ERROR_MSG: Record<string, string> = {
  network: '浏览器语音服务网络不可用，请安装 Whisper 后使用录音识别，或检查网络',
  'no-speech': '未检测到语音，请靠近麦克风后重试',
  'audio-capture': '无法访问麦克风，请检查设备与权限',
  'not-allowed': '请允许浏览器使用麦克风',
  'service-not-allowed': '当前环境不支持浏览器语音，请使用 localhost 或 HTTPS',
  'language-not-supported': '当前浏览器不支持中文语音识别',
}

function voiceErrorMessage(code: string) {
  return VOICE_ERROR_MSG[code] || `语音识别失败（${code}），请重试`
}

function cleanupMediaStream(clearChunks = true) {
  if (mediaStream) {
    mediaStream.getTracks().forEach(t => t.stop())
    mediaStream = null
  }
  mediaRecorder = null
  if (clearChunks) audioChunks = []
}

function pickRecorderMime(): string {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',
  ]
  return candidates.find(t => MediaRecorder.isTypeSupported(t)) || ''
}

function stopVoiceInput() {
  if (speechRecognition && voiceListening.value && voiceEngine.value === 'webspeech') {
    try { speechRecognition.stop() } catch { /* ignore */ }
  }
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    try { mediaRecorder.stop() } catch { /* ignore */ }
  } else {
    voiceListening.value = false
    cleanupMediaStream()
  }
}

async function loadVoiceStatus() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition
  try {
    const { data } = await http.get('/chat/voice-status', { timeout: 5000 })
    voiceHint.value = data.hint || ''
    if (data.available) {
      voiceEngine.value = 'whisper'
      voiceSupported.value = true
      return
    }
    if (data.whisper && !data.ffmpeg) {
      voiceEngine.value = 'none'
      voiceSupported.value = false
      return
    }
  } catch { /* fallback */ }
  if (SR && (window.isSecureContext || location.hostname === 'localhost')) {
    voiceEngine.value = 'webspeech'
    voiceSupported.value = true
    voiceHint.value = '浏览器语音识别'
    initWebSpeech(SR)
    return
  }
  voiceEngine.value = 'none'
  voiceSupported.value = false
}

function initWebSpeech(SR: typeof window.SpeechRecognition) {
  const rec = new SR()
  rec.lang = 'zh-CN'
  rec.continuous = true
  rec.interimResults = true
  rec.onresult = (event: SpeechRecognitionEvent) => {
    let interim = ''
    let final = ''
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const text = event.results[i][0].transcript
      if (event.results[i].isFinal) final += text
      else interim += text
    }
    if (final) voiceBaseText += final
    input.value = voiceBaseText + interim
  }
  rec.onerror = (event: SpeechRecognitionErrorEvent) => {
    voiceListening.value = false
    if (event.error === 'aborted') return
    ElMessage.error(voiceErrorMessage(event.error))
  }
  rec.onend = () => { voiceListening.value = false }
  speechRecognition = rec
}

async function startWhisperRecording() {
  if (!navigator.mediaDevices?.getUserMedia) {
    ElMessage.error('当前浏览器不支持录音')
    return
  }
  if (!window.MediaRecorder) {
    ElMessage.error('当前浏览器不支持 MediaRecorder 录音')
    return
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    })
  } catch {
    ElMessage.error('请允许浏览器使用麦克风')
    return
  }
  voiceBaseText = input.value
  audioChunks = []
  const mime = pickRecorderMime()
  const options = mime ? { mimeType: mime } : undefined
  try {
    mediaRecorder = new MediaRecorder(mediaStream, options)
  } catch {
    mediaRecorder = new MediaRecorder(mediaStream)
  }
  const recordMime = mediaRecorder.mimeType || mime || 'audio/webm'
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) audioChunks.push(e.data)
  }
  mediaRecorder.onerror = () => {
    voiceListening.value = false
    cleanupMediaStream()
    ElMessage.error('录音失败，请重试')
  }
  mediaRecorder.onstop = async () => {
    voiceListening.value = false
    const chunks = [...audioChunks]
    const blob = new Blob(chunks, { type: recordMime })
    cleanupMediaStream()
    if (!blob.size) {
      ElMessage.warning('未录到有效音频，请按住麦克风说话 1–2 秒后再结束')
      return
    }
    voiceTranscribing.value = true
    try {
      const ext = recordMime.includes('ogg') ? 'ogg' : recordMime.includes('mp4') ? 'm4a' : 'webm'
      const fd = new FormData()
      fd.append('file', blob, `voice.${ext}`)
      const { data } = await http.post('/chat/transcribe', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120000,
      })
      const text = (data.text || '').trim()
      if (text) {
        input.value = voiceBaseText ? `${voiceBaseText}${text}` : text
        ElMessage.success('语音识别完成')
      } else {
        ElMessage.warning('未识别到有效内容')
      }
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '语音识别失败'
      ElMessage.error(msg)
    } finally {
      voiceTranscribing.value = false
    }
  }
  mediaRecorder.start(250)
  voiceListening.value = true
}

function startWebSpeech() {
  if (!speechRecognition) return
  voiceBaseText = input.value
  voiceListening.value = true
  try {
    speechRecognition.start()
  } catch {
    voiceListening.value = false
    ElMessage.error('无法启动语音识别，请稍后重试')
  }
}

async function toggleVoiceInput() {
  if (voiceTranscribing.value) return
  if (!voiceSupported.value || voiceEngine.value === 'none') {
    await loadVoiceStatus()
    if (!voiceSupported.value || voiceEngine.value === 'none') {
      ElMessage.warning(voiceHint.value || '语音输入不可用：请安装 Whisper + ffmpeg 后重启后端')
      return
    }
  }
  if (voiceListening.value) {
    stopVoiceInput()
    return
  }
  if (voiceEngine.value === 'whisper') {
    await startWhisperRecording()
    return
  }
  startWebSpeech()
}

function fileTypeLabel(type: string) {
  const map: Record<string, string> = {
    pdf: 'PDF', word: 'Word', ppt: 'PPT', text: '文本', document: '文档', image: '图片',
  }
  return map[type] || type
}

function revokeBlobUrl(url?: string) {
  if (url) URL.revokeObjectURL(url)
}

function removeAttachment(index: number) {
  revokeBlobUrl(attachments.value[index]?.blobUrl)
  attachments.value.splice(index, 1)
}

async function onFileSelect(file: { raw: File }) {
  if (attachments.value.length >= MAX_ATTACHMENTS) {
    ElMessage.warning(`最多上传 ${MAX_ATTACHMENTS} 个文件`)
    return
  }
  const raw = file.raw
  fileParsing.value = true
  try {
    const fd = new FormData()
    fd.append('file', raw)
    const { data } = await http.post('/chat/parse-file', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
    if (attachments.value.some(a => a.name === data.name)) {
      ElMessage.warning('该文件已添加')
      return
    }
    attachments.value.push({
      ...data,
      blobUrl: URL.createObjectURL(raw),
      mimeType: raw.type,
    })
    if (data.truncated) {
      ElMessage.warning(`${data.name} 内容较长，已截断部分文本`)
    } else {
      ElMessage.success(`已解析 ${data.name}`)
    }
  } finally {
    fileParsing.value = false
  }
}

async function loadQaHistory() {
  historyLoading.value = true
  try {
    const params: Record<string, number> = { page: 1, size: 20 }
    if (agentStore.current?.id) params.agent_id = agentStore.current.id
    const { data } = await http.get('/agents/course/history', { params })
    qaHistory.value = data.items
  } finally {
    historyLoading.value = false
  }
}

function openHistory(item: QaHistoryItem) {
  selectedHistory.value = item
  historyDrawer.value = true
}

function reuseQuestion(q: string) {
  input.value = q.replace(/\s*\[附件:.*\]$/, '').trim()
  historyDrawer.value = false
}

function historyQuestionText(q: string) {
  const text = q.replace(/\s*\[附件:.*\]$/, '').trim()
  return text || '（基于附件提问）'
}

function resolveHistoryAttachments(item: QaHistoryItem): ChatAttachment[] {
  if (item.attachments?.length) {
    return item.attachments.map(a => ({
      name: a.name,
      type: a.type || 'document',
      text: a.text || '',
      file_id: a.file_id || undefined,
      truncated: a.truncated,
      size: a.size,
    }))
  }
  const m = item.question.match(/\[附件:\s*(.+?)\]\s*$/)
  if (!m) return []
  return m[1].split(/[、,]/).map(name => ({
    name: name.trim(),
    type: 'document',
    text: '',
    legacy: true,
  }))
}

function attachmentAccessUrl(att: ChatAttachment): string | null {
  if (!att.file_id) return null
  const token = localStorage.getItem('token') || ''
  if (!token) return null
  return `/api/chat/attachments/${att.file_id}?token=${encodeURIComponent(token)}`
}

function attachmentPreviewUrl(att: ChatAttachment): string {
  return attachmentAccessUrl(att) || att.blobUrl || ''
}

async function ensureAttachmentPreview(att: ChatAttachment): Promise<ChatAttachment> {
  if (attachmentAccessUrl(att) || att.blobUrl || !att.file_id) return att
  const resp = await fetch(`/api/chat/attachments/${att.file_id}`, {
    headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}` },
  })
  if (!resp.ok) throw new Error('附件加载失败')
  const blob = await resp.blob()
  if (fetchedBlobUrl.value) revokeBlobUrl(fetchedBlobUrl.value)
  const blobUrl = URL.createObjectURL(blob)
  fetchedBlobUrl.value = blobUrl
  return { ...att, blobUrl, mimeType: blob.type }
}

async function openAttachment(att: ChatAttachment) {
  if (att.legacy) {
    ElMessage.warning('该历史记录未保存附件内容，请重新上传文件后提问')
    return
  }
  selectedAttachment.value = att
  attachmentDrawer.value = true
}

function canOpenInBrowser(att: ChatAttachment) {
  return att.type === 'pdf' || att.type === 'image'
}

function attachmentActionLabel(att: ChatAttachment) {
  return canOpenInBrowser(att) ? '在新窗口打开' : '下载原文件'
}

function triggerFileDownload(url: string, filename: string) {
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

async function openAttachmentExternal(att: ChatAttachment) {
  try {
    const serverUrl = attachmentAccessUrl(att)
    if (canOpenInBrowser(att)) {
      if (serverUrl) {
        window.open(serverUrl, '_blank', 'noopener,noreferrer')
        return
      }
      const loaded = await ensureAttachmentPreview(att)
      if (loaded.blobUrl) {
        triggerFileDownload(loaded.blobUrl, loaded.name)
        ElMessage.info('当前环境无法直接预览，已改为下载')
      } else {
        ElMessage.warning('无法获取原文件')
      }
      return
    }
    if (serverUrl) {
      triggerFileDownload(serverUrl, att.name)
      ElMessage.success('文件下载已开始')
      return
    }
    const loaded = await ensureAttachmentPreview(att)
    if (loaded.blobUrl) {
      triggerFileDownload(loaded.blobUrl, loaded.name)
      ElMessage.success('文件下载已开始')
    } else {
      ElMessage.warning('无法获取原文件')
    }
  } catch {
    ElMessage.error('附件打开失败')
  }
}

watch(attachmentDrawer, (open) => {
  if (!open) {
    if (fetchedBlobUrl.value) {
      revokeBlobUrl(fetchedBlobUrl.value)
      fetchedBlobUrl.value = null
    }
    selectedAttachment.value = null
  }
})

function fmtHistoryTime(iso: string | null) {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(0, 16)
}

async function loadChapters() {
  const params: Record<string, number> = {}
  if (agentStore.current?.course_id) params.course_id = agentStore.current.course_id
  if (agentStore.current?.id) params.agent_id = agentStore.current.id
  const { data } = await http.get<Chapter[]>('/chapters', { params })
  chapters.value = data
}

async function loadClasses() {
  if (isStudent.value) {
    try {
      const { data } = await http.get<Enrollment[]>('/classes/my')
      myEnrollments.value = data
    } catch {
      myEnrollments.value = []
    }
    return
  }
  if (isTeacher.value) {
    const data = await loadScopedClasses()
    classes.value = data
    selectedClassId.value = pickClassId(data, selectedClassId.value, 'qa_class_id')
  }
}

function onClassChange(id: number) {
  selectedClassId.value = id
  localStorage.setItem('qa_class_id', String(id))
}

function providerLabel(p: string) {
  return providers.value.find(x => x.provider === p)?.label || p
}

function configLabel(cfg: LlmCfg) {
  const name = `${providerLabel(cfg.provider)} · ${cfg.model}`
  return cfg.is_default ? `${name}（默认）` : name
}

async function loadConfigs() {
  const [cfgRes, provRes] = await Promise.all([
    http.get<LlmCfg[]>('/llm-configs'),
    http.get<Prov[]>('/llm-configs/providers'),
  ])
  configs.value = cfgRes.data
  providers.value = provRes.data
  const saved = Number(localStorage.getItem('chat_config_id') || 0)
  if (saved && cfgRes.data.some(c => c.id === saved)) {
    selectedConfigId.value = saved
  } else {
    const def = cfgRes.data.find(c => c.is_default)
    selectedConfigId.value = def?.id ?? cfgRes.data[0]?.id
  }
}

function onConfigChange(id: number) {
  selectedConfigId.value = id
  localStorage.setItem('chat_config_id', String(id))
}

async function scrollBottom() {
  await nextTick()
  if (boxRef.value) boxRef.value.scrollTop = boxRef.value.scrollHeight
}

async function send() {
  const text = input.value.trim()
  const files = [...attachments.value]
  if ((!text && !files.length) || loading.value) return
  stopVoiceInput()
  if (!selectedConfigId.value) {
    ElMessage.warning('请先选择大模型')
    return
  }
  if (!activeClassId.value) {
    ElMessage.warning(isTeacher.value ? '请先选择班级' : '未加入班级，无法检索课程资料')
    return
  }
  if (!agentStore.current?.id) {
    ElMessage.warning('请先从「课程智能体」选择一门课程')
    return
  }
  if (!agentStore.isActive()) {
    ElMessage.warning('当前课程智能体尚未上线，请从课程智能体列表选择已上线课程')
    return
  }
  input.value = ''
  attachments.value = []
  loading.value = true
  messages.value.push({
    role: 'user',
    content: text,
    attachments: files.map(f => ({ ...f })),
  })
  messages.value.push({ role: 'assistant', content: '', recommends: [] })
  const idx = messages.value.length - 1
  await scrollBottom()

  const history = messages.value
    .slice(0, -1)
    .filter(m => m.content || (m.role === 'user' && m.attachments?.length))
    .map(m => ({ role: m.role, content: m.content || '（基于附件提问）' }))

  try {
    await sseStream(
      '/agents/course/ask',
      {
        question: text,
        chapter_id: chapterId.value,
        class_id: activeClassId.value,
        agent_id: agentStore.current?.id,
        history,
        config_id: selectedConfigId.value,
        attachments: files.map(f => ({
          name: f.name,
          text: f.text,
          type: f.type,
          file_id: f.file_id,
          truncated: f.truncated,
          size: f.size,
        })),
      },
      (chunk) => { messages.value[idx].content += chunk; scrollBottom() },
      {
        onEvent: (name, data) => {
          if (name === 'recommend') {
            try {
              const obj = JSON.parse(data)
              messages.value[idx].recommends = obj.recommendations || []
            } catch {}
          } else if (name === 'error') {
            try {
              const obj = JSON.parse(data)
              messages.value[idx].content += `\n[出错] ${obj.text || ''}`
            } catch {}
          }
        },
      },
    )
  } catch (e: any) {
    messages.value[idx].content += `\n[出错] ${e.message || e}`
  } finally {
    loading.value = false
    await loadQaHistory()
  }
}

function onEnter(e: KeyboardEvent) {
  if (e.shiftKey) return
  e.preventDefault()
  send()
}

function showVideo(blobUrl: string, startSec: number) {
  if (videoBlobUrl.value) URL.revokeObjectURL(videoBlobUrl.value)
  videoBlobUrl.value = blobUrl
  videoStart.value = startSec
  videoDialog.value = true
  nextTick(() => {
    const v = document.querySelector('video#qa-video') as HTMLVideoElement | null
    if (v) {
      v.currentTime = startSec
      v.play().catch(() => {})
    }
  })
}

function onVideoDialogClose() {
  if (videoBlobUrl.value) {
    URL.revokeObjectURL(videoBlobUrl.value)
    videoBlobUrl.value = ''
  }
}

async function openRecommend(rec: Recommend | MaterialRec) {
  const key = `${rec.material_id || rec.file_url}`
  if (materialLoading.value) return
  materialLoading.value = key
  try {
    await handleMaterialClick(rec, showVideo)
  } finally {
    materialLoading.value = null
  }
}

function recActionLabel(rec: Recommend | MaterialRec) {
  if (rec.type === 'video') {
    const sec = rec.video_start_sec || 0
    return sec ? `观看 ${fmtTime(sec)}` : '观看'
  }
  return '下载'
}

const typeTag = (t: string) => {
  const map: Record<string, string> = { pdf: 'danger', ppt: 'warning', video: 'success', word: 'info' }
  return map[t] || ''
}

function fmtTime(s: number) {
  return fmtVideoTime(s)
}

onMounted(async () => {
  await agentStore.restoreAgent()
  if (agentStore.current?.name) {
    messages.value[0].content =
      `你好，我是${agentStore.current.name}。可以问任何课程相关问题，我会从课程资料中检索并回答，同时推荐相关学习资源。也可上传文件或语音输入提问。`
  }
  await loadVoiceStatus()
  await loadClasses()
  await Promise.all([loadChapters(), loadConfigs(), loadQaHistory()])
})

onUnmounted(() => {
  stopVoiceInput()
  cleanupMediaStream()
  for (const a of attachments.value) revokeBlobUrl(a.blobUrl)
})
</script>

<template>
  <el-row :gutter="16">
    <el-col :span="18">
      <el-card shadow="never" class="chat-card">
        <template #header>
          <div class="qa-header-actions">
              <el-select
                v-if="isTeacher"
                v-model="selectedClassId"
                placeholder="选择班级"
                style="width: 200px"
                :disabled="loading || !classes.length"
                @change="onClassChange"
              >
                <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
              <el-tag v-else-if="classLabel" type="info">{{ classLabel }}</el-tag>
              <el-select
                v-model="selectedConfigId"
                placeholder="选择模型"
                style="width: 260px"
                :disabled="loading || !configs.length"
                @change="onConfigChange"
              >
                <el-option
                  v-for="c in configs"
                  :key="c.id"
                  :label="configLabel(c)"
                  :value="c.id"
                />
              </el-select>
              <el-select v-model="chapterId" placeholder="限定章节（可选）" clearable style="width: 200px">
                <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
              </el-select>
          </div>
        </template>

        <el-alert
          v-if="isSharedPreview"
          type="info"
          :closable="false"
          show-icon
          title="正在体验共享智能体问答"
          description="检索范围来自源教师共享资料。若回答空洞，请确认左侧班级筛选为源侧班级。"
          style="margin-bottom: 8px"
        />

        <el-alert
          v-if="needsAgentGuide"
          type="warning"
          :closable="false"
          title="尚未选择课程"
          style="margin-bottom: 8px"
        >
          <template #default>
            请先从
            <el-link type="primary" @click="router.push('/agents')">课程智能体</el-link>
            选择一门课程，或从课程首页进入本页。
          </template>
        </el-alert>

        <el-alert
          v-if="agentPlanned"
          type="info"
          :closable="false"
          :title="`${agentStore.current?.name} 尚未上线`"
          description="该课程正在筹备中，暂无法使用课程问答。请选择已上线的 C 语言课程智能体。"
          style="margin-bottom: 8px"
        />

        <el-alert
          v-if="studentNeedsEnrollment"
          type="warning"
          :closable="false"
          title="尚未加入该课程班级"
          description="请先在「我的班级」使用邀请码加入对应课程班级后，再使用课程问答。"
          style="margin-bottom: 8px"
        />

        <el-alert
          v-if="isTeacher && !classes.length"
          type="warning"
          :closable="false"
          title="您尚未管理任何班级，请先在「班级管理」中创建或认领班级"
          style="margin-bottom: 8px"
        />

        <div ref="boxRef" class="chat-box">
          <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
            <div class="bubble">
              <div class="role">{{ m.role === 'user' ? '我' : 'AI' }}</div>
              <div v-if="m.attachments?.length" class="msg-attachments">
                <el-tag
                  v-for="(att, j) in m.attachments"
                  :key="j"
                  size="small"
                  type="info"
                  effect="plain"
                  class="attach-tag"
                  @click="openAttachment(att)"
                >
                  {{ att.name }}
                </el-tag>
              </div>
              <MarkdownView v-if="m.role === 'assistant'" :content="m.content || (loading && i === messages.length - 1 ? '检索中…' : '')" />
              <div v-else class="chat-stream">
                <template v-if="m.content">{{ m.content }}</template>
                <span v-else-if="m.attachments?.length" class="attach-only-hint">（基于附件提问）</span>
              </div>
              <div v-if="m.recommends && m.recommends.length" class="recommends">
                <div class="rec-title">建议学习：</div>
                <div
                  v-for="r in m.recommends"
                  :key="r.material_id + '-' + (r.page || '') + '-' + (r.video_start_sec ?? '')"
                  class="rec-item"
                >
                  <el-tag :type="typeTag(r.type) as any" size="small">{{ r.type }}</el-tag>
                  <span class="rec-name">{{ r.title }}</span>
                  <span class="rec-chapter">{{ r.chapter_title }}</span>
                  <span v-if="r.pages?.length" class="rec-page">PDF第{{ r.pages.join('、') }}页</span>
                  <span v-else-if="r.page" class="rec-page">PDF第{{ r.page }}页</span>
                  <span v-if="r.type === 'video' && r.video_start_sec != null" class="rec-page">
                    视频 {{ fmtTime(r.video_start_sec) }}
                  </span>
                  <span v-if="r.keywords?.length" class="rec-kw">{{ r.keywords.join('、') }}</span>
                  <el-button
                    text type="primary" size="small"
                    :loading="materialLoading === `${r.material_id || r.file_url}`"
                    @click="openRecommend(r)"
                  >{{ recActionLabel(r) }}</el-button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="input-area">
          <div v-if="attachments.length" class="attachment-bar">
            <div
              v-for="(att, i) in attachments"
              :key="att.name + i"
              class="attachment-chip"
            >
              <span class="attachment-name attach-link" :title="att.name" @click="openAttachment(att)">{{ att.name }}</span>
              <el-tag size="small" type="info">{{ fileTypeLabel(att.type) }}</el-tag>
              <el-button
                :icon="Close"
                circle
                size="small"
                text
                :disabled="loading || fileParsing"
                @click="removeAttachment(i)"
              />
            </div>
          </div>
          <div class="input-bar">
            <div class="input-actions">
              <div class="action-item">
                <el-upload
                  :show-file-list="false"
                  :auto-upload="false"
                  :accept="ACCEPT_TYPES"
                  :disabled="loading || fileParsing || attachments.length >= MAX_ATTACHMENTS"
                  :on-change="onFileSelect"
                >
                  <el-button
                    class="action-btn"
                    :icon="Paperclip"
                    :loading="fileParsing"
                    :disabled="loading || attachments.length >= MAX_ATTACHMENTS"
                    title="上传文件"
                  />
                </el-upload>
              </div>
              <div class="action-item">
                <el-button
                  class="action-btn"
                  :icon="Microphone"
                  :type="voiceListening ? 'danger' : 'default'"
                  :class="{ 'voice-active': voiceListening }"
                  :loading="voiceTranscribing"
                  :disabled="loading || voiceTranscribing"
                  :title="voiceListening ? '点击结束录音' : (voiceEngine === 'whisper' ? '录音识别' : '语音输入')"
                  @click="toggleVoiceInput"
                />
              </div>
            </div>
            <el-input
              v-model="input"
              type="textarea"
              :rows="2"
              :placeholder="voiceTranscribing ? '正在识别语音…' : (voiceListening ? '正在录音，说完后再次点击麦克风结束' : '输入问题，Enter 发送，Shift+Enter 换行；可语音或上传文件')"
              @keydown.enter="onEnter"
              :disabled="loading"
            />
            <el-button type="primary" class="send-btn" :loading="loading" @click="send">
              提问
            </el-button>
          </div>
        </div>
      </el-card>
    </el-col>

    <el-col :span="6" class="side-col">
      <el-card shadow="never" class="side-card tips-card">
        <template #header>使用说明</template>
        <ul class="tips-list">
          <li>教师需先选择班级，检索与推荐仅使用该班在「资料管理」中的资源</li>
          <li>学生自动使用所属班级的课程资料</li>
          <li>选择章节后，检索范围将限定在该章节</li>
          <li>回答下方会列出推荐资源（PPT/PDF/视频）</li>
          <li>视频推荐支持「精准跳转到对应知识点时间点」</li>
          <li>支持上传 PDF、Word、PPT、代码等文件辅助提问</li>
          <li>支持语音输入（优先本地录音识别）</li>
        </ul>
      </el-card>

      <el-card shadow="never" class="side-card history-card">
        <template #header>
          <div class="history-header">
            <span>历史提问</span>
            <el-button text type="primary" size="small" :loading="historyLoading" @click="loadQaHistory">刷新</el-button>
          </div>
        </template>
        <div v-loading="historyLoading" class="history-list">
          <el-empty v-if="!qaHistory.length" description="暂无提问记录" :image-size="48" />
          <div
            v-for="item in qaHistory"
            :key="item.id"
            class="history-item"
            @click="openHistory(item)"
          >
            <div class="history-q">{{ item.question || '（无问题摘要）' }}</div>
            <div class="history-meta">
              <span>{{ fmtHistoryTime(item.created_at) }}</span>
              <span v-if="item.model_name">{{ item.model_name }}</span>
            </div>
          </div>
        </div>
      </el-card>
    </el-col>
  </el-row>

  <el-drawer v-model="attachmentDrawer" :title="selectedAttachment?.name || '附件预览'" size="560px">
    <template v-if="selectedAttachment">
      <div class="drawer-meta attach-drawer-meta">
        <span>类型：{{ fileTypeLabel(selectedAttachment.type) }}</span>
        <span v-if="selectedAttachment.size">大小：{{ (selectedAttachment.size / 1024).toFixed(1) }} KB</span>
        <span v-if="selectedAttachment.truncated" class="drawer-hint">发送给模型的文本已截断</span>
      </div>
      <div v-if="selectedAttachment.type === 'pdf' && attachmentPreviewUrl(selectedAttachment)" class="attach-preview-frame">
        <iframe :src="attachmentPreviewUrl(selectedAttachment)" title="PDF 预览" />
      </div>
      <div v-else-if="selectedAttachment.type === 'image' && attachmentPreviewUrl(selectedAttachment)" class="attach-preview-image">
        <img :src="attachmentPreviewUrl(selectedAttachment)" :alt="selectedAttachment.name" />
      </div>
      <div v-else class="drawer-section">
        <div class="drawer-label">文档内容（解析文本）</div>
        <div class="drawer-content answer-preview attach-text-preview">
          <pre v-if="selectedAttachment.text">{{ selectedAttachment.text }}</pre>
          <span v-else class="drawer-hint">暂无解析文本</span>
        </div>
      </div>
      <div class="attach-drawer-actions">
        <el-button
          v-if="attachmentPreviewUrl(selectedAttachment) || selectedAttachment.file_id"
          type="primary"
          @click="openAttachmentExternal(selectedAttachment)"
        >
          {{ attachmentActionLabel(selectedAttachment) }}
        </el-button>
      </div>
    </template>
  </el-drawer>

  <el-drawer v-model="historyDrawer" title="提问记录详情" size="480px">
    <template v-if="selectedHistory">
      <div class="drawer-section">
        <div class="drawer-label">提问</div>
        <div class="drawer-content">{{ historyQuestionText(selectedHistory.question) }}</div>
        <div v-if="resolveHistoryAttachments(selectedHistory).length" class="history-attachments">
          <el-tag
            v-for="(att, j) in resolveHistoryAttachments(selectedHistory)"
            :key="j"
            size="small"
            type="info"
            effect="plain"
            class="attach-tag"
            @click.stop="openAttachment(att)"
          >
            {{ att.name }}
          </el-tag>
        </div>
      </div>
      <div class="drawer-section">
        <div class="drawer-label">回答</div>
        <div class="drawer-content answer-preview">
          <MarkdownView :content="selectedHistory.answer || '（无回答记录）'" />
        </div>
        <div v-if="!selectedHistory.has_full_answer && selectedHistory.answer" class="drawer-hint">
          该记录创建于完整回答保存功能上线前，仅保留摘要
        </div>
      </div>
      <div class="drawer-meta">
        <span v-if="selectedHistory.model_name">模型：{{ selectedHistory.model_name }}</span>
        <span>{{ fmtHistoryTime(selectedHistory.created_at) }}</span>
      </div>
      <el-button type="primary" @click="reuseQuestion(selectedHistory.question)">再次提问</el-button>
    </template>
  </el-drawer>

  <el-dialog v-model="videoDialog" title="视频预览" width="720px" @close="onVideoDialogClose">
    <video v-if="videoBlobUrl" id="qa-video" :src="videoBlobUrl" controls style="width: 100%"></video>
  </el-dialog>
</template>

<style scoped>
.chat-card { height: calc(100vh - 140px); display: flex; flex-direction: column; }
.qa-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
:deep(.el-card__body) { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.chat-box { flex: 1; overflow-y: auto; padding: 8px; background: #fafafa; border-radius: 4px; }
.msg { display: flex; margin-bottom: 12px; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 90%; padding: 10px 14px; border-radius: 8px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.msg.user .bubble { background: #409eff; color: #fff; }
.role { font-size: 12px; color: #999; margin-bottom: 4px; }
.msg.user .role { color: #d6e8ff; }
.msg-attachments { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
.attach-tag { cursor: pointer; }
.attach-tag:hover { opacity: 0.85; }
.attach-link { cursor: pointer; }
.attach-link:hover { color: #409eff; }
.attach-preview-frame {
  height: calc(100vh - 220px);
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;
}
.attach-preview-frame iframe {
  width: 100%;
  height: 100%;
  border: none;
}
.attach-preview-image {
  text-align: center;
  background: #f5f7fa;
  border-radius: 6px;
  padding: 12px;
}
.attach-preview-image img {
  max-width: 100%;
  max-height: calc(100vh - 240px);
  object-fit: contain;
}
.attach-text-preview pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
}
.attach-drawer-meta { margin-bottom: 12px; }
.attach-drawer-actions { margin-top: 16px; }
.attach-only-hint { font-size: 13px; opacity: 0.85; }
.recommends { margin-top: 10px; padding-top: 8px; border-top: 1px dashed #ddd; }
.rec-title { font-size: 12px; color: #888; margin-bottom: 4px; }
.rec-item { display: flex; align-items: center; gap: 6px; font-size: 13px; padding: 3px 0; }
.rec-name { font-weight: 500; }
.rec-chapter { color: #888; font-size: 12px; }
.rec-page { color: #409eff; font-size: 12px; font-weight: 500; }
.rec-kw { color: #909399; font-size: 11px; }
.input-area { margin-top: 12px; }
.attachment-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 6px;
}
.attachment-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  max-width: 100%;
}
.attachment-name {
  font-size: 13px;
  color: #303133;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.input-bar {
  display: flex;
  align-items: stretch;
  gap: 8px;
}
.input-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 36px;
  flex-shrink: 0;
  align-self: stretch;
}
.action-item {
  flex: 1 1 0;
  width: 36px;
  min-height: 0;
  display: flex;
}
.action-item > :deep(*) {
  flex: 1;
  width: 100%;
  min-height: 0;
  display: flex;
}
.action-item :deep(.el-upload) {
  width: 100%;
  height: 100%;
  display: flex;
}
.action-btn,
.action-item :deep(.el-button) {
  width: 36px !important;
  height: 100% !important;
  min-height: 0;
  margin: 0 !important;
  padding: 0 !important;
  display: inline-flex !important;
  align-items: center;
  justify-content: center;
}
.input-bar :deep(.el-textarea) { flex: 1; }
.input-bar :deep(.el-textarea__inner) {
  height: 100%;
  min-height: 52px;
  box-sizing: border-box;
}
.send-btn {
  align-self: stretch;
  height: auto;
  min-width: 64px;
}
.voice-active {
  animation: voice-pulse 1.2s ease-in-out infinite;
}
@keyframes voice-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245, 108, 108, 0.45); }
  50% { box-shadow: 0 0 0 6px rgba(245, 108, 108, 0); }
}

.side-col {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 140px);
}
.side-card {
  flex: 1 1 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.side-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.tips-card :deep(.el-card__body) {
  padding-top: 8px;
}
.history-card :deep(.el-card__body) {
  padding-top: 0;
}
.tips-list {
  line-height: 2;
  color: #555;
  padding-left: 18px;
  margin: 0;
}
.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.history-list {
  height: 100%;
  overflow-y: auto;
}
.history-item {
  padding: 10px 4px;
  border-bottom: 1px solid #f0f0f0;
  cursor: pointer;
  transition: background 0.15s;
}
.history-item:hover { background: #f5f7fa; }
.history-item:last-child { border-bottom: none; }
.history-q {
  font-size: 13px;
  color: #303133;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.history-meta {
  margin-top: 4px;
  font-size: 11px;
  color: #909399;
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.drawer-section { margin-bottom: 16px; }
.history-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.drawer-label { font-size: 13px; color: #909399; margin-bottom: 6px; }
.drawer-content { font-size: 14px; line-height: 1.6; color: #303133; white-space: pre-wrap; }
.answer-preview { background: #f5f7fa; padding: 10px; border-radius: 6px; }
.drawer-hint { margin-top: 6px; font-size: 12px; color: #909399; }
.drawer-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #909399;
  margin-bottom: 16px;
}
</style>

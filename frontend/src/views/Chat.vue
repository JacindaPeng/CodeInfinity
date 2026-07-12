<script setup lang="ts">
import { onMounted, onUnmounted, ref, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Paperclip, Close, Microphone } from '@element-plus/icons-vue'
import { sseStream } from '@/api'
import http from '@/api'
import MarkdownView from '@/components/MarkdownView.vue'

interface Msg {
  role: 'user' | 'assistant'
  content: string
  attachments?: ChatAttachment[]
}
interface LlmCfg {
  id: number
  provider: string
  model: string
  is_default: boolean
}
interface Prov { provider: string; label: string }
interface ChatHistoryItem {
  id: number
  question: string
  answer: string
  has_full_answer?: boolean
  model_name: string
  attachments?: ChatAttachment[]
  created_at: string | null
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

const MAX_ATTACHMENTS = 5
const ACCEPT_TYPES = '.pdf,.doc,.docx,.ppt,.pptx,.txt,.md,.c,.h,.cpp,.java,.py,.js,.ts,.vue,.html,.css,.json,.xml,.csv,.jpg,.jpeg,.png,.gif,.webp'

const messages = ref<Msg[]>([
  { role: 'assistant', content: '你好，我是通用大模型对话。可以直接提问，也可上传 PDF、Word、PPT、代码等文件后提问，回答会流式返回。' },
])
const input = ref('')
const loading = ref(false)
const fileParsing = ref(false)
const boxRef = ref<HTMLElement | null>(null)
const attachments = ref<ChatAttachment[]>([])

const configs = ref<LlmCfg[]>([])
const providers = ref<Prov[]>([])
const selectedConfigId = ref<number | undefined>(undefined)

const chatHistory = ref<ChatHistoryItem[]>([])
const historyLoading = ref(false)
const historyDrawer = ref(false)
const selectedHistory = ref<ChatHistoryItem | null>(null)
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
  rec.onend = () => {
    voiceListening.value = false
  }
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
  // 定时切片，避免部分浏览器在 stop 前不产生 dataavailable 事件
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

function historyQuestionText(q: string) {
  const text = q.replace(/\s*\[附件:.*\]$/, '').trim()
  return text || '（基于附件提问）'
}

function resolveHistoryAttachments(item: ChatHistoryItem): ChatAttachment[] {
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

function providerLabel(p: string) {
  return providers.value.find(x => x.provider === p)?.label || p
}

function configLabel(cfg: LlmCfg) {
  const name = `${providerLabel(cfg.provider)} · ${cfg.model}`
  return cfg.is_default ? `${name}（默认）` : name
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

function revokeAttachmentUrls(items: ChatAttachment[]) {
  for (const a of items) revokeBlobUrl(a.blobUrl)
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

async function loadChatHistory() {
  historyLoading.value = true
  try {
    const { data } = await http.get('/chat/history', { params: { page: 1, size: 20 } })
    chatHistory.value = data.items
  } finally {
    historyLoading.value = false
  }
}

function onConfigChange(id: number) {
  selectedConfigId.value = id
  localStorage.setItem('chat_config_id', String(id))
}

function openHistory(item: ChatHistoryItem) {
  selectedHistory.value = item
  historyDrawer.value = true
}

function reuseQuestion(q: string) {
  input.value = q.replace(/\s*\[附件:.*\]$/, '').trim()
  historyDrawer.value = false
}

function fmtHistoryTime(iso: string | null) {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(0, 16)
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
    messages.value.push({ role: 'assistant', content: '请先在上方选择可用的大模型配置。' })
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
  messages.value.push({ role: 'assistant', content: '' })
  const idx = messages.value.length - 1
  await scrollBottom()

  const history = messages.value
    .slice(0, -1)
    .filter(m => m.content || (m.role === 'user' && m.attachments?.length))
    .map(m => ({ role: m.role, content: m.content || '（基于附件提问）' }))

  try {
    await sseStream('/chat/stream', {
      messages: history,
      config_id: selectedConfigId.value,
      attachments: files.map(f => ({
        name: f.name,
        text: f.text,
        type: f.type,
        file_id: f.file_id,
        truncated: f.truncated,
        size: f.size,
      })),
    }, (chunk) => {
      messages.value[idx].content += chunk
      scrollBottom()
    })
  } catch (e: any) {
    messages.value[idx].content += `\n[出错] ${e.message || e}`
  } finally {
    loading.value = false
    await loadChatHistory()
  }
}

function onEnter(e: KeyboardEvent) {
  if (e.shiftKey) return
  e.preventDefault()
  send()
}

function clearAll() {
  for (const m of messages.value) {
    if (m.attachments?.length) revokeAttachmentUrls(m.attachments)
  }
  revokeAttachmentUrls(attachments.value)
  messages.value = [{ role: 'assistant', content: '对话已清空。' }]
  attachments.value = []
}

onMounted(async () => {
  await loadVoiceStatus()
  await Promise.all([loadConfigs(), loadChatHistory()])
})

onUnmounted(() => {
  stopVoiceInput()
  cleanupMediaStream()
})
</script>

<template>
  <el-row :gutter="16">
    <el-col :span="18">
      <el-card shadow="never" class="chat-card">
        <template #header>
          <div class="chat-header">
            <span>大模型对话</span>
            <div class="chat-header-actions">
              <el-select
                v-model="selectedConfigId"
                placeholder="选择模型"
                style="width: 280px"
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
              <el-button text @click="clearAll">清空</el-button>
            </div>
          </div>
        </template>

        <div ref="boxRef" class="chat-box">
          <div
            v-for="(m, i) in messages"
            :key="i"
            :class="['msg', m.role]"
          >
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
              <MarkdownView v-if="m.role === 'assistant'" :content="m.content || (loading && i === messages.length - 1 ? '思考中…' : '')" />
              <div v-else class="chat-stream">
                <template v-if="m.content">{{ m.content }}</template>
                <span v-else-if="m.attachments?.length" class="attach-only-hint">（基于附件提问）</span>
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
              发送
            </el-button>
          </div>
        </div>
      </el-card>
    </el-col>

    <el-col :span="6" class="side-col">
      <el-card shadow="never" class="side-card tips-card">
        <template #header>使用说明</template>
        <ul class="tips-list">
          <li>可在上方切换不同大模型配置</li>
          <li>支持上传 PDF、Word、PPT、TXT、代码等文件</li>
          <li>文档内容会解析后一并发送给大模型</li>
          <li>支持语音输入（优先本地录音识别；未安装 Whisper 时用浏览器语音）</li>
          <li>右侧可查看历史提问记录</li>
        </ul>
      </el-card>

      <el-card shadow="never" class="side-card history-card">
        <template #header>
          <div class="history-header">
            <span>历史提问</span>
            <el-button text type="primary" size="small" :loading="historyLoading" @click="loadChatHistory">刷新</el-button>
          </div>
        </template>
        <div v-loading="historyLoading" class="history-list">
          <el-empty v-if="!chatHistory.length" description="暂无提问记录" :image-size="48" />
          <div
            v-for="item in chatHistory"
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

  <el-drawer v-model="historyDrawer" title="对话记录详情" size="480px">
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
</template>

<style scoped>
.chat-card { display: flex; flex-direction: column; height: calc(100vh - 140px); }
:deep(.el-card__body) { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.chat-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chat-box { flex: 1; overflow-y: auto; padding: 8px; background: #fafafa; border-radius: 4px; }
.msg { display: flex; margin-bottom: 12px; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 70%; padding: 10px 14px; border-radius: 8px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.msg.user .bubble { background: #409eff; color: #fff; }
.role { font-size: 12px; color: #999; margin-bottom: 4px; }
.msg.user .role { color: #d6e8ff; }
.msg-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}
.msg.user .msg-attachments :deep(.el-tag) {
  background: rgba(255,255,255,0.2);
  border-color: rgba(255,255,255,0.35);
  color: #fff;
}
.attach-tag {
  cursor: pointer;
}
.attach-tag:hover {
  opacity: 0.85;
}
.attach-link {
  cursor: pointer;
}
.attach-link:hover {
  color: #409eff;
}
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
.attach-drawer-meta {
  margin-bottom: 12px;
}
.attach-drawer-actions {
  margin-top: 16px;
}
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
.input-bar :deep(.el-textarea) {
  flex: 1;
}
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

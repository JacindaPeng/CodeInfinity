<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import http, { sseStream } from '@/api'

interface Chapter { id: number; title: string }
interface Recommend {
  material_id: number; type: string; title: string
  chapter_id: number; chapter_title: string; score: number
  video_start_sec: number | null; video_end_sec: number | null
  page: string | null; file_url: string
}
interface Msg { role: 'user' | 'assistant'; content: string; recommends?: Recommend[] }

const chapters = ref<Chapter[]>([])
const chapterId = ref<number | undefined>(undefined)
const messages = ref<Msg[]>([
  { role: 'assistant', content: '你好，我是 C语言课程智能体。可以问任何 C 语言相关问题，我会从课程资料中检索并回答，同时推荐相关学习资源。' },
])
const input = ref('')
const loading = ref(false)
const boxRef = ref<HTMLElement | null>(null)
const videoDialog = ref(false)
const videoUrl = ref('')
const videoStart = ref(0)

async function loadChapters() {
  const { data } = await http.get<Chapter[]>('/chapters')
  chapters.value = data
}

async function scrollBottom() {
  await nextTick()
  if (boxRef.value) boxRef.value.scrollTop = boxRef.value.scrollHeight
}

async function send() {
  const text = input.value.trim()
  if (!text || loading.value) return
  input.value = ''
  loading.value = true
  messages.value.push({ role: 'user', content: text })
  messages.value.push({ role: 'assistant', content: '', recommends: [] })
  const idx = messages.value.length - 1
  await scrollBottom()

  const history = messages.value
    .slice(0, -1)
    .filter(m => m.content)
    .map(m => ({ role: m.role, content: m.content }))

  try {
    await sseStream(
      '/agents/course/ask',
      { question: text, chapter_id: chapterId.value, history },
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
  }
}

function playVideo(rec: Recommend) {
  videoUrl.value = rec.file_url
  videoStart.value = rec.video_start_sec || 0
  videoDialog.value = true
  nextTick(() => {
    const v = document.querySelector('video#qa-video') as HTMLVideoElement | null
    if (v) {
      v.currentTime = videoStart.value
      v.play().catch(() => {})
    }
  })
}

const typeTag = (t: string) => {
  const map: Record<string, string> = { pdf: 'danger', ppt: 'warning', video: 'success', word: 'info' }
  return map[t] || ''
}

function fmtTime(s: number) {
  const m = Math.floor(s / 60); const r = s % 60
  return `${m}:${r.toString().padStart(2, '0')}`
}

function openUrl(url: string) {
  window.open(url, '_blank')
}

onMounted(loadChapters)
</script>

<template>
  <el-row :gutter="16">
    <el-col :span="18">
      <el-card shadow="never" class="chat-card">
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            <span>课程问答（RAG 流式）</span>
            <el-select v-model="chapterId" placeholder="限定章节（可选）" clearable style="width: 220px">
              <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
            </el-select>
          </div>
        </template>

        <div ref="boxRef" class="chat-box">
          <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
            <div class="bubble">
              <div class="role">{{ m.role === 'user' ? '我' : 'AI' }}</div>
              <div class="chat-stream">{{ m.content || (loading && i === messages.length - 1 ? '检索中…' : '') }}</div>
              <!-- 推荐资源 -->
              <div v-if="m.recommends && m.recommends.length" class="recommends">
                <div class="rec-title">建议学习：</div>
                <div v-for="r in m.recommends" :key="r.material_id" class="rec-item">
                  <el-tag :type="typeTag(r.type) as any" size="small">{{ r.type }}</el-tag>
                  <span class="rec-name">{{ r.title }}</span>
                  <span class="rec-chapter">{{ r.chapter_title }}</span>
                  <el-button v-if="r.type === 'video'" text type="primary" size="small"
                    @click="playVideo(r)">
                    跳转视频 {{ fmtTime(r.video_start_sec || 0) }}
                  </el-button>
                  <el-button v-else text type="primary" size="small"
                    @click="openUrl(r.file_url)">查看</el-button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="input-bar">
          <el-input
            v-model="input"
            type="textarea"
            :rows="2"
            placeholder="例如：什么是 AVL 树？"
            @keyup.enter="send"
            :disabled="loading"
          />
          <el-button type="primary" :loading="loading" @click="send" style="margin-left: 8px">
            提问
          </el-button>
        </div>
      </el-card>
    </el-col>

    <el-col :span="6">
      <el-card shadow="never">
        <template #header>使用说明</template>
        <ul style="line-height: 2; color: #555; padding-left: 18px">
          <li>选择章节后，检索范围将限定在该章节</li>
          <li>回答下方会列出推荐资源（PPT/PDF/视频）</li>
          <li>视频推荐支持「精准跳转到对应知识点时间点」</li>
        </ul>
      </el-card>
    </el-col>
  </el-row>

  <el-dialog v-model="videoDialog" title="视频预览" width="720px" @close="videoUrl = ''">
    <video v-if="videoUrl" id="qa-video" :src="videoUrl" controls style="width: 100%"></video>
  </el-dialog>
</template>

<style scoped>
.chat-card { height: calc(100vh - 140px); display: flex; flex-direction: column; }
:deep(.el-card__body) { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.chat-box { flex: 1; overflow-y: auto; padding: 8px; background: #fafafa; border-radius: 4px; }
.msg { display: flex; margin-bottom: 12px; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 90%; padding: 10px 14px; border-radius: 8px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.msg.user .bubble { background: #409eff; color: #fff; }
.role { font-size: 12px; color: #999; margin-bottom: 4px; }
.msg.user .role { color: #d6e8ff; }
.recommends { margin-top: 10px; padding-top: 8px; border-top: 1px dashed #ddd; }
.rec-title { font-size: 12px; color: #888; margin-bottom: 4px; }
.rec-item { display: flex; align-items: center; gap: 6px; font-size: 13px; padding: 3px 0; }
.rec-name { font-weight: 500; }
.rec-chapter { color: #888; font-size: 12px; }
.input-bar { display: flex; margin-top: 12px; align-items: flex-end; }
</style>

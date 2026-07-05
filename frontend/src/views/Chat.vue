<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { sseStream } from '@/api'
import { useAuthStore } from '@/stores/auth'

interface Msg { role: 'user' | 'assistant'; content: string }

const auth = useAuthStore()
const messages = ref<Msg[]>([
  { role: 'assistant', content: '你好，我是通用大模型对话。可以直接提问，回答会流式返回。' },
])
const input = ref('')
const loading = ref(false)
const boxRef = ref<HTMLElement | null>(null)

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
  messages.value.push({ role: 'assistant', content: '' })
  const idx = messages.value.length - 1
  await scrollBottom()

  const history = messages.value
    .slice(0, -1) // 排除当前空的 assistant
    .filter(m => m.content)
    .map(m => ({ role: m.role, content: m.content }))

  try {
    await sseStream('/chat/stream', { messages: history }, (chunk) => {
      messages.value[idx].content += chunk
      scrollBottom()
    })
  } catch (e: any) {
    messages.value[idx].content += `\n[出错] ${e.message || e}`
  } finally {
    loading.value = false
  }
}

function clearAll() {
  messages.value = [{ role: 'assistant', content: '对话已清空。' }]
}
</script>

<template>
  <el-card shadow="never" class="chat-card">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>大模型对话</span>
        <el-button text @click="clearAll">清空</el-button>
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
          <div class="chat-stream">{{ m.content || (loading && i === messages.length - 1 ? '思考中…' : '') }}</div>
        </div>
      </div>
    </div>

    <div class="input-bar">
      <el-input
        v-model="input"
        type="textarea"
        :rows="2"
        placeholder="输入问题，回车发送"
        @keyup.enter="send"
        :disabled="loading"
      />
      <el-button type="primary" :loading="loading" @click="send" style="margin-left: 8px">
        发送
      </el-button>
    </div>
  </el-card>
</template>

<style scoped>
.chat-card { display: flex; flex-direction: column; height: calc(100vh - 140px); }
.chat-box { flex: 1; overflow-y: auto; padding: 8px; background: #fafafa; border-radius: 4px; }
.msg { display: flex; margin-bottom: 12px; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 70%; padding: 10px 14px; border-radius: 8px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.msg.user .bubble { background: #409eff; color: #fff; }
.role { font-size: 12px; color: #999; margin-bottom: 4px; }
.msg.user .role { color: #d6e8ff; }
.input-bar { display: flex; margin-top: 12px; align-items: flex-end; }
</style>

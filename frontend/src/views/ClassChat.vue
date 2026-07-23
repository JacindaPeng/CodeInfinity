<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useCourseAgentStore } from '@/stores/courseAgent'
import { useAgentBoundClasses, type ScopedClassItem } from '@/composables/useAgentBoundClasses'

interface ChatMsg {
  id: number
  class_id: number
  msg_type: string
  content: string
  title?: string | null
  parent_id?: number | null
  knowledge_point_id?: number | null
  knowledge_point_name?: string | null
  sender_id: number
  sender_name: string
  sender_role: string
  created_at?: string | null
  reply_count?: number
}

interface PeerUser {
  id: number
  display_name: string
  username: string
  role: string
}

interface Enrollment {
  class_id: number
  class_name: string
  course_id: number
  course_name: string
}

interface KpItem {
  id: number
  name: string
  chapter_id: number
}

const POLL_MS = 2500

const auth = useAuthStore()
const agentStore = useCourseAgentStore()
const router = useRouter()
const { loadScopedClasses, pickClassId } = useAgentBoundClasses()

const isStudent = computed(() => auth.user?.role === 'student')
const isTeacher = computed(() => auth.user?.role === 'teacher' || auth.user?.role === 'admin')
const myId = computed(() => auth.user?.id || 0)

const classes = ref<ScopedClassItem[]>([])
const myEnrollments = ref<Enrollment[]>([])
const selectedClassId = ref<number | undefined>()
const tab = ref<'group' | 'topics' | 'dms'>('group')

const activeClassId = computed(() => {
  if (isStudent.value) {
    const courseId = agentStore.current?.course_id
    if (!courseId) return undefined
    const e = myEnrollments.value.find(x => x.course_id === courseId)
    return e?.class_id
  }
  return selectedClassId.value
})

const classLabel = computed(() => {
  if (isStudent.value) {
    const e = myEnrollments.value.find(x => x.class_id === activeClassId.value)
    return e ? `${e.class_name}（${e.course_name}）` : ''
  }
  return classes.value.find(c => c.id === selectedClassId.value)?.name || ''
})

const studentNeedsEnrollment = computed(
  () => isStudent.value && !!agentStore.current?.course_id && !activeClassId.value,
)
const needsAgentGuide = computed(() => !agentStore.current)

// ---- 群聊 ----
const groupMsgs = ref<ChatMsg[]>([])
const groupInput = ref('')
const groupSending = ref(false)
const groupBox = ref<HTMLElement | null>(null)
let groupAfterId = 0

// ---- 话题 ----
const topics = ref<ChatMsg[]>([])
const activeTopic = ref<ChatMsg | null>(null)
const topicReplies = ref<ChatMsg[]>([])
const replyInput = ref('')
const replySending = ref(false)
const topicDialog = ref(false)
const topicForm = ref({ title: '', content: '', knowledge_point_id: undefined as number | undefined })
const kps = ref<KpItem[]>([])
const topicBox = ref<HTMLElement | null>(null)
let replyAfterId = 0

// ---- 私信 ----
const peers = ref<PeerUser[]>([])
const peerId = ref<number | undefined>()
const dmMsgs = ref<ChatMsg[]>([])
const dmInput = ref('')
const dmSending = ref(false)
const dmBox = ref<HTMLElement | null>(null)
let dmAfterId = 0

let pollTimer: ReturnType<typeof setInterval> | null = null

function fmtTime(iso?: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

function roleTag(role: string) {
  if (role === 'teacher' || role === 'admin') return '教师'
  if (role === 'student') return '学生'
  return role
}

async function scrollBottom(el: HTMLElement | null) {
  await nextTick()
  if (el) el.scrollTop = el.scrollHeight
}

async function loadClasses() {
  if (isStudent.value) {
    const { data } = await http.get<Enrollment[]>('/classes/my')
    myEnrollments.value = data
    return
  }
  const data = await loadScopedClasses()
  classes.value = data
  selectedClassId.value = pickClassId(data, selectedClassId.value, 'class_chat_class_id')
}

function onClassChange(id: number) {
  selectedClassId.value = id
  localStorage.setItem('class_chat_class_id', String(id))
  resetChannels()
  bootstrapChannel()
}

function resetChannels() {
  groupMsgs.value = []
  groupAfterId = 0
  topics.value = []
  activeTopic.value = null
  topicReplies.value = []
  replyAfterId = 0
  peers.value = []
  peerId.value = undefined
  dmMsgs.value = []
  dmAfterId = 0
}

async function fetchGroup(incremental = false) {
  const cid = activeClassId.value
  if (!cid) return
  const after = incremental ? groupAfterId : 0
  const { data } = await http.get<{ items: ChatMsg[] }>(
    `/classes/${cid}/chat/messages`,
    { params: { after_id: after, limit: 50 } },
  )
  const items = data.items || []
  if (!incremental) {
    groupMsgs.value = items
  } else if (items.length) {
    const seen = new Set(groupMsgs.value.map(m => m.id))
    for (const m of items) {
      if (!seen.has(m.id)) groupMsgs.value.push(m)
    }
  }
  if (groupMsgs.value.length) {
    groupAfterId = Math.max(...groupMsgs.value.map(m => m.id))
    await http.post(`/classes/${cid}/chat/read`, {
      channel: 'group',
      last_read_message_id: groupAfterId,
    }).catch(() => {})
  }
  if (!incremental || items.length) await scrollBottom(groupBox.value)
}

async function sendGroup() {
  const cid = activeClassId.value
  const text = groupInput.value.trim()
  if (!cid || !text) return
  groupSending.value = true
  try {
    const { data } = await http.post<ChatMsg>(`/classes/${cid}/chat/messages`, { content: text })
    groupInput.value = ''
    if (!groupMsgs.value.some(m => m.id === data.id)) groupMsgs.value.push(data)
    groupAfterId = Math.max(groupAfterId, data.id)
    await scrollBottom(groupBox.value)
  } finally {
    groupSending.value = false
  }
}

async function fetchTopics() {
  const cid = activeClassId.value
  if (!cid) return
  const { data } = await http.get<{ items: ChatMsg[] }>(`/classes/${cid}/chat/topics`)
  topics.value = data.items || []
}

async function openTopic(t: ChatMsg) {
  activeTopic.value = t
  topicReplies.value = []
  replyAfterId = 0
  tab.value = 'topics'
  await fetchReplies(false)
}

async function fetchReplies(incremental = false) {
  const cid = activeClassId.value
  const tid = activeTopic.value?.id
  if (!cid || !tid) return
  const after = incremental ? replyAfterId : 0
  const { data } = await http.get<{ topic: ChatMsg; items: ChatMsg[] }>(
    `/classes/${cid}/chat/topics/${tid}/replies`,
    { params: { after_id: after, limit: 80 } },
  )
  if (data.topic) activeTopic.value = data.topic
  const items = data.items || []
  if (!incremental) {
    topicReplies.value = items
  } else if (items.length) {
    const seen = new Set(topicReplies.value.map(m => m.id))
    for (const m of items) {
      if (!seen.has(m.id)) topicReplies.value.push(m)
    }
  }
  if (topicReplies.value.length) {
    replyAfterId = Math.max(...topicReplies.value.map(m => m.id), replyAfterId)
  }
  if (!incremental || items.length) await scrollBottom(topicBox.value)
}

async function sendReply() {
  const cid = activeClassId.value
  const tid = activeTopic.value?.id
  const text = replyInput.value.trim()
  if (!cid || !tid || !text) return
  replySending.value = true
  try {
    const { data } = await http.post<ChatMsg>(`/classes/${cid}/chat/topics/${tid}/replies`, { content: text })
    replyInput.value = ''
    if (!topicReplies.value.some(m => m.id === data.id)) topicReplies.value.push(data)
    replyAfterId = Math.max(replyAfterId, data.id)
    await scrollBottom(topicBox.value)
    fetchTopics()
  } finally {
    replySending.value = false
  }
}

async function loadKps() {
  const cid = activeClassId.value
  if (!cid) return
  const { data } = await http.get<{ items: KpItem[] }>(`/classes/${cid}/chat/knowledge-points`)
  kps.value = data.items || []
}

async function openTopicDialog() {
  await loadKps()
  topicForm.value = { title: '', content: '', knowledge_point_id: undefined }
  topicDialog.value = true
}

async function publishTopic() {
  const cid = activeClassId.value
  if (!cid) return
  const title = topicForm.value.title.trim()
  if (!title) {
    ElMessage.warning('请填写话题标题')
    return
  }
  const { data } = await http.post<ChatMsg>(`/classes/${cid}/chat/topics`, {
    title,
    content: topicForm.value.content.trim(),
    knowledge_point_id: topicForm.value.knowledge_point_id || null,
  })
  topicDialog.value = false
  await fetchTopics()
  await openTopic(data)
  ElMessage.success('话题已发布')
}

async function loadPeers() {
  const cid = activeClassId.value
  if (!cid) return
  if (isStudent.value) {
    const { data } = await http.get<{ items: PeerUser[] }>(`/classes/${cid}/chat/teachers`)
    peers.value = data.items || []
  } else {
    const { data } = await http.get<{ items: PeerUser[] }>(`/classes/${cid}/chat/students`)
    peers.value = data.items || []
  }
  if (!peerId.value && peers.value.length) peerId.value = peers.value[0].id
}

async function fetchDms(incremental = false) {
  const cid = activeClassId.value
  const pid = peerId.value
  if (!cid || !pid) return
  const after = incremental ? dmAfterId : 0
  const { data } = await http.get<{ items: ChatMsg[] }>(`/classes/${cid}/chat/dms`, {
    params: { peer_id: pid, after_id: after, limit: 50 },
  })
  const items = data.items || []
  if (!incremental) {
    dmMsgs.value = items
  } else if (items.length) {
    const seen = new Set(dmMsgs.value.map(m => m.id))
    for (const m of items) {
      if (!seen.has(m.id)) dmMsgs.value.push(m)
    }
  }
  if (dmMsgs.value.length) {
    dmAfterId = Math.max(...dmMsgs.value.map(m => m.id))
    await http.post(`/classes/${cid}/chat/read`, {
      channel: `dm:${pid}`,
      last_read_message_id: dmAfterId,
    }).catch(() => {})
  }
  if (!incremental || items.length) await scrollBottom(dmBox.value)
}

async function sendDm() {
  const cid = activeClassId.value
  const pid = peerId.value
  const text = dmInput.value.trim()
  if (!cid || !pid || !text) return
  dmSending.value = true
  try {
    const { data } = await http.post<ChatMsg>(`/classes/${cid}/chat/dms`, {
      receiver_id: pid,
      content: text,
    })
    dmInput.value = ''
    if (!dmMsgs.value.some(m => m.id === data.id)) dmMsgs.value.push(data)
    dmAfterId = Math.max(dmAfterId, data.id)
    await scrollBottom(dmBox.value)
  } finally {
    dmSending.value = false
  }
}

function onPeerChange(id: number) {
  peerId.value = id
  dmMsgs.value = []
  dmAfterId = 0
  fetchDms(false)
}

async function bootstrapChannel() {
  if (!activeClassId.value) return
  if (tab.value === 'group') await fetchGroup(false)
  else if (tab.value === 'topics') {
    await fetchTopics()
    if (activeTopic.value) await fetchReplies(false)
  } else {
    await loadPeers()
    await fetchDms(false)
  }
}

async function pollTick() {
  if (!activeClassId.value) return
  try {
    if (tab.value === 'group') await fetchGroup(true)
    else if (tab.value === 'topics' && activeTopic.value) await fetchReplies(true)
    else if (tab.value === 'dms' && peerId.value) await fetchDms(true)
  } catch {
    /* ignore transient poll errors */
  }
}

function startPoll() {
  stopPoll()
  pollTimer = setInterval(pollTick, POLL_MS)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(tab, () => {
  bootstrapChannel()
})

watch(activeClassId, (v, old) => {
  if (v === old) return
  resetChannels()
  bootstrapChannel()
})

onMounted(async () => {
  if (needsAgentGuide.value) return
  await loadClasses()
  await bootstrapChannel()
  startPoll()
})

onUnmounted(() => stopPoll())
</script>

<template>
  <div class="class-chat">
    <div v-if="needsAgentGuide" class="guide">
      <el-empty description="请先从「课程智能体」进入一门课程">
        <el-button type="primary" @click="router.push('/agents')">选择课程</el-button>
      </el-empty>
    </div>
    <div v-else-if="studentNeedsEnrollment" class="guide">
      <el-empty description="请先加入本课程对应班级后再使用群聊">
        <el-button type="primary" @click="router.push('/my-class')">我的班级</el-button>
      </el-empty>
    </div>
    <template v-else>
      <div class="chat-toolbar">
        <div class="left">
          <h2>课程群聊</h2>
          <span v-if="classLabel" class="sub">{{ classLabel }}</span>
        </div>
        <div v-if="isTeacher && classes.length" class="right">
          <span class="label">班级</span>
          <el-select
            :model-value="selectedClassId"
            placeholder="选择班级"
            style="width: 220px"
            @change="onClassChange"
          >
            <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </div>
      </div>

      <el-tabs v-model="tab" class="chat-tabs">
        <el-tab-pane label="群聊" name="group" />
        <el-tab-pane label="话题" name="topics" />
        <el-tab-pane :label="isStudent ? '私信老师' : '学生私信'" name="dms" />
      </el-tabs>

      <!-- 群聊 -->
      <div v-show="tab === 'group'" class="panel">
        <div ref="groupBox" class="msg-box">
          <div v-if="!groupMsgs.length" class="empty-hint">暂无消息，打个招呼吧</div>
          <div
            v-for="m in groupMsgs"
            :key="m.id"
            class="msg-row"
            :class="{ mine: m.sender_id === myId }"
          >
            <div v-if="m.msg_type === 'topic'" class="topic-card" @click="openTopic(m)">
              <div class="topic-card-title">话题：{{ m.title }}</div>
              <div v-if="m.knowledge_point_name" class="kp">知识点 · {{ m.knowledge_point_name }}</div>
              <div class="topic-card-body">{{ m.content || '点击查看讨论' }}</div>
              <div class="meta">{{ m.sender_name }} · {{ fmtTime(m.created_at) }}</div>
            </div>
            <div v-else class="bubble">
              <div class="meta">
                <span class="name">{{ m.sender_name }}</span>
                <el-tag size="small" type="info">{{ roleTag(m.sender_role) }}</el-tag>
                <span class="time">{{ fmtTime(m.created_at) }}</span>
              </div>
              <div class="body">{{ m.content }}</div>
            </div>
          </div>
        </div>
        <div class="composer">
          <el-input
            v-model="groupInput"
            type="textarea"
            :rows="2"
            maxlength="2000"
            show-word-limit
            placeholder="输入群消息，Enter 发送（Shift+Enter 换行）"
            @keydown.enter.exact.prevent="sendGroup"
          />
          <el-button type="primary" :loading="groupSending" @click="sendGroup">发送</el-button>
        </div>
      </div>

      <!-- 话题 -->
      <div v-show="tab === 'topics'" class="panel topics-panel">
        <div class="topics-side">
          <div class="side-head">
            <span>话题列表</span>
            <el-button v-if="isTeacher" type="primary" size="small" @click="openTopicDialog">
              发布话题
            </el-button>
          </div>
          <div
            v-for="t in topics"
            :key="t.id"
            class="topic-item"
            :class="{ active: activeTopic?.id === t.id }"
            @click="openTopic(t)"
          >
            <div class="t-title">{{ t.title }}</div>
            <div class="t-meta">
              <span v-if="t.knowledge_point_name">{{ t.knowledge_point_name }} · </span>
              {{ t.reply_count || 0 }} 回复 · {{ t.sender_name }}
            </div>
          </div>
          <div v-if="!topics.length" class="empty-hint">暂无话题</div>
        </div>
        <div class="topics-main">
          <template v-if="activeTopic">
            <div class="topic-detail-head">
              <h3>{{ activeTopic.title }}</h3>
              <el-tag v-if="activeTopic.knowledge_point_name" type="success" size="small">
                {{ activeTopic.knowledge_point_name }}
              </el-tag>
              <p class="topic-content">{{ activeTopic.content || '（无正文）' }}</p>
              <div class="meta">{{ activeTopic.sender_name }} · {{ fmtTime(activeTopic.created_at) }}</div>
            </div>
            <div ref="topicBox" class="msg-box compact">
              <div
                v-for="m in topicReplies"
                :key="m.id"
                class="msg-row"
                :class="{ mine: m.sender_id === myId }"
              >
                <div class="bubble">
                  <div class="meta">
                    <span class="name">{{ m.sender_name }}</span>
                    <el-tag size="small" type="info">{{ roleTag(m.sender_role) }}</el-tag>
                    <span class="time">{{ fmtTime(m.created_at) }}</span>
                  </div>
                  <div class="body">{{ m.content }}</div>
                </div>
              </div>
              <div v-if="!topicReplies.length" class="empty-hint">还没有回复，来讨论吧</div>
            </div>
            <div class="composer">
              <el-input
                v-model="replyInput"
                type="textarea"
                :rows="2"
                maxlength="2000"
                show-word-limit
                placeholder="回复该话题"
                @keydown.enter.exact.prevent="sendReply"
              />
              <el-button type="primary" :loading="replySending" @click="sendReply">回复</el-button>
            </div>
          </template>
          <el-empty v-else description="选择或发布一个话题" />
        </div>
      </div>

      <!-- 私信 -->
      <div v-show="tab === 'dms'" class="panel dms-panel">
        <div class="peers-side">
          <div class="side-head">
            <span>{{ isStudent ? '本班教师' : '本班学生' }}</span>
          </div>
          <div
            v-for="p in peers"
            :key="p.id"
            class="peer-item"
            :class="{ active: peerId === p.id }"
            @click="onPeerChange(p.id)"
          >
            {{ p.display_name }}
          </div>
          <div v-if="!peers.length" class="empty-hint">暂无联系人</div>
        </div>
        <div class="dms-main">
          <template v-if="peerId">
            <div ref="dmBox" class="msg-box">
              <div
                v-for="m in dmMsgs"
                :key="m.id"
                class="msg-row"
                :class="{ mine: m.sender_id === myId }"
              >
                <div class="bubble">
                  <div class="meta">
                    <span class="name">{{ m.sender_name }}</span>
                    <span class="time">{{ fmtTime(m.created_at) }}</span>
                  </div>
                  <div class="body">{{ m.content }}</div>
                </div>
              </div>
              <div v-if="!dmMsgs.length" class="empty-hint">开始私信留言吧</div>
            </div>
            <div class="composer">
              <el-input
                v-model="dmInput"
                type="textarea"
                :rows="2"
                maxlength="2000"
                show-word-limit
                placeholder="输入私信内容"
                @keydown.enter.exact.prevent="sendDm"
              />
              <el-button type="primary" :loading="dmSending" @click="sendDm">发送</el-button>
            </div>
          </template>
          <el-empty v-else description="请选择联系人" />
        </div>
      </div>
    </template>

    <el-dialog v-model="topicDialog" title="发布话题讨论" width="480px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="标题" required>
          <el-input v-model="topicForm.title" maxlength="120" show-word-limit />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="topicForm.content" type="textarea" :rows="4" maxlength="2000" show-word-limit />
        </el-form-item>
        <el-form-item label="知识点">
          <el-select
            v-model="topicForm.knowledge_point_id"
            clearable
            filterable
            placeholder="可选"
            style="width: 100%"
          >
            <el-option v-for="k in kps" :key="k.id" :label="k.name" :value="k.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="topicDialog = false">取消</el-button>
        <el-button type="primary" @click="publishTopic">发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.class-chat {
  height: calc(100vh - 100px);
  display: flex;
  flex-direction: column;
  min-height: 480px;
}
.guide {
  padding: 64px 0;
}
.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  gap: 12px;
}
.chat-toolbar h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}
.chat-toolbar .sub {
  margin-left: 10px;
  color: #909399;
  font-size: 13px;
}
.chat-toolbar .right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chat-toolbar .label {
  color: #606266;
  font-size: 13px;
}
.chat-tabs {
  margin-bottom: 0;
}
.panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
}
.msg-box {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: #f7f8fa;
}
.msg-box.compact {
  min-height: 180px;
}
.empty-hint {
  color: #909399;
  text-align: center;
  padding: 24px 8px;
  font-size: 13px;
}
.msg-row {
  display: flex;
  margin-bottom: 12px;
}
.msg-row.mine {
  justify-content: flex-end;
}
.bubble {
  max-width: 72%;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  padding: 8px 12px;
}
.msg-row.mine .bubble {
  background: #ecf5ff;
  border-color: #d9ecff;
}
.bubble .meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  font-size: 12px;
  color: #909399;
}
.bubble .name {
  color: #303133;
  font-weight: 600;
}
.bubble .body {
  white-space: pre-wrap;
  line-height: 1.6;
  word-break: break-word;
}
.topic-card {
  max-width: 80%;
  background: #fff8e6;
  border: 1px solid #f5dab1;
  border-radius: 10px;
  padding: 10px 12px;
  cursor: pointer;
}
.topic-card-title {
  font-weight: 600;
  color: #b88230;
}
.topic-card .kp {
  font-size: 12px;
  color: #67c23a;
  margin-top: 2px;
}
.topic-card-body {
  margin-top: 6px;
  color: #606266;
  font-size: 13px;
}
.topic-card .meta {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}
.composer {
  display: flex;
  gap: 10px;
  padding: 12px;
  border-top: 1px solid #ebeef5;
  background: #fff;
  align-items: flex-end;
}
.composer .el-textarea {
  flex: 1;
}
.topics-panel,
.dms-panel {
  flex-direction: row;
}
.topics-side,
.peers-side {
  width: 240px;
  border-right: 1px solid #ebeef5;
  overflow-y: auto;
  background: #fff;
}
.topics-main,
.dms-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid #ebeef5;
  font-weight: 600;
  font-size: 13px;
}
.topic-item,
.peer-item {
  padding: 10px 12px;
  border-bottom: 1px solid #f2f3f5;
  cursor: pointer;
}
.topic-item:hover,
.peer-item:hover,
.topic-item.active,
.peer-item.active {
  background: #f5f7fa;
}
.t-title {
  font-size: 14px;
  font-weight: 500;
}
.t-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
.topic-detail-head {
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  background: #fff;
}
.topic-detail-head h3 {
  margin: 0 0 6px;
  font-size: 16px;
}
.topic-content {
  margin: 8px 0 4px;
  color: #606266;
  white-space: pre-wrap;
  line-height: 1.6;
}
</style>

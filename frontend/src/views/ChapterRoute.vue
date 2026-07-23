<script setup lang="ts">
import { onMounted, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useCourseAgentStore } from '@/stores/courseAgent'
import { useAgentBoundClasses } from '@/composables/useAgentBoundClasses'
import { useAgentCourseScope } from '@/composables/useAgentCourseScope'

interface Chapter { id: number; title: string; order_idx: number; description: string }
interface Progress { chapter_id: number; status: string; last_exam_id: number | null }
interface HistoryRow {
  id: number; chapter_id: number; chapter_title: string
  status: string; total_score: number | null
  started_at: string | null; submitted_at: string | null
}
interface Enrollment {
  class_id: number
  class_name: string
  course_id: number
  course_name: string
}
interface ClassItem { id: number; name: string }
interface AttemptInfo {
  used: number; max: number; remaining: number; configured: boolean
}
interface ChapterProgressStat {
  chapter_id: number; chapter_title: string; order_idx: number
  completed_count: number; student_count: number; completion_rate: number; configured: boolean
}

const router = useRouter()
const userStore = useAuthStore()
const agentStore = useCourseAgentStore()
const { loadScopedClasses, pickClassId } = useAgentBoundClasses()
const { chapterListParams } = useAgentCourseScope()
const needsAgentGuide = computed(() => !agentStore.current)
const agentPlanned = computed(() => agentStore.current && !agentStore.isActive())
const chapters = ref<Chapter[]>([])
const progress = ref<Record<number, Progress>>({})
const loading = ref(false)
const history = ref<HistoryRow[]>([])
const attempts = ref<Record<number, AttemptInfo>>({})
const myEnrollments = ref<Enrollment[]>([])
const classes = ref<ClassItem[]>([])
const selectedClassId = ref<number | undefined>(undefined)
const classProgress = ref<ChapterProgressStat[]>([])
const classOverview = ref<{ class_name: string; student_count: number } | null>(null)

const isStudent = computed(() => userStore.user?.role === 'student')
const isTeacher = computed(() => userStore.user?.role === 'teacher' || userStore.user?.role === 'admin')
const noChapters = computed(() => !loading.value && chapters.value.length === 0)

const studentClassId = computed(() => {
  const courseId = agentStore.current?.course_id
  if (!courseId) return undefined
  const e = myEnrollments.value.find(x => x.course_id === courseId)
  return e?.class_id
})
const classLabel = computed(() => {
  if (isStudent.value) {
    const cid = studentClassId.value
    const e = myEnrollments.value.find(x => x.class_id === cid)
    return e ? `${e.class_name}（${e.course_name}）` : ''
  }
  const c = classes.value.find(x => x.id === selectedClassId.value)
  return c?.name || ''
})
const hasClass = computed(() => {
  if (isTeacher.value) return !!selectedClassId.value
  return !!studentClassId.value
})

const progressMap = computed(() =>
  Object.fromEntries(classProgress.value.map(p => [p.chapter_id, p]))
)

const ongoingByChapter = computed(() => {
  const map: Record<number, number> = {}
  for (const h of history.value) {
    if (h.status === 'ongoing') map[h.chapter_id] = h.id
  }
  return map
})

const latestSubmittedByChapter = computed(() => {
  const map: Record<number, number> = {}
  for (const h of history.value) {
    if (h.status === 'submitted' && !map[h.chapter_id]) map[h.chapter_id] = h.id
  }
  return map
})

const bestScoreByChapter = computed(() => {
  const map: Record<number, number | null> = {}
  for (const h of history.value) {
    if (h.status === 'submitted' && h.total_score !== null) {
      const cur = map[h.chapter_id]
      if (cur === null || cur === undefined || h.total_score > cur) map[h.chapter_id] = h.total_score
    }
  }
  return map
})

const submittedCountByChapter = computed(() => {
  const map: Record<number, number> = {}
  for (const h of history.value) {
    if (h.status === 'submitted') map[h.chapter_id] = (map[h.chapter_id] || 0) + 1
  }
  return map
})

function attemptsParams() {
  const p: Record<string, number> = {}
  if (isTeacher.value && selectedClassId.value) {
    p.class_id = selectedClassId.value
  } else if (isStudent.value && studentClassId.value) {
    p.class_id = studentClassId.value
  }
  if (agentStore.current?.id) p.agent_id = agentStore.current.id
  return p
}

async function loadAttempts(chapterList: Chapter[]) {
  const results = await Promise.all(
    chapterList.map((c) =>
      http.get(`/exams/attempts/${c.id}`, { params: attemptsParams() }).catch(() => null)
    )
  )
  attempts.value = {}
  chapterList.forEach((c, i) => {
    if (results[i]?.data) attempts.value[c.id] = results[i].data
  })
}

async function loadClassProgress() {
  if (!isTeacher.value || !selectedClassId.value) {
    classProgress.value = []
    classOverview.value = null
    return
  }
  const { data } = await http.get('/exams/teacher/class-progress', {
    params: {
      class_id: selectedClassId.value,
      course_id: agentStore.current?.course_id || undefined,
      agent_id: agentStore.current?.id || undefined,
    },
  })
  classProgress.value = data.chapters || []
  classOverview.value = {
    class_name: data.class_name,
    student_count: data.student_count,
  }
}

async function load() {
  await agentStore.restoreAgent()
  loading.value = true
  try {
    if (isStudent.value) {
      try {
        const { data } = await http.get<Enrollment[]>('/classes/my')
        myEnrollments.value = data
      } catch {
        myEnrollments.value = []
      }
    } else if (isTeacher.value) {
      const data = await loadScopedClasses()
      classes.value = data
      selectedClassId.value = pickClassId(data, selectedClassId.value)
    }

    const chapterParams = chapterListParams()
    const progressParams = chapterListParams()
    const historyParams: Record<string, number> = {}
    if (agentStore.current?.course_id) {
      historyParams.course_id = agentStore.current.course_id
    }
    const [ch, pr, hist] = await Promise.all([
      http.get<Chapter[]>('/chapters', { params: chapterParams }),
      isStudent.value
        ? http.get<Progress[]>('/chapters/progress/all', { params: progressParams })
        : Promise.resolve({ data: [] }),
      http.get('/exams/history/mine', { params: historyParams }),
    ])
    chapters.value = ch.data
    progress.value = Object.fromEntries(pr.data.map((p) => [p.chapter_id, p]))
    history.value = hist.data

    if (isTeacher.value && selectedClassId.value) {
      await Promise.all([loadClassProgress(), loadAttempts(ch.data)])
    } else if (isStudent.value && studentClassId.value) {
      await loadAttempts(ch.data)
    }
  } finally {
    loading.value = false
  }
}

function statusOf(ch: Chapter): string {
  if (isTeacher.value) return ''
  if (submittedCountByChapter.value[ch.id] > 0) return '已完成'
  return progress.value[ch.id]?.status || '未完成'
}

function statusType(s: string) {
  return s === '已完成' ? 'success' : s === '待学习' ? 'warning' : 'info'
}

function scoreColor(score: number): string {
  if (score >= 80) return '#67c23a'
  if (score >= 60) return '#e6a23c'
  return '#f56c6c'
}

function progressColor(rate: number): string {
  if (rate >= 80) return '#67c23a'
  if (rate >= 50) return '#e6a23c'
  return '#f56c6c'
}

async function startExam(ch: Chapter) {
  if (!hasClass.value) {
    ElMessage.warning(isTeacher.value ? '请先选择班级' : '请先加入班级后再开始考核')
    return
  }
  const att = attempts.value[ch.id]
  if (isTeacher.value && att && !att.configured) {
    ElMessage.warning('该章节尚未为本班配置考核，请先在「考核配置」中设置')
    return
  }

  const ongoingId = ongoingByChapter.value[ch.id]
  if (ongoingId) {
    try {
      await ElMessageBox.confirm(
        `该章节有一个进行中的考核（ID: ${ongoingId}），是否继续答题？点击「取消」可新建一份。`,
        '提示',
        { type: 'warning', confirmButtonText: '继续答题', cancelButtonText: '新建考核' }
      )
      router.push(`/exams/${ongoingId}`)
      return
    } catch { /* 新建 */ }
  }

  const actionLabel = isTeacher.value ? '考核测试' : '考核'
  try {
    await ElMessageBox.confirm(
      `开始「${ch.title}」${actionLabel}？试卷将根据${classLabel.value || '本班'}的考核配置动态生成。`,
      '提示',
      { type: 'warning' }
    )
    const payload: { chapter_id: number; class_id?: number; agent_id?: number } = { chapter_id: ch.id }
    if (isTeacher.value && selectedClassId.value) {
      payload.class_id = selectedClassId.value
    } else if (isStudent.value && studentClassId.value) {
      payload.class_id = studentClassId.value
    }
    if (agentStore.current?.id) payload.agent_id = agentStore.current.id
    const { data } = await http.post('/exams/start', payload, { timeout: 120000 })
    if (data.warnings?.length) ElMessage.warning(data.warnings.join('; '))
    ElMessage.success('试卷已生成')
    sessionStorage.setItem(`exam-${data.exam_id}`, JSON.stringify(data))
    router.push(`/exams/${data.exam_id}`)
  } catch (e: any) {
    if (e?.response?.data?.detail) ElMessage.error(e.response.data.detail)
  }
}

function resumeExam(examId: number) { router.push(`/exams/${examId}`) }
function viewReport(examId: number) { router.push(`/exams/${examId}/report`) }

const regenerating = ref<number | null>(null)
async function regenerateReport(examId: number) {
  regenerating.value = examId
  try {
    const { data } = await http.post(`/exams/${examId}/regenerate-report`, {}, { timeout: 180000 })
    ElMessage.success(`报告已生成，总分 ${data.total_score}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '报告生成失败')
  } finally {
    regenerating.value = null
  }
}

async function onClassChange() {
  if (!selectedClassId.value) return
  loading.value = true
  try {
    await Promise.all([loadClassProgress(), loadAttempts(chapters.value)])
  } finally {
    loading.value = false
  }
}

watch(
  () => agentStore.current?.id,
  (id, prev) => {
    if (id && id !== prev) load()
  },
)

onMounted(load)
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px">
        <span>章节学习路线</span>
        <div style="display: flex; align-items: center; gap: 8px">
          <el-select
            v-if="isTeacher"
            v-model="selectedClassId"
            placeholder="选择班级"
            style="width: 220px"
            @change="onClassChange"
          >
            <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-tag v-else-if="classLabel" type="info">{{ classLabel }}</el-tag>
        </div>
      </div>
    </template>

    <el-alert
      v-if="needsAgentGuide"
      type="warning"
      :closable="false"
      title="尚未选择课程"
      style="margin-bottom: 12px"
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
      description="该课程正在筹备中，章节考核功能暂不可用。"
      style="margin-bottom: 12px"
    />

    <el-alert
      v-if="isStudent && !hasClass"
      type="warning"
      :closable="false"
      title="尚未加入班级"
      description="请先在「我的班级」加入班级后，才能使用本班考核配置进行章节考核。"
      style="margin-bottom: 12px"
    />

    <el-alert
      v-if="isTeacher && classOverview"
      type="info"
      :closable="false"
      :title="`${classOverview.class_name} · 共 ${classOverview.student_count} 名学生`"
      description="选择班级后可预览该班考核配置并进行测试，下方显示各章节学生完成率。"
      style="margin-bottom: 12px"
    />

    <el-alert
      v-if="isTeacher && !classes.length"
      type="warning"
      :closable="false"
      title="暂无管理班级"
      description="请先在「班级管理」创建班级并让学生加入。"
      style="margin-bottom: 12px"
    />

    <el-alert
      v-if="noChapters && !needsAgentGuide"
      type="warning"
      :closable="false"
      title="尚未生成章节"
      style="margin-bottom: 12px"
    >
      <template #default>
        <span v-if="isTeacher">
          本课程章节需先建立结构。请在
          <el-link type="primary" @click="router.push('/teacher/materials')">资料管理</el-link>
          中批量上传各章课件自动识别章节，或上传整本教材 PDF，或自定义章节结构后按章上传资料。
        </span>
        <span v-else>教师上传教材并生成章节后，此处将显示章节学习路线与考核入口。</span>
      </template>
    </el-alert>

    <el-timeline v-if="chapters.length">
      <el-timeline-item
        v-for="ch in chapters"
        :key="ch.id"
        :type="isStudent ? (statusType(statusOf(ch)) as any) : undefined"
        :timestamp="`第 ${ch.order_idx} 章`"
        placement="top"
      >
        <el-card shadow="hover" style="margin-bottom: 8px">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 16px">
            <div style="flex: 1">
              <h3 style="margin: 0 0 4px">{{ ch.title }}</h3>
              <p style="color: #666; margin: 0 0 8px">{{ ch.description }}</p>

              <!-- 教师：班级完成率 -->
              <div v-if="isTeacher && progressMap[ch.id]" style="margin-top: 8px">
                <div style="display: flex; justify-content: space-between; font-size: 13px; color: #666; margin-bottom: 4px">
                  <span>班级完成率</span>
                  <span>
                    {{ progressMap[ch.id].completed_count }}/{{ progressMap[ch.id].student_count }}
                    （{{ progressMap[ch.id].completion_rate }}%）
                  </span>
                </div>
                <el-progress
                  :percentage="progressMap[ch.id].completion_rate"
                  :color="progressColor(progressMap[ch.id].completion_rate)"
                  :stroke-width="10"
                />
                <span v-if="!progressMap[ch.id].configured" style="font-size: 12px; color: #e6a23c">
                  尚未配置考核
                </span>
              </div>
            </div>

            <div style="display: flex; flex-direction: column; gap: 8px; align-items: flex-end; min-width: 160px">
              <template v-if="isStudent">
                <el-tag :type="statusType(statusOf(ch)) as any">
                  {{ statusType(statusOf(ch)) === 'success' ? '√ 已完成' :
                     statusType(statusOf(ch)) === 'info' ? '○ 未完成' : '○ 待学习' }}
                </el-tag>
                <span v-if="bestScoreByChapter[ch.id] != null" style="font-size: 14px">
                  最高分：<b :style="{ color: scoreColor(bestScoreByChapter[ch.id]!) }">{{ bestScoreByChapter[ch.id] }}</b>
                </span>
              </template>

              <span v-if="attempts[ch.id]" style="font-size: 12px; color: #999; text-align: right">
                <template v-if="isTeacher">
                  配置：{{ attempts[ch.id].configured ? '已设置' : '未设置' }}
                  <span v-if="attempts[ch.id].configured && attempts[ch.id].max > 0">
                    · 上限 {{ attempts[ch.id].max }} 次
                  </span>
                </template>
                <template v-else>
                  已考 {{ attempts[ch.id].used }} 次
                  <span v-if="attempts[ch.id].max > 0">/ 上限 {{ attempts[ch.id].max }} 次</span>
                  <span v-if="attempts[ch.id].remaining === 0" style="color: #f56c6c">（已达上限）</span>
                </template>
              </span>

              <div>
                <el-button
                  v-if="ongoingByChapter[ch.id]"
                  type="warning" size="small"
                  @click="resumeExam(ongoingByChapter[ch.id])"
                >继续答题</el-button>
                <el-button
                  v-if="latestSubmittedByChapter[ch.id] && !ongoingByChapter[ch.id]"
                  size="small"
                  @click="viewReport(latestSubmittedByChapter[ch.id])"
                >查看报告</el-button>
                <el-button
                  type="primary" size="small"
                  :disabled="(!ongoingByChapter[ch.id] && !isTeacher && attempts[ch.id]?.remaining === 0) || !hasClass"
                  @click="startExam(ch)"
                >{{ isTeacher ? '考核测试' : '开始考核' }}</el-button>
              </div>
            </div>
          </div>
        </el-card>
      </el-timeline-item>
    </el-timeline>

    <el-empty
      v-else-if="noChapters && !needsAgentGuide"
      description="暂无章节，请先在「资料管理」中上传课件、整本教材或自定义章节结构"
    />

    <template v-if="chapters.length && isTeacher && classProgress.length">
      <el-divider>班级各章完成率汇总</el-divider>
      <el-table :data="classProgress" size="small" border>
        <el-table-column label="章节" prop="chapter_title" />
        <el-table-column label="已完成" width="100">
          <template #default="{ row }">{{ row.completed_count }}/{{ row.student_count }}</template>
        </el-table-column>
        <el-table-column label="完成率" width="160">
          <template #default="{ row }">
            <el-progress
              :percentage="row.completion_rate"
              :color="progressColor(row.completion_rate)"
              :stroke-width="8"
            />
          </template>
        </el-table-column>
        <el-table-column label="考核配置" width="100">
          <template #default="{ row }">
            <el-tag :type="row.configured ? 'success' : 'warning'" size="small">
              {{ row.configured ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <el-divider>{{ isTeacher ? '我的测试记录' : '历史考核' }}</el-divider>
    <el-table :data="history" size="small" border>
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="章节" prop="chapter_title" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'submitted' ? 'success' : 'warning'" size="small">
            {{ row.status === 'submitted' ? '已提交' : '进行中' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="总分" width="80">
        <template #default="{ row }">
          <span v-if="row.total_score !== null" style="font-weight: 600">{{ row.total_score }}</span>
          <span v-else style="color: #ccc">—</span>
        </template>
      </el-table-column>
      <el-table-column label="开始时间" prop="started_at" width="180" />
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button v-if="row.status === 'ongoing'" text type="warning" @click="resumeExam(row.id)">继续答题</el-button>
          <el-button v-if="row.status === 'submitted' && row.total_score !== null" text type="primary" @click="viewReport(row.id)">报告</el-button>
          <el-button v-if="row.status === 'submitted' && row.total_score === null" text type="warning" :loading="regenerating === row.id" @click="regenerateReport(row.id)">生成报告</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

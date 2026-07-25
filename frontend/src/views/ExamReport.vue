<script setup lang="ts">
import { onMounted, ref, computed, reactive, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http, { sseStream } from '@/api'
import MarkdownView from '@/components/MarkdownView.vue'
import { useAuthStore } from '@/stores/auth'
import { handleMaterialClick, fmtVideoTime, type MaterialRec } from '@/utils/materialAccess'

interface Recommend {
  material_id: number; type: string; title: string
  chapter_title?: string; file_url: string; video_start_sec?: number | null
  page?: string | null
}
interface Followup {
  id: number; question: string; answer: string
  recommendations: Recommend[]; created_at: string | null
}
interface GradingFb {
  verdict: string; comment: string; reward_delta?: number
  teacher_confirmed: boolean | null
  reviewer_id?: number; reviewer_name?: string
}
interface InterventionMeta {
  id: number; status: string; trigger: string
  student_message?: string
  teacher_response: string; resolved_score: number | null
  created_at?: string | null
  resolved_at?: string | null
}
interface FeedbackMeta {
  grading_feedback: Record<number, GradingFb>
  teacher_reviews?: Record<number, GradingFb>
  my_teacher_reviews?: Record<number, GradingFb>
  interventions: Record<number, InterventionMeta>
  followups?: Record<number, Followup[]>
}
interface ReportData {
  exam_id: number; chapter_id: number
  dimensions: Record<string, number>
  summary: string
  suggestions: string
  total_score: number | null
  weak_points: string[]
  created_at: string | null
  questions: any[]
  chapter_title?: string
  student_name?: string
  student_username?: string
  feedback_meta?: FeedbackMeta
  student_feedback_credit?: number
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const report = ref<ReportData | null>(null)

const isTeacherView = computed(() => route.path.includes('/teacher/'))
const isAdminView = computed(() => route.path.includes('/admin/exams/'))
const isStaffView = computed(() => isTeacherView.value || isAdminView.value)
/** 本人报告：可反馈/追问（学生或教师/管理员自测） */
const canInteract = computed(() => !isStaffView.value)
/** 教师/管理员审阅学生报告时的复核面板 */
const canTeacherReview = computed(() => isStaffView.value)
/** 教师/管理员自己做单元测试 */
const isStaffSelfTest = computed(
  () => canInteract.value && (auth.user?.role === 'teacher' || auth.user?.role === 'admin'),
)
const examId = computed(() => Number(route.params.id))
const staffGradingApi = computed(() => `/exams/teacher/all/${examId.value}/questions`)
const staffFollowupsApi = computed(() => `/exams/teacher/all/${examId.value}/questions`)
const reportApiUrl = computed(() => {
  if (isAdminView.value) return `/admin/exams/${route.params.id}/report`
  if (isTeacherView.value) return `/exams/teacher/all/${route.params.id}/report`
  return `/exams/${route.params.id}/report`
})

const dimensionList = computed(() => {
  const dims = report.value?.dimensions || {}
  return Object.entries(dims).map(([name, score]) => ({
    name,
    score: Number(score) || 0,
  }))
})

const totalScore = computed(() => {
  if (report.value?.total_score !== null && report.value?.total_score !== undefined) {
    return report.value.total_score
  }
  if (!report.value?.questions?.length) return 0
  const total = report.value.questions.reduce((s, q) => s + (q.ai_score || 0), 0)
  return (total / report.value.questions.length).toFixed(1)
})

const correctRate = computed(() => {
  if (!report.value?.questions?.length) return '0%'
  const c = report.value.questions.filter(q => q.is_correct).length
  return Math.round((c / report.value.questions.length) * 100) + '%'
})

function getGradingFb(idx: number): GradingFb | null {
  const meta = report.value?.feedback_meta
  if (!meta) return null
  return meta.grading_feedback?.[idx] ?? meta.grading_feedback?.[String(idx) as any] ?? null
}
function getTeacherReview(idx: number): GradingFb | null {
  const meta = report.value?.feedback_meta
  if (!meta) return null
  return meta.teacher_reviews?.[idx] ?? meta.teacher_reviews?.[String(idx) as any] ?? null
}
function getMyTeacherReview(idx: number): GradingFb | null {
  const meta = report.value?.feedback_meta
  if (!meta) return null
  return meta.my_teacher_reviews?.[idx] ?? meta.my_teacher_reviews?.[String(idx) as any] ?? null
}
function getIntervention(idx: number): InterventionMeta | null {
  const meta = report.value?.feedback_meta
  if (!meta) return null
  return meta.interventions?.[idx] ?? meta.interventions?.[String(idx) as any] ?? null
}
function feedbackLocked(idx: number): boolean {
  return !!getGradingFb(idx)?.verdict
}
/** 仅「判卷有误」且存在有效介入时展示介入信息 */
function showIntervention(idx: number): boolean {
  const iv = getIntervention(idx)
  if (!iv || iv.status === 'dismissed') return false
  if (isStaffSelfTest.value) return false
  return getGradingFb(idx)?.verdict === 'disagree'
}
function getFollowupList(idx: number): Followup[] {
  return followups.value[idx] || []
}
function getFollowupCount(idx: number): number {
  return getFollowupList(idx).length
}

function syncFollowupsFromReport() {
  const raw = report.value?.feedback_meta?.followups
  if (!raw) return
  for (const [k, v] of Object.entries(raw)) {
    const idx = Number(k)
    if (Array.isArray(v) && v.length) {
      followups.value[idx] = v as Followup[]
    }
  }
}

// 每题追问状态
const expandedQ = ref<Record<number, boolean>>({})
const followups = ref<Record<number, Followup[]>>({})
const askInputs = reactive<Record<number, string>>({})
const askLoading = ref<Record<number, boolean>>({})
const disagreeComments = reactive<Record<number, string>>({})
const fbSubmitting = ref<Record<number, boolean>>({})
const materialLoading = ref<string | null>(null)
const videoDialog = ref(false)
const videoBlobUrl = ref('')
const videoStartSec = ref(0)
const interventionDialog = ref(false)
const interventionDetail = ref<InterventionMeta | null>(null)
const interventionLoading = ref(false)
const interventionQuestionIdx = ref<number | null>(null)

async function load() {
  try {
    const { data } = await http.get(reportApiUrl.value)
    report.value = data
    syncFollowupsFromReport()
    await loadAdaptiveRecommend()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  }
}

function followupsUrl(idx: number) {
  if (canTeacherReview.value) return `${staffFollowupsApi.value}/${idx}/followups`
  return `/exams/${examId.value}/questions/${idx}/followups`
}

async function loadFollowups(idx: number) {
  try {
    const { data } = await http.get(followupsUrl(idx))
    followups.value[idx] = data || []
  } catch {
    followups.value[idx] = []
  }
}

async function toggleQuestionPanel(idx: number) {
  expandedQ.value[idx] = !expandedQ.value[idx]
  if (expandedQ.value[idx] && !followups.value[idx]) {
    await loadFollowups(idx)
  }
}

async function submitGradingFeedback(idx: number, verdict: 'agree' | 'disagree') {
  if (canTeacherReview.value) {
    return submitTeacherGradingReview(idx, verdict)
  }
  if (!canInteract.value) return
  if (feedbackLocked(idx)) {
    ElMessage.warning('本题已提交判卷反馈，不可修改')
    return
  }
  let comment = disagreeComments[idx] || ''
  if (verdict === 'disagree' && !comment.trim()) {
    try {
      const { value } = await ElMessageBox.prompt(
        isStaffSelfTest.value
          ? '请说明 AI 判卷有误的原因（可留空，将直接用于模型校正）'
          : '请简要说明判卷有误的原因（可留空，提交后将自动通知教师介入）',
        isStaffSelfTest.value ? '教师判卷反馈' : '判卷反馈',
        {
          confirmButtonText: '提交',
          cancelButtonText: '取消',
          inputPlaceholder: isStaffSelfTest.value
            ? '例如：参考答案应接受等价写法…'
            : '例如：我的答案与参考答案等价…',
        },
      )
      comment = value || ''
      disagreeComments[idx] = comment
    } catch {
      return
    }
  }
  fbSubmitting.value[idx] = true
  try {
    const { data } = await http.post(`/exams/${examId.value}/questions/${idx}/grading-feedback`, {
      verdict,
      comment,
    })
    if (!report.value!.feedback_meta) {
      report.value!.feedback_meta = { grading_feedback: {}, interventions: {} }
    }
    report.value!.feedback_meta!.grading_feedback[idx] = {
      verdict,
      comment: disagreeComments[idx] || '',
      reward_delta: data.reward_delta ?? 0,
      teacher_confirmed: data.direct_ai_correction ? true : null,
    }
    if (data.question_ai_feedback && report.value?.questions) {
      const q = report.value.questions.find((item: any) => item.idx === idx)
      if (q) q.ai_feedback = data.question_ai_feedback
    }
    if (data.intervention_id) {
      const prev = getIntervention(idx)
      report.value!.feedback_meta!.interventions[idx] = {
        id: data.intervention_id,
        status: prev?.status || 'pending',
        trigger: prev?.trigger || (data.intervention_auto ? 'auto' : 'manual'),
        student_message: prev?.student_message || comment || '',
        teacher_response: prev?.teacher_response || '',
        resolved_score: prev?.resolved_score ?? null,
        created_at: prev?.created_at || new Date().toISOString(),
        resolved_at: prev?.resolved_at ?? null,
      }
      if (data.intervention_existing) {
        ElMessage.info('判卷异议已记录，已关联您的教师介入申请')
      } else {
        ElMessage.warning('已标记判卷有误，系统已自动提交教师介入')
      }
    } else if (verdict === 'agree') {
      ElMessage.success(isStaffSelfTest.value ? '教师反馈已记录（用于模型训练）' : '感谢反馈，已记录')
    } else if (data.direct_ai_correction) {
      ElMessage.success('AI 判卷错误已直接记录，将用于模型优化')
    } else {
      ElMessage.info('已记录您的异议')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    fbSubmitting.value[idx] = false
  }
}

async function submitTeacherGradingReview(idx: number, verdict: 'agree' | 'disagree') {
  let comment = disagreeComments[idx] || ''
  if (verdict === 'disagree' && !comment.trim()) {
    try {
      const { value } = await ElMessageBox.prompt('请说明 AI 判卷有误的原因（可留空）', '教师复核', {
        confirmButtonText: '提交',
        cancelButtonText: '取消',
        inputPlaceholder: '例如：应给部分分…',
      })
      comment = value || ''
      disagreeComments[idx] = comment
    } catch {
      return
    }
  }
  fbSubmitting.value[idx] = true
  try {
    const { data } = await http.post(`${staffGradingApi.value}/${idx}/grading-feedback`, {
      verdict,
      comment,
    })
    if (!report.value!.feedback_meta) {
      report.value!.feedback_meta = { grading_feedback: {}, interventions: {}, teacher_reviews: {}, my_teacher_reviews: {} }
    }
    const item: GradingFb = {
      verdict,
      comment,
      teacher_confirmed: null,
      reviewer_name: data.reviewer_name,
    }
    report.value!.feedback_meta!.my_teacher_reviews = report.value!.feedback_meta!.my_teacher_reviews || {}
    report.value!.feedback_meta!.teacher_reviews = report.value!.feedback_meta!.teacher_reviews || {}
    report.value!.feedback_meta!.my_teacher_reviews[idx] = item
    report.value!.feedback_meta!.teacher_reviews[idx] = item
    ElMessage.success('教师复核已记录')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    fbSubmitting.value[idx] = false
  }
}

async function viewIntervention(idx: number) {
  const local = getIntervention(idx)
  if (!local) return
  interventionQuestionIdx.value = idx
  interventionDetail.value = local
  interventionDialog.value = true
  interventionLoading.value = true
  try {
    const { data } = await http.get<InterventionMeta>(`/exams/${examId.value}/questions/${idx}/intervention`)
    interventionDetail.value = data
    if (report.value?.feedback_meta) {
      report.value.feedback_meta.interventions[idx] = data
    }
  } catch {
    /* 使用本地缓存 */
  } finally {
    interventionLoading.value = false
  }
}

async function askAboutQuestion(idx: number) {
  const text = (askInputs[idx] || '').trim()
  if (!text || askLoading.value[idx]) return
  askLoading.value[idx] = true
  const pendingRecs: Recommend[] = []
  let answer = ''
  try {
    await sseStream(
      `/exams/${examId.value}/questions/${idx}/ask`,
      { question: text },
      (chunk) => { answer += chunk },
      {
        onEvent: (name, data) => {
          if (name === 'recommend') {
            try {
              const obj = JSON.parse(data)
              pendingRecs.push(...(obj.recommendations || []))
            } catch { /* ignore */ }
          }
        },
      },
    )
    askInputs[idx] = ''
    expandedQ.value[idx] = true
    await loadFollowups(idx)
  } catch (e: any) {
    ElMessage.error(e?.message || '提问失败')
  } finally {
    askLoading.value[idx] = false
  }
}

const adaptiveRecs = ref<any[]>([])
async function loadAdaptiveRecommend() {
  if (!report.value) return
  const weakPoints = report.value.weak_points || []
  const query = weakPoints.length > 0
    ? weakPoints.join(' ')
    : Object.keys(report.value.dimensions || {}).join(' ')
  try {
    const { data } = await http.post('/recommend', {
      question: query,
      chapter_id: report.value.chapter_id,
      k: 4,
    })
    if (data && data.length > 0) {
      adaptiveRecs.value = data
      return
    }
    const { data: allData } = await http.post('/recommend', {
      question: query,
      k: 4,
    })
    if (allData && allData.length > 0) {
      adaptiveRecs.value = allData
      return
    }
  } catch { /* fallback */ }
  try {
    const { data: materials } = await http.get('/materials', {
      params: { chapter_id: report.value.chapter_id },
    })
    adaptiveRecs.value = (materials || []).map((m: any) => ({
      material_id: m.id,
      type: m.type,
      title: m.title,
      chapter_title: '',
      file_url: `/api/materials/file/${m.id}`,
      video_start_sec: null,
    }))
  } catch {
    adaptiveRecs.value = []
  }
}

const typeTag = (t: string) => ({ 选择题: '', 判断题: 'success', 填空题: 'info', 简答题: 'warning' } as any)[t] || (t === 'pdf' ? 'danger' : t === 'ppt' ? 'warning' : t === 'video' ? 'success' : 'info')

function fmtTime(s: number) {
  return fmtVideoTime(s)
}

function showVideo(blobUrl: string, startSec: number) {
  videoBlobUrl.value = blobUrl
  videoStartSec.value = startSec
  videoDialog.value = true
  nextTick(() => {
    const v = document.querySelector('video#report-video') as HTMLVideoElement | null
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

const fromInterventions = computed(() => route.query.from === 'interventions')

const backButtonLabel = computed(() => {
  if (fromInterventions.value) return '返回判卷介入'
  if (isStaffView.value) return '返回考核记录'
  return '返回路线'
})

function goBack() {
  if (fromInterventions.value) {
    const q: Record<string, string> = {}
    const s = route.query.status
    if (s === 'pending' || s === 'resolved') q.status = s
    const cid = route.query.class_id
    if (cid) q.class_id = String(cid)
    router.push({ path: '/teacher/exam-interventions', query: q })
    return
  }
  if (isAdminView.value) router.push('/admin/exam-records')
  else if (isTeacherView.value) router.push('/teacher/exam-records')
  else router.push('/chapters')
}

function answerToFullText(answer: string, options: string[]): string {
  if (!answer) return ''
  if (answer.length > 2 && answer.includes('.')) return answer
  const letter = answer.trim().toUpperCase().charAt(0)
  const opt = options.find(o => o.trim().toUpperCase().startsWith(letter))
  return opt || answer
}

function isCorrectOption(opt: string, correctAnswer: string): boolean {
  if (!correctAnswer) return false
  const letter = correctAnswer.trim().toUpperCase().charAt(0)
  return opt.trim().toUpperCase().startsWith(letter)
}

function isUserAnswer(opt: string, userAnswer: string): boolean {
  if (!userAnswer) return false
  if (userAnswer === opt) return true
  const letter = userAnswer.trim().toUpperCase().charAt(0)
  return opt.trim().toUpperCase().startsWith(letter)
}

function scoreColor(score: number): string {
  if (score >= 80) return '#67c23a'
  if (score >= 60) return '#e6a23c'
  return '#f56c6c'
}

function interventionStatusLabel(iv: InterventionMeta) {
  if (iv.status === 'pending') return '待教师处理'
  if (iv.status === 'resolved') return '教师已处理'
  return ''
}

function interventionTriggerLabel(trigger?: string) {
  return trigger === 'auto' ? '系统自动（判卷异议）' : '学生申请'
}

function interventionStatusText(status?: string) {
  if (status === 'pending') return '待教师处理'
  if (status === 'resolved') return '已处理'
  return status || '-'
}

function fmtDateTime(iso?: string | null) {
  if (!iso) return '-'
  return iso.replace('T', ' ').slice(0, 19)
}

onMounted(load)
</script>

<template>
  <div v-if="report">
    <div style="margin-bottom: 16px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
      <el-button @click="goBack">
        <el-icon><ArrowLeft /></el-icon>
        {{ backButtonLabel }}
      </el-button>
      <h3 style="margin: 0">{{ isStaffView ? '学生考核报告' : '学习评价报告' }}</h3>
    </div>

    <el-card v-if="isAdminView && report.student_feedback_credit != null" shadow="never" style="margin-bottom: 16px">
      <template #header>模型反馈训练（管理员）</template>
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="学生反馈信誉分">{{ report.student_feedback_credit }}</el-descriptions-item>
        <el-descriptions-item label="学生判卷反馈">
          {{ Object.keys(report.feedback_meta?.grading_feedback || {}).length }} 题有反馈
        </el-descriptions-item>
        <el-descriptions-item label="追问记录">
          {{ Object.values(report.feedback_meta?.followups || {}).reduce((s, arr) => s + (arr?.length || 0), 0) }} 条
        </el-descriptions-item>
      </el-descriptions>
      <div style="margin-top: 8px">
        <el-button text type="primary" size="small" @click="router.push('/admin/ai-feedback')">查看全站 AI 反馈监控</el-button>
      </div>
    </el-card>

    <el-card shadow="never" style="margin-bottom: 16px" v-if="isStaffView && report.student_name">
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="学生">{{ report.student_name }}（{{ report.student_username }}）</el-descriptions-item>
        <el-descriptions-item label="章节">{{ report.chapter_title }}</el-descriptions-item>
        <el-descriptions-item label="总分">{{ totalScore }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header>维度评价</template>
      <div v-if="dimensionList.length" class="dim-list">
        <div v-for="d in dimensionList" :key="d.name" class="dim-item">
          <div class="dim-label">
            <span>{{ d.name }}</span>
            <span :style="{ color: scoreColor(d.score), fontWeight: 600 }">{{ d.score }}</span>
          </div>
          <el-progress :percentage="d.score" :color="scoreColor(d.score)" :show-text="false" :stroke-width="14" />
        </div>
      </div>
      <el-empty v-else description="暂无维度数据" :image-size="60" />
      <el-divider />
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="总分">
          <span :style="{ color: scoreColor(Number(totalScore)), fontWeight: 600, fontSize: '16px' }">{{ totalScore }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="正确率">{{ correctRate }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header>总体评价</template>
      <p style="line-height: 1.8">{{ report.summary }}</p>
      <el-divider />
      <div v-if="report.weak_points && report.weak_points.length">
        <h4>薄弱知识点</h4>
        <div style="margin-bottom: 12px">
          <el-tag v-for="wp in report.weak_points" :key="wp" type="danger" size="small" style="margin: 0 4px 4px 0">{{ wp }}</el-tag>
        </div>
      </div>
      <h4>建议复习</h4>
      <MarkdownView :content="report.suggestions" />
    </el-card>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header>题目回顾</template>
      <div v-for="q in report.questions" :key="q.idx" class="q-review">
        <div class="q-head">
          <el-tag :type="typeTag(q.type)" size="small">{{ q.type }}</el-tag>
          <span class="q-idx">第 {{ q.idx }} 题</span>
          <el-tag v-if="q.kp_name" type="info" size="small">知识点：{{ q.kp_name }}</el-tag>
          <el-tag :type="q.is_correct ? 'success' : 'danger'" size="small">
            {{ q.is_correct ? '正确' : '错误' }} · {{ q.ai_score }}分
          </el-tag>
          <el-tag v-if="showIntervention(q.idx)" size="small" :type="getIntervention(q.idx)!.status === 'pending' ? 'warning' : 'success'">
            {{ interventionStatusLabel(getIntervention(q.idx)!) }}
          </el-tag>
        </div>
        <div class="q-stem">{{ q.stem }}</div>

        <div v-if="q.options && q.options.length" class="q-options">
          <div
            v-for="opt in q.options" :key="opt"
            :class="['q-option', {
              'opt-correct': isCorrectOption(opt, q.correct_answer),
              'opt-user-wrong': isUserAnswer(opt, q.user_answer) && !isCorrectOption(opt, q.correct_answer),
            }]"
          >
            <span v-if="isCorrectOption(opt, q.correct_answer)" class="opt-mark">✓</span>
            <span v-else-if="isUserAnswer(opt, q.user_answer)" class="opt-mark">✗</span>
            <span v-else class="opt-mark">○</span>
            {{ opt }}
          </div>
        </div>

        <div class="q-line"><b>你的回答：</b>{{ answerToFullText(q.user_answer, q.options || []) || '（未作答）' }}</div>
        <div class="q-line"><b>正确答案：</b>{{ answerToFullText(q.correct_answer, q.options || []) }}</div>
        <div v-if="q.analysis" class="q-line q-analysis"><b>解析：</b>{{ q.analysis }}</div>
        <div class="q-line q-fb"><b>评语：</b>{{ q.ai_feedback }}</div>

        <!-- 学生反馈与追问 -->
        <div v-if="canInteract" class="q-feedback-panel">
          <div class="q-feedback-actions">
            <span class="fb-label">{{ isStaffSelfTest ? '教师 AI 判卷反馈：' : 'AI 判卷反馈：' }}</span>
            <el-button
              size="small"
              :type="getGradingFb(q.idx)?.verdict === 'agree' ? 'success' : 'default'"
              :loading="fbSubmitting[q.idx]"
              :disabled="feedbackLocked(q.idx)"
              @click="submitGradingFeedback(q.idx, 'agree')"
            >判卷正确</el-button>
            <el-button
              size="small"
              :type="getGradingFb(q.idx)?.verdict === 'disagree' ? 'danger' : 'default'"
              :loading="fbSubmitting[q.idx]"
              :disabled="feedbackLocked(q.idx)"
              @click="submitGradingFeedback(q.idx, 'disagree')"
            >判卷有误</el-button>
            <el-button
              v-if="!isStaffSelfTest && showIntervention(q.idx)"
              size="small" text type="warning"
              @click="viewIntervention(q.idx)"
            >查看介入结果</el-button>
            <el-button size="small" text type="primary" @click="toggleQuestionPanel(q.idx)">
              {{ expandedQ[q.idx] ? '收起追问' : '向 AI 追问' }}
              <el-badge v-if="getFollowupCount(q.idx)" :value="getFollowupCount(q.idx)" style="margin-left: 4px" />
            </el-button>
          </div>
          <div v-if="feedbackLocked(q.idx)" class="teacher-review-hint">
            <el-tag size="small" :type="getGradingFb(q.idx)!.verdict === 'agree' ? 'success' : 'danger'">
              已反馈：{{ getGradingFb(q.idx)!.verdict === 'agree' ? '判卷正确' : '判卷有误' }}
            </el-tag>
            <span v-if="getGradingFb(q.idx)?.comment" style="font-size: 12px; color: #666; margin-left: 6px">
              {{ getGradingFb(q.idx)!.comment }}
            </span>
          </div>
          <div v-if="getTeacherReview(q.idx) && canInteract && !isStaffSelfTest" class="teacher-review-hint">
            <el-tag size="small" :type="getTeacherReview(q.idx)!.verdict === 'agree' ? 'success' : 'warning'">
              教师复核：{{ getTeacherReview(q.idx)!.verdict === 'agree' ? '认可 AI 判卷' : '认为 AI 判卷有误' }}
            </el-tag>
            <span v-if="getTeacherReview(q.idx)!.comment" style="font-size: 12px; color: #666; margin-left: 6px">
              {{ getTeacherReview(q.idx)!.comment }}
            </span>
          </div>
          <div v-if="isStaffSelfTest && getGradingFb(q.idx)?.verdict === 'disagree'" class="intervention-hint">
            <el-text type="info" size="small">教师标记的判卷错误已直接记录，将用于 AI 模型优化（不触发教师介入流程）</el-text>
          </div>
          <div v-if="!isStaffSelfTest && showIntervention(q.idx) && getIntervention(q.idx)?.status === 'pending'" class="intervention-hint">
            <el-text type="warning" size="small">教师介入申请已自动提交，请等待教师处理</el-text>
          </div>

          <div v-if="getFollowupCount(q.idx) && !expandedQ[q.idx]" class="followup-preview">
            <span style="font-size: 12px; color: #888">已有 {{ getFollowupCount(q.idx) }} 条追问记录，</span>
            <el-button text type="primary" size="small" @click="toggleQuestionPanel(q.idx)">点击查看</el-button>
          </div>

          <div v-if="expandedQ[q.idx]" class="q-ask-box">
            <div v-if="!getFollowupList(q.idx).length" style="font-size: 12px; color: #999; margin-bottom: 8px">暂无追问记录</div>
            <div v-for="f in getFollowupList(q.idx)" :key="f.id" class="followup-item">
              <div class="fu-meta" v-if="f.created_at">{{ f.created_at.replace('T', ' ').slice(0, 19) }}</div>
              <div class="fu-q"><b>问：</b>{{ f.question }}</div>
              <div class="fu-a"><MarkdownView :content="f.answer" /></div>
              <div v-if="f.recommendations?.length" class="fu-recs">
                <div class="rec-title">推荐资料</div>
                <div v-for="r in f.recommendations" :key="r.material_id + '-' + (r.page || '')" class="rec-item">
                  <el-tag :type="typeTag(r.type)" size="small">{{ r.type || '资料' }}</el-tag>
                  <span class="rec-name">{{ r.title }}</span>
                  <span v-if="r.chapter_title" class="rec-chapter">{{ r.chapter_title }}</span>
                  <el-button
                    text type="primary" size="small"
                    :loading="materialLoading === `${r.material_id || r.file_url}`"
                    @click="openRecommend(r)"
                  >{{ recActionLabel(r) }}</el-button>
                </div>
              </div>
            </div>
            <div class="ask-input-row">
              <el-input
                v-model="askInputs[q.idx]"
                placeholder="针对本题向 AI 提问，例如：为什么我的答案不对？"
                @keyup.enter="askAboutQuestion(q.idx)"
              />
              <el-button type="primary" :loading="askLoading[q.idx]" @click="askAboutQuestion(q.idx)">提问</el-button>
            </div>
          </div>
        </div>

        <!-- 教师/管理员：复核判卷 + 查看学生追问 -->
        <div v-else-if="canTeacherReview" class="q-feedback-panel">
          <div class="q-feedback-actions">
            <span class="fb-label">教师 AI 判卷复核：</span>
            <el-button
              size="small"
              :type="getMyTeacherReview(q.idx)?.verdict === 'agree' ? 'success' : 'default'"
              :loading="fbSubmitting[q.idx]"
              @click="submitGradingFeedback(q.idx, 'agree')"
            >判卷正确</el-button>
            <el-button
              size="small"
              :type="getMyTeacherReview(q.idx)?.verdict === 'disagree' ? 'danger' : 'default'"
              :loading="fbSubmitting[q.idx]"
              @click="submitGradingFeedback(q.idx, 'disagree')"
            >判卷有误</el-button>
            <el-button size="small" text type="primary" @click="toggleQuestionPanel(q.idx)">
              学生追问记录
              <el-badge v-if="getFollowupCount(q.idx)" :value="getFollowupCount(q.idx)" style="margin-left: 4px" />
            </el-button>
          </div>
          <div v-if="getGradingFb(q.idx)" style="margin-top: 6px">
            <el-tag size="small" :type="getGradingFb(q.idx)!.verdict === 'agree' ? 'success' : 'danger'">
              学生反馈：{{ getGradingFb(q.idx)!.verdict === 'agree' ? '认可判卷' : '质疑判卷' }}
            </el-tag>
            <span v-if="getGradingFb(q.idx)?.comment" style="font-size: 12px; color: #666; margin-left: 6px">
              {{ getGradingFb(q.idx)!.comment }}
            </span>
          </div>
          <div v-if="getIntervention(q.idx) && canTeacherReview" style="margin-top: 4px">
            <el-tag size="small" type="warning">{{ interventionStatusLabel(getIntervention(q.idx)!) || '介入记录' }}</el-tag>
          </div>
          <div v-if="getFollowupCount(q.idx) && !expandedQ[q.idx]" class="followup-preview">
            <span style="font-size: 12px; color: #888">学生已有 {{ getFollowupCount(q.idx) }} 条追问，</span>
            <el-button text type="primary" size="small" @click="toggleQuestionPanel(q.idx)">点击查看</el-button>
          </div>
          <div v-if="expandedQ[q.idx]" class="q-ask-box">
            <div v-if="!getFollowupList(q.idx).length" style="font-size: 12px; color: #999">该题暂无学生追问</div>
            <div v-for="f in getFollowupList(q.idx)" :key="f.id" class="followup-item">
              <div class="fu-meta" v-if="f.created_at">{{ f.created_at.replace('T', ' ').slice(0, 19) }}</div>
              <div class="fu-q"><b>问：</b>{{ f.question }}</div>
              <div class="fu-a"><MarkdownView :content="f.answer" /></div>
              <div v-if="f.recommendations?.length" class="fu-recs">
                <div class="rec-title">推荐资料</div>
                <div v-for="r in f.recommendations" :key="r.material_id + '-' + (r.page || '')" class="rec-item">
                  <el-tag :type="typeTag(r.type)" size="small">{{ r.type || '资料' }}</el-tag>
                  <span class="rec-name">{{ r.title }}</span>
                  <span v-if="r.chapter_title" class="rec-chapter">{{ r.chapter_title }}</span>
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
      </div>
    </el-card>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header><span>自适应学习推荐（基于薄弱知识点自动检索）</span></template>
      <el-empty v-if="!adaptiveRecs.length" description="该章节暂无课程资料，请联系教师上传教材后重新考核" :image-size="80" />
      <div v-else>
        <p v-if="report.weak_points?.length" style="color: #999; font-size: 12px; margin-bottom: 8px">
          针对薄弱知识点：{{ report.weak_points.join('、') }}
        </p>
        <div v-for="r in adaptiveRecs" :key="r.material_id" class="rec-item">
          <el-tag :type="typeTag(r.type)" size="small">{{ r.type }}</el-tag>
          <span class="rec-name">{{ r.title }}</span>
          <span v-if="r.chapter_title" class="rec-chapter">{{ r.chapter_title }}</span>
          <el-button
            text type="primary" size="small"
            :loading="materialLoading === `${r.material_id || r.file_url}`"
            @click="openRecommend(r)"
          >{{ recActionLabel(r) }}</el-button>
        </div>
      </div>
    </el-card>
  </div>
  <div v-else style="text-align: center; padding: 40px">
    <el-text type="info">报告加载中...</el-text>
  </div>

  <el-dialog v-model="videoDialog" title="视频预览" width="720px" @close="onVideoDialogClose">
    <video v-if="videoBlobUrl" id="report-video" :src="videoBlobUrl" controls style="width: 100%" />
  </el-dialog>

  <el-dialog
    v-model="interventionDialog"
    :title="interventionQuestionIdx != null ? `第 ${interventionQuestionIdx} 题 · 教师介入` : '教师介入'"
    width="520px"
  >
    <div v-loading="interventionLoading">
      <template v-if="interventionDetail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="处理状态">
            <el-tag
              size="small"
              :type="interventionDetail.status === 'pending' ? 'warning' : interventionDetail.status === 'resolved' ? 'success' : 'info'"
            >{{ interventionStatusText(interventionDetail.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="申请方式">{{ interventionTriggerLabel(interventionDetail.trigger) }}</el-descriptions-item>
          <el-descriptions-item label="申请时间">{{ fmtDateTime(interventionDetail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="申请说明">
            {{ interventionDetail.student_message || '（无）' }}
          </el-descriptions-item>
          <el-descriptions-item v-if="interventionDetail.status !== 'pending'" label="处理时间">
            {{ fmtDateTime(interventionDetail.resolved_at) }}
          </el-descriptions-item>
          <el-descriptions-item v-if="interventionDetail.teacher_response" label="教师回复">
            {{ interventionDetail.teacher_response }}
          </el-descriptions-item>
          <el-descriptions-item v-if="interventionDetail.resolved_score != null" label="修正得分">
            {{ interventionDetail.resolved_score }} 分
          </el-descriptions-item>
        </el-descriptions>
        <el-alert
          v-if="interventionDetail.status === 'pending'"
          type="info"
          :closable="false"
          show-icon
          style="margin-top: 12px"
          title="教师尚未处理，请耐心等待。每题仅可申请一次教师介入。"
        />
      </template>
    </div>
  </el-dialog>
</template>

<style scoped>
.dim-list { padding: 8px 0; }
.dim-item { margin-bottom: 16px; }
.dim-label { display: flex; justify-content: space-between; margin-bottom: 4px; font-size: 14px; }
.q-review { padding: 12px 0; border-bottom: 1px solid #f0f0f0; }
.q-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }
.q-idx { font-weight: 600; }
.q-stem { font-size: 15px; margin: 6px 0; line-height: 1.6; }
.q-options { margin: 8px 0; }
.q-option { font-size: 13px; padding: 4px 8px; margin: 3px 0; border-radius: 4px; display: flex; align-items: center; gap: 6px; }
.opt-correct { background: #f0f9eb; color: #67c23a; font-weight: 500; }
.opt-user-wrong { background: #fef0f0; color: #f56c6c; }
.opt-mark { font-weight: bold; width: 16px; }
.q-line { font-size: 13px; color: #555; margin: 4px 0; }
.q-fb { color: #409eff; }
.q-analysis { color: #e6a23c; }
.q-feedback-panel { margin-top: 10px; padding: 10px; background: #fafafa; border-radius: 6px; }
.q-feedback-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.fb-label { font-size: 13px; color: #666; }
.q-ask-box { margin-top: 10px; }
.followup-item { margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px dashed #e8e8e8; }
.fu-meta { font-size: 11px; color: #aaa; margin-bottom: 2px; }
.followup-preview { margin-top: 8px; font-size: 12px; }
.teacher-review-hint { margin-top: 6px; }
.fu-q { font-size: 13px; margin-bottom: 4px; }
.fu-a { font-size: 13px; }
.fu-recs { margin-top: 4px; }
.rec-title { font-size: 12px; color: #888; margin-bottom: 4px; }
.ask-input-row { display: flex; gap: 8px; margin-top: 8px; }
.intervention-hint { margin-top: 6px; }
.teacher-reply { margin-top: 8px; font-size: 13px; color: #e6a23c; }
.q-feedback-readonly { margin-top: 8px; }
.rec-item { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px dashed #eee; }
.rec-name { font-weight: 500; }
.rec-chapter { color: #888; font-size: 12px; }
</style>

<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/api'
import MarkdownView from '@/components/MarkdownView.vue'

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
}

const route = useRoute()
const router = useRouter()
const report = ref<ReportData | null>(null)

const isTeacherView = computed(() => route.path.includes('/teacher/'))
const isAdminView = computed(() => route.path.includes('/admin/exams/'))
const isStaffView = computed(() => isTeacherView.value || isAdminView.value)
const reportApiUrl = computed(() => {
  if (isAdminView.value) return `/admin/exams/${route.params.id}/report`
  if (isTeacherView.value) return `/exams/teacher/all/${route.params.id}/report`
  return `/exams/${route.params.id}/report`
})

// 维度列表（用于进度条展示）
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

async function load() {
  try {
    const { data } = await http.get(reportApiUrl.value)
    report.value = data
    await loadAdaptiveRecommend()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  }
}

const adaptiveRecs = ref<any[]>([])
async function loadAdaptiveRecommend() {
  if (!report.value) return

  // 优先用薄弱知识点作为检索词（比维度名更精准）
  const weakPoints = report.value.weak_points || []
  const query = weakPoints.length > 0
    ? weakPoints.join(' ')
    : Object.keys(report.value.dimensions || {}).join(' ')

  try {
    // 先限定章节搜索
    const { data } = await http.post('/recommend', {
      question: query,
      chapter_id: report.value.chapter_id,
      k: 4,
    })
    if (data && data.length > 0) {
      adaptiveRecs.value = data
      return
    }
    // 章内无结果，全库搜索
    const { data: allData } = await http.post('/recommend', {
      question: query,
      k: 4,
    })
    if (allData && allData.length > 0) {
      adaptiveRecs.value = allData
      return
    }
  } catch {
    // 检索失败，降级为直接列出章节资料
  }

  // 降级：直接列出该章节的所有资料
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

const typeTag = (t: string) => ({ 选择题: '', 判断题: 'success', 简答题: 'warning' } as any)[t] || (t === 'pdf' ? 'danger' : t === 'ppt' ? 'warning' : t === 'video' ? 'success' : 'info')

function openUrl(url: string) { window.open(url, '_blank') }

function goBack() {
  if (isAdminView.value) {
    router.push('/admin/exam-records')
  } else if (isTeacherView.value) {
    router.push('/teacher/exam-records')
  } else {
    router.push('/chapters')
  }
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

onMounted(load)
</script>

<template>
  <div v-if="report">
    <div style="margin-bottom: 16px; display: flex; align-items: center; gap: 12px">
      <el-button @click="goBack">
        <el-icon><ArrowLeft /></el-icon>
        {{ isStaffView ? '返回考核记录' : '返回路线' }}
      </el-button>
      <h3 style="margin: 0">{{ isStaffView ? '学生考核报告' : '学习评价报告' }}</h3>
    </div>

    <el-card shadow="never" style="margin-bottom: 16px" v-if="isStaffView && report.student_name">
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="学生">{{ report.student_name }}（{{ report.student_username }}）</el-descriptions-item>
        <el-descriptions-item label="章节">{{ report.chapter_title }}</el-descriptions-item>
        <el-descriptions-item label="总分">{{ totalScore }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header>维度评价</template>

      <!-- 用进度条展示各维度得分 -->
      <div v-if="dimensionList.length" class="dim-list">
        <div v-for="d in dimensionList" :key="d.name" class="dim-item">
          <div class="dim-label">
            <span>{{ d.name }}</span>
            <span :style="{ color: scoreColor(d.score), fontWeight: 600 }">{{ d.score }}</span>
          </div>
          <el-progress
            :percentage="d.score"
            :color="scoreColor(d.score)"
            :show-text="false"
            :stroke-width="14"
          />
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
          <el-tag v-for="wp in report.weak_points" :key="wp" type="danger" size="small" style="margin: 0 4px 4px 0">
            {{ wp }}
          </el-tag>
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
        </div>
        <div class="q-stem">{{ q.stem }}</div>

        <!-- 选项列表（选择题/判断题） -->
        <div v-if="q.options && q.options.length" class="q-options">
          <div
            v-for="opt in q.options"
            :key="opt"
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
      </div>
    </el-card>

    <!-- 创新扩展：自适应学习推荐 -->
    <el-card shadow="never" style="margin-top: 16px">
      <template #header>
        <span>自适应学习推荐（基于薄弱知识点自动检索）</span>
      </template>
      <el-empty v-if="!adaptiveRecs.length" description="该章节暂无课程资料，请联系教师上传教材后重新考核" :image-size="80" />
      <div v-else>
        <p v-if="report.weak_points && report.weak_points.length" style="color: #999; font-size: 12px; margin-bottom: 8px">
          针对薄弱知识点：{{ report.weak_points.join('、') }}
        </p>
        <div v-for="r in adaptiveRecs" :key="r.material_id" class="rec-item">
          <el-tag :type="typeTag(r.type)" size="small">{{ r.type }}</el-tag>
          <span class="rec-name">{{ r.title }}</span>
          <span v-if="r.chapter_title" class="rec-chapter">{{ r.chapter_title }}</span>
          <el-button text type="primary" size="small" @click="openUrl(r.file_url)">
            {{ r.type === 'video' ? `观看视频 (${r.video_start_sec || 0}s)` : '查看' }}
          </el-button>
        </div>
      </div>
    </el-card>
  </div>
  <div v-else style="text-align: center; padding: 40px">
    <el-text type="info">报告加载中...</el-text>
  </div>
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
.rec-item { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px dashed #eee; }
.rec-name { font-weight: 500; }
.rec-chapter { color: #888; font-size: 12px; }
</style>

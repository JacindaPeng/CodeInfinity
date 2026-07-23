<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/api'
import { useCourseAgentStore } from '@/stores/courseAgent'
import { useAgentBoundClasses } from '@/composables/useAgentBoundClasses'

interface QuestionContext {
  type?: string
  stem?: string
  options?: string[]
  user_answer?: string
  correct_answer?: string
  is_correct?: boolean | null
  ai_score?: number | null
  ai_feedback?: string
  analysis?: string
  kp_name?: string
  max_score?: number
}

interface Intervention {
  id: number
  exam_id: number
  question_idx: number
  student_id: number
  student_name: string
  student_username: string
  chapter_title: string
  class_id: number
  trigger: string
  status: string
  student_message: string
  teacher_response: string
  resolved_by_id?: number | null
  resolved_by_name?: string
  context: QuestionContext
  resolved_score: number | null
  created_at: string | null
  resolved_at: string | null
}

interface ClassItem {
  id: number
  name: string
}

const route = useRoute()
const router = useRouter()
const agentStore = useCourseAgentStore()
const { loadScopedClasses, pickClassId } = useAgentBoundClasses()
const list = ref<Intervention[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const statusFilter = ref('pending')
const pendingCount = ref(0)
const classes = ref<ClassItem[]>([])
const filterClass = ref<number | undefined>(undefined)

const resolveVisible = ref(false)
const detailVisible = ref(false)
const resolving = ref<Intervention | null>(null)
const detailLoading = ref(false)
const resolveForm = ref({
  teacher_response: '',
  resolved_score: undefined as number | undefined,
  student_feedback_correct: undefined as boolean | undefined,
})

async function loadPendingCount() {
  try {
    const { data } = await http.get('/exams/teacher/interventions/pending-count')
    pendingCount.value = data.count || 0
  } catch {
    pendingCount.value = 0
  }
}

async function loadClasses() {
  try {
    await agentStore.restoreAgent()
    const data = await loadScopedClasses()
    classes.value = data || []
    filterClass.value = pickClassId(classes.value, filterClass.value)
  } catch {
    classes.value = []
    filterClass.value = undefined
  }
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/exams/teacher/interventions', {
      params: {
        status: statusFilter.value,
        class_id: filterClass.value || undefined,
        agent_id: agentStore.current?.id || undefined,
        page: page.value,
        size: size.value,
      },
    })
    list.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  page.value = 1
  load()
}

async function fetchDetail(row: Intervention) {
  detailLoading.value = true
  try {
    const { data } = await http.get<Intervention>(`/exams/teacher/interventions/${row.id}`)
    resolving.value = data
    return data
  } catch {
    resolving.value = row
    return row
  } finally {
    detailLoading.value = false
  }
}

async function openResolve(row: Intervention) {
  resolveVisible.value = true
  const data = await fetchDetail(row)
  resolveForm.value = {
    teacher_response: '',
    resolved_score: data.context?.ai_score ?? undefined,
    student_feedback_correct: undefined,
  }
}

async function openDetail(row: Intervention) {
  detailVisible.value = true
  await fetchDetail(row)
}

async function submitResolve() {
  if (!resolving.value) return
  try {
    await http.put(`/exams/teacher/interventions/${resolving.value.id}`, {
      action: 'resolved',
      ...resolveForm.value,
    })
    ElMessage.success('已处理')
    resolveVisible.value = false
    await Promise.all([load(), loadPendingCount()])
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '处理失败')
  }
}

function viewReport(examId: number) {
  router.push({
    path: `/teacher/exams/${examId}/report`,
    query: {
      from: 'interventions',
      status: statusFilter.value,
      class_id: filterClass.value ? String(filterClass.value) : undefined,
    },
  })
}

function triggerLabel(t: string) {
  return t === 'auto' ? '系统自动' : '学生申请'
}

function resultSummary(row: Intervention) {
  const parts: string[] = []
  if (row.resolved_score != null) parts.push(`修正得分 ${row.resolved_score}`)
  if (row.teacher_response?.trim()) parts.push(row.teacher_response.trim())
  return parts.join(' · ') || '—'
}

function fmtTime(iso?: string | null) {
  if (!iso) return '—'
  return iso.replace('T', ' ').slice(0, 19)
}

function maxScore(ctx?: QuestionContext) {
  return ctx?.max_score ?? 100
}

function isCorrectOption(opt: string, correctAnswer?: string): boolean {
  if (!correctAnswer) return false
  const letter = correctAnswer.trim().toUpperCase().charAt(0)
  return opt.trim().toUpperCase().startsWith(letter)
}

function isUserAnswer(opt: string, userAnswer?: string): boolean {
  if (!userAnswer) return false
  if (userAnswer === opt) return true
  const letter = userAnswer.trim().toUpperCase().charAt(0)
  return opt.trim().toUpperCase().startsWith(letter)
}

onMounted(async () => {
  const s = route.query.status
  if (s === 'pending' || s === 'resolved') statusFilter.value = s
  const cid = route.query.class_id
  if (cid) {
    const n = Number(cid)
    if (!Number.isNaN(n)) filterClass.value = n
  }
  await loadClasses()
  await loadPendingCount()
  await load()
})
</script>

<template>
  <div>
    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px">
      <h3 style="margin: 0">判卷争议介入</h3>
      <el-badge v-if="pendingCount" :value="pendingCount" type="danger" />
    </div>

    <el-card shadow="never" style="margin-bottom: 16px">
      <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
        <el-radio-group v-model="statusFilter" @change="onFilterChange">
          <el-radio-button value="pending">待处理</el-radio-button>
          <el-radio-button value="resolved">已处理</el-radio-button>
        </el-radio-group>
        <el-select
          v-model="filterClass"
          placeholder="按班级筛选"
          clearable
          style="width: 200px"
          @change="onFilterChange"
        >
          <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
      </div>
    </el-card>

    <el-table :data="list" v-loading="loading" stripe>
      <el-table-column label="学生" min-width="120">
        <template #default="{ row }">
          {{ row.student_name }}（{{ row.student_username }}）
        </template>
      </el-table-column>
      <el-table-column prop="chapter_title" label="章节" min-width="140" />
      <el-table-column label="题号" width="70">
        <template #default="{ row }">第 {{ row.question_idx }} 题</template>
      </el-table-column>
      <el-table-column prop="student_message" label="学生说明" min-width="160" show-overflow-tooltip />
      <el-table-column v-if="statusFilter === 'resolved'" label="处理人" width="100">
        <template #default="{ row }">{{ row.resolved_by_name || '—' }}</template>
      </el-table-column>
      <el-table-column v-if="statusFilter === 'resolved'" label="处理结果" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ resultSummary(row) }}</template>
      </el-table-column>
      <el-table-column v-if="statusFilter === 'resolved'" label="处理时间" width="160">
        <template #default="{ row }">{{ fmtTime(row.resolved_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" size="small" @click="viewReport(row.exam_id)">查看报告</el-button>
          <el-button
            v-if="row.status === 'pending'"
            text type="warning" size="small"
            @click="openResolve(row)"
          >处理</el-button>
          <el-button
            v-else-if="row.status === 'resolved'"
            text type="primary" size="small"
            @click="openDetail(row)"
          >查看详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div style="margin-top: 16px; text-align: right">
      <el-pagination
        v-model:current-page="page"
        :page-size="size"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="load"
      />
    </div>

    <el-dialog v-model="resolveVisible" title="处理判卷争议" width="640px">
      <div v-loading="detailLoading">
        <template v-if="resolving">
          <p style="color: #666; font-size: 13px; margin-bottom: 8px">
            学生：{{ resolving.student_name }} · 第 {{ resolving.question_idx }} 题
            <el-tag v-if="resolving.context?.type" size="small" style="margin-left: 6px">{{ resolving.context.type }}</el-tag>
          </p>
          <p v-if="resolving.student_message" style="font-size: 13px; margin-bottom: 12px">
            <b>学生说明：</b>{{ resolving.student_message }}
          </p>

          <div v-if="resolving.context" class="ctx-box">
            <div class="ctx-line"><b>题干：</b>{{ resolving.context.stem }}</div>
            <div v-if="resolving.context.options?.length" class="ctx-options">
              <div
                v-for="opt in resolving.context.options"
                :key="opt"
                :class="['ctx-opt', {
                  'opt-correct': isCorrectOption(opt, resolving.context.correct_answer),
                  'opt-user': isUserAnswer(opt, resolving.context.user_answer),
                  'opt-user-wrong': isUserAnswer(opt, resolving.context.user_answer) && !isCorrectOption(opt, resolving.context.correct_answer),
                }]"
              >
                {{ opt }}
              </div>
            </div>
            <div class="ctx-line"><b>学生作答：</b>{{ resolving.context.user_answer || '（未作答）' }}</div>
            <div class="ctx-line"><b>参考答案：</b>{{ resolving.context.correct_answer }}</div>
            <div v-if="resolving.context.kp_name" class="ctx-line"><b>知识点：</b>{{ resolving.context.kp_name }}</div>
            <div class="ctx-line">
              <b>AI 得分：</b>{{ resolving.context.ai_score ?? '—' }} / {{ maxScore(resolving.context) }}
              <el-tag size="small" :type="resolving.context.is_correct ? 'success' : 'danger'" style="margin-left: 6px">
                {{ resolving.context.is_correct ? '判为正确' : '判为错误' }}
              </el-tag>
            </div>
            <div class="ctx-line"><b>AI 评语：</b>{{ resolving.context.ai_feedback || '—' }}</div>
            <div v-if="resolving.context.analysis" class="ctx-line ctx-analysis"><b>题目解析：</b>{{ resolving.context.analysis }}</div>
          </div>

          <el-form label-width="120px" style="margin-top: 12px">
            <el-form-item label="修正得分">
              <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
                <el-input-number
                  v-model="resolveForm.resolved_score"
                  :min="0"
                  :max="maxScore(resolving.context)"
                  :step="5"
                />
                <span style="font-size: 12px; color: #888">满分 {{ maxScore(resolving.context) }} 分</span>
              </div>
            </el-form-item>
            <el-form-item label="反馈是否正确">
              <el-select v-model="resolveForm.student_feedback_correct" placeholder="可选" clearable style="width: 100%">
                <el-option :value="true" label="反馈正确（+信誉分）" />
                <el-option :value="false" label="反馈不实（扣信誉分）" />
              </el-select>
            </el-form-item>
            <el-form-item label="回复学生">
              <el-input v-model="resolveForm.teacher_response" type="textarea" :rows="3" placeholder="处理说明将展示给学生" />
            </el-form-item>
          </el-form>
        </template>
      </div>
      <template #footer>
        <el-button @click="resolveVisible = false">取消</el-button>
        <el-button type="primary" @click="submitResolve">确认处理</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="介入处理详情" width="640px">
      <div v-loading="detailLoading">
        <template v-if="resolving">
          <el-descriptions :column="1" border size="small" style="margin-bottom: 12px">
            <el-descriptions-item label="学生">{{ resolving.student_name }}（{{ resolving.student_username }}）</el-descriptions-item>
            <el-descriptions-item label="章节">{{ resolving.chapter_title }}</el-descriptions-item>
            <el-descriptions-item label="题号">第 {{ resolving.question_idx }} 题</el-descriptions-item>
            <el-descriptions-item label="来源">{{ triggerLabel(resolving.trigger) }}</el-descriptions-item>
            <el-descriptions-item label="学生说明">{{ resolving.student_message || '—' }}</el-descriptions-item>
            <el-descriptions-item label="处理人">{{ resolving.resolved_by_name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="处理时间">{{ fmtTime(resolving.resolved_at) }}</el-descriptions-item>
            <el-descriptions-item label="修正得分">
              {{ resolving.resolved_score != null ? resolving.resolved_score : '未改分' }}
            </el-descriptions-item>
            <el-descriptions-item label="处理说明">{{ resolving.teacher_response || '—' }}</el-descriptions-item>
          </el-descriptions>
        </template>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button type="primary" @click="viewReport(resolving!.exam_id)">查看报告</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ctx-box {
  background: #f8f8f8;
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  margin-bottom: 12px;
}
.ctx-line { margin: 6px 0; line-height: 1.6; }
.ctx-options { margin: 8px 0; }
.ctx-opt {
  padding: 4px 8px;
  margin: 3px 0;
  border-radius: 4px;
  font-size: 13px;
}
.opt-correct { background: #f0f9eb; color: #67c23a; }
.opt-user-wrong { background: #fef0f0; color: #f56c6c; }
.opt-user:not(.opt-user-wrong):not(.opt-correct) { background: #ecf5ff; }
.ctx-analysis { color: #e6a23c; }
</style>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import http from '@/api'

interface Overview {
  student_feedback_total: number
  student_agree: number
  student_disagree: number
  teacher_review_total: number
  teacher_agree: number
  teacher_disagree: number
  confirmed_right: number
  confirmed_wrong: number
  pending_confirm: number
  feedback_accuracy_pct: number | null
  interventions_pending: number
  interventions_resolved: number
  followup_total: number
  credit_rank: { user_id: number; username: string; display_name: string; feedback_credit: number }[]
}

interface Record {
  id: number
  user_id: number
  username: string
  display_name: string
  role: string
  exam_id: number | null
  question_idx: number | null
  verdict: string
  comment: string
  reward_delta: number
  teacher_confirmed: boolean | null
  created_at: string | null
}

const overview = ref<Overview | null>(null)
const records = ref<Record[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)

async function loadOverview() {
  const { data } = await http.get<Overview>('/admin/ai-feedback/overview')
  overview.value = data
}

async function loadRecords() {
  loading.value = true
  try {
    const { data } = await http.get('/admin/ai-feedback/records', {
      params: { page: page.value, size: size.value },
    })
    records.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

function roleLabel(r: string) {
  return { student: '学生', teacher: '教师', admin: '管理员' }[r] || r
}

function verdictLabel(v: string) {
  return v === 'agree' ? '认可判卷' : '质疑判卷'
}

function confirmedLabel(v: boolean | null) {
  if (v === true) return '反馈正确'
  if (v === false) return '反馈不实'
  return '待确认'
}

onMounted(async () => {
  await Promise.all([loadOverview(), loadRecords()])
})
</script>

<template>
  <div>
    <h3 style="margin: 0 0 16px">AI 判卷反馈与训练监控</h3>
    <p style="color: #888; font-size: 13px; margin-bottom: 16px">
      汇总学生对 AI 判卷的反馈、教师复核与信誉分奖惩，用于评估判卷模型与反馈机制效果（仅管理员可见）。
    </p>

    <el-row v-if="overview" :gutter="16" style="margin-bottom: 16px">
      <el-col :span="6">
        <el-statistic title="学生反馈总数" :value="overview.student_feedback_total" />
      </el-col>
      <el-col :span="6">
        <el-statistic title="认可 / 质疑" :value="`${overview.student_agree} / ${overview.student_disagree}`" />
      </el-col>
      <el-col :span="6">
        <el-statistic
          title="反馈准确率"
          :value="overview.feedback_accuracy_pct != null ? `${overview.feedback_accuracy_pct}%` : '—'"
        />
      </el-col>
      <el-col :span="6">
        <el-statistic title="追问总数" :value="overview.followup_total" />
      </el-col>
    </el-row>

    <el-row v-if="overview" :gutter="16" style="margin-bottom: 16px">
      <el-col :span="6">
        <el-statistic title="教师复核" :value="`${overview.teacher_agree} 认可 / ${overview.teacher_disagree} 质疑`" />
      </el-col>
      <el-col :span="6">
        <el-statistic title="已确认反馈正确" :value="overview.confirmed_right" />
      </el-col>
      <el-col :span="6">
        <el-statistic title="已确认反馈不实" :value="overview.confirmed_wrong" />
      </el-col>
      <el-col :span="6">
        <el-statistic title="待处理介入" :value="overview.interventions_pending" />
      </el-col>
    </el-row>

    <el-card v-if="overview?.credit_rank?.length" shadow="never" style="margin-bottom: 16px">
      <template #header>学生反馈信誉分排行</template>
      <el-table :data="overview.credit_rank" size="small" stripe>
        <el-table-column prop="display_name" label="姓名" />
        <el-table-column prop="username" label="账号" />
        <el-table-column prop="feedback_credit" label="信誉分" width="100" />
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>反馈明细</template>
      <el-table :data="records" v-loading="loading" stripe size="small">
        <el-table-column label="用户" min-width="120">
          <template #default="{ row }">{{ row.display_name }}（{{ row.username }}）</template>
        </el-table-column>
        <el-table-column label="角色" width="80">
          <template #default="{ row }">{{ roleLabel(row.role) }}</template>
        </el-table-column>
        <el-table-column label="考核/题号" width="100">
          <template #default="{ row }">
            {{ row.exam_id ? `#${row.exam_id} 第${row.question_idx}题` : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="反馈" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.verdict === 'agree' ? 'success' : 'danger'">
              {{ verdictLabel(row.verdict) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="comment" label="说明" min-width="140" show-overflow-tooltip />
        <el-table-column label="奖惩" width="70">
          <template #default="{ row }">
            <span v-if="row.role === 'student'">{{ row.reward_delta > 0 ? '+' : '' }}{{ row.reward_delta }}</span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="教师确认" width="100">
          <template #default="{ row }">
            <span v-if="row.role === 'student'">{{ confirmedLabel(row.teacher_confirmed) }}</span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="160" />
      </el-table>
      <div style="margin-top: 12px; text-align: right">
        <el-pagination
          v-model:current-page="page"
          :page-size="size"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadRecords"
        />
      </div>
    </el-card>
  </div>
</template>

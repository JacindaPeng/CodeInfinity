<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'

interface Chapter { id: number; title: string; order_idx: number; description: string }
interface Progress { chapter_id: number; status: string; last_exam_id: number | null }

const router = useRouter()
const chapters = ref<Chapter[]>([])
const progress = ref<Record<number, Progress>>({})
const loading = ref(false)
const history = ref<{ id: number; chapter_id: number; chapter_title: string; status: string }[]>([])

async function load() {
  loading.value = true
  try {
    const [ch, pr, hist] = await Promise.all([
      http.get<Chapter[]>('/chapters'),
      http.get<Progress[]>('/chapters/progress/all'),
      http.get('/exams/history/mine'),
    ])
    chapters.value = ch.data
    progress.value = Object.fromEntries(pr.data.map((p) => [p.chapter_id, p]))
    history.value = hist.data
  } finally {
    loading.value = false
  }
}

function statusOf(ch: Chapter): string {
  return progress.value[ch.id]?.status || '未完成'
}

function statusType(s: string) {
  return s === '已完成' ? 'success' : s === '待学习' ? 'warning' : 'info'
}

async function startExam(ch: Chapter) {
  try {
    await ElMessageBox.confirm(`开始「${ch.title}」考核？试卷将根据教师配置动态生成。`, '提示', { type: 'warning' })
    const { data } = await http.post('/exams/start', { chapter_id: ch.id }, { timeout: 120000 })
    ElMessage.success('试卷已生成')
    // 暂存题目到 sessionStorage 供答题页使用
    sessionStorage.setItem(`exam-${data.exam_id}`, JSON.stringify(data.questions))
    router.push(`/exams/${data.exam_id}`)
  } catch (e: any) {
    if (e?.response?.data?.detail) ElMessage.error(e.response.data.detail)
  }
}

function viewReport(examId: number) {
  router.push(`/exams/${examId}/report`)
}

onMounted(load)
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>章节学习路线</template>

    <el-timeline>
      <el-timeline-item
        v-for="ch in chapters"
        :key="ch.id"
        :type="statusType(statusOf(ch)) as any"
        :timestamp="`第 ${ch.order_idx} 章`"
        placement="top"
      >
        <el-card shadow="hover" style="margin-bottom: 8px">
          <div style="display: flex; justify-content: space-between; align-items: center">
            <div>
              <h3 style="margin: 0 0 4px">{{ ch.title }}</h3>
              <p style="color: #666; margin: 0">{{ ch.description }}</p>
            </div>
            <div style="display: flex; flex-direction: column; gap: 8px; align-items: flex-end">
              <el-tag :type="statusType(statusOf(ch)) as any">
                {{ statusType(statusOf(ch)) === 'success' ? '√ 已完成' :
                   statusType(statusOf(ch)) === 'info' ? '○ 未完成' : '○ 待学习' }}
              </el-tag>
              <div>
                <el-button type="primary" size="small" @click="startExam(ch)">开始考核</el-button>
                <el-button v-if="progress[ch.id]?.last_exam_id" size="small"
                  @click="viewReport(progress[ch.id].last_exam_id!)">查看报告</el-button>
              </div>
            </div>
          </div>
        </el-card>
      </el-timeline-item>
    </el-timeline>

    <el-divider>历史考核</el-divider>
    <el-table :data="history" size="small" border>
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="章节" prop="chapter_title" />
      <el-table-column label="状态" prop="status" width="120" />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button v-if="row.status === 'submitted'" text type="primary" @click="viewReport(row.id)">报告</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

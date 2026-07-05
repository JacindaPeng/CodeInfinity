<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'

interface Question {
  idx: number; source: string; type: string
  stem: string; options: string[]
  user_answer: string
}

const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)
const questions = ref<Question[]>([])
const current = ref(0)
const answers = ref<Record<number, string>>({})
const submitting = ref(false)

const cur = computed(() => questions.value[current.value])

async function load() {
  // 优先用 sessionStorage（开始考核时暂存）
  const cached = sessionStorage.getItem(`exam-${examId}`)
  if (cached) {
    questions.value = JSON.parse(cached)
    return
  }
  const { data } = await http.get(`/exams/${examId}`)
  questions.value = data.questions
}

async function saveCurrent() {
  if (!cur.value) return
  const ans = answers.value[cur.value.idx] || ''
  await http.post(`/exams/${examId}/answer`, { idx: cur.value.idx, answer: ans })
}

function next() {
  saveCurrent()
  if (current.value < questions.value.length - 1) current.value++
}
function prev() {
  saveCurrent()
  if (current.value > 0) current.value--
}

async function submit() {
  try {
    await ElMessageBox.confirm('确定提交考核？提交后将自动评分并生成评价报告。', '提示', { type: 'warning' })
  } catch { return }
  submitting.value = true
  try {
    // 先保存当前题
    if (cur.value) {
      await http.post(`/exams/${examId}/answer`, { idx: cur.value.idx, answer: answers.value[cur.value.idx] || '' })
    }
    await http.post(`/exams/${examId}/submit`, {}, { timeout: 180000 })
    ElMessage.success('已提交，评价报告已生成')
    sessionStorage.removeItem(`exam-${examId}`)
    router.push(`/exams/${examId}/report`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

const progressPct = computed(() =>
  questions.value.length ? Math.round(((current.value + 1) / questions.value.length) * 100) : 0
)

const answeredCount = computed(() =>
  questions.value.filter(q => (answers.value[q.idx] || '').trim()).length
)

onMounted(load)
</script>

<template>
  <el-card shadow="never" v-if="cur">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>第 {{ current + 1 }} / {{ questions.length }} 题（{{ cur.type }} · {{ cur.source === 'bank' ? '题库' : 'AI生成' }}）</span>
        <span>已答 {{ answeredCount }} / {{ questions.length }}</span>
      </div>
    </template>

    <el-progress :percentage="progressPct" style="margin-bottom: 16px" />

    <div class="q-stem">{{ cur.idx }}. {{ cur.stem }}</div>

    <div v-if="cur.type === '选择题'" style="margin: 16px 0">
      <el-radio-group v-model="answers[cur.idx]">
        <el-radio v-for="opt in cur.options" :key="opt" :value="opt" size="large" style="margin: 8px 0; display: block">
          {{ opt }}
        </el-radio>
      </el-radio-group>
    </div>

    <div v-else-if="cur.type === '判断题'" style="margin: 16px 0">
      <el-radio-group v-model="answers[cur.idx]">
        <el-radio v-for="opt in cur.options" :key="opt" :value="opt" size="large" style="margin-right: 24px">
          {{ opt }}
        </el-radio>
      </el-radio-group>
    </div>

    <div v-else style="margin: 16px 0">
      <el-input
        v-model="answers[cur.idx]"
        type="textarea"
        :rows="6"
        placeholder="请输入你的回答"
      />
    </div>

    <div style="display: flex; justify-content: space-between; margin-top: 24px">
      <el-button @click="prev" :disabled="current === 0">上一题</el-button>
      <div>
        <el-button v-if="current < questions.length - 1" type="primary" @click="next">下一题</el-button>
        <el-button type="success" :loading="submitting" @click="submit">提交考核</el-button>
      </div>
    </div>
  </el-card>
  <el-empty v-else description="加载中..." />
</template>

<style scoped>
.q-stem { font-size: 16px; line-height: 1.8; }
</style>

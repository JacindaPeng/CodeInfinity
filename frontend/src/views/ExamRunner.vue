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
const examStatus = ref<string>('')

const cur = computed(() => questions.value[current.value])

async function load() {
  // 始终从 API 加载（获取最新已保存的答案）
  // sessionStorage 缓存仅在创建考核后首次进入时用于避免重复请求，
  // 但恢复进行中的考核时必须从 API 获取已保存的答案
  const cached = sessionStorage.getItem(`exam-${examId}`)
  if (cached) {
    // 有缓存：检查是否有已保存的答案
    const obj = JSON.parse(cached)
    const cachedQs = obj.questions || obj
    const hasSavedAnswers = cachedQs.some((q: any) => q.user_answer && q.user_answer.trim())
    if (hasSavedAnswers) {
      // 缓存中有答案，使用缓存
      questions.value = cachedQs
      questions.value.forEach(q => {
        if (q.user_answer) answers.value[q.idx] = q.user_answer
      })
      return
    }
    // 缓存中无答案，可能是刚创建的，改为从 API 加载以获取最新状态
    sessionStorage.removeItem(`exam-${examId}`)
  }

  const { data } = await http.get(`/exams/${examId}`)
  questions.value = data.questions
  // 回填已有答案（刷新/恢复）
  questions.value.forEach(q => {
    if (q.user_answer) answers.value[q.idx] = q.user_answer
  })
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

    <el-alert
      v-if="answeredCount > 0"
      type="info"
      :closable="false"
      style="margin-bottom: 12px"
      :title="`已恢复之前的答题进度（${answeredCount}/${questions.length}题已答）`"
    />

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

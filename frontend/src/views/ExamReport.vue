<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/api'
import * as echarts from 'echarts'
import VChart from 'vue-echarts'

interface ReportData {
  exam_id: number; chapter_id: number
  dimensions: Record<string, number>
  summary: string
  suggestions: string
  created_at: string | null
  questions: any[]
}

const route = useRoute()
const router = useRouter()
const report = ref<ReportData | null>(null)

const radarOption = computed(() => {
  const dims = report.value?.dimensions || {}
  const indicators = Object.keys(dims).map(name => ({ name, max: 100 }))
  const values = Object.values(dims)
  return {
    tooltip: {},
    radar: { indicator: indicators.length ? indicators : [{ name: '暂无', max: 100 }] },
    series: [{
      type: 'radar',
      data: [{ value: values, areaStyle: { opacity: 0.3 } }],
    }],
  }
})

const totalScore = computed(() => {
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
    const { data } = await http.get(`/exams/${route.params.id}/report`)
    report.value = data
    // 创新扩展：自适应学习推荐 —— 按薄弱维度自动检索复习资源
    await loadAdaptiveRecommend()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载失败')
  }
}

const adaptiveRecs = ref<any[]>([])
async function loadAdaptiveRecommend() {
  if (!report.value) return
  const dims = report.value.dimensions || {}
  // 找出最低分维度作为薄弱点，结合该章节检索
  const sorted = Object.entries(dims).sort((a, b) => (a[1] as number) - (b[1] as number))
  const weakest = sorted.slice(0, 2).map(([k]) => k).join(' ')
  try {
    const { data } = await http.post('/recommend', {
      question: weakest + ' 复习',
      chapter_id: report.value.chapter_id,
      k: 4,
    })
    adaptiveRecs.value = data
  } catch {
    adaptiveRecs.value = []
  }
}

const typeTag = (t: string) => ({ 选择题: '', 判断题: 'success', 简答题: 'warning' } as any)[t] || (t === 'pdf' ? 'danger' : t === 'ppt' ? 'warning' : t === 'video' ? 'success' : 'info')

function openUrl(url: string) { window.open(url, '_blank') }

onMounted(load)
</script>

<template>
  <div v-if="report">
    <el-page-header @back="router.push('/chapters')" title="返回路线" content="学习评价报告" style="margin-bottom: 16px" />

    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>四维度评价</template>
          <v-chart :option="radarOption" style="height: 360px" autoresize />
          <el-descriptions :column="2" border size="small" style="margin-top: 12px">
            <el-descriptions-item label="平均分">{{ totalScore }}</el-descriptions-item>
            <el-descriptions-item label="正确率">{{ correctRate }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card shadow="never">
          <template #header>总体评价</template>
          <p style="line-height: 1.8">{{ report.summary }}</p>
          <el-divider />
          <h4>建议复习</h4>
          <p style="line-height: 1.8; white-space: pre-wrap">{{ report.suggestions }}</p>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header>题目回顾</template>
      <div v-for="q in report.questions" :key="q.idx" class="q-review">
        <div class="q-head">
          <el-tag :type="typeTag(q.type)" size="small">{{ q.type }}</el-tag>
          <span class="q-idx">第 {{ q.idx }} 题</span>
          <el-tag :type="q.is_correct ? 'success' : 'danger'" size="small">
            {{ q.is_correct ? '正确' : '错误' }} · {{ q.ai_score }}分
          </el-tag>
        </div>
        <div class="q-stem">{{ q.stem }}</div>
        <div class="q-line"><b>你的回答：</b>{{ q.user_answer || '（未作答）' }}</div>
        <div class="q-line"><b>正确答案：</b>{{ q.correct_answer }}</div>
        <div class="q-line q-fb"><b>评语：</b>{{ q.ai_feedback }}</div>
      </div>
    </el-card>

    <!-- 创新扩展：自适应学习推荐 -->
    <el-card shadow="never" style="margin-top: 16px">
      <template #header>
        <span>自适应学习推荐（基于薄弱维度自动检索）</span>
      </template>
      <el-empty v-if="!adaptiveRecs.length" description="暂无可推荐资源" />
      <div v-else>
        <div v-for="r in adaptiveRecs" :key="r.material_id" class="rec-item">
          <el-tag :type="typeTag(r.type)" size="small">{{ r.type }}</el-tag>
          <span class="rec-name">{{ r.title }}</span>
          <span class="rec-chapter">{{ r.chapter_title }}</span>
          <el-button text type="primary" size="small" @click="openUrl(r.file_url)">
            {{ r.type === 'video' ? `观看视频 (${r.video_start_sec || 0}s)` : '查看' }}
          </el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.q-review { padding: 12px 0; border-bottom: 1px solid #f0f0f0; }
.q-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.q-idx { font-weight: 600; }
.q-stem { font-size: 15px; margin: 6px 0; line-height: 1.6; }
.q-line { font-size: 13px; color: #555; margin: 4px 0; }
.q-fb { color: #409eff; }
.rec-item { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px dashed #eee; }
.rec-name { font-weight: 500; }
.rec-chapter { color: #888; font-size: 12px; }
</style>

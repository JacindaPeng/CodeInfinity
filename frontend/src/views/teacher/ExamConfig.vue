<script setup lang="ts">
import { onMounted, ref, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api'

interface Chapter { id: number; title: string }
interface KP { id: number; name: string }

const chapters = ref<Chapter[]>([])
const kps = ref<KP[]>([])
const selectedChapter = ref<number | undefined>(undefined)
const config = reactive<{ 选择题: number; 判断题: number; 简答题: number; knowledge_points: string[] }>({
  选择题: 2, 判断题: 2, 简答题: 2, knowledge_points: [],
})
const allKpNames = ref<string[]>([])
const saving = ref(false)

async function loadChapters() {
  const { data } = await http.get<Chapter[]>('/chapters')
  chapters.value = data
  if (data.length) {
    selectedChapter.value = data[0].id
    await loadChapter()
  }
}

async function loadChapter() {
  if (!selectedChapter.value) return
  const [cfg, kp, full] = await Promise.all([
    http.get(`/exams/config/${selectedChapter.value}`),
    http.get(`/exams/knowledge-points/${selectedChapter.value}`),
    http.get(`/chapters/${selectedChapter.value}`),
  ])
  const c = cfg.data.config || {}
  config.选择题 = c['选择题'] ?? 2
  config.判断题 = c['判断题'] ?? 2
  config.简答题 = c['简答题'] ?? 2
  config.knowledge_points = c['knowledge_points'] || []
  kps.value = kp.data
  allKpNames.value = full.data.knowledge_points.map((k: any) => k.name)
}

async function save() {
  if (!selectedChapter.value) return
  saving.value = true
  try {
    await http.post('/exams/config', {
      chapter_id: selectedChapter.value,
      config: {
        选择题: Number(config.选择题), 判断题: Number(config.判断题), 简答题: Number(config.简答题),
        knowledge_points: config.knowledge_points,
      },
    })
    ElMessage.success('已保存考核配置')
  } finally {
    saving.value = false
  }
}

watch(selectedChapter, loadChapter)
onMounted(loadChapters)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>章节考核配置</span>
        <el-select v-model="selectedChapter" style="width: 240px">
          <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
        </el-select>
      </div>
    </template>

    <el-form label-width="120px" v-if="selectedChapter">
      <el-form-item label="选择题数量">
        <el-input-number v-model="config.选择题" :min="0" :max="20" />
      </el-form-item>
      <el-form-item label="判断题数量">
        <el-input-number v-model="config.判断题" :min="0" :max="20" />
      </el-form-item>
      <el-form-item label="简答题数量">
        <el-input-number v-model="config.简答题" :min="0" :max="10" />
      </el-form-item>
      <el-form-item label="考核知识点">
        <el-select v-model="config.knowledge_points" multiple placeholder="选择考核知识点" style="width: 100%">
          <el-option v-for="n in allKpNames" :key="n" :label="n" :value="n" />
        </el-select>
        <div style="color: #999; font-size: 12px">总题数：{{ config.选择题 + config.判断题 + config.简答题 }}</div>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
      </el-form-item>
    </el-form>

    <el-alert
      title="说明：题库不足部分将由 LLM 基于知识点动态生成。"
      type="info"
      :closable="false"
      style="margin-top: 12px"
    />
  </el-card>
</template>

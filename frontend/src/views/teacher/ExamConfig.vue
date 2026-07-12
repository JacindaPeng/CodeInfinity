<script setup lang="ts">
import { onMounted, ref, reactive, watch, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'

interface Chapter { id: number; title: string }
interface ClassItem { id: number; name: string }
interface KP { id: number; name: string }

const chapters = ref<Chapter[]>([])
const classes = ref<ClassItem[]>([])
const kps = ref<KP[]>([])
const selectedChapter = ref<number | undefined>(undefined)
const selectedClasses = ref<number[]>([])
const config = reactive<{ 选择题: number; 判断题: number; 简答题: number; knowledge_points: string[] }>({
  选择题: 2, 判断题: 2, 简答题: 1, knowledge_points: [],
})
const maxAttempts = ref(0)
const allKpNames = ref<string[]>([])
const saving = ref(false)
const addingKp = ref(false)
const newKpName = ref('')

const primaryClassId = computed(() => selectedClasses.value[0])

const classLabel = computed(() => {
  if (!selectedClasses.value.length) return ''
  if (selectedClasses.value.length === 1) {
    return classes.value.find(c => c.id === selectedClasses.value[0])?.name || ''
  }
  return `已选 ${selectedClasses.value.length} 个班级`
})

async function loadChapters() {
  const { data } = await http.get<Chapter[]>('/chapters')
  chapters.value = data
  if (data.length && !selectedChapter.value) selectedChapter.value = data[0].id
}

async function loadClasses() {
  const { data } = await http.get<ClassItem[]>('/classes/mine')
  classes.value = data
  if (data.length && !selectedClasses.value.length) {
    selectedClasses.value = data.map(c => c.id)
  }
}

async function loadChapter() {
  if (!selectedChapter.value || !primaryClassId.value) {
    kps.value = []
    allKpNames.value = []
    return
  }
  const [cfg, full] = await Promise.all([
    http.get(`/exams/config/${selectedChapter.value}`, { params: { class_id: primaryClassId.value } }),
    http.get(`/chapters/${selectedChapter.value}`, { params: { class_id: primaryClassId.value } }),
  ])
  const c = cfg.data.config || {}
  config.选择题 = c['选择题'] ?? 2
  config.判断题 = c['判断题'] ?? 2
  config.简答题 = c['简答题'] ?? 1
  config.knowledge_points = c['knowledge_points'] || []
  maxAttempts.value = cfg.data.max_attempts ?? 0
  kps.value = full.data.knowledge_points.map((k: any) => ({ id: k.id, name: k.name }))
  allKpNames.value = kps.value.map(k => k.name)
}

async function save() {
  if (!selectedChapter.value || !selectedClasses.value.length) {
    ElMessage.warning('请至少选择一个班级')
    return
  }
  saving.value = true
  try {
    const { data } = await http.post('/exams/config', {
      chapter_id: selectedChapter.value,
      class_ids: selectedClasses.value,
      config: {
        选择题: Number(config.选择题),
        判断题: Number(config.判断题),
        简答题: Number(config.简答题),
        knowledge_points: config.knowledge_points,
      },
      max_attempts: Number(maxAttempts.value),
    })
    const hint = data.class_count > 1 ? `，已同步到 ${data.class_count} 个班级` : ''
    ElMessage.success(`已保存考核配置${hint}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function addKp() {
  const name = newKpName.value.trim()
  if (!name) {
    ElMessage.warning('请输入知识点名称')
    return
  }
  if (!selectedChapter.value || !selectedClasses.value.length) {
    ElMessage.warning('请先选择章节和班级')
    return
  }
  addingKp.value = true
  try {
    const { data } = await http.post('/exams/knowledge-points', {
      chapter_id: selectedChapter.value,
      class_ids: selectedClasses.value,
      name,
    })
    newKpName.value = ''
    await loadChapter()
    const hint = selectedClasses.value.length > 1
      ? `（${data.created || 0} 个班级新增，${data.skipped || 0} 个已存在）`
      : ''
    ElMessage.success(`知识点已添加${hint}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '添加失败')
  } finally {
    addingKp.value = false
  }
}

async function deleteKp(kp: KP) {
  await ElMessageBox.confirm(`删除知识点「${kp.name}」？`, '提示', { type: 'warning' })
  try {
    await http.delete(`/exams/knowledge-points/${kp.id}`)
    await loadChapter()
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

watch([selectedChapter, selectedClasses], loadChapter, { deep: true })
onMounted(async () => {
  await Promise.all([loadChapters(), loadClasses()])
  await loadChapter()
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap">
        <span>章节考核配置</span>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <el-select
            v-model="selectedClasses"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择班级（可多选）"
            style="width: 280px"
          >
            <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-select v-model="selectedChapter" style="width: 280px">
            <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
        </div>
      </div>
    </template>

    <el-alert
      v-if="!selectedClasses.length"
      type="warning"
      :closable="false"
      title="请先创建或选择班级后再配置考核"
      style="margin-bottom: 12px"
    />

    <el-alert
      v-else-if="selectedClasses.length > 1"
      type="info"
      :closable="false"
      :title="`多班级同步模式：${classLabel}`"
      description="保存配置与添加知识点将同步到所有已选班级；下方知识点列表展示第一个所选班级的内容。"
      style="margin-bottom: 12px"
    />

    <el-form label-width="120px" v-if="selectedChapter && selectedClasses.length">
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
      <el-form-item label="考核次数上限">
        <el-input-number v-model="maxAttempts" :min="0" :max="100" />
        <span style="margin-left: 8px; color: #999; font-size: 12px">
          {{ maxAttempts === 0 ? '无限次' : `限 ${maxAttempts} 次` }}
        </span>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
      </el-form-item>
    </el-form>

    <el-divider>知识点维护{{ primaryClassId ? `（${classLabel}）` : '' }}</el-divider>
    <div v-if="selectedChapter && selectedClasses.length">
      <div style="display: flex; gap: 8px; margin-bottom: 12px; align-items: center">
        <el-input
          v-model="newKpName"
          placeholder="新知识点名称"
          style="width: 240px"
          @keyup.enter="addKp"
        />
        <el-button type="primary" :loading="addingKp" @click="addKp">添加</el-button>
      </div>
      <div>
        <el-tag
          v-for="kp in kps"
          :key="kp.id"
          closable
          @close="deleteKp(kp)"
          style="margin: 0 8px 8px 0"
        >
          {{ kp.name }}
        </el-tag>
        <span v-if="!kps.length" style="color: #999">暂无知识点，请在上方输入名称后点击添加</span>
      </div>
    </div>

    <el-alert
      title="说明：可多选班级一次性保存相同考核配置；题库不足部分将由 LLM 动态生成。"
      type="info"
      :closable="false"
      style="margin-top: 12px"
    />
  </el-card>
</template>

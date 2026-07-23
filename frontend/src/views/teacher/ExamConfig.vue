<script setup lang="ts">
import { onMounted, ref, reactive, watch, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { useCourseAgentStore } from '@/stores/courseAgent'
import { useAgentCourseScope } from '@/composables/useAgentCourseScope'
import { useAgentBoundClasses } from '@/composables/useAgentBoundClasses'

interface Chapter { id: number; title: string }
interface ClassItem { id: number; name: string }
interface CourseItem { id: number; name: string }
interface KP { id: number; name: string }

const agentStore = useCourseAgentStore()
const { lockedCourse, applyLockedCourse, chapterListParams } = useAgentCourseScope()
const { loadScopedClasses, syncMultiClassIds, isSharedPreview } = useAgentBoundClasses()
const courses = ref<CourseItem[]>([])
const selectedCourseId = ref<number | undefined>(undefined)
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
const suggestVisible = ref(false)
const suggestLoading = ref(false)
const suggestSource = ref<'question_bank' | 'chapter_materials' | 'textbook' | 'chapter_desc' | 'empty'>('empty')
const suggestChunkCount = ref(0)
const suggestQuestionCount = ref(0)
const suggestItems = ref<string[]>([])
const suggestExisting = ref<string[]>([])
const selectedSuggestions = ref<string[]>([])
const addingSelected = ref(false)

const primaryClassId = computed(() => selectedClasses.value[0])

const classLabel = computed(() => {
  if (!selectedClasses.value.length) return ''
  if (selectedClasses.value.length === 1) {
    return classes.value.find(c => c.id === selectedClasses.value[0])?.name || ''
  }
  return `已选 ${selectedClasses.value.length} 个班级`
})

async function loadCourses() {
  if (applyLockedCourse(selectedCourseId, courses)) return
  const { data } = await http.get<CourseItem[]>('/courses')
  courses.value = data
  if (!selectedCourseId.value) {
    selectedCourseId.value = data[0]?.id
  }
}

async function loadChapters() {
  const params = chapterListParams()
  if (!params.course_id && selectedCourseId.value) params.course_id = selectedCourseId.value
  const { data } = await http.get<Chapter[]>('/chapters', { params })
  chapters.value = data
  if (data.length && !selectedChapter.value) selectedChapter.value = data[0].id
}

function onCourseChange() {
  selectedChapter.value = undefined
  loadChapters().then(() => loadChapter())
}

async function loadClasses() {
  const data = await loadScopedClasses()
  classes.value = data
  selectedClasses.value = syncMultiClassIds(data, selectedClasses.value)
}

async function loadChapter() {
  if (!selectedChapter.value || !primaryClassId.value) {
    kps.value = []
    allKpNames.value = []
    return
  }
  const cfgParams: Record<string, number> = { class_id: primaryClassId.value }
  const chParams: Record<string, number> = { class_id: primaryClassId.value }
  if (agentStore.current?.id) {
    cfgParams.agent_id = agentStore.current.id
    chParams.agent_id = agentStore.current.id
  }
  const [cfg, full] = await Promise.all([
    http.get(`/exams/config/${selectedChapter.value}`, { params: cfgParams }),
    http.get(`/chapters/${selectedChapter.value}`, { params: chParams }),
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

async function openSuggestDialog() {
  if (!selectedChapter.value || !primaryClassId.value) {
    ElMessage.warning('请先选择章节和班级')
    return
  }
  suggestVisible.value = true
  suggestLoading.value = true
  selectedSuggestions.value = []
  suggestItems.value = []
  suggestExisting.value = []
  try {
    const params: Record<string, number> = { class_id: primaryClassId.value }
    if (agentStore.current?.id) params.agent_id = agentStore.current.id
    const { data } = await http.get(`/exams/knowledge-points/${selectedChapter.value}/suggest`, {
      params,
      timeout: 120000,
    })
    suggestSource.value = data.source || 'empty'
    suggestChunkCount.value = data.chunk_count || 0
    suggestQuestionCount.value = data.question_count || 0
    suggestExisting.value = data.existing || []
    suggestItems.value = data.suggestions || []
    selectedSuggestions.value = [...suggestItems.value]
    if (suggestSource.value === 'empty') {
      ElMessage.warning('暂无可用来源，请先在题库或资料管理中补充本章内容')
    } else if (!suggestItems.value.length) {
      ElMessage.info('未识别到新的知识点，可能已全部添加或资料内容较少')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '生成失败')
    suggestVisible.value = false
  } finally {
    suggestLoading.value = false
  }
}

async function addSelectedSuggestions() {
  const names = selectedSuggestions.value.map(n => n.trim()).filter(Boolean)
  if (!names.length || !selectedChapter.value || !selectedClasses.value.length) return
  addingSelected.value = true
  let created = 0
  let skipped = 0
  try {
    for (const name of names) {
      const { data } = await http.post('/exams/knowledge-points', {
        chapter_id: selectedChapter.value,
        class_ids: selectedClasses.value,
        name,
      })
      created += data.created || 0
      skipped += data.skipped || 0
    }
    suggestVisible.value = false
    await loadChapter()
    ElMessage.success(`已添加 ${names.length} 个知识点${selectedClasses.value.length > 1 ? `（新增 ${created}，跳过 ${skipped}）` : ''}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '添加失败')
  } finally {
    addingSelected.value = false
  }
}

function isExistingSuggestion(name: string) {
  return suggestExisting.value.some(e => e.toLowerCase() === name.toLowerCase())
}

watch([selectedChapter, selectedClasses], loadChapter, { deep: true })
onMounted(async () => {
  await agentStore.restoreAgent()
  await loadCourses()
  await loadClasses()
  await loadChapters()
  await loadChapter()
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap">
        <span>{{ isSharedPreview ? '共享考核配置（只读体验）' : '章节考核配置' }}</span>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
          <el-select v-if="!lockedCourse" v-model="selectedCourseId" placeholder="选择课程" style="width: 200px" @change="onCourseChange">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
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
      <div v-if="!isSharedPreview" style="display: flex; gap: 8px; margin-bottom: 12px; align-items: center; flex-wrap: wrap">
        <el-input
          v-model="newKpName"
          placeholder="新知识点名称"
          style="width: 240px"
          @keyup.enter="addKp"
        />
        <el-button type="primary" :loading="addingKp" @click="addKp">手动添加</el-button>
        <el-button :loading="suggestLoading && !suggestVisible" @click="openSuggestDialog">从资料生成</el-button>
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
        <span v-if="!kps.length" style="color: #999">暂无知识点，可手动添加或点击「从资料生成」</span>
      </div>
    </div>

    <el-dialog v-model="suggestVisible" title="从资料生成知识点" width="560px" destroy-on-close>
      <div v-loading="suggestLoading">
        <el-alert
          v-if="suggestSource === 'empty'"
          type="warning"
          :closable="false"
          title="暂无可用来源"
          description="生成优先级：① 题库中该章节题目 → ② 资料管理中该章单独上传的资料 → ③ 整本教材该章片段。请至少满足一项。"
          style="margin-bottom: 12px"
        />
        <el-alert
          v-else-if="suggestSource === 'question_bank'"
          type="success"
          :closable="false"
          :title="`已根据题库中 ${suggestQuestionCount} 道相关题目生成建议`"
          description="优先使用题库已有题目及关联知识点；若题目未标注知识点，将从题干中提炼。"
          style="margin-bottom: 12px"
        />
        <el-alert
          v-else-if="suggestSource === 'chapter_materials'"
          type="info"
          :closable="false"
          :title="`已根据该章单独上传的资料（${suggestChunkCount} 段）生成建议`"
          description="未在题库中找到题目，已使用资料管理中本章上传的课件/PPT 等内容。"
          style="margin-bottom: 12px"
        />
        <el-alert
          v-else-if="suggestSource === 'textbook'"
          type="info"
          :closable="false"
          :title="`已根据整本教材该章片段（${suggestChunkCount} 段）生成建议`"
          description="题库与本章课件均无内容，已回退至整本教材中该章节对应部分。"
          style="margin-bottom: 12px"
        />
        <el-alert
          v-else-if="suggestSource === 'chapter_desc'"
          type="info"
          :closable="false"
          title="资料片段不足，已根据章节描述生成建议"
          style="margin-bottom: 12px"
        />
        <p v-else-if="suggestChunkCount || suggestQuestionCount" style="color: #999; font-size: 12px; margin: 0 0 12px">
          勾选需要添加的知识点：
        </p>
        <el-checkbox-group v-model="selectedSuggestions" style="display: flex; flex-direction: column; gap: 8px">
          <el-checkbox
            v-for="name in suggestItems"
            :key="name"
            :label="name"
            :disabled="isExistingSuggestion(name)"
          >
            {{ name }}
            <span v-if="isExistingSuggestion(name)" style="color: #999; font-size: 12px">（已存在）</span>
          </el-checkbox>
        </el-checkbox-group>
        <p v-if="!suggestLoading && !suggestItems.length" style="color: #999; margin-top: 12px">
          暂无可用建议，请补充资料后重试。
        </p>
      </div>
      <template #footer>
        <el-button @click="suggestVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="addingSelected"
          :disabled="!selectedSuggestions.length"
          @click="addSelectedSuggestions"
        >
          添加选中（{{ selectedSuggestions.length }}）
        </el-button>
      </template>
    </el-dialog>

    <el-alert
      title="说明：可多选班级一次性保存相同考核配置；题库不足部分将由 LLM 动态生成。「从资料生成」优先级：题库题目 → 本章上传资料 → 整本教材。"
      type="info"
      :closable="false"
      style="margin-top: 12px"
    />
  </el-card>
</template>
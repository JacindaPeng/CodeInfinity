<script setup lang="ts">
import { onMounted, ref, reactive, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { useCourseAgentStore } from '@/stores/courseAgent'
import { useAgentCourseScope } from '@/composables/useAgentCourseScope'
import { useAgentBoundClasses } from '@/composables/useAgentBoundClasses'

interface Chapter { id: number; title: string }
interface ClassItem { id: number; name: string }
interface CourseItem { id: number; name: string }
interface Material {
  id: number; chapter_id: number; class_id: number | null; type: string; title: string
  file_name: string; created_at: string | null
}

/** 列表展示行：相同章节/标题/文件的多班资料合并为一行 */
interface MaterialGroup extends Material {
  class_ids: (number | null)[]
  material_ids: number[]
}

const agentStore = useCourseAgentStore()
const { lockedCourse, applyLockedCourse, chapterListParams } = useAgentCourseScope()
const { loadScopedClasses, pickClassId, syncMultiClassIds, inAgentContext, isSharedPreview } = useAgentBoundClasses()
const courses = ref<CourseItem[]>([])
const selectedCourseId = ref<number | undefined>(undefined)
const chapters = ref<Chapter[]>([])
const classes = ref<ClassItem[]>([])
const list = ref<Material[]>([])
const loading = ref(false)
const stats = ref<{ chunks: number }>({ chunks: 0 })

const filterChapter = ref<number | undefined>(undefined)
const filterClass = ref<number | undefined>(undefined)

/** 仅原 C 语言智能体使用课程级预置章节（与后端 uses_preset_chapters 一致）。 */
const usesPresetChapters = computed(() => {
  const agent = agentStore.current
  if (agent) return agent.uses_preset_chapters === true
  return selectedCourseId.value === 1
})

const needsChapterSetup = computed(
  () => !!selectedCourseId.value && !usesPresetChapters.value && chapters.value.length === 0 && !isSharedPreview.value,
)
const canResetCourseStructure = computed(
  () => !!selectedCourseId.value && !usesPresetChapters.value && chapters.value.length > 0 && !isSharedPreview.value,
)
const canSingleChapterUpload = computed(() => chapters.value.length > 0)
const noScopedClasses = computed(
  () => inAgentContext.value && classes.value.length === 0 && !isSharedPreview.value,
)

// 上传弹窗 + Tab
const dialogVisible = ref(false)
const uploadTab = ref('single')
const customChapters = ref<{ title: string; description: string }[]>([])
const form = reactive({
  chapter_id: 0, class_ids: [] as number[], title: '', file: null as File | null,
})
const textbookForm = reactive({
  class_ids: [] as number[],
  file: null as File | null,
  title_prefix: '',
  toc_page_start: undefined as number | undefined,
  toc_page_end: undefined as number | undefined,
})
const coursewareForm = reactive({
  class_ids: [] as number[],
  files: [] as File[],
})
const textbookResult = ref<any>(null)
const coursewareResult = ref<any>(null)
const uploading = ref(false)

const longUploadOpts = {
  headers: { 'Content-Type': 'multipart/form-data' as const },
  timeout: 600000,
  skipGlobalError: true,
}

function uploadErrorMessage(e: any, fallback = '上传失败') {
  const detail = e?.response?.data?.detail
  if (detail) return typeof detail === 'string' ? detail : fallback
  if (e?.code === 'ECONNABORTED' || /timeout/i.test(e?.message || '')) {
    return '教材拆分与索引超时（大文件可能需要数分钟），请稍后刷新资料列表确认是否已成功'
  }
  if (!e?.response) {
    return '连接中断：后端可能仍在处理大文件，请稍候刷新资料列表；若持续失败请确认 backend 已在 8000 端口运行'
  }
  return fallback
}

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
  if (data.length && !form.chapter_id) form.chapter_id = data[0].id
  if (data.length && filterChapter.value && !data.some(c => c.id === filterChapter.value)) {
    filterChapter.value = undefined
  }
}

function onCourseChange() {
  loadChapters()
  loadList()
}

async function loadClasses() {
  const data = await loadScopedClasses()
  classes.value = data
  if (isSharedPreview.value) {
    // 默认不按班筛选，一次拉全共享资料，避免误选源班导致 403
    filterClass.value = undefined
    form.class_ids = []
    textbookForm.class_ids = []
    coursewareForm.class_ids = []
  } else if (data.length) {
    form.class_ids = syncMultiClassIds(data, form.class_ids.length ? form.class_ids : defaultClassIds())
    textbookForm.class_ids = syncMultiClassIds(data, textbookForm.class_ids.length ? textbookForm.class_ids : defaultClassIds())
    coursewareForm.class_ids = syncMultiClassIds(data, coursewareForm.class_ids.length ? coursewareForm.class_ids : defaultClassIds())
    filterClass.value = pickClassId(data, filterClass.value)
  } else {
    form.class_ids = []
    textbookForm.class_ids = []
    coursewareForm.class_ids = []
    filterClass.value = undefined
  }
}

function defaultClassIds(): number[] {
  if (filterClass.value) return [filterClass.value]
  return classes.value.map(c => c.id)
}

const classTitle = (id: number | null) =>
  classes.value.find(c => c.id === id)?.name || (id ? `班级${id}` : (isSharedPreview.value ? '共享模板' : '未分配班级'))

function classTitles(ids: (number | null)[]) {
  const names = ids.map(classTitle)
  return [...new Set(names)].join('、')
}

function groupMaterials(items: Material[]): MaterialGroup[] {
  const map = new Map<string, MaterialGroup>()
  for (const m of items) {
    const key = `${m.chapter_id}\0${m.type}\0${m.title}\0${m.file_name || ''}`
    const hit = map.get(key)
    if (!hit) {
      map.set(key, {
        ...m,
        class_ids: [m.class_id],
        material_ids: [m.id],
      })
      continue
    }
    if (!hit.class_ids.includes(m.class_id)) hit.class_ids.push(m.class_id)
    hit.material_ids.push(m.id)
    if (m.id < hit.id) hit.id = m.id
    if (m.created_at && (!hit.created_at || m.created_at < hit.created_at)) {
      hit.created_at = m.created_at
    }
  }
  return Array.from(map.values())
}

const displayList = computed(() => groupMaterials(list.value))

async function loadList() {
  loading.value = true
  try {
    if (inAgentContext.value && !agentStore.current?.id) {
      list.value = []
      return
    }
    const params: Record<string, number | undefined> = {
      chapter_id: filterChapter.value || undefined,
      class_id: filterClass.value || undefined,
      course_id: selectedCourseId.value || undefined,
    }
    if (agentStore.current?.id) params.agent_id = agentStore.current.id
    const { data } = await http.get<Material[]>('/materials', { params })
    list.value = data
  } catch (e: any) {
    list.value = []
    const detail = e?.response?.data?.detail
    if (detail) ElMessage.error(typeof detail === 'string' ? detail : '加载资料失败')
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  const { data } = await http.get('/materials/stats')
  stats.value = data
}

function initCustomChapters() {
  customChapters.value = [
    { title: '第1章 ', description: '' },
    { title: '第2章 ', description: '' },
    { title: '第3章 ', description: '' },
  ]
}

function addCustomRow() {
  const n = customChapters.value.length + 1
  customChapters.value.push({ title: `第${n}章 `, description: '' })
}

function removeCustomRow(index: number) {
  if (customChapters.value.length <= 1) {
    ElMessage.warning('至少保留一个章节')
    return
  }
  customChapters.value.splice(index, 1)
}

function openCustomChapters() {
  initCustomChapters()
  uploadTab.value = 'custom'
  dialogVisible.value = true
}

function openCoursewareBatch() {
  coursewareForm.files = []
  coursewareResult.value = null
  uploadTab.value = 'courseware'
  dialogVisible.value = true
}

function openTextbookUpload() {
  textbookForm.file = null
  textbookForm.title_prefix = ''
  textbookResult.value = null
  uploadTab.value = 'textbook'
  if (classes.value.length) textbookForm.class_ids = defaultClassIds()
  dialogVisible.value = true
}

watch(uploadTab, (tab) => {
  if (tab === 'custom' && !customChapters.value.length) initCustomChapters()
})

function openUpload() {
  form.title = ''; form.file = null
  textbookForm.file = null; textbookForm.title_prefix = ''
  coursewareForm.files = []
  textbookResult.value = null
  coursewareResult.value = null
  uploadTab.value = needsChapterSetup.value ? 'courseware' : 'single'
  if (chapters.value.length) form.chapter_id = chapters.value[0].id
  if (classes.value.length) {
    form.class_ids = defaultClassIds()
    textbookForm.class_ids = defaultClassIds()
    coursewareForm.class_ids = defaultClassIds()
  }
  dialogVisible.value = true
}

function onFileChange(file: any) {
  form.file = file.raw
  if (!form.title) form.title = file.name.replace(/\.[^.]+$/, '')
}

function onFileRemove() {
  form.file = null
}

function onTextbookFileChange(file: any) {
  textbookForm.file = file.raw
  if (!textbookForm.title_prefix) textbookForm.title_prefix = file.name.replace(/\.[^.]+$/, '')
}

function onTextbookFileRemove() {
  textbookForm.file = null
}

function onCoursewareFilesChange(_file: any, fileList: any[]) {
  coursewareForm.files = fileList.map(f => f.raw).filter(Boolean)
}

async function submitUpload() {
  if (!form.class_ids.length) { ElMessage.warning('请至少选择一个班级'); return }
  if (!form.chapter_id) { ElMessage.warning('请选择章节'); return }
  if (!form.file) { ElMessage.warning('请选择文件'); return }
  if (!form.title) { ElMessage.warning('请填写标题'); return }
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('chapter_id', String(form.chapter_id))
    form.class_ids.forEach(id => fd.append('class_ids', String(id)))
    fd.append('title', form.title)
    fd.append('file', form.file)
    if (agentStore.current?.id) fd.append('agent_id', String(agentStore.current.id))
    const { data } = await http.post('/materials/upload', fd, longUploadOpts)
    const classHint = data.class_count > 1 ? `，已同步到 ${data.class_count} 个班级` : ''
    ElMessage.success(`上传成功，索引 ${data.chunks} 个片段${classHint}${data.warning ? '（' + data.warning + '）' : ''}`)
    if (data.warning) ElMessage.warning(data.warning)
    dialogVisible.value = false
    loadList(); loadStats()
  } catch (e: any) {
    ElMessage.error(uploadErrorMessage(e))
  } finally {
    uploading.value = false
  }
}

async function submitTextbookUpload() {
  if (!selectedCourseId.value) { ElMessage.warning('请选择课程'); return }
  if (!textbookForm.class_ids.length) { ElMessage.warning('请至少选择一个班级'); return }
  if (!textbookForm.file) { ElMessage.warning('请选择 PDF 教材'); return }
  uploading.value = true
  textbookResult.value = null
  try {
    const fd = new FormData()
    fd.append('course_id', String(selectedCourseId.value))
    textbookForm.class_ids.forEach(id => fd.append('class_ids', String(id)))
    fd.append('file', textbookForm.file)
    fd.append('title_prefix', textbookForm.title_prefix)
    if (agentStore.current?.id) fd.append('agent_id', String(agentStore.current.id))
    if (textbookForm.toc_page_start != null && textbookForm.toc_page_start > 0) {
      fd.append('toc_page_start', String(textbookForm.toc_page_start))
    }
    if (textbookForm.toc_page_end != null && textbookForm.toc_page_end > 0) {
      fd.append('toc_page_end', String(textbookForm.toc_page_end))
    } else if (textbookForm.toc_page_start != null && textbookForm.toc_page_start > 0) {
      fd.append('toc_page_end', String(textbookForm.toc_page_start))
    }
    const { data } = await http.post('/materials/upload-textbook', fd, longUploadOpts)
    textbookResult.value = data
    const classHint = data.class_count > 1 ? `，已同步到 ${data.class_count} 个班级` : ''
    const createdHint = data.chapters_created ? '，已从教材分析生成章节' : ''
    ElMessage.success(`整本教材已拆分：${data.chapters_split} 章，共 ${data.total_chunks} 个片段${classHint}${createdHint}`)
    if (data.warning) ElMessage.warning(data.warning)
    await loadChapters()
    if (data.chapters_created && agentStore.current?.course_id === selectedCourseId.value) {
      const { data: agent } = await http.get(`/agents/${agentStore.current.id}`)
      agentStore.setAgent(agent)
    }
    loadList(); loadStats()
  } catch (e: any) {
    ElMessage.error(uploadErrorMessage(e))
  } finally {
    uploading.value = false
  }
}

async function submitCoursewareBatch() {
  if (!selectedCourseId.value) { ElMessage.warning('请选择课程'); return }
  if (!coursewareForm.class_ids.length) { ElMessage.warning('请至少选择一个班级'); return }
  if (!coursewareForm.files.length) { ElMessage.warning('请至少选择一个课件文件'); return }
  uploading.value = true
  coursewareResult.value = null
  try {
    const fd = new FormData()
    fd.append('course_id', String(selectedCourseId.value))
    coursewareForm.class_ids.forEach(id => fd.append('class_ids', String(id)))
    coursewareForm.files.forEach(f => fd.append('files', f))
    if (agentStore.current?.id) fd.append('agent_id', String(agentStore.current.id))
    const { data } = await http.post('/materials/upload-courseware-batch', fd, longUploadOpts)
    coursewareResult.value = data
    const classHint = data.class_count > 1 ? `，已同步到 ${data.class_count} 个班级` : ''
    ElMessage.success(`已识别 ${data.chapters_created} 个章节并索引 ${data.total_chunks} 个片段${classHint}`)
    if (data.warning) ElMessage.warning(data.warning)
    await loadChapters()
    if (agentStore.current?.course_id === selectedCourseId.value) {
      const { data: agent } = await http.get(`/agents/${agentStore.current.id}`)
      agentStore.setAgent(agent)
    }
    loadList(); loadStats()
  } catch (e: any) {
    ElMessage.error(uploadErrorMessage(e))
  } finally {
    uploading.value = false
  }
}

async function submitCustomChapters() {
  if (!selectedCourseId.value) { ElMessage.warning('请选择课程'); return }
  const items = customChapters.value
    .map((c, i) => ({
      title: c.title.trim(),
      description: c.description.trim(),
      order_idx: i + 1,
    }))
    .filter(c => c.title)
  if (!items.length) { ElMessage.warning('请至少填写一个章节标题'); return }
  uploading.value = true
  try {
    const payload: { course_id: number; chapters: typeof items; agent_id?: number } = {
      course_id: selectedCourseId.value,
      chapters: items,
    }
    if (agentStore.current?.id) payload.agent_id = agentStore.current.id
    const { data } = await http.post('/chapters/custom', payload)
    ElMessage.success(`已创建 ${data.count} 个章节，可按章上传资料构建知识库`)
    dialogVisible.value = false
    await loadChapters()
    loadList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  } finally {
    uploading.value = false
  }
}

async function remove(row: MaterialGroup) {
  const ids = row.material_ids?.length ? row.material_ids : [row.id]
  const classHint = ids.length > 1 ? `（将同时删除其在 ${ids.length} 个班级中的副本）` : ''
  await ElMessageBox.confirm(`删除资料「${row.title}」${classHint}？`, '提示', { type: 'warning' })
  for (const id of ids) {
    await http.delete(`/materials/${id}`)
  }
  ElMessage.success(ids.length > 1 ? `已删除 ${ids.length} 条班级副本` : '已删除')
  loadList(); loadStats()
}

async function reindex() {
  const msg = classes.value.length > 1
    ? '将重建您所管班级的资料索引（不影响其他班级），可能耗时较长，确认？'
    : '将清空并重建资料索引，可能耗时较长，确认？'
  await ElMessageBox.confirm(msg, '重建索引', { type: 'warning' })
  const { data } = await http.post('/materials/reindex', {}, { timeout: 600000 })
  ElMessage.success(`重建完成：${data.materials} 个资料，${data.chunks} 个片段`)
  loadStats()
}

async function resetCourseStructure() {
  if (!selectedCourseId.value) return
  await ElMessageBox.confirm(
    '将删除本课程下所有章节、资料与向量索引，智能体恢复为筹备中。之后请重新通过「课件识别章节」等方式建立章节结构。确认继续？',
    '重新建立章节结构',
    { type: 'warning' },
  )
  uploading.value = true
  try {
    const resetParams: Record<string, number> = { course_id: selectedCourseId.value }
    if (agentStore.current?.id) resetParams.agent_id = agentStore.current.id
    await http.post('/chapters/reset-course', null, { params: resetParams })
    ElMessage.success('已清空章节与资料，请重新上传识别')
    chapters.value = []
    list.value = []
    if (agentStore.current?.course_id === selectedCourseId.value) {
      const { data: agent } = await http.get(`/agents/${agentStore.current.id}`)
      agentStore.setAgent(agent)
    }
    await loadChapters()
    loadList()
    loadStats()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '重置失败')
  } finally {
    uploading.value = false
  }
}

async function resplitTextbook() {
  await ElMessageBox.confirm(
    '将用最新的章节拆分逻辑重新分配教材页码归属并重建索引。用于修复章节归属错误（如数组内容被分到错误章节）。确认执行？',
    '重新拆分教材',
    { type: 'warning' }
  )
  uploading.value = true
  try {
    const { data } = await http.post('/materials/re-split-textbook', {}, { timeout: 600000 })
    ElMessage.success(`重新拆分完成：${data.materials_resplit} 个资料，${data.total_chunks} 个片段`)
    loadList(); loadStats()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '重新拆分失败')
  } finally {
    uploading.value = false
  }
}

function fileUrl(row: Material | MaterialGroup) {
  const id = 'material_ids' in row && row.material_ids?.length ? row.material_ids[0] : row.id
  return `/api/materials/file/${id}`
}

function preview(row: Material | MaterialGroup) {
  window.open(fileUrl(row), '_blank')
}

const typeTag = (t: string) => {
  const map: Record<string, string> = { pdf: 'danger', ppt: 'warning', video: 'success', word: 'info' }
  return map[t] || ''
}

onMounted(async () => {
  await agentStore.restoreAgent()
  await loadCourses()
  await loadClasses()
  await loadChapters()
  await Promise.all([loadList(), loadStats()])
})

watch(
  () => agentStore.current?.id,
  async (id, prev) => {
    if (!id || id === prev) return
    chapters.value = []
    list.value = []
    filterChapter.value = undefined
    await loadCourses()
    await loadClasses()
    await loadChapters()
    await Promise.all([loadList(), loadStats()])
  },
)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>{{ isSharedPreview ? '共享资料库（只读体验）' : '课程资料管理' }}</span>
        <div>
          <el-tag style="margin-right: 8px">索引片段: {{ stats.chunks }}</el-tag>
          <template v-if="!isSharedPreview">
            <el-button v-if="canResetCourseStructure" type="warning" plain @click="resetCourseStructure">重新建立章节</el-button>
            <el-button @click="resplitTextbook" :loading="uploading">重新拆分教材</el-button>
            <el-button @click="reindex">重建索引</el-button>
            <el-button type="primary" @click="openUpload">上传资料</el-button>
          </template>
        </div>
      </div>
    </template>

    <el-alert
      v-if="!isSharedPreview && agentStore.current?.source_agent_id && classes.length"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
      title="已采纳共享智能体"
      description="列表仅显示已绑定班级的资料（班级列不再出现空白）。若数量偏少，请到「课程智能体 → 我的管理」重新保存一次「绑定班级」以同步快照。"
    />

    <el-alert
      v-if="isSharedPreview"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
      title="正在只读体验共享资料库"
      description="默认显示源教师全部共享资料；班级筛选项可再按班查看。若要在本班使用，请返回共享广场「加入我的管理」并绑定班级。"
    />

    <el-alert
      v-if="needsChapterSetup"
      type="warning"
      :closable="false"
      title="请先建立章节结构"
      style="margin-bottom: 12px"
    >
      <template #default>
        本课程章节不会预置。您可
        <el-link type="primary" @click="openCoursewareBatch">批量上传各章课件</el-link>
        自动识别章节，或
        <el-link type="primary" @click="openTextbookUpload">上传整本教材 PDF</el-link>
        分析章节，或
        <el-link type="primary" @click="openCustomChapters">自定义章节结构</el-link>
        后按章上传资料构建知识库。
      </template>
    </el-alert>

    <div style="margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
      <el-select v-if="!lockedCourse" v-model="selectedCourseId" placeholder="选择课程" style="width: 220px" @change="onCourseChange">
        <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
      <el-select v-model="filterClass" placeholder="按班级筛选" clearable @change="loadList" style="width: 220px">
        <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
      <el-select v-model="filterChapter" placeholder="按章节筛选" clearable @change="loadList" style="width: 220px">
        <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
      </el-select>
    </div>

    <el-table :data="displayList" v-loading="loading" border>
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="标题" prop="title" />
      <el-table-column label="班级" min-width="200">
        <template #default="{ row }">{{ classTitles(row.class_ids) }}</template>
      </el-table-column>
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag :type="typeTag(row.type) as any">{{ row.type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="章节" width="180">
        <template #default="{ row }">
          {{ chapters.find(c => c.id === row.chapter_id)?.title || row.chapter_id }}
        </template>
      </el-table-column>
      <el-table-column label="文件" prop="file_name" show-overflow-tooltip />
      <el-table-column label="上传时间" prop="created_at" width="180" />
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button text type="primary" @click="preview(row)">预览</el-button>
          <el-button v-if="!isSharedPreview" text type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="上传资料" width="600px" class="material-upload-dialog">
      <el-alert
        v-if="noScopedClasses"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
        title="暂无可选班级"
        description="智能体上下文中仅显示「已绑定且由您管理」的班级。请先在「班级管理」创建对应课程的班级，再在「课程智能体 → 我的管理」点击「绑定班级」。"
      />
      <el-tabs v-model="uploadTab">
        <el-tab-pane label="单章上传" name="single" :disabled="!canSingleChapterUpload">
          <el-alert
            v-if="!canSingleChapterUpload"
            type="info"
            :closable="false"
            title="暂无章节"
            description="请先通过「课件识别章节」「整本教材上传」或「自定义章节」建立章节结构后，再使用单章上传补充资料。"
            style="margin-bottom: 12px"
          />
          <el-form v-else label-width="80px">
            <el-form-item label="班级">
              <el-select
                v-model="form.class_ids"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="选择所属班级（可多选）"
                style="width: 100%"
              >
                <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="章节">
              <el-select v-model="form.chapter_id">
                <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="标题">
              <el-input v-model="form.title" placeholder="资料标题" />
            </el-form-item>
            <el-form-item label="文件">
              <el-upload
                class="material-file-upload"
                :auto-upload="false"
                :limit="1"
                :on-change="onFileChange"
                :on-remove="onFileRemove"
                accept=".pdf,.ppt,.pptx,.doc,.docx,.txt,.mp4,.mov,.avi,.mkv"
              >
                <el-button>选择文件</el-button>
                <template #tip>
                  <div style="color: #999; font-size: 12px">支持 PDF/PPT/Word/视频；视频将自动转字幕并索引</div>
                </template>
              </el-upload>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane v-if="needsChapterSetup" label="课件识别章节" name="courseware">
          <el-alert
            type="info"
            :closable="false"
            style="margin-bottom: 12px"
            title="批量上传各章课件，自动识别章节"
            description="请先在「课程智能体 → 我的管理」中为本智能体绑定好班级。一次选择多份课件（PDF/PPT/Word），系统按文件名或课件首页标题识别「第N章」等并创建章节、索引资料。"
          />
          <el-form label-width="80px">
            <el-form-item label="班级">
              <el-select
                v-model="coursewareForm.class_ids"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="选择所属班级（可多选）"
                style="width: 100%"
              >
                <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
              <div style="margin-top: 6px; font-size: 12px; color: #909399; line-height: 1.4">
                若无可选班级，请先绑定班级后再上传
              </div>
            </el-form-item>
            <el-form-item label="课件">
              <el-upload
                class="material-file-upload"
                :auto-upload="false"
                multiple
                :on-change="onCoursewareFilesChange"
                :on-remove="onCoursewareFilesChange"
                accept=".pdf,.ppt,.pptx,.doc,.docx,.txt"
              >
                <el-button>选择课件（可多选）</el-button>
                <template #tip>
                  <div style="color: #999; font-size: 12px">
                    支持 PDF/PPT/Word；文件名建议含「第N章」或「01-章节名」便于识别
                  </div>
                </template>
              </el-upload>
            </el-form-item>
          </el-form>

          <div v-if="coursewareResult" style="margin-top: 12px">
            <el-divider>识别结果</el-divider>
            <el-table :data="coursewareResult.details" size="small" border max-height="240">
              <el-table-column label="章节" prop="chapter_title" />
              <el-table-column label="文件" prop="file_name" show-overflow-tooltip />
              <el-table-column label="识别方式" width="100">
                <template #default="{ row }">
                  {{ row.parse_source === 'filename' ? '文件名' : row.parse_source === 'content' ? '课件内容' : '排序' }}
                </template>
              </el-table-column>
              <el-table-column label="片段数" prop="chunks" width="80" />
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane label="整本教材上传" name="textbook">
          <el-alert
            type="info"
            :closable="false"
            style="margin-bottom: 12px"
            title="整本教材 PDF 自动按章节拆分"
            :description="needsChapterSetup
              ? '可批量上传各章课件自动识别章节，或上传整本教材 PDF 分析，或手动自定义章节。C 语言课程使用预置章节。'
              : '上传含「第N章」格式章节标题的 PDF 教材，系统将自动按章节拆分并为每章创建独立资料与索引。大文件拆分与索引可能需要数分钟，请勿关闭页面。'"
          />
          <el-form label-width="80px">
            <el-form-item label="班级">
              <el-select
                v-model="textbookForm.class_ids"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="选择所属班级（可多选）"
                style="width: 100%"
              >
                <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="标题前缀">
              <el-input v-model="textbookForm.title_prefix" placeholder="如：C程序设计快速进阶大学教程" />
            </el-form-item>
            <el-form-item label="目录页码">
              <div style="display: flex; align-items: center; gap: 8px; width: 100%">
                <el-input-number
                  v-model="textbookForm.toc_page_start"
                  :min="1"
                  :controls="true"
                  placeholder="起始"
                  style="width: 120px"
                />
                <span style="color: #909399">—</span>
                <el-input-number
                  v-model="textbookForm.toc_page_end"
                  :min="1"
                  :controls="true"
                  placeholder="结束"
                  style="width: 120px"
                />
              </div>
              <div style="color: #999; font-size: 12px; margin-top: 4px; line-height: 1.4">
                可选。填 PDF 阅读器中的页码（如目录在第 5–8 页填 5 和 8）。不填则自动检测目录页。
              </div>
            </el-form-item>
            <el-form-item label="PDF文件">
              <el-upload
                class="material-file-upload"
                :auto-upload="false"
                :limit="1"
                :on-change="onTextbookFileChange"
                :on-remove="onTextbookFileRemove"
                accept=".pdf"
              >
                <el-button>选择 PDF</el-button>
                <template #tip>
                  <div style="color: #999; font-size: 12px">仅支持 PDF；需含「第N章」格式章节标题</div>
                </template>
              </el-upload>
            </el-form-item>
          </el-form>

          <div v-if="textbookResult" style="margin-top: 12px">
            <el-divider>拆分结果</el-divider>
            <el-table :data="textbookResult.details" size="small" border max-height="240">
              <el-table-column label="章节" prop="chapter_title" />
              <el-table-column label="页码" prop="page_range" width="100" />
              <el-table-column label="片段数" prop="chunks" width="80" />
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane v-if="needsChapterSetup" label="自定义章节" name="custom">
          <el-alert
            type="info"
            :closable="false"
            style="margin-bottom: 12px"
            title="手动定义章节结构"
            description="无需整本教材 PDF。添加章节标题后，可在「单章上传」中按章上传 PPT、PDF、Word、视频等资料构建知识库。"
          />
          <div style="margin-bottom: 8px">
            <el-button @click="addCustomRow">添加章节</el-button>
          </div>
          <el-table :data="customChapters" border size="small">
            <el-table-column label="序号" width="70">
              <template #default="{ $index }">{{ $index + 1 }}</template>
            </el-table-column>
            <el-table-column label="章节标题" min-width="200">
              <template #default="{ row }">
                <el-input v-model="row.title" placeholder="如：第1章 绪论" />
              </template>
            </el-table-column>
            <el-table-column label="简介（可选）" min-width="180">
              <template #default="{ row }">
                <el-input v-model="row.description" placeholder="章节简介" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ $index }">
                <el-button text type="danger" @click="removeCustomRow($index)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button
          v-if="uploadTab === 'single'"
          type="primary"
          :loading="uploading"
          @click="submitUpload">上传并索引</el-button>
        <el-button
          v-else-if="uploadTab === 'custom'"
          type="primary"
          :loading="uploading"
          @click="submitCustomChapters">创建章节</el-button>
        <el-button
          v-else-if="uploadTab === 'courseware'"
          type="primary"
          :loading="uploading"
          @click="submitCoursewareBatch">识别并索引</el-button>
        <el-button
          v-else
          type="primary"
          :loading="uploading"
          @click="submitTextbookUpload">拆分并索引</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.material-file-upload {
  width: 100%;
}
.material-file-upload :deep(.el-upload-list) {
  width: 100%;
  max-width: 100%;
}
.material-file-upload :deep(.el-upload-list__item) {
  max-width: 100%;
}
.material-file-upload :deep(.el-upload-list__item-info) {
  max-width: calc(100% - 36px);
  overflow: hidden;
}
.material-file-upload :deep(.el-upload-list__item-name) {
  display: block !important;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.material-file-upload :deep(.el-upload-list__item .el-icon--close),
.material-file-upload :deep(.el-upload-list__item .el-upload-list__item-status-label) {
  flex-shrink: 0;
}
</style>
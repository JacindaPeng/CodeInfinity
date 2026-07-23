<script setup lang="ts">
import { onMounted, onUnmounted, ref, reactive, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { useCourseAgentStore } from '@/stores/courseAgent'
import { useAgentCourseScope } from '@/composables/useAgentCourseScope'
import { useAgentBoundClasses } from '@/composables/useAgentBoundClasses'

interface Chapter { id: number; title: string }
interface ClassItem { id: number; name: string }
interface CourseItem { id: number; name: string }
interface KP { id: number; name: string }
interface QRow {
  id: number; chapter_id: number; class_id: number | null; kp_id: number | null; type: string
  stem: string; options: string[]; answer: string; analysis: string
}
interface ImportJob {
  id: number
  status: string
  progress: number
  error_message: string
  stats: Record<string, number>
  candidate_count?: number
  pending_count?: number
  approved_count?: number
}
interface Candidate {
  id: number
  original_number: string
  type: string
  stem: string
  options: string[]
  answer: string
  analysis: string
  chapter_id: number | null
  extra_chapter_ids: number[]
  kp_id: number | null
  new_kp_name: string
  extra_kp_names: string[]
  status: string
  answer_source: string
  confidence: number | null
  classification_note: string
  selected?: boolean
}

const agentStore = useCourseAgentStore()
const { lockedCourse, applyLockedCourse, chapterListParams } = useAgentCourseScope()
const { loadScopedClasses, pickClassId, syncMultiClassIds, isSharedPreview } = useAgentBoundClasses()
const courses = ref<CourseItem[]>([])
const selectedCourseId = ref<number | undefined>(undefined)
const chapters = ref<Chapter[]>([])
const classes = ref<ClassItem[]>([])
const kps = ref<KP[]>([])
const list = ref<QRow[]>([])
const filterChapter = ref<number | undefined>(undefined)
const filterClass = ref<number | undefined>(undefined)

const dialogVisible = ref(false)
const editing = ref(false)
const form = reactive({
  id: 0, chapter_id: 0, class_id: 0, class_ids: [] as number[], kp_id: null as number | null,
  type: '选择题', stem: '', options: ['', '', '', ''], answer: '', analysis: '',
})

const primaryClassId = computed(() =>
  editing.value ? form.class_id : (form.class_ids[0] || 0)
)

// ---- 导入试卷 ----
const importVisible = ref(false)
const importStep = ref<'upload' | 'parsing' | 'review' | 'done'>('upload')
const importClassIds = ref<number[]>([])
const answersInPaper = ref(false)
const paperFile = ref<File | null>(null)
const answerFile = ref<File | null>(null)
const importing = ref(false)
const publishing = ref(false)
const importJob = ref<ImportJob | null>(null)
const candidates = ref<Candidate[]>([])
const editCand = ref<Candidate | null>(null)
const editVisible = ref(false)
const importKps = ref<KP[]>([])
let pollTimer: ReturnType<typeof setInterval> | null = null

const STANDARD_TYPES = ['选择题', '判断题', '填空题', '简答题']
const typeOptions = computed(() => {
  const extra = new Set<string>()
  for (const c of candidates.value) {
    if (c.type && !STANDARD_TYPES.includes(c.type)) extra.add(c.type)
  }
  return [...STANDARD_TYPES, ...extra]
})

const pendingCount = computed(() => candidates.value.filter(c => c.status === 'pending').length)
const approvedCount = computed(() => candidates.value.filter(c => c.status === 'approved').length)
const aiAnswerCount = computed(() => candidates.value.filter(c => c.answer_source === 'ai').length)

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
  if (data.length) form.chapter_id = data[0].id
}

function onCourseChange() {
  filterChapter.value = undefined
  loadChapters()
  loadList()
}

async function loadClasses() {
  const data = await loadScopedClasses()
  classes.value = data
  if (isSharedPreview.value) {
    filterClass.value = undefined
    form.class_ids = []
  } else {
    filterClass.value = pickClassId(data, filterClass.value)
    if (data.length && !form.class_ids.length) {
      form.class_ids = syncMultiClassIds(data, [])
    }
  }
}

const classTitle = (id: number | null) =>
  classes.value.find(c => c.id === id)?.name || (id ? `班级${id}` : '-')

async function loadKps(chapterId?: number, classId?: number) {
  const cid = classId || primaryClassId.value || filterClass.value
  if (!chapterId || !cid) { kps.value = []; return }
  const params: Record<string, number> = { class_id: cid }
  if (agentStore.current?.id) params.agent_id = agentStore.current.id
  const { data } = await http.get<KP[]>(`/exams/knowledge-points/${chapterId}`, { params })
  kps.value = data
}

async function loadList() {
  try {
    const params: Record<string, number | undefined> = {
      chapter_id: filterChapter.value || undefined,
      class_id: filterClass.value || undefined,
      course_id: selectedCourseId.value || undefined,
    }
    if (agentStore.current?.id) params.agent_id = agentStore.current.id
    const { data } = await http.get<QRow[]>('/exams/bank', { params })
    list.value = data
  } catch (e: any) {
    list.value = []
    const detail = e?.response?.data?.detail
    if (detail) ElMessage.error(typeof detail === 'string' ? detail : '加载题库失败')
  }
}

function defaultClassIds(): number[] {
  if (filterClass.value) return [filterClass.value]
  return classes.value.map(c => c.id)
}

function openAdd() {
  editing.value = false
  Object.assign(form, {
    id: 0,
    chapter_id: chapters.value[0]?.id || 0,
    class_id: 0,
    class_ids: defaultClassIds(),
    kp_id: null,
    type: '选择题', stem: '', options: ['', '', '', ''], answer: '', analysis: '',
  })
  loadKps(form.chapter_id, form.class_ids[0])
  dialogVisible.value = true
}

function openEdit(row: QRow) {
  editing.value = true
  Object.assign(form, {
    id: row.id, chapter_id: row.chapter_id, class_id: row.class_id || 0, class_ids: [],
    kp_id: row.kp_id, type: row.type, stem: row.stem,
    options: row.options.length ? [...row.options] : ['', '', '', ''],
    answer: row.answer, analysis: row.analysis,
  })
  loadKps(row.chapter_id, row.class_id || undefined)
  dialogVisible.value = true
}

async function submit() {
  if (!form.stem || !form.answer) { ElMessage.warning('题干和答案必填'); return }
  const base = {
    chapter_id: form.chapter_id, kp_id: form.kp_id, type: form.type,
    stem: form.stem,
    options: form.type === '简答题' || form.type === '填空题' ? [] : form.options.filter(o => o.trim()),
    answer: form.answer, analysis: form.analysis,
  }
  try {
    if (editing.value) {
      if (!form.class_id) { ElMessage.warning('请选择班级'); return }
      await http.put(`/exams/bank/${form.id}`, { ...base, class_id: form.class_id })
      ElMessage.success('已更新')
    } else {
      if (!form.class_ids.length) { ElMessage.warning('请至少选择一个班级'); return }
      const { data } = await http.post('/exams/bank', { ...base, class_ids: form.class_ids })
      const hint = data.created > 1 ? `，已同步到 ${data.created} 个班级` : ''
      ElMessage.success(`已新增${hint}`)
    }
    dialogVisible.value = false
    loadList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

async function remove(row: QRow) {
  await ElMessageBox.confirm(`删除该题目？`, '提示', { type: 'warning' })
  await http.delete(`/exams/bank/${row.id}`)
  ElMessage.success('已删除')
  loadList()
}

function onChapterChange() { loadKps(form.chapter_id, primaryClassId.value) }
function onFormClassChange() { loadKps(form.chapter_id, primaryClassId.value) }

const chapterTitle = (id: number | null | undefined) =>
  chapters.value.find(c => c.id === id)?.title || (id ? String(id) : '-')

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function openImport() {
  importStep.value = 'upload'
  importClassIds.value = defaultClassIds()
  answersInPaper.value = false
  paperFile.value = null
  answerFile.value = null
  importJob.value = null
  candidates.value = []
  importing.value = false
  publishing.value = false
  stopPoll()
  importVisible.value = true
}

function onPaperChange(file: any) {
  paperFile.value = file?.raw || null
  return false
}
function onAnswerChange(file: any) {
  answerFile.value = file?.raw || null
  return false
}
function clearPaper() { paperFile.value = null }
function clearAnswer() { answerFile.value = null }

async function submitImport() {
  if (!selectedCourseId.value) { ElMessage.warning('请先选择课程'); return }
  if (!importClassIds.value.length) { ElMessage.warning('请至少选择一个班级'); return }
  if (!paperFile.value) { ElMessage.warning('请上传试卷文件'); return }

  const fd = new FormData()
  fd.append('course_id', String(selectedCourseId.value))
  fd.append('class_ids', JSON.stringify(importClassIds.value))
  fd.append('answers_in_paper', answersInPaper.value ? 'true' : 'false')
  fd.append('paper', paperFile.value)
  if (answerFile.value) fd.append('answer', answerFile.value)
  if (agentStore.current?.id) fd.append('agent_id', String(agentStore.current.id))

  importing.value = true
  importStep.value = 'parsing'
  try {
    const { data } = await http.post<ImportJob>('/exam-imports', fd, {
      timeout: 60000,
      headers: { 'Content-Type': 'multipart/form-data' },
      skipGlobalError: true,
    })
    importJob.value = { ...data, progress: 0, error_message: '', stats: {} }
    startPoll(data.id)
  } catch (e: any) {
    importing.value = false
    importStep.value = 'upload'
    ElMessage.error(e?.response?.data?.detail || '上传失败')
  }
}

function startPoll(jobId: number) {
  stopPoll()
  const tick = async () => {
    try {
      const { data } = await http.get<ImportJob>(`/exam-imports/${jobId}`, { skipGlobalError: true })
      importJob.value = data
      if (data.status === 'reviewing') {
        stopPoll()
        importing.value = false
        await loadCandidates(jobId)
        importStep.value = 'review'
      } else if (data.status === 'failed') {
        stopPoll()
        importing.value = false
        ElMessage.error(data.error_message || '解析失败')
        importStep.value = 'upload'
      } else if (data.status === 'completed') {
        stopPoll()
        importing.value = false
        importStep.value = 'done'
      }
    } catch {
      /* 忽略瞬时错误，继续轮询 */
    }
  }
  tick()
  pollTimer = setInterval(tick, 2000)
}

async function loadCandidates(jobId: number) {
  const { data } = await http.get<Candidate[]>(`/exam-imports/${jobId}/candidates`)
  candidates.value = data.map(c => ({
    ...c,
    selected: c.status !== 'rejected',
    options: c.options?.length ? [...c.options] : [],
  }))
}

async function loadImportKps(chapterId?: number | null) {
  const cid = importClassIds.value[0]
  if (!chapterId || !cid) { importKps.value = []; return }
  const params: Record<string, number> = { class_id: cid }
  if (agentStore.current?.id) params.agent_id = agentStore.current.id
  const { data } = await http.get<KP[]>(`/exams/knowledge-points/${chapterId}`, { params })
  importKps.value = data
}

function openEditCand(row: Candidate) {
  editCand.value = {
    ...row,
    options: row.options?.length ? [...row.options] : ['', '', '', ''],
    extra_chapter_ids: [...(row.extra_chapter_ids || [])],
    extra_kp_names: [...(row.extra_kp_names || [])],
  }
  loadImportKps(row.chapter_id)
  editVisible.value = true
}

function onEditCandChapter(v: number | string | null) {
  if (editCand.value) editCand.value.kp_id = null
  const cid = typeof v === 'number' ? v : Number(v)
  loadImportKps(Number.isFinite(cid) && cid > 0 ? cid : null)
}

async function saveCand() {
  if (!editCand.value || !importJob.value) return
  const c = editCand.value
  if (!c.stem) { ElMessage.warning('题干不能为空'); return }
  try {
    const { data } = await http.put<Candidate>(
      `/exam-imports/${importJob.value.id}/candidates/${c.id}`,
      {
        type: c.type,
        stem: c.stem,
        options: (c.type === '简答题' || c.type === '填空题') ? [] : c.options.filter(o => o.trim()),
        answer: c.answer,
        analysis: c.analysis,
        chapter_id: c.chapter_id,
        extra_chapter_ids: c.extra_chapter_ids,
        kp_id: c.new_kp_name ? null : c.kp_id,
        new_kp_name: c.new_kp_name || '',
        extra_kp_names: c.extra_kp_names,
        status: c.status,
      },
      { skipGlobalError: true },
    )
    const idx = candidates.value.findIndex(x => x.id === c.id)
    if (idx >= 0) {
      candidates.value[idx] = { ...candidates.value[idx], ...data, selected: data.status !== 'rejected' }
    }
    editVisible.value = false
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

async function bulkSetStatus(status: 'approved' | 'rejected') {
  if (!importJob.value) return
  const ids = candidates.value.filter(c => c.selected).map(c => c.id)
  if (!ids.length) { ElMessage.warning('请先勾选题目'); return }
  await http.post(`/exam-imports/${importJob.value.id}/candidates/bulk-review`, {
    candidate_ids: ids,
    status,
  })
  await loadCandidates(importJob.value.id)
  ElMessage.success(status === 'approved' ? '已标记通过' : '已标记拒绝')
}

async function approveAllPending() {
  if (!importJob.value) return
  await http.post(`/exam-imports/${importJob.value.id}/candidates/bulk-review`, {
    candidate_ids: [],
    status: 'approved',
    all_pending: true,
  })
  await loadCandidates(importJob.value.id)
  ElMessage.success('已全部通过待审核题目')
}

async function publishImport() {
  if (!importJob.value) return
  const toPublish = candidates.value.filter(c => c.status === 'approved' || c.status === 'pending')
  if (!toPublish.length) {
    ElMessage.warning('没有可入库的题目')
    return
  }
  const aiN = toPublish.filter(c => c.answer_source === 'ai').length
  const tip = aiN
    ? `将入库 ${toPublish.length} 道题（其中 ${aiN} 道答案由 AI 生成）。请确认已核实无误。`
    : `将入库 ${toPublish.length} 道题，确认继续？`
  await ElMessageBox.confirm(tip, '核实并入库', { type: 'warning' })

  // 先把仍 pending 的视为通过
  if (pendingCount.value) {
    await http.post(`/exam-imports/${importJob.value.id}/candidates/bulk-review`, {
      candidate_ids: [],
      status: 'approved',
      all_pending: true,
    })
  }

  publishing.value = true
  try {
    const { data } = await http.post(
      `/exam-imports/${importJob.value.id}/publish`,
      null,
      { params: { only_approved: true }, timeout: 120000, skipGlobalError: true },
    )
    ElMessage.success(
      `已入库 ${data.published} 道` +
      (data.skipped_dup ? `，跳过重复 ${data.skipped_dup}` : '') +
      (data.created_kps ? `，新建知识点 ${data.created_kps}` : ''),
    )
    importStep.value = 'done'
    loadList()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '入库失败')
  } finally {
    publishing.value = false
  }
}

async function retryImport() {
  if (!importJob.value) return
  importing.value = true
  importStep.value = 'parsing'
  await http.post(`/exam-imports/${importJob.value.id}/retry`)
  startPoll(importJob.value.id)
}

const answerSourceLabel = (s: string) => {
  if (s === 'ai') return 'AI生成'
  if (s === 'manual') return '已手改'
  if (s === 'embedded') return '卷内答案'
  return '答案文件'
}

onMounted(async () => {
  await agentStore.restoreAgent()
  await loadCourses()
  await loadClasses()
  await loadChapters()
  await Promise.all([loadList(), loadKps(chapters.value[0]?.id, classes.value[0]?.id)])
})

onUnmounted(() => stopPoll())
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>{{ isSharedPreview ? '共享题库（只读体验）' : '题库管理' }}</span>
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
          <el-select
            v-if="!lockedCourse"
            v-model="selectedCourseId"
            placeholder="选择课程"
            style="width: 200px; margin-right: 8px"
            @change="onCourseChange"
          >
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-select
            v-model="filterClass"
            placeholder="按班级筛选"
            clearable
            @change="loadList"
            style="width: 180px; margin-right: 8px"
          >
            <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-select v-model="filterChapter" placeholder="按章节筛选" clearable @change="loadList" style="width: 200px; margin-right: 8px">
            <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
          <el-button v-if="!isSharedPreview" @click="openImport">导入试卷</el-button>
          <el-button v-if="!isSharedPreview" type="primary" @click="openAdd">新增题目</el-button>
        </div>
      </div>
    </template>

    <el-alert
      v-if="isSharedPreview"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
      title="正在只读体验共享题库"
      description="可浏览源教师题库。若要在本班使用，请返回共享广场「加入我的管理」并绑定班级。"
    />

    <el-table :data="list" border size="small">
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="班级" width="140">
        <template #default="{ row }">{{ classTitle(row.class_id) }}</template>
      </el-table-column>
      <el-table-column label="章节" width="180">
        <template #default="{ row }">{{ chapterTitle(row.chapter_id) }}</template>
      </el-table-column>
      <el-table-column label="题型" prop="type" width="90" />
      <el-table-column label="题干" prop="stem" show-overflow-tooltip />
      <el-table-column label="答案" prop="answer" width="120" show-overflow-tooltip />
      <el-table-column v-if="!isSharedPreview" label="操作" width="140">
        <template #default="{ row }">
          <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button text type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑题目' : '新增题目'" width="640px">
      <el-form label-width="80px">
        <el-form-item label="班级">
          <el-select
            v-if="editing"
            v-model="form.class_id"
            placeholder="选择所属班级"
            style="width: 100%"
            @change="onFormClassChange"
          >
            <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-select
            v-else
            v-model="form.class_ids"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择所属班级（可多选）"
            style="width: 100%"
            @change="onFormClassChange"
          >
            <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="章节">
          <el-select v-model="form.chapter_id" @change="onChapterChange">
            <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="知识点">
          <el-select v-model="form.kp_id" clearable placeholder="可选">
            <el-option v-for="k in kps" :key="k.id" :label="k.name" :value="k.id" />
          </el-select>
          <div v-if="!editing && form.class_ids.length > 1" style="color: #999; font-size: 12px">
            知识点列表展示第一个所选班级的内容
          </div>
        </el-form-item>
        <el-form-item label="题型">
          <el-radio-group v-model="form.type">
            <el-radio value="选择题">选择题</el-radio>
            <el-radio value="判断题">判断题</el-radio>
            <el-radio value="填空题">填空题</el-radio>
            <el-radio value="简答题">简答题</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="题干">
          <el-input v-model="form.stem" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item v-if="form.type !== '简答题' && form.type !== '填空题'" label="选项">
          <div v-for="(_, i) in form.options" :key="i" style="margin-bottom: 6px">
            <el-input v-model="form.options[i]" :placeholder="`选项 ${i + 1}（如 A. xxx）`" />
          </div>
          <div v-if="form.type === '判断题'" style="color: #999; font-size: 12px">判断题选项填「对」「错」即可</div>
        </el-form-item>
        <el-form-item label="答案">
          <el-input v-model="form.answer" :placeholder="form.type === '选择题' ? '如 A' : form.type === '判断题' ? '对/错' : '参考答案'" />
        </el-form-item>
        <el-form-item label="解析">
          <el-input v-model="form.analysis" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 导入试卷 -->
    <el-dialog
      v-model="importVisible"
      title="导入试卷（自动拆题）"
      width="960px"
      :close-on-click-modal="false"
      @closed="stopPoll"
    >
      <div v-if="importStep === 'upload'">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 16px"
          title="支持可复制文本的 PDF / DOC / DOCX；扫描版暂不支持 OCR"
          description="有答案时按答案配对；无答案时由 AI 生成答案，需教师核实后再入库。综合题会归入主章节并可保留多章节标签。"
        />
        <el-form label-width="110px">
          <el-form-item label="目标班级" required>
            <el-select
              v-model="importClassIds"
              multiple
              collapse-tags
              collapse-tags-tooltip
              placeholder="选择入库班级"
              style="width: 100%"
            >
              <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="试卷文件" required>
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
              <el-upload
                :auto-upload="false"
                :show-file-list="false"
                accept=".pdf,.doc,.docx"
                :on-change="onPaperChange"
              >
                <el-button type="primary" plain>选择试卷</el-button>
              </el-upload>
              <span v-if="paperFile" class="file-name" :title="paperFile.name">{{ paperFile.name }}</span>
              <el-button v-if="paperFile" text type="danger" @click="clearPaper">清除</el-button>
            </div>
          </el-form-item>
          <el-form-item label="答案文件">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
              <el-upload
                :auto-upload="false"
                :show-file-list="false"
                accept=".pdf,.doc,.docx"
                :on-change="onAnswerChange"
              >
                <el-button plain>选择答案（可选）</el-button>
              </el-upload>
              <span v-if="answerFile" class="file-name" :title="answerFile.name">{{ answerFile.name }}</span>
              <el-button v-if="answerFile" text type="danger" @click="clearAnswer">清除</el-button>
            </div>
          </el-form-item>
          <el-form-item label="答案位置">
            <el-checkbox v-model="answersInPaper" :disabled="!!answerFile">
              答案已包含在试卷中
            </el-checkbox>
          </el-form-item>
        </el-form>
      </div>

      <div v-else-if="importStep === 'parsing'" style="text-align: center; padding: 40px 20px">
        <el-progress
          type="circle"
          :percentage="Math.min(99, importJob?.progress || 5)"
          :status="importJob?.status === 'failed' ? 'exception' : undefined"
        />
        <p style="margin-top: 16px; color: #666">
          {{ importJob?.status === 'classifying' ? '正在归类章节与知识点…' : '正在解析试卷并拆题…' }}
        </p>
        <p style="color: #999; font-size: 13px">大模型拆题可能需要 1～3 分钟，请耐心等待</p>
      </div>

      <div v-else-if="importStep === 'review'">
        <el-alert
          :type="aiAnswerCount ? 'warning' : 'success'"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
          :title="`共拆出 ${candidates.length} 道题 · 待审 ${pendingCount} · 已通过 ${approvedCount}` + (aiAnswerCount ? ` · AI 答案 ${aiAnswerCount} 道需核实` : '')"
        />
        <div style="margin-bottom: 10px; display: flex; gap: 8px; flex-wrap: wrap">
          <el-button size="small" type="success" @click="bulkSetStatus('approved')">勾选通过</el-button>
          <el-button size="small" type="danger" plain @click="bulkSetStatus('rejected')">勾选拒绝</el-button>
          <el-button size="small" @click="approveAllPending">全部通过待审</el-button>
          <el-button size="small" @click="retryImport">重新解析</el-button>
        </div>
        <el-table :data="candidates" border size="small" max-height="420">
          <el-table-column width="48">
            <template #default="{ row }">
              <el-checkbox v-model="row.selected" />
            </template>
          </el-table-column>
          <el-table-column label="题号" prop="original_number" width="60" />
          <el-table-column label="题型" prop="type" width="80" />
          <el-table-column label="章节" width="140">
            <template #default="{ row }">{{ chapterTitle(row.chapter_id) }}</template>
          </el-table-column>
          <el-table-column label="题干" prop="stem" min-width="200" show-overflow-tooltip />
          <el-table-column label="答案来源" width="90">
            <template #default="{ row }">
              <el-tag :type="row.answer_source === 'ai' ? 'warning' : 'info'" size="small">
                {{ answerSourceLabel(row.answer_source) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.status === 'approved' ? 'success' : row.status === 'rejected' ? 'danger' : 'warning'"
              >
                {{ row.status === 'approved' ? '通过' : row.status === 'rejected' ? '拒绝' : '待审' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" @click="openEditCand(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div v-else-if="importStep === 'done'" style="text-align: center; padding: 32px">
        <el-result icon="success" title="入库完成" sub-title="题目已写入题库，可关闭窗口继续管理">
          <template #extra>
            <el-button type="primary" @click="importVisible = false">关闭</el-button>
          </template>
        </el-result>
      </div>

      <template #footer>
        <el-button @click="importVisible = false">{{ importStep === 'done' ? '关闭' : '取消' }}</el-button>
        <el-button v-if="importStep === 'upload'" type="primary" :loading="importing" @click="submitImport">
          开始解析
        </el-button>
        <el-button
          v-if="importStep === 'review'"
          type="primary"
          :loading="publishing"
          @click="publishImport"
        >
          核实无误，写入题库
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑候选题" width="680px" append-to-body>
      <el-form v-if="editCand" label-width="100px">
        <el-form-item label="题型">
          <el-select v-model="editCand.type" filterable allow-create default-first-option style="width: 100%">
            <el-option v-for="t in typeOptions" :key="t" :label="t" :value="t" />
          </el-select>
          <div style="color: #999; font-size: 12px">可输入新题型名称，入库后将保留该题型字符串</div>
        </el-form-item>
        <el-form-item label="主章节">
          <el-select
            v-model="editCand.chapter_id"
            style="width: 100%"
            @change="onEditCandChapter"
          >
            <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="附加章节">
          <el-select
            v-model="editCand.extra_chapter_ids"
            multiple
            collapse-tags
            style="width: 100%"
            placeholder="综合题可多选"
          >
            <el-option
              v-for="c in chapters.filter(ch => ch.id !== editCand?.chapter_id)"
              :key="c.id"
              :label="c.title"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="知识点">
          <el-select v-model="editCand.kp_id" clearable placeholder="选择已有" style="width: 100%" :disabled="!!editCand.new_kp_name">
            <el-option v-for="k in importKps" :key="k.id" :label="k.name" :value="k.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="新建知识点">
          <el-input v-model="editCand.new_kp_name" placeholder="若无匹配项，填写后将随入库创建" />
        </el-form-item>
        <el-form-item label="题干">
          <el-input v-model="editCand.stem" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item v-if="editCand.type !== '简答题' && editCand.type !== '填空题'" label="选项">
          <div v-for="(_, i) in editCand.options" :key="i" style="margin-bottom: 6px">
            <el-input v-model="editCand.options[i]" :placeholder="`选项 ${i + 1}`" />
          </div>
          <el-button size="small" @click="editCand.options.push('')">加选项</el-button>
        </el-form-item>
        <el-form-item label="答案">
          <el-input v-model="editCand.answer" type="textarea" :rows="2" />
          <div v-if="editCand.answer_source === 'ai'" style="color: #e6a23c; font-size: 12px">
            当前为 AI 生成答案，请仔细核实
          </div>
        </el-form-item>
        <el-form-item label="解析">
          <el-input v-model="editCand.analysis" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="归类说明">
          <div style="color: #666; font-size: 13px">{{ editCand.classification_note || '—' }}</div>
        </el-form-item>
        <el-form-item label="审核状态">
          <el-radio-group v-model="editCand.status">
            <el-radio value="pending">待审</el-radio>
            <el-radio value="approved">通过</el-radio>
            <el-radio value="rejected">拒绝</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCand">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.file-name {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #606266;
  font-size: 13px;
}
</style>

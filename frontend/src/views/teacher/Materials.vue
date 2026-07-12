<script setup lang="ts">
import { onMounted, ref, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'

interface Chapter { id: number; title: string }
interface ClassItem { id: number; name: string }
interface Material {
  id: number; chapter_id: number; class_id: number | null; type: string; title: string
  file_name: string; created_at: string | null
}

const chapters = ref<Chapter[]>([])
const classes = ref<ClassItem[]>([])
const list = ref<Material[]>([])
const loading = ref(false)
const stats = ref<{ chunks: number }>({ chunks: 0 })

const filterChapter = ref<number | undefined>(undefined)
const filterClass = ref<number | undefined>(undefined)

// 上传弹窗 + Tab
const dialogVisible = ref(false)
const uploadTab = ref('single')
const form = reactive({
  chapter_id: 0, class_ids: [] as number[], title: '', file: null as File | null,
})
const textbookForm = reactive({
  class_ids: [] as number[],
  file: null as File | null,
  title_prefix: '',
})
const textbookResult = ref<any>(null)
const uploading = ref(false)

async function loadChapters() {
  const { data } = await http.get<Chapter[]>('/chapters')
  chapters.value = data
  if (data.length && !form.chapter_id) form.chapter_id = data[0].id
}

async function loadClasses() {
  const { data } = await http.get<ClassItem[]>('/classes/mine')
  classes.value = data
  if (data.length) {
    form.class_ids = data.map(c => c.id)
    textbookForm.class_ids = data.map(c => c.id)
  }
}

function defaultClassIds(): number[] {
  if (filterClass.value) return [filterClass.value]
  return classes.value.map(c => c.id)
}

const classTitle = (id: number | null) =>
  classes.value.find(c => c.id === id)?.name || (id ? `班级${id}` : '-')

async function loadList() {
  loading.value = true
  try {
    const { data } = await http.get<Material[]>('/materials', {
      params: {
        chapter_id: filterChapter.value || undefined,
        class_id: filterClass.value || undefined,
      },
    })
    list.value = data
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  const { data } = await http.get('/materials/stats')
  stats.value = data
}

function openUpload() {
  form.title = ''; form.file = null
  textbookForm.file = null; textbookForm.title_prefix = ''
  textbookResult.value = null
  uploadTab.value = 'single'
  if (chapters.value.length) form.chapter_id = chapters.value[0].id
  if (classes.value.length) {
    form.class_ids = defaultClassIds()
    textbookForm.class_ids = defaultClassIds()
  }
  dialogVisible.value = true
}

function onFileChange(file: any) {
  form.file = file.raw
  if (!form.title) form.title = file.name.replace(/\.[^.]+$/, '')
}

function onTextbookFileChange(file: any) {
  textbookForm.file = file.raw
  if (!textbookForm.title_prefix) textbookForm.title_prefix = file.name.replace(/\.[^.]+$/, '')
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
    const { data } = await http.post('/materials/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    })
    const classHint = data.class_count > 1 ? `，已同步到 ${data.class_count} 个班级` : ''
    ElMessage.success(`上传成功，索引 ${data.chunks} 个片段${classHint}${data.warning ? '（' + data.warning + '）' : ''}`)
    if (data.warning) ElMessage.warning(data.warning)
    dialogVisible.value = false
    loadList(); loadStats()
  } catch {} finally {
    uploading.value = false
  }
}

async function submitTextbookUpload() {
  if (!textbookForm.class_ids.length) { ElMessage.warning('请至少选择一个班级'); return }
  if (!textbookForm.file) { ElMessage.warning('请选择 PDF 教材'); return }
  uploading.value = true
  textbookResult.value = null
  try {
    const fd = new FormData()
    textbookForm.class_ids.forEach(id => fd.append('class_ids', String(id)))
    fd.append('file', textbookForm.file)
    fd.append('title_prefix', textbookForm.title_prefix)
    const { data } = await http.post('/materials/upload-textbook', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    })
    textbookResult.value = data
    const classHint = data.class_count > 1 ? `，已同步到 ${data.class_count} 个班级` : ''
    ElMessage.success(`整本教材已拆分：${data.chapters_split} 章，共 ${data.total_chunks} 个片段${classHint}`)
    loadList(); loadStats()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function remove(row: Material) {
  await ElMessageBox.confirm(`删除资料「${row.title}」？`, '提示', { type: 'warning' })
  await http.delete(`/materials/${row.id}`)
  ElMessage.success('已删除')
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

function fileUrl(row: Material) {
  return `/api/materials/file/${row.id}`
}

function preview(row: Material) {
  window.open(fileUrl(row), '_blank')
}

const typeTag = (t: string) => {
  const map: Record<string, string> = { pdf: 'danger', ppt: 'warning', video: 'success', word: 'info' }
  return map[t] || ''
}

onMounted(async () => {
  await Promise.all([loadChapters(), loadClasses()])
  await Promise.all([loadList(), loadStats()])
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>课程资料管理（知识库构建：PPT / PDF / Word / 视频 / 整本教材）</span>
        <div>
          <el-tag style="margin-right: 8px">索引片段: {{ stats.chunks }}</el-tag>
          <el-button @click="resplitTextbook" :loading="uploading">重新拆分教材</el-button>
          <el-button @click="reindex">重建索引</el-button>
          <el-button type="primary" @click="openUpload">上传资料</el-button>
        </div>
      </div>
    </template>

    <div style="margin-bottom: 12px; display: flex; gap: 8px">
      <el-select v-model="filterClass" placeholder="按班级筛选" clearable @change="loadList" style="width: 220px">
        <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
      <el-select v-model="filterChapter" placeholder="按章节筛选" clearable @change="loadList" style="width: 220px">
        <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
      </el-select>
    </div>

    <el-table :data="list" v-loading="loading" border>
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="标题" prop="title" />
      <el-table-column label="班级" width="160">
        <template #default="{ row }">{{ classTitle(row.class_id) }}</template>
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
          <el-button text type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="上传资料" width="600px">
      <el-tabs v-model="uploadTab">
        <el-tab-pane label="单章上传" name="single">
          <el-form label-width="80px">
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
                :auto-upload="false"
                :limit="1"
                :on-change="onFileChange"
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

        <el-tab-pane label="整本教材上传" name="textbook">
          <el-alert
            type="info"
            :closable="false"
            style="margin-bottom: 12px"
            title="整本教材 PDF 自动按章节拆分"
            description="上传含「第N章」格式章节标题的 PDF 教材，系统将自动按章节拆分并为每章创建独立资料与索引。"
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
            <el-form-item label="PDF文件">
              <el-upload
                :auto-upload="false"
                :limit="1"
                :on-change="onTextbookFileChange"
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
      </el-tabs>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button
          v-if="uploadTab === 'single'"
          type="primary"
          :loading="uploading"
          @click="submitUpload">上传并索引</el-button>
        <el-button
          v-else
          type="primary"
          :loading="uploading"
          @click="submitTextbookUpload">拆分并索引</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

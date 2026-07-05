<script setup lang="ts">
import { onMounted, ref, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'

interface Chapter { id: number; title: string }
interface Material {
  id: number; chapter_id: number; type: string; title: string
  file_name: string; created_at: string | null
}

const chapters = ref<Chapter[]>([])
const list = ref<Material[]>([])
const loading = ref(false)
const stats = ref<{ chunks: number }>({ chunks: 0 })

const filterChapter = ref<number | undefined>(undefined)

const dialogVisible = ref(false)
const form = reactive({
  chapter_id: 0, title: '', file: null as File | null,
})

async function loadChapters() {
  const { data } = await http.get<Chapter[]>('/chapters')
  chapters.value = data
  if (data.length && !form.chapter_id) form.chapter_id = data[0].id
}

async function loadList() {
  loading.value = true
  try {
    const { data } = await http.get<Material[]>('/materials', {
      params: { chapter_id: filterChapter.value || undefined },
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
  if (chapters.value.length) form.chapter_id = chapters.value[0].id
  dialogVisible.value = true
}

function onFileChange(file: any) {
  form.file = file.raw
  if (!form.title) form.title = file.name.replace(/\.[^.]+$/, '')
}

async function submitUpload() {
  if (!form.chapter_id) { ElMessage.warning('请选择章节'); return }
  if (!form.file) { ElMessage.warning('请选择文件'); return }
  if (!form.title) { ElMessage.warning('请填写标题'); return }
  const fd = new FormData()
  fd.append('chapter_id', String(form.chapter_id))
  fd.append('title', form.title)
  fd.append('file', form.file)
  try {
    const { data } = await http.post('/materials/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    })
    ElMessage.success(`上传成功，索引 ${data.chunks} 个片段${data.warning ? '（' + data.warning + '）' : ''}`)
    dialogVisible.value = false
    loadList(); loadStats()
  } catch {}
}

async function remove(row: Material) {
  await ElMessageBox.confirm(`删除资料「${row.title}」？`, '提示', { type: 'warning' })
  await http.delete(`/materials/${row.id}`)
  ElMessage.success('已删除')
  loadList(); loadStats()
}

async function reindex() {
  await ElMessageBox.confirm('将清空并重建全部索引，可能耗时较长，确认？', '重建索引', { type: 'warning' })
  const { data } = await http.post('/materials/reindex', {}, { timeout: 600000 })
  ElMessage.success(`重建完成：${data.materials} 个资料，${data.chunks} 个片段`)
  loadStats()
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
  await loadChapters()
  await Promise.all([loadList(), loadStats()])
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>课程资料管理（知识库构建：PPT / PDF / Word / 视频）</span>
        <div>
          <el-tag style="margin-right: 8px">索引片段: {{ stats.chunks }}</el-tag>
          <el-button @click="reindex">重建索引</el-button>
          <el-button type="primary" @click="openUpload">上传资料</el-button>
        </div>
      </div>
    </template>

    <div style="margin-bottom: 12px">
      <el-select v-model="filterChapter" placeholder="按章节筛选" clearable @change="loadList" style="width: 220px">
        <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
      </el-select>
    </div>

    <el-table :data="list" v-loading="loading" border>
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="标题" prop="title" />
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
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button text type="primary" @click="preview(row)">预览</el-button>
          <el-button text type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="上传资料" width="500px">
      <el-form label-width="80px">
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
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitUpload">上传并索引</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

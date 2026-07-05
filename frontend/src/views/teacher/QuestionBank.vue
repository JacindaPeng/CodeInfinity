<script setup lang="ts">
import { onMounted, ref, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'

interface Chapter { id: number; title: string }
interface KP { id: number; name: string }
interface QRow {
  id: number; chapter_id: number; kp_id: number | null; type: string
  stem: string; options: string[]; answer: string; analysis: string
}

const chapters = ref<Chapter[]>([])
const kps = ref<KP[]>([])
const list = ref<QRow[]>([])
const filterChapter = ref<number | undefined>(undefined)

const dialogVisible = ref(false)
const editing = ref(false)
const form = reactive({
  id: 0, chapter_id: 0, kp_id: null as number | null,
  type: '选择题', stem: '', options: ['', '', '', ''], answer: '', analysis: '',
})

async function loadChapters() {
  const { data } = await http.get<Chapter[]>('/chapters')
  chapters.value = data
  if (data.length) form.chapter_id = data[0].id
}

async function loadKps(chapterId?: number) {
  if (!chapterId) { kps.value = []; return }
  const { data } = await http.get<KP[]>(`/exams/knowledge-points/${chapterId}`)
  kps.value = data
}

async function loadList() {
  const { data } = await http.get<QRow[]>('/exams/bank', {
    params: { chapter_id: filterChapter.value || undefined },
  })
  list.value = data
}

function openAdd() {
  editing.value = false
  Object.assign(form, {
    id: 0, chapter_id: chapters.value[0]?.id || 0, kp_id: null,
    type: '选择题', stem: '', options: ['', '', '', ''], answer: '', analysis: '',
  })
  loadKps(form.chapter_id)
  dialogVisible.value = true
}

function openEdit(row: QRow) {
  editing.value = true
  Object.assign(form, {
    id: row.id, chapter_id: row.chapter_id, kp_id: row.kp_id,
    type: row.type, stem: row.stem,
    options: row.options.length ? [...row.options] : ['', '', '', ''],
    answer: row.answer, analysis: row.analysis,
  })
  loadKps(row.chapter_id)
  dialogVisible.value = true
}

async function submit() {
  if (!form.stem || !form.answer) { ElMessage.warning('题干和答案必填'); return }
  const payload = {
    chapter_id: form.chapter_id, kp_id: form.kp_id, type: form.type,
    stem: form.stem,
    options: form.type === '简答题' ? [] : form.options.filter(o => o.trim()),
    answer: form.answer, analysis: form.analysis,
  }
  if (editing.value) {
    await http.put(`/exams/bank/${form.id}`, payload)
    ElMessage.success('已更新')
  } else {
    await http.post('/exams/bank', payload)
    ElMessage.success('已新增')
  }
  dialogVisible.value = false
  loadList()
}

async function remove(row: QRow) {
  await ElMessageBox.confirm(`删除该题目？`, '提示', { type: 'warning' })
  await http.delete(`/exams/bank/${row.id}`)
  ElMessage.success('已删除')
  loadList()
}

function onChapterChange() { loadKps(form.chapter_id) }

const chapterTitle = (id: number) => chapters.value.find(c => c.id === id)?.title || id

onMounted(async () => {
  await loadChapters()
  await Promise.all([loadList(), loadKps(chapters.value[0]?.id)])
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>题库管理</span>
        <div>
          <el-select v-model="filterChapter" placeholder="按章节筛选" clearable @change="loadList" style="width: 200px; margin-right: 8px">
            <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
          <el-button type="primary" @click="openAdd">新增题目</el-button>
        </div>
      </div>
    </template>

    <el-table :data="list" border size="small">
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="章节" width="180">
        <template #default="{ row }">{{ chapterTitle(row.chapter_id) }}</template>
      </el-table-column>
      <el-table-column label="题型" prop="type" width="90" />
      <el-table-column label="题干" prop="stem" show-overflow-tooltip />
      <el-table-column label="答案" prop="answer" width="120" show-overflow-tooltip />
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button text type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑题目' : '新增题目'" width="640px">
      <el-form label-width="80px">
        <el-form-item label="章节">
          <el-select v-model="form.chapter_id" @change="onChapterChange">
            <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="知识点">
          <el-select v-model="form.kp_id" clearable placeholder="可选">
            <el-option v-for="k in kps" :key="k.id" :label="k.name" :value="k.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="题型">
          <el-radio-group v-model="form.type">
            <el-radio value="选择题">选择题</el-radio>
            <el-radio value="判断题">判断题</el-radio>
            <el-radio value="简答题">简答题</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="题干">
          <el-input v-model="form.stem" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item v-if="form.type !== '简答题'" label="选项">
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
  </el-card>
</template>

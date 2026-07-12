<script setup lang="ts">
import { onMounted, ref, reactive, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'

interface Chapter { id: number; title: string }
interface ClassItem { id: number; name: string }
interface KP { id: number; name: string }
interface QRow {
  id: number; chapter_id: number; class_id: number | null; kp_id: number | null; type: string
  stem: string; options: string[]; answer: string; analysis: string
}

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

async function loadChapters() {
  const { data } = await http.get<Chapter[]>('/chapters')
  chapters.value = data
  if (data.length) form.chapter_id = data[0].id
}

async function loadClasses() {
  const { data } = await http.get<ClassItem[]>('/classes/mine')
  classes.value = data
}

const classTitle = (id: number | null) =>
  classes.value.find(c => c.id === id)?.name || (id ? `班级${id}` : '-')

async function loadKps(chapterId?: number, classId?: number) {
  const cid = classId || primaryClassId.value || filterClass.value
  if (!chapterId || !cid) { kps.value = []; return }
  const { data } = await http.get<KP[]>(`/exams/knowledge-points/${chapterId}`, {
    params: { class_id: cid },
  })
  kps.value = data
}

async function loadList() {
  const { data } = await http.get<QRow[]>('/exams/bank', {
    params: {
      chapter_id: filterChapter.value || undefined,
      class_id: filterClass.value || undefined,
    },
  })
  list.value = data
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
    options: form.type === '简答题' ? [] : form.options.filter(o => o.trim()),
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

const chapterTitle = (id: number) => chapters.value.find(c => c.id === id)?.title || id

onMounted(async () => {
  await Promise.all([loadChapters(), loadClasses()])
  await Promise.all([loadList(), loadKps(chapters.value[0]?.id, classes.value[0]?.id)])
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>题库管理</span>
        <div>
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
          <el-button type="primary" @click="openAdd">新增题目</el-button>
        </div>
      </div>
    </template>

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
      <el-table-column label="操作" width="140">
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

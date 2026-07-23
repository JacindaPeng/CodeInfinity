<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { useCourseSelect, type CourseItem } from '@/composables/useCourseSelect'
import { AGENT_LANGUAGES } from '@/constants/agentLanguages'

interface AgentRow {
  id: number
  name: string
  intro: string
  endpoint: string
  course_id: number | null
  course_name: string
  slug: string
  status: string
  owner_id: number | null
  owner_name: string
}

const list = ref<AgentRow[]>([])
const courses = ref<CourseItem[]>([])
const languageSlugs = new Set(AGENT_LANGUAGES.map(l => l.slug))
const { resolveCourseSelection } = useCourseSelect(courses)
const loading = ref(false)
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const form = reactive({
  id: 0,
  name: '',
  intro: '',
  endpoint: '/api/agents/course/ask',
  course_id: null as number | null,
  slug: '',
  status: 'planned',
})

const statusLabel: Record<string, string> = {
  active: '已上线',
  planned: '筹备中',
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get<AgentRow[]>('/admin/agents')
    list.value = data
  } finally {
    loading.value = false
  }
}

async function loadCourses() {
  const { data } = await http.get<CourseItem[]>('/courses')
  courses.value = data
}

function openCreate() {
  dialogMode.value = 'create'
  Object.assign(form, {
    id: 0,
    name: '',
    intro: '',
    endpoint: '/api/agents/course/ask',
    course_id: courses.value[0]?.id ?? null,
    slug: '',
    status: 'planned',
  })
  dialogVisible.value = true
}

function openEdit(row: AgentRow) {
  dialogMode.value = 'edit'
  Object.assign(form, {
    id: row.id,
    name: row.name,
    intro: row.intro,
    endpoint: row.endpoint,
    course_id: row.course_id,
    slug: row.slug,
    status: row.status,
  })
  dialogVisible.value = true
}

function onAgentCourseChange(val: number | string | null | undefined) {
  resolveCourseSelection(val, id => { form.course_id = id })
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写智能体名称')
    return
  }
  if (!form.slug.trim()) {
    ElMessage.warning('请选择编程语言')
    return
  }
  const payload = {
    name: form.name.trim(),
    intro: form.intro.trim(),
    endpoint: form.endpoint.trim() || '/api/agents/course/ask',
    course_id: form.course_id,
    slug: form.slug.trim(),
    status: form.status,
  }
  try {
    if (dialogMode.value === 'create') {
      await http.post('/admin/agents', payload)
      ElMessage.success('已创建智能体')
    } else {
      await http.put(`/admin/agents/${form.id}`, payload)
      ElMessage.success('已更新智能体')
    }
    dialogVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

async function remove(row: AgentRow) {
  await ElMessageBox.confirm(
    `确定删除智能体「${row.name}」？删除后教师/学生将无法选择该课程智能体。`,
    '删除确认',
    { type: 'warning' },
  )
  try {
    await http.delete(`/admin/agents/${row.id}`)
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

onMounted(async () => {
  await loadCourses()
  await load()
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>智能体管理</span>
        <el-button type="primary" @click="openCreate">新增智能体</el-button>
      </div>
    </template>

    <p class="hint">
      管理员在此维护课程智能体元数据（名称、绑定课程、上线状态等）。教师与学生从「课程智能体」入口选择已上线智能体进入学习。
    </p>

    <el-table :data="list" v-loading="loading" border size="small">
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="名称" prop="name" min-width="140" />
      <el-table-column label="slug" prop="slug" width="100" />
      <el-table-column label="绑定课程" min-width="160">
        <template #default="{ row }">
          {{ row.course_name || '（未绑定）' }}
        </template>
      </el-table-column>
      <el-table-column label="所属教师" min-width="120">
        <template #default="{ row }">
          {{ row.owner_name || '（平台预设）' }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
            {{ statusLabel[row.status] || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="介绍" prop="intro" show-overflow-tooltip min-width="200" />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-dialog
    v-model="dialogVisible"
    :title="dialogMode === 'create' ? '新增智能体' : '编辑智能体'"
    width="520px"
  >
    <el-form label-width="96px">
      <el-form-item label="名称" required>
        <el-input v-model="form.name" placeholder="如 Java课程智能体" />
      </el-form-item>
      <el-form-item label="slug" required>
        <el-select v-model="form.slug" filterable placeholder="选择编程语言" style="width: 100%">
          <el-option
            v-if="form.slug && !languageSlugs.has(form.slug)"
            :key="'legacy-' + form.slug"
            :label="`${form.slug}（当前）`"
            :value="form.slug"
          />
          <el-option
            v-for="lang in AGENT_LANGUAGES.filter(l => l.slug !== 'c-lang')"
            :key="lang.slug"
            :label="lang.label"
            :value="lang.slug"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="绑定课程">
        <el-select
          :model-value="form.course_id"
          filterable
          allow-create
          default-first-option
          clearable
          placeholder="选择已有课程，或直接输入新课程名称"
          style="width: 100%"
          @update:model-value="onAgentCourseChange"
        >
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="状态">
        <el-radio-group v-model="form.status">
          <el-radio value="planned">筹备中</el-radio>
          <el-radio value="active">已上线</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="介绍">
        <el-input v-model="form.intro" type="textarea" :rows="4" />
      </el-form-item>
      <el-form-item label="API 入口">
        <el-input v-model="form.endpoint" placeholder="/api/agents/course/ask" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.hint {
  margin: 0 0 12px;
  color: #909399;
  font-size: 13px;
  line-height: 1.6;
}
</style>

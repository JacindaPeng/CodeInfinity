<script setup lang="ts">
import { onMounted, ref, reactive, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useCourseAgentStore, type CourseAgentInfo } from '@/stores/courseAgent'
import { useCourseSelect, type CourseItem } from '@/composables/useCourseSelect'
import { AGENT_LANGUAGES, slugTheme, slugLabel } from '@/constants/agentLanguages'

interface Agent extends CourseAgentInfo {
  already_adopted?: boolean
  adopted_agent_id?: number | null
  adopter_count?: number | null
}

interface AdopterRow {
  adopted_agent_id: number
  adopted_agent_name: string
  status: string
  teacher_id: number | null
  username: string
  display_name: string
  bound_class_ids: number[]
  bound_class_names: string[]
  snapshot_at: string | null
}

interface ClassItem { id: number; name: string; course_id?: number | null; course_name?: string | null }

const languageSlugs = new Set(AGENT_LANGUAGES.map(l => l.slug))

const enterList = ref<Agent[]>([])
const myList = ref<Agent[]>([])
const sharedList = ref<Agent[]>([])
const courses = ref<CourseItem[]>([])
const { resolveCourseSelection } = useCourseSelect(courses)
const classes = ref<ClassItem[]>([])
const route = useRoute()
const router = useRouter()
const agentStore = useCourseAgentStore()
const auth = useAuthStore()
const isStudentUser = computed(() => auth.user?.role === 'student')
const studentEnrollments = ref<{ course_id: number }[]>([])

async function loadStudentMeta() {
  if (!isStudentUser.value) return
  try {
    const { data } = await http.get<{ course_id: number }[]>('/classes/my')
    studentEnrollments.value = data
  } catch {
    studentEnrollments.value = []
  }
}

function isEnrolledForAgent(agent: Agent) {
  if (!isStudentUser.value || !agent.course_id) return true
  return studentEnrollments.value.some(e => e.course_id === agent.course_id)
}

const isTeacher = computed(() => auth.user?.role === 'teacher')
const activeTab = ref('enter')
const loading = ref(false)
const courseFilter = ref<number | undefined>(undefined)

const dialogVisible = ref(false)
const bindDialogVisible = ref(false)
const adoptersDialogVisible = ref(false)
const adoptersLoading = ref(false)
const adoptersAgentName = ref('')
const adopters = ref<AdopterRow[]>([])
const dialogMode = ref<'create' | 'edit'>('create')
const editingAgent = ref<Agent | null>(null)
const bindClassIds = ref<number[]>([])
const bindSaving = ref(false)
const formSaving = ref(false)
const form = reactive({
  name: '',
  intro: '',
  course_id: null as number | null,
  slug: '',
  status: 'planned',
})

function theme(slug: string) {
  return slugTheme(slug)
}

function statusTag(status: string) {
  return status === 'active' ? { type: 'success' as const, label: '已上线' } : { type: 'info' as const, label: '筹备中' }
}

async function openAdopters(agent: Agent) {
  adoptersAgentName.value = agent.name
  adoptersDialogVisible.value = true
  adoptersLoading.value = true
  adopters.value = []
  try {
    const { data } = await http.get<{
      agent_name: string
      total: number
      items: AdopterRow[]
    }>(`/teacher/agents/${agent.id}/adopters`)
    adoptersAgentName.value = data.agent_name || agent.name
    adopters.value = data.items || []
  } catch {
    adoptersDialogVisible.value = false
  } finally {
    adoptersLoading.value = false
  }
}

async function loadEnter() {
  const { data } = await http.get<Agent[]>('/agents')
  enterList.value = data
}

async function loadMy() {
  const { data } = await http.get<Agent[]>('/teacher/agents')
  myList.value = data
}

const sharedLangFilter = ref<string | undefined>(undefined)

function classOptionLabel(c: ClassItem) {
  return c.course_name ? `${c.name} · ${c.course_name}` : c.name
}

function isClassDisabledForAgent(c: ClassItem) {
  const agent = editingAgent.value
  if (!agent?.course_id || c.course_id == null) return false
  return c.course_id !== agent.course_id
}

const courseFilterOptions = computed(() => {
  if (courses.value.length) return courses.value
  const map = new Map<number, string>()
  for (const a of [...enterList.value, ...myList.value, ...sharedList.value]) {
    if (a.course_id) map.set(a.course_id, a.course_name || `课程${a.course_id}`)
  }
  return [...map.entries()].map(([id, name]) => ({ id, name }))
})

function matchCourseFilter(agent: Agent) {
  if (!courseFilter.value) return true
  return agent.course_id === courseFilter.value
}

const filteredEnterList = computed(() => enterList.value.filter(matchCourseFilter))
const filteredMyList = computed(() => myList.value.filter(matchCourseFilter))
const filteredSharedList = computed(() => sharedList.value.filter(matchCourseFilter))

const myAgentsByCourse = computed(() => {
  const map = new Map<string, Agent[]>()
  for (const a of filteredMyList.value) {
    const key = a.course_name || '未绑定课程'
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(a)
  }
  return [...map.entries()]
})

async function loadShared() {
  const params: Record<string, string> = {}
  if (sharedLangFilter.value) params.slug = sharedLangFilter.value
  const { data } = await http.get<Agent[]>('/teacher/agents/shared', { params })
  sharedList.value = data
}

async function loadMeta() {
  const [c, cl] = await Promise.all([
    http.get<CourseItem[]>('/courses'),
    http.get<ClassItem[]>('/classes/mine'),
  ])
  courses.value = c.data
  classes.value = cl.data
}

async function load() {
  loading.value = true
  try {
    await Promise.allSettled([loadEnter(), loadStudentMeta()])
    if (auth.user?.role === 'teacher') {
      await Promise.allSettled([loadMy(), loadShared(), loadMeta()])
    }
  } finally {
    loading.value = false
  }
}

function openAgent(agent: Agent) {
  agentStore.setAgent(agent)
  if (isTeacher.value || agent.status === 'active') {
    router.push(`/agents/${agent.id}/home`)
  } else {
    router.push(`/agents/${agent.id}`)
  }
}

function openCreate() {
  dialogMode.value = 'create'
  editingAgent.value = null
  form.name = ''
  form.intro = ''
  form.course_id = courses.value[0]?.id ?? null
  form.slug = ''
  form.status = 'planned'
  dialogVisible.value = true
}

function openEdit(agent: Agent) {
  dialogMode.value = 'edit'
  editingAgent.value = agent
  form.name = agent.name
  form.intro = agent.intro
  form.course_id = agent.course_id
  form.slug = agent.slug
  form.status = agent.status
  dialogVisible.value = true
}

function onAgentCourseChange(val: number | string | null | undefined) {
  resolveCourseSelection(val, id => { form.course_id = id })
}

function formatApiDetail(e: any, fallback = '保存失败') {
  const detail = e?.response?.data?.detail
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((x: any) => x?.msg || x?.message || JSON.stringify(x)).join('；') || fallback
  }
  return fallback
}

async function submitForm() {
  if (!form.name.trim()) { ElMessage.warning('请填写名称'); return }
  if (!form.slug.trim()) { ElMessage.warning('请选择编程语言'); return }
  if (form.course_id == null) { ElMessage.warning('请选择或创建课程'); return }
  const payload = {
    name: form.name.trim(),
    intro: form.intro,
    course_id: Number(form.course_id),
    slug: form.slug.trim(),
    status: form.status,
  }
  formSaving.value = true
  try {
    if (dialogMode.value === 'create') {
      await http.post('/teacher/agents', payload, { skipGlobalError: true })
      ElMessage.success('智能体已创建')
    } else if (editingAgent.value) {
      await http.put(`/teacher/agents/${editingAgent.value.id}`, payload, { skipGlobalError: true })
      ElMessage.success('已保存')
    }
    dialogVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(formatApiDetail(e, '保存失败'))
  } finally {
    formSaving.value = false
  }
}

async function submitBind() {
  if (!editingAgent.value) return
  const classIds = bindClassIds.value.map(id => Number(id)).filter(id => Number.isFinite(id))
  if (!classIds.length) {
    const selectable = classes.value.filter(c => !isClassDisabledForAgent(c))
    ElMessage.warning(
      selectable.length
        ? '请至少选择一个班级'
        : '没有可选班级：请先创建与本智能体同课程的班级，或检查课程是否一致',
    )
    return
  }
  bindSaving.value = true
  try {
    await http.put(
      `/teacher/agents/${editingAgent.value.id}/classes`,
      { class_ids: classIds },
      { timeout: 120000 },
    )
    ElMessage.success('班级绑定已更新；资料与题库将后台同步到该班')
    bindDialogVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '绑定失败，请稍后重试')
  } finally {
    bindSaving.value = false
  }
}

async function removeAgent(agent: Agent) {
  await ElMessageBox.confirm(`删除智能体「${agent.name}」？`, '提示', { type: 'warning' })
  await http.delete(`/teacher/agents/${agent.id}`)
  ElMessage.success('已删除')
  await load()
}

async function toggleShare(agent: Agent) {
  const next = !agent.is_shared
  if (next && agent.status !== 'active') {
    ElMessage.warning('仅已上线的智能体可共享，请先将状态改为「已上线」')
    return
  }
  try {
    await http.post(`/teacher/agents/${agent.id}/share`, { is_shared: next })
    ElMessage.success(next ? '已发布到共享广场' : '已取消共享')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

function openBind(agent: Agent) {
  editingAgent.value = agent
  const managedIds = new Set(classes.value.map(c => c.id))
  const prev = (agent.bound_class_ids || []).map(id => Number(id))
  bindClassIds.value = prev.filter(id => managedIds.has(id))
  bindDialogVisible.value = true
  loadMeta().then(() => {
    const ids = new Set(classes.value.map(c => c.id))
    bindClassIds.value = prev.filter(id => ids.has(id))
    if (prev.length && !bindClassIds.value.length) {
      ElMessage.warning('该智能体此前绑定的班级不在您名下，请重新选择')
    }
  })
}

async function adoptAgent(agent: Agent) {
  try {
    await http.post<Agent>(`/teacher/agents/adopt/${agent.id}`, null, {
      timeout: 120000,
    })
    ElMessage.success(
      agent.already_adopted
        ? '该智能体已在您的管理中；请绑定班级后，资料/题库/考核配置会同步到该班'
        : '已加入我的管理，资料库/题库/考核配置已快照。请在「我的管理」中绑定班级后即可使用',
    )
    activeTab.value = 'manage'
    await load()
    const row = myList.value.find(a => a.source_agent_id === agent.id || a.name === agent.name)
    if (row && !(row.bound_class_ids || []).length) {
      ElMessage.info('请先为本智能体绑定班级')
      openBind(row)
    }
  } catch {
    await load()
  }
}

function goToAdopted(agent: Agent) {
  activeTab.value = 'manage'
  const adoptedId = agent.adopted_agent_id
  const row = adoptedId ? myList.value.find(a => a.id === adoptedId) : undefined
  if (row) {
    openBind(row)
  } else {
    ElMessage.info('请刷新页面后在「我的管理」中查看')
    loadMy()
  }
}

function viewSharedAgent(agent: Agent) {
  agentStore.setAgent(agent)
  router.push({ path: `/agents/${agent.id}`, query: { from: 'shared' } })
}

function experienceSharedAgent(agent: Agent) {
  agentStore.setAgent(agent)
  router.push({ path: `/agents/${agent.id}/home`, query: { from: 'shared' } })
}

const classLabel = (ids: number[]) => {
  const managedIds = new Set(classes.value.map(c => c.id))
  return ids.map(id => {
    const cls = classes.value.find(c => c.id === id)
    if (cls) return cls.name
    if (!managedIds.size) return `班级${id}`
    return managedIds.has(id) ? `班级${id}` : `班级${id}(无权限)`
  }).join('、') || '未绑定'
}

watch(
  () => route.query.tab,
  (tab) => {
    if (tab === 'shared' || tab === 'manage' || tab === 'enter') {
      activeTab.value = tab
    }
  },
)

onMounted(() => {
  if (route.query.tab === 'shared') activeTab.value = 'shared'
  else if (route.query.tab === 'manage') activeTab.value = 'manage'
  load()
})
</script>

<template>
  <div class="agent-manage" v-loading="loading">
    <el-card shadow="never" class="header-card">
      <h2 class="page-title">课程智能体</h2>
      <p class="page-desc">
        选择已绑定班级的智能体进入课程；教师可创建私有智能体、绑定班级，或从共享广场采纳他人共享的智能体。
      </p>
    </el-card>

    <el-tabs v-if="isTeacher" v-model="activeTab" style="margin-bottom: 16px">
      <el-tab-pane label="进入课程" name="enter" />
      <el-tab-pane label="我的管理" name="manage" />
      <el-tab-pane label="共享广场" name="shared" />
    </el-tabs>

    <div
      v-if="courseFilterOptions.length || (isTeacher && activeTab === 'manage')"
      class="filter-bar"
    >
      <div class="filter-bar-left">
        <el-select
          v-if="courseFilterOptions.length"
          v-model="courseFilter"
          clearable
          filterable
          placeholder="按课程筛选"
          style="width: 240px"
        >
          <el-option v-for="c in courseFilterOptions" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-select
          v-if="isTeacher && activeTab === 'shared'"
          v-model="sharedLangFilter"
          clearable
          filterable
          placeholder="按语言筛选"
          style="width: 200px"
          @change="loadShared"
        >
          <el-option
            v-for="lang in AGENT_LANGUAGES.filter(l => l.slug !== 'c-lang')"
            :key="lang.slug"
            :label="lang.label"
            :value="lang.slug"
          />
        </el-select>
      </div>
      <el-button
        v-if="isTeacher && activeTab === 'manage'"
        type="primary"
        @click="openCreate"
      >
        创建智能体
      </el-button>
    </div>

    <template v-if="!isTeacher || activeTab === 'enter'">
      <div class="agent-grid">
        <el-card
          v-for="a in filteredEnterList"
          :key="a.id"
          shadow="hover"
          class="agent-card"
          @click="openAgent(a)"
        >
          <div class="agent-card-head" :style="{ background: theme(a.slug).bg }">
            <div class="agent-icon" :style="{ color: theme(a.slug).color }">{{ a.name.charAt(0) }}</div>
            <el-tag :type="statusTag(a.status).type" size="small">{{ statusTag(a.status).label }}</el-tag>
          </div>
          <h3>{{ a.name }}</h3>
          <p class="agent-intro">{{ a.intro || '暂无介绍' }}</p>
          <div class="agent-meta">
            <span v-if="a.course_name" class="course-name">{{ a.course_name }}</span>
            <span v-if="a.owner_name" class="owner-tag">· {{ a.owner_name }}</span>
            <el-tag v-if="a.is_adopted" size="small" type="warning" style="margin-left: 4px">已采纳</el-tag>
            <el-tag
              v-if="isStudentUser && !isEnrolledForAgent(a)"
              size="small"
              type="danger"
              style="margin-left: 4px"
            >未加入班级</el-tag>
          </div>
          <span class="enter-hint">进入课程 →</span>
        </el-card>
      </div>
      <el-empty
        v-if="!filteredEnterList.length"
        :description="courseFilter ? '当前课程下暂无可进入的智能体' : '暂无可进入的课程智能体'"
      />
    </template>

    <template v-else-if="activeTab === 'manage'">
      <div v-for="[courseName, agents] in myAgentsByCourse" :key="courseName" class="course-group">
        <h4 class="course-group-title">{{ courseName }}</h4>
        <el-table :data="agents" border>
        <el-table-column label="名称" prop="name" />
        <el-table-column label="课程" prop="course_name" width="200" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status).type" size="small">{{ statusTag(row.status).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="班级" min-width="160">
          <template #default="{ row }">{{ classLabel(row.bound_class_ids || []) }}</template>
        </el-table-column>
        <el-table-column label="共享" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_shared ? 'success' : 'info'" size="small">{{ row.is_shared ? '是' : '否' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="采纳" width="90">
          <template #default="{ row }">
            <el-button
              v-if="(row.adopter_count || 0) > 0 || row.is_shared"
              text
              type="primary"
              @click="openAdopters(row)"
            >{{ row.adopter_count || 0 }} 人</el-button>
            <span v-else style="color: #c0c4cc">—</span>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.is_adopted" size="small" type="warning">采纳</el-tag>
            <span v-else>自建</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="openAgent(row)">进入</el-button>
            <el-button text @click="openEdit(row)">编辑</el-button>
            <el-button text @click="openBind(row)">绑定班级</el-button>
            <el-button
              text
              :disabled="row.status !== 'active' && !row.is_shared"
              @click="toggleShare(row)"
            >{{ row.is_shared ? '取消共享' : '共享' }}</el-button>
            <el-button text type="danger" @click="removeAgent(row)">删除</el-button>
          </template>
        </el-table-column>
        </el-table>
      </div>
      <el-empty
        v-if="!filteredMyList.length"
        :description="courseFilter ? '当前课程下暂无智能体' : '尚未创建智能体，可从共享广场采纳或点击上方创建'"
      />
    </template>

    <template v-else>
      <div class="agent-grid">
        <el-card v-for="a in filteredSharedList" :key="a.id" shadow="hover" class="agent-card">
          <div class="agent-card-head" :style="{ background: theme(a.slug).bg }">
            <div class="agent-icon" :style="{ color: theme(a.slug).color }">{{ a.name.charAt(0) }}</div>
            <div style="display: flex; gap: 4px; flex-wrap: wrap">
              <el-tag type="success" size="small">共享</el-tag>
              <el-tag v-if="a.is_owner" size="small" type="warning">我的</el-tag>
            </div>
          </div>
          <h3>{{ a.name }}</h3>
          <p class="agent-intro">{{ a.intro || '暂无介绍' }}</p>
          <p class="shared-hint">含共享资料库、题库与考核配置</p>
          <div class="agent-meta">
            <el-tag size="small" type="info">{{ slugLabel(a.slug) }}</el-tag>
            <span class="course-name">{{ a.course_name || '未绑定课程' }}</span>
            <span class="owner-tag">· {{ a.owner_name }}</span>
            <el-tag
              v-if="a.is_owner && (a.adopter_count || 0) > 0"
              size="small"
              type="warning"
              style="margin-left: 4px"
            >已采纳 {{ a.adopter_count }}</el-tag>
          </div>
          <div class="shared-card-actions">
            <el-button text type="primary" size="small" @click="viewSharedAgent(a)">查看详情</el-button>
            <el-button text type="success" size="small" @click="experienceSharedAgent(a)">体验功能</el-button>
            <el-button
              v-if="a.is_owner"
              text
              type="warning"
              size="small"
              @click="openAdopters(a)"
            >使用情况</el-button>
            <el-button
              type="primary"
              size="small"
              :disabled="a.is_owner"
              @click="a.already_adopted ? goToAdopted(a) : adoptAgent(a)"
            >{{ a.is_owner ? '我的智能体' : a.already_adopted ? '已加入管理' : '加入我的管理' }}</el-button>
          </div>
        </el-card>
      </div>
      <el-empty
        v-if="!filteredSharedList.length"
        :description="courseFilter || sharedLangFilter ? '当前筛选条件下暂无智能体' : '共享广场暂无智能体'"
      />
    </template>

    <el-dialog v-model="dialogVisible" :title="dialogMode === 'create' ? '创建智能体' : '编辑智能体'" width="520px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="介绍"><el-input v-model="form.intro" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="课程" required>
          <el-select
            :model-value="form.course_id"
            filterable
            allow-create
            default-first-option
            clearable
            placeholder="选择或输入课程名（必填）"
            style="width: 100%"
            @update:model-value="onAgentCourseChange"
          >
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <div class="form-tip">可直接输入新课程名创建；智能体将按课程分类管理</div>
        </el-form-item>
        <el-form-item label="语言" required>
          <el-select
            v-model="form.slug"
            filterable
            placeholder="选择编程语言"
            style="width: 100%"
          >
            <el-option
              v-if="form.slug && !languageSlugs.has(form.slug)"
              :key="'legacy-' + form.slug"
              :label="`${form.slug}（当前）`"
              :value="form.slug"
            />
            <el-option
              v-for="lang in AGENT_LANGUAGES.filter(l => l.slug !== 'c-lang' || form.slug === 'c-lang')"
              :key="lang.slug"
              :label="lang.label"
              :value="lang.slug"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="筹备中" value="planned" />
            <el-option label="已上线" value="active" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="formSaving" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="bindDialogVisible" title="绑定班级" width="480px">
      <p style="color: #666; margin: 0 0 12px">绑定后，该班学生与助教可见并使用此智能体。列表包含您名下全部班级；与智能体课程不一致的班级不可选。</p>
      <el-select v-model="bindClassIds" multiple collapse-tags style="width: 100%" placeholder="选择班级">
        <el-option
          v-for="c in classes"
          :key="c.id"
          :label="classOptionLabel(c)"
          :value="c.id"
          :disabled="isClassDisabledForAgent(c)"
        />
      </el-select>
      <template #footer>
        <el-button @click="bindDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="bindSaving" @click="submitBind">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="adoptersDialogVisible"
      :title="`使用情况 · ${adoptersAgentName}`"
      width="720px"
    >
      <p style="color: #666; margin: 0 0 12px; font-size: 13px">
        以下教师已从共享广场采纳本智能体（副本归对方所有；可查看其绑定班级情况）。
      </p>
      <el-table :data="adopters" v-loading="adoptersLoading" border size="small">
        <el-table-column label="教师" min-width="140">
          <template #default="{ row }">
            {{ row.display_name }}
            <div style="color: #909399; font-size: 12px">{{ row.username }}</div>
          </template>
        </el-table-column>
        <el-table-column label="副本状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status).type" size="small">{{ statusTag(row.status).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="已绑定班级" min-width="200">
          <template #default="{ row }">
            {{ row.bound_class_names?.length ? row.bound_class_names.join('、') : '尚未绑定' }}
          </template>
        </el-table-column>
        <el-table-column label="快照时间" width="170">
          <template #default="{ row }">
            {{ row.snapshot_at ? row.snapshot_at.replace('T', ' ').slice(0, 19) : '—' }}
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!adoptersLoading && !adopters.length" description="暂无人采纳" />
      <template #footer>
        <el-button type="primary" @click="adoptersDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.agent-manage {
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.header-card {
  margin-bottom: 14px;
  flex-shrink: 0;
  background: linear-gradient(135deg, #f5f7fa 0%, #fff 70%);
  border: 1px solid #ebeef5;
}
.header-card :deep(.el-card__body) {
  padding: 16px 20px;
}
.page-title { margin: 0 0 6px; font-size: 20px; font-weight: 600; }
.page-desc { margin: 0; color: #606266; line-height: 1.55; font-size: 13px; }
.filter-bar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  flex-shrink: 0;
}
.filter-bar-left { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.agent-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  align-items: stretch;
}
.agent-card {
  cursor: pointer;
  margin-bottom: 0;
  transition: transform 0.15s;
  height: 100%;
  border: 1px solid #ebeef5;
}
.agent-card:hover { transform: translateY(-2px); }
.agent-card :deep(.el-card__body) {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 0 16px 16px;
}
.agent-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 0 -16px 12px;
  padding: 14px 16px;
  border-radius: 4px 4px 0 0;
}
.agent-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
}
.agent-card h3 {
  margin: 0 0 8px;
  font-size: 16px;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.agent-intro {
  color: #606266;
  font-size: 13px;
  line-height: 1.55;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: calc(1.55em * 3);
  flex: 1;
}
.agent-meta {
  margin-top: 10px;
  font-size: 12px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 0;
}
.course-name { color: #409eff; }
.owner-tag { color: #909399; }
.enter-hint {
  display: inline-block;
  margin-top: auto;
  padding-top: 12px;
  font-size: 13px;
  color: #409eff;
}
.course-group { margin-bottom: 20px; }
.course-group-title {
  margin: 0 0 10px;
  font-size: 14px;
  font-weight: 600;
  color: #606266;
}
.shared-hint { margin: 0 0 8px; font-size: 12px; color: #67c23a; }
.shared-card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: auto;
  padding-top: 12px;
}
.form-tip {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
}
@media (max-width: 1100px) {
  .agent-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 640px) {
  .agent-grid {
    grid-template-columns: 1fr;
  }
}
</style>

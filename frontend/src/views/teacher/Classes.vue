<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { useCourseSelect, type CourseItem } from '@/composables/useCourseSelect'

interface ClassItem {
  id: number
  name: string
  invite_code: string
  course_id: number | null
  course_name: string | null
  student_count: number
  teacher_count: number
  created_at: string | null
}

interface ClassAgent {
  id: number
  name: string
  course_name: string
  status: string
  is_adopted: boolean
  assigned: boolean
  owner_name?: string
  is_mine?: boolean
  editable?: boolean
}

interface Member {
  id: number
  username: string
  display_name: string
}

const classes = ref<ClassItem[]>([])
const selectedId = ref<number | undefined>(undefined)
const students = ref<Member[]>([])
const teachers = ref<Member[]>([])
const loading = ref(false)
const detailLoading = ref(false)
const detailPanelRef = ref<HTMLElement | null>(null)

const createDialog = ref(false)
const createName = ref('')
const createCourseId = ref<number | undefined>(undefined)
const courses = ref<CourseItem[]>([])
const { resolveCourseSelection } = useCourseSelect(courses)
const classAgents = ref<ClassAgent[]>([])
const agentSaving = ref(false)
const selectedAgentIds = ref<number[]>([])
const courseFilter = ref<number | undefined>(undefined)

const filteredClasses = computed(() => {
  if (!courseFilter.value) return classes.value
  return classes.value.filter(c => c.course_id === courseFilter.value)
})
const editDialog = ref(false)
const editName = ref('')
const editingClassId = ref<number | undefined>(undefined)
let detailSeq = 0
let listSeq = 0

const studentDialog = ref(false)
const assistantDialog = ref(false)
const studentCandidates = ref<Member[]>([])
const assistantCandidates = ref<Member[]>([])
const studentKeyword = ref('')
const assistantKeyword = ref('')
const manualStudentUsername = ref('')
const manualAssistantUsername = ref('')
const candidateLoading = ref(false)
const addingStudent = ref(false)
const addingAssistant = ref(false)

/** 仅刷新班级列表，不触碰当前选中状态 */
async function refreshClassList() {
  const seq = ++listSeq
  loading.value = true
  try {
    const { data } = await http.get<ClassItem[]>('/classes/mine')
    if (seq !== listSeq) return
    classes.value = data
    if (!data.length) {
      selectedId.value = undefined
      students.value = []
      teachers.value = []
      return
    }
    if (selectedId.value && !data.some(c => c.id === selectedId.value)) {
      selectedId.value = undefined
      students.value = []
      teachers.value = []
    }
  } finally {
    if (seq === listSeq) loading.value = false
  }
}

async function loadClasses() {
  await refreshClassList()
  if (selectedId.value) {
    await loadDetail()
  }
}

async function loadDetail() {
  const classId = selectedId.value
  if (!classId) {
    students.value = []
    teachers.value = []
    classAgents.value = []
    selectedAgentIds.value = []
    detailLoading.value = false
    return
  }
  const seq = ++detailSeq
  students.value = []
  teachers.value = []
  classAgents.value = []
  detailLoading.value = true
  try {
    const [st, te, ag] = await Promise.all([
      http.get<Member[]>(`/classes/${classId}/students`),
      http.get<Member[]>(`/classes/${classId}/teachers`),
      http.get<ClassAgent[]>(`/classes/${classId}/agents`).catch(() => ({ data: [] as ClassAgent[] })),
    ])
    if (seq !== detailSeq || selectedId.value !== classId) return
    students.value = st.data
    teachers.value = te.data
    classAgents.value = ag.data
    selectedAgentIds.value = ag.data.filter(a => a.is_mine !== false && a.assigned).map(a => a.id)
  } catch (e: any) {
    if (seq === detailSeq && selectedId.value === classId) {
      students.value = []
      teachers.value = []
      ElMessage.error(e?.response?.data?.detail || '加载班级详情失败')
    }
  } finally {
    if (seq === detailSeq) {
      detailLoading.value = false
    }
  }
}

async function selectClass(row: ClassItem) {
  selectedId.value = row.id
  await loadDetail()
  await nextTick()
  detailPanelRef.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

function onRowClick(row: ClassItem, _column: unknown, event: Event) {
  const target = event.target as HTMLElement
  if (target.closest('button, .el-button, a')) return
  void selectClass(row)
}

function rowClassName({ row }: { row: ClassItem }) {
  return row.id === selectedId.value ? 'selected-class-row' : ''
}

function filterMembers(list: Member[], keyword: string) {
  const q = keyword.trim().toLowerCase()
  if (!q) return list
  return list.filter(m =>
    m.username.toLowerCase().includes(q) ||
    (m.display_name || '').toLowerCase().includes(q)
  )
}

const filteredStudentCandidates = () => filterMembers(studentCandidates.value, studentKeyword.value)
const filteredAssistantCandidates = () => filterMembers(assistantCandidates.value, assistantKeyword.value)

async function openStudentDialog() {
  if (!selectedId.value) {
    ElMessage.warning('请先选择班级')
    return
  }
  studentDialog.value = true
  studentKeyword.value = ''
  manualStudentUsername.value = ''
  candidateLoading.value = true
  try {
    const { data } = await http.get<Member[]>(`/classes/${selectedId.value}/students/available`)
    studentCandidates.value = data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载可添加学生失败')
    studentDialog.value = false
  } finally {
    candidateLoading.value = false
  }
}

async function openAssistantDialog() {
  if (!selectedId.value) {
    ElMessage.warning('请先选择班级')
    return
  }
  assistantDialog.value = true
  assistantKeyword.value = ''
  manualAssistantUsername.value = ''
  candidateLoading.value = true
  try {
    const { data } = await http.get<Member[]>(`/classes/${selectedId.value}/teachers/available`)
    assistantCandidates.value = data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载可添加助教失败')
    assistantDialog.value = false
  } finally {
    candidateLoading.value = false
  }
}

async function submitAddStudent(username?: string) {
  if (!selectedId.value) return
  const name = (username || manualStudentUsername.value).trim()
  if (!name) {
    ElMessage.warning('请选择学生或输入用户名')
    return
  }
  addingStudent.value = true
  try {
    await http.post(`/classes/${selectedId.value}/students`, { username: name })
    ElMessage.success('学生已添加')
    studentDialog.value = false
    manualStudentUsername.value = ''
    await loadDetail()
    await loadClasses()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '添加失败')
  } finally {
    addingStudent.value = false
  }
}

async function submitAddAssistant(username?: string) {
  if (!selectedId.value) return
  const name = (username || manualAssistantUsername.value).trim()
  if (!name) {
    ElMessage.warning('请选择助教或输入用户名')
    return
  }
  addingAssistant.value = true
  try {
    await http.post(`/classes/${selectedId.value}/teachers`, { username: name })
    ElMessage.success('助教已添加')
    assistantDialog.value = false
    manualAssistantUsername.value = ''
    await loadDetail()
    await loadClasses()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '添加失败')
  } finally {
    addingAssistant.value = false
  }
}

function onCreateCourseChange(val: number | string | null | undefined) {
  resolveCourseSelection(val, id => { createCourseId.value = id ?? undefined })
}

async function createClass() {
  const name = createName.value.trim()
  if (!name) {
    ElMessage.warning('请输入班级名称')
    return
  }
  if (!createCourseId.value) {
    ElMessage.warning('请选择课程')
    return
  }
  try {
    const { data } = await http.post<ClassItem>('/classes', {
      name,
      course_id: createCourseId.value,
    })
    ElMessage.success('班级已创建')
    createDialog.value = false
    createName.value = ''
    createCourseId.value = undefined
    await loadClasses()
    selectedId.value = data.id
    await nextTick()
    await loadDetail()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

async function saveClassAgents() {
  if (!selectedId.value) return
  agentSaving.value = true
  try {
    await http.put(`/classes/${selectedId.value}/agents`, {
      agent_ids: selectedAgentIds.value,
    })
    ElMessage.success('智能体分配已保存')
    await loadDetail()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    agentSaving.value = false
  }
}

async function loadCourses() {
  try {
    const { data } = await http.get<CourseItem[]>('/courses')
    courses.value = data
  } catch {
    courses.value = []
  }
}

async function updateClass() {
  if (!editingClassId.value) return
  const name = editName.value.trim()
  if (!name) return
  try {
    await http.put(`/classes/${editingClassId.value}`, { name })
    ElMessage.success('已更新')
    editDialog.value = false
    editingClassId.value = undefined
    await loadClasses()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '更新失败')
  }
}

function openEdit(row: ClassItem) {
  editingClassId.value = row.id
  editName.value = row.name
  editDialog.value = true
}

async function deleteClass(row: ClassItem) {
  await ElMessageBox.confirm(`确定删除班级「${row.name}」吗？学生将被移出班级。`, '警告', { type: 'warning' })
  try {
    await http.delete(`/classes/${row.id}`)
    ElMessage.success('已删除')
    if (selectedId.value === row.id) {
      selectedId.value = undefined
      students.value = []
      teachers.value = []
    }
    await loadClasses()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

async function copyCode(code: string) {
  try {
    await navigator.clipboard.writeText(code)
    ElMessage.success('邀请码已复制')
  } catch {
    ElMessage.info(`邀请码：${code}`)
  }
}

async function regenerateCode() {
  if (!selectedId.value) return
  await ElMessageBox.confirm('刷新后旧邀请码将失效，确定继续？', '提示')
  try {
    const { data } = await http.post(`/classes/${selectedId.value}/regenerate-code`)
    ElMessage.success(`新邀请码：${data.invite_code}`)
    await loadClasses()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '刷新失败')
  }
}

async function removeStudent(row: Member) {
  if (!selectedId.value) return
  await ElMessageBox.confirm(`确定将 ${row.display_name || row.username} 移出班级？`, '提示')
  try {
    await http.delete(`/classes/${selectedId.value}/students/${row.id}`)
    ElMessage.success('已移除')
    await loadDetail()
    await loadClasses()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '移除失败')
  }
}

async function removeTeacher(row: Member) {
  if (!selectedId.value) return
  await ElMessageBox.confirm(`确定移除助教 ${row.display_name || row.username}？`, '提示')
  try {
    await http.delete(`/classes/${selectedId.value}/teachers/${row.id}`)
    ElMessage.success('已移除')
    await loadDetail()
    await loadClasses()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '移除失败')
  }
}

const selectedClass = () => classes.value.find(c => c.id === selectedId.value)

onMounted(() => {
  void loadCourses()
  void refreshClassList()
})
</script>

<template>
  <div class="classes-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>班级管理</span>
          <el-button type="primary" size="small" @click="createDialog = true; loadCourses()">创建班级</el-button>
        </div>
      </template>

      <el-select
        v-model="courseFilter"
        clearable
        placeholder="按课程筛选"
        style="width: 220px; margin-bottom: 12px"
      >
        <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>

      <el-table
        :data="filteredClasses"
        row-key="id"
        size="small"
        border
        class="class-table"
        v-loading="loading"
        :row-class-name="rowClassName"
        @row-click="onRowClick"
      >
        <el-table-column label="班级" prop="name" min-width="160" class-name="clickable-cell" />
        <el-table-column label="课程" prop="course_name" min-width="140" class-name="clickable-cell" />
        <el-table-column label="学生数" prop="student_count" width="80" align="center" class-name="clickable-cell" />
        <el-table-column label="教师数" prop="teacher_count" width="80" align="center" class-name="clickable-cell" />
        <el-table-column label="邀请码（点击即可复制）" width="160" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="copyCode(row.invite_code)">
              {{ row.invite_code }}
            </el-button>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openEdit(row)">编辑名称</el-button>
            <el-button link type="danger" @click.stop="deleteClass(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <div v-if="selectedId" ref="detailPanelRef" class="detail-card-wrap">
      <el-card
        :key="selectedId"
        shadow="never"
        v-loading="detailLoading"
        class="detail-card"
      >
      <template #header>
        <div class="card-header">
          <span>{{ selectedClass()?.name || '班级详情' }}</span>
          <el-button size="small" @click="regenerateCode">刷新邀请码</el-button>
        </div>
      </template>

      <section class="detail-section">
        <div class="section-header">
          <h4>学生管理</h4>
          <el-button size="small" type="primary" @click="openStudentDialog">添加学生</el-button>
        </div>
        <el-table :data="students" size="small" border>
          <el-table-column label="用户名" prop="username" />
          <el-table-column label="姓名" prop="display_name" />
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-button link type="danger" @click="removeStudent(row)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="detail-section">
        <div class="section-header">
          <h4>课程智能体</h4>
          <el-button
            size="small"
            type="primary"
            :loading="agentSaving"
            :disabled="!classAgents.length"
            @click="saveClassAgents"
          >
            保存分配
          </el-button>
        </div>
        <p v-if="!selectedClass()?.course_id" class="hint-text">
          该班级尚未绑定课程，无法分配智能体。
        </p>
        <el-checkbox-group
          v-else
          v-model="selectedAgentIds"
          class="agent-check-group"
        >
          <el-checkbox
            v-for="a in classAgents.filter(x => x.is_mine !== false)"
            :key="a.id"
            :label="a.id"
            :value="a.id"
          >
            {{ a.name }}
            <el-tag v-if="a.is_adopted" size="small" type="info" style="margin-left: 6px">采纳</el-tag>
            <el-tag v-if="a.status !== 'active'" size="small" type="warning" style="margin-left: 6px">未上线</el-tag>
          </el-checkbox>
          <div
            v-for="a in classAgents.filter(x => x.is_mine === false)"
            :key="'other-' + a.id"
            class="other-agent-row"
          >
            <el-tag type="info" size="small">{{ a.name }}</el-tag>
            <span class="other-agent-owner">（{{ a.owner_name }} 已分配）</span>
          </div>
        </el-checkbox-group>
        <el-empty
          v-if="selectedClass()?.course_id && !classAgents.length"
          description="您暂无该课程可分配的智能体（需拥有或从共享广场采纳）"
          :image-size="60"
        />
      </section>

      <section class="detail-section">
        <div class="section-header">
          <h4>助教管理</h4>
          <el-button size="small" type="primary" @click="openAssistantDialog">添加助教</el-button>
        </div>
        <el-table :data="teachers" size="small" border>
          <el-table-column label="用户名" prop="username" />
          <el-table-column label="姓名" prop="display_name" />
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-button link type="danger" @click="removeTeacher(row)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
      </el-card>
    </div>

    <el-card v-else shadow="never" class="detail-card">
      <el-empty description="请点击上方班级列表中的某一行，查看该班级的学生与助教管理" />
    </el-card>
  </div>

  <el-dialog v-model="createDialog" title="创建班级" width="420px">
    <el-form label-width="72px">
      <el-form-item label="课程" required>
        <el-select
          :model-value="createCourseId"
          filterable
          allow-create
          default-first-option
          clearable
          placeholder="选择已有课程，或直接输入新课程名称"
          style="width: 100%"
          @update:model-value="onCreateCourseChange"
        >
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="班级名" required>
        <el-input v-model="createName" placeholder="如 2025软院C语言1班" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="createDialog = false">取消</el-button>
      <el-button type="primary" @click="createClass">创建</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="studentDialog" title="添加学生" width="520px">
    <el-input
      v-model="studentKeyword"
      placeholder="搜索用户名或姓名"
      clearable
      style="margin-bottom: 12px"
    />
    <el-table
      :data="filteredStudentCandidates()"
      v-loading="candidateLoading"
      size="small"
      border
      max-height="280"
      empty-text="暂无可添加的学生（已在该课程其他班级中的学生不可重复添加）"
    >
      <el-table-column label="用户名" prop="username" />
      <el-table-column label="姓名" prop="display_name" />
      <el-table-column label="操作" width="80" align="center">
        <template #default="{ row }">
          <el-button link type="primary" :loading="addingStudent" @click="submitAddStudent(row.username)">
            添加
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="manual-add">
      <span>或输入用户名：</span>
      <el-input
        v-model="manualStudentUsername"
        placeholder="学生用户名"
        style="width: 200px"
        @keyup.enter="submitAddStudent()"
      />
      <el-button type="primary" :loading="addingStudent" @click="submitAddStudent()">确认添加</el-button>
    </div>
  </el-dialog>

  <el-dialog v-model="assistantDialog" title="添加助教" width="520px">
    <el-input
      v-model="assistantKeyword"
      placeholder="搜索用户名或姓名"
      clearable
      style="margin-bottom: 12px"
    />
    <el-table
      :data="filteredAssistantCandidates()"
      v-loading="candidateLoading"
      size="small"
      border
      max-height="280"
      empty-text="暂无可添加的助教（尚未管理本班的教师/管理员）"
    >
      <el-table-column label="用户名" prop="username" />
      <el-table-column label="姓名" prop="display_name" />
      <el-table-column label="操作" width="80" align="center">
        <template #default="{ row }">
          <el-button link type="primary" :loading="addingAssistant" @click="submitAddAssistant(row.username)">
            添加
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="manual-add">
      <span>或输入用户名：</span>
      <el-input
        v-model="manualAssistantUsername"
        placeholder="助教用户名"
        style="width: 200px"
        @keyup.enter="submitAddAssistant()"
      />
      <el-button type="primary" :loading="addingAssistant" @click="submitAddAssistant()">确认添加</el-button>
    </div>
  </el-dialog>

  <el-dialog v-model="editDialog" title="编辑班级" width="400px">
    <el-input v-model="editName" placeholder="班级名称" />
    <template #footer>
      <el-button @click="editDialog = false">取消</el-button>
      <el-button type="primary" @click="updateClass">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.classes-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.detail-card-wrap {
  width: 100%;
}

.detail-card {
  width: 100%;
}

.class-table :deep(.el-table__row) {
  cursor: pointer;
}

.class-table :deep(.selected-class-row > td.el-table__cell) {
  background-color: var(--el-table-current-row-bg-color, #ecf5ff) !important;
}

.detail-section + .detail-section {
  margin-top: 20px;
}

.detail-section h4 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.manual-add {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  flex-wrap: wrap;
}

.hint-text {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.agent-check-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.other-agent-row {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  padding-left: 4px;
}

.other-agent-owner {
  margin-left: 6px;
}
</style>

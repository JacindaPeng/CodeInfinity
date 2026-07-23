<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api'
import { useCourseAgentStore } from '@/stores/courseAgent'
import { useAgentCourseScope } from '@/composables/useAgentCourseScope'
import { useAgentBoundClasses } from '@/composables/useAgentBoundClasses'

interface ExamRecordRow {
  id: number
  user_id: number
  username: string
  display_name: string
  chapter_id: number
  chapter_title: string
  status: string
  total_score: number | null
  has_report: boolean
  started_at: string | null
  submitted_at: string | null
}
interface Chapter { id: number; title: string }
interface ClassItem { id: number; name: string }
interface CourseItem { id: number; name: string }

const agentStore = useCourseAgentStore()
const { lockedCourse, applyLockedCourse, chapterListParams } = useAgentCourseScope()
const { loadScopedClasses, pickClassId } = useAgentBoundClasses()
const route = useRoute()
const router = useRouter()
const isAdminMode = computed(() => route.path.includes('/admin/'))

const list = ref<ExamRecordRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)

const chapters = ref<Chapter[]>([])
const courses = ref<CourseItem[]>([])
const selectedCourseId = ref<number | undefined>(undefined)
const classes = ref<ClassItem[]>([])
const filterClass = ref<number | undefined>(undefined)
const filterChapter = ref<number | undefined>(undefined)

async function loadFilters() {
  if (!applyLockedCourse(selectedCourseId, courses)) {
    const { data: courseData } = await http.get<CourseItem[]>('/courses')
    courses.value = courseData
    if (!selectedCourseId.value) {
      selectedCourseId.value = courseData[0]?.id
    }
  }
  const params = chapterListParams()
  if (!params.course_id && selectedCourseId.value) params.course_id = selectedCourseId.value
  const ch = await http.get<Chapter[]>('/chapters', { params })
  chapters.value = ch.data
  if (isAdminMode.value) {
    const cls = await http.get<ClassItem[]>('/admin/classes')
    classes.value = cls.data
  } else {
    classes.value = await loadScopedClasses()
    filterClass.value = pickClassId(classes.value, filterClass.value)
  }
}

function onCourseChange() {
  filterChapter.value = undefined
  loadFilters().then(() => onFilter())
}

function onClassChange() {
  onFilter()
}

async function load() {
  loading.value = true
  try {
    const url = isAdminMode.value ? '/admin/exams' : '/exams/teacher/all'
    const { data } = await http.get(url, {
      params: {
        page: page.value, size: size.value,
        class_id: filterClass.value || undefined,
        chapter_id: filterChapter.value || undefined,
        agent_id: agentStore.current?.id || undefined,
      },
    })
    list.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function onPage(p: number) { page.value = p; load() }
function onFilter() { page.value = 1; load() }

function viewReport(row: ExamRecordRow) {
  const prefix = isAdminMode.value ? '/admin/exams' : '/teacher/exams'
  router.push(`${prefix}/${row.id}/report`)
}

const scoreColor = (s: number | null) => {
  if (s === null) return ''
  if (s >= 80) return '#67c23a'
  if (s >= 60) return '#e6a23c'
  return '#f56c6c'
}

onMounted(async () => {
  await agentStore.restoreAgent()
  await loadFilters()
  await load()
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>{{ isAdminMode ? '全站考核记录' : '学生考核记录' }}</span>
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
          <el-select v-model="filterClass" placeholder="按班级筛选" clearable @change="onClassChange" style="width: 180px; margin-right: 8px">
            <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-select v-model="filterChapter" placeholder="按章节筛选" clearable @change="onFilter" style="width: 200px">
            <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
        </div>
      </div>
    </template>

    <el-table :data="list" v-loading="loading" border size="small">
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="学生" width="120">
        <template #default="{ row }">{{ row.display_name || row.username }}</template>
      </el-table-column>
      <el-table-column label="章节" prop="chapter_title" show-overflow-tooltip />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'submitted' ? 'success' : 'warning'" size="small">
            {{ row.status === 'submitted' ? '已提交' : '进行中' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="总分" width="100">
        <template #default="{ row }">
          <span v-if="row.total_score !== null" :style="{ color: scoreColor(row.total_score), fontWeight: 600 }">
            {{ row.total_score }}
          </span>
          <span v-else style="color: #ccc">—</span>
        </template>
      </el-table-column>
      <el-table-column label="提交时间" prop="submitted_at" width="180" />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button v-if="row.has_report" text type="primary" @click="viewReport(row)">查看报告</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      style="margin-top: 12px; justify-content: flex-end; display: flex"
      v-model:current-page="page"
      :page-size="size"
      :total="total"
      layout="prev, pager, next, total"
      @current-change="onPage"
    />
  </el-card>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { MenuInstance } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useCourseAgentStore, isAgentSharedPreview } from '@/stores/courseAgent'
import http from '@/api'

interface MenuItem {
  index: string
  title: string
  icon: string
  disabled?: boolean
}

const auth = useAuthStore()
const agentStore = useCourseAgentStore()
const route = useRoute()
const router = useRouter()

const isAdmin = computed(() => auth.user?.role === 'admin')
const isTeacher = computed(() => auth.user?.role === 'teacher')
const isStudent = computed(() => auth.user?.role === 'student')

interface StudentEnrollment {
  class_id: number
  class_name: string
  course_id: number
  course_name: string
}

const studentEnrollments = ref<StudentEnrollment[]>([])
const studentAgents = ref<{ id: number; course_id: number | null; name: string; status: string }[]>([])
const unreadPushCount = ref(0)

async function loadUnreadPush() {
  if (!isStudent.value) {
    unreadPushCount.value = 0
    return
  }
  try {
    const { data } = await http.get<{ count: number }>('/knowledge-push/unread-count')
    unreadPushCount.value = data.count || 0
  } catch {
    unreadPushCount.value = 0
  }
}

async function loadStudentNav() {
  if (!isStudent.value) return
  try {
    const [en, ag] = await Promise.all([
      http.get<StudentEnrollment[]>('/classes/my'),
      http.get<{ id: number; course_id: number | null; name: string; status: string }[]>('/agents'),
    ])
    studentEnrollments.value = en.data
    studentAgents.value = ag.data
  } catch {
    studentEnrollments.value = []
    studentAgents.value = []
  }
}

function switchStudentCourse(courseId: number) {
  const agent = studentAgents.value.find(a => a.course_id === courseId && a.status === 'active')
  if (!agent) return
  agentStore.setAgent(agent as any)
  router.push(`/agents/${agent.id}/home`)
}

const studentCourseOptions = computed(() =>
  studentEnrollments.value.map(e => ({
    course_id: e.course_id,
    label: `${e.course_name} · ${e.class_name}`,
  }))
)

const roleLabel = computed(() => {
  const r = auth.user?.role
  if (r === 'admin') return '系统管理员'
  if (r === 'teacher') return '教师'
  if (r === 'student') return '学生'
  return r || ''
})

/** 平台级页面：不展示课程智能体专属侧边栏 */
function isGlobalRoute(path: string) {
  if (path === '/agents' || path === '/admin/agents') return true
  if (/^\/agents\/\d+$/.test(path)) return true
  const globalPrefixes = [
    '/home', '/chat', '/my-class', '/knowledge-push', '/llm-config', '/admin', '/logs', '/teacher/classes',
  ]
  return globalPrefixes.some(p => path === p || path.startsWith(p + '/'))
}

const inCourseContext = computed(() => {
  if (isAdmin.value) return false
  return !!agentStore.current && !isGlobalRoute(route.path)
})

const sidebarTitle = computed(() => {
  if (inCourseContext.value && agentStore.current) {
    return agentStore.current.name
  }
  return 'CodeInfinity'
})

const globalMenus = computed<MenuItem[]>(() => [
  { index: '/home', title: '首页', icon: 'HomeFilled' },
  ...(!isAdmin.value
    ? [{ index: '/chat', title: '大模型对话', icon: 'ChatDotRound' }]
    : []),
  ...(isAdmin.value
    ? [{ index: '/admin/agents', title: '智能体管理', icon: 'Cpu' }]
    : [{ index: '/agents', title: '课程智能体', icon: 'Cpu' }]),
  ...(isStudent.value
    ? [
        { index: '/my-class', title: '我的班级', icon: 'User' },
        { index: '/knowledge-push', title: '知识推送', icon: 'Bell' },
      ]
    : []),
  ...(isAdmin.value
    ? [
        { index: '/admin/users', title: '用户管理', icon: 'UserFilled' },
        { index: '/llm-config', title: '大模型配置', icon: 'Setting' },
        { index: '/admin/exam-records', title: '全站考核记录', icon: 'DataAnalysis' },
        { index: '/admin/knowledge-push', title: '知识推送记录', icon: 'Bell' },
        { index: '/admin/ai-feedback', title: 'AI反馈监控', icon: 'TrendCharts' },
        { index: '/admin/logs', title: '全站调用日志', icon: 'List' },
      ]
    : []),
  ...(isTeacher.value
    ? [
        { index: '/teacher/classes', title: '班级管理', icon: 'UserFilled' },
        { index: '/logs', title: '调用日志', icon: 'List' },
      ]
    : []),
])

const courseMenus = computed<MenuItem[]>(() => {
  const agent = agentStore.current
  if (!agent) return []
  const active = agent.status === 'active'
  const sharedPreview = isTeacher.value && isAgentSharedPreview(agent)
  const homePath = `/agents/${agent.id}/home`
  const items: MenuItem[] = [
    { index: homePath, title: '首页', icon: 'HomeFilled' },
  ]
  if (!isAdmin.value) {
    items.push(
      { index: '/course-qa', title: '课程问答', icon: 'Reading', disabled: !active },
      { index: '/class-chat', title: '课程群聊', icon: 'ChatLineRound', disabled: !active },
      { index: '/chapters', title: '章节学习路线', icon: 'Guide', disabled: !active },
    )
  }
  if (isTeacher.value) {
    items.push({
      index: '/teacher/materials',
      title: sharedPreview ? '共享资料库' : '资料管理',
      icon: 'FolderOpened',
    })
    if (active) {
      items.push(
        {
          index: '/teacher/exam-config',
          title: sharedPreview ? '共享考核配置' : '考核配置',
          icon: 'Document',
        },
        {
          index: '/teacher/question-bank',
          title: sharedPreview ? '共享题库' : '题库管理',
          icon: 'Tickets',
        },
      )
      if (!sharedPreview) {
        items.push(
          { index: '/teacher/exam-records', title: '考核记录', icon: 'DataAnalysis' },
          { index: '/teacher/exam-interventions', title: '判卷介入', icon: 'Bell' },
        )
      }
    }
  }
  items.push({
    index: '__back_agents__',
    title: sharedPreview ? '返回共享广场' : '返回课程智能体',
    icon: 'ArrowLeft',
  })
  return items
})

const menus = computed(() => (inCourseContext.value ? courseMenus.value : globalMenus.value))

const activeMenu = computed(() => {
  const p = route.path
  if (p.match(/^\/agents\/\d+\/home/)) return p
  if (p.startsWith('/teacher/exams/')) return '/teacher/exam-records'
  if (p.startsWith('/teacher/exam-interventions')) return '/teacher/exam-interventions'
  if (p.startsWith('/admin/exams/')) return '/admin/exam-records'
  if (p.startsWith('/exams/')) {
    return inCourseContext.value ? '/chapters' : '/home'
  }
  return p
})

const headerTitle = computed(() => {
  if (route.meta.title) return route.meta.title as string
  if (inCourseContext.value && agentStore.current) {
    return agentStore.current.course_name || agentStore.current.name
  }
  return 'CodeInfinity'
})

const menuRef = ref<MenuInstance>()

function go(idx: string) {
  if (idx === '__back_agents__') {
    const sharedPreview = isTeacher.value && isAgentSharedPreview(agentStore.current)
    agentStore.clearAgent()
    router.push({ path: '/agents', query: { tab: sharedPreview ? 'shared' : 'manage' } })
    return
  }
  if (route.path !== idx) {
    const sharedPreview = isTeacher.value && isAgentSharedPreview(agentStore.current)
    if (sharedPreview) {
      router.push({ path: idx, query: { from: 'shared' } })
    } else {
      router.push(idx)
    }
  }
}

onMounted(() => {
  if (!isGlobalRoute(route.path)) {
    agentStore.restoreAgent()
  }
  void loadStudentNav()
  void loadUnreadPush()
  window.addEventListener('knowledge-push-changed', loadUnreadPush)
})

onUnmounted(() => {
  window.removeEventListener('knowledge-push-changed', loadUnreadPush)
})

watch(
  () => auth.user?.id,
  () => {
    void loadStudentNav()
    void loadUnreadPush()
  },
)

watch(
  () => [route.path, agentStore.current?.id],
  () => { void loadUnreadPush() },
)

watch(
  () => route.path,
  (path) => {
    if (!isGlobalRoute(path) && !agentStore.current) {
      agentStore.restoreAgent()
    }
  },
)

watch(activeMenu, (idx) => {
  menuRef.value?.updateActiveIndex(idx)
})
</script>

<template>
  <el-container class="app-layout">
    <el-aside width="220px" class="app-aside">
      <div class="menu-title">{{ sidebarTitle }}</div>
      <el-menu
        ref="menuRef"
        :key="String(inCourseContext)"
        :default-active="activeMenu"
        background-color="#001529"
        text-color="#bfcbd9"
        active-text-color="#409eff"
        @select="go"
      >
        <el-menu-item
          v-for="m in menus"
          :key="m.index"
          :index="m.index"
          :disabled="m.disabled"
        >
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="app-header">
        <div>{{ headerTitle }}</div>
        <div>
          <el-select
            v-if="isStudent && studentCourseOptions.length > 1 && !inCourseContext"
            :model-value="agentStore.current?.course_id"
            placeholder="切换课程"
            style="width: 200px; margin-right: 8px"
            @change="switchStudentCourse"
          >
            <el-option
              v-for="o in studentCourseOptions"
              :key="o.course_id"
              :label="o.label"
              :value="o.course_id"
            />
          </el-select>
          <el-badge
            v-if="isStudent"
            :value="unreadPushCount"
            :hidden="!unreadPushCount"
            style="margin-right: 12px"
          >
            <el-button text @click="router.push('/knowledge-push')">
              <el-icon style="margin-right: 4px"><Bell /></el-icon>
              推送
            </el-button>
          </el-badge>
          <el-tag v-if="auth.user" type="info" style="margin-right: 12px">
            {{ auth.user.display_name }}（{{ roleLabel }}）
          </el-tag>
          <el-button text @click="auth.logout(); router.push('/welcome')">退出</el-button>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view :key="route.fullPath" />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const isAdmin = computed(() => auth.user?.role === 'admin')
const isTeacher = computed(() => auth.user?.role === 'teacher')
const isStudent = computed(() => auth.user?.role === 'student')

const roleLabel = computed(() => {
  const r = auth.user?.role
  if (r === 'admin') return '系统管理员'
  if (r === 'teacher') return '教师'
  if (r === 'student') return '学生'
  return r || ''
})

const menus = computed(() => [
  { index: '/home', title: '首页', icon: 'HomeFilled' },
  ...(!isAdmin.value
    ? [
        { index: '/chat', title: '大模型对话', icon: 'ChatDotRound' },
        { index: '/course-qa', title: '课程问答', icon: 'Reading' },
        { index: '/chapters', title: '章节学习路线', icon: 'Guide' },
      ]
    : []),
  { index: '/agents', title: '课程智能体', icon: 'Cpu' },
  ...(isStudent.value
    ? [{ index: '/my-class', title: '我的班级', icon: 'User' }]
    : []),
  ...(isAdmin.value
    ? [
        { index: '/admin/users', title: '用户管理', icon: 'UserFilled' },
        { index: '/llm-config', title: '大模型配置', icon: 'Setting' },
        { index: '/admin/exam-records', title: '全站考核记录', icon: 'DataAnalysis' },
        { index: '/admin/logs', title: '全站调用日志', icon: 'List' },
      ]
    : []),
  ...(isTeacher.value
    ? [
        { index: '/teacher/classes', title: '班级管理', icon: 'UserFilled' },
        { index: '/teacher/materials', title: '资料管理', icon: 'FolderOpened' },
        { index: '/teacher/exam-config', title: '考核配置', icon: 'Document' },
        { index: '/teacher/question-bank', title: '题库管理', icon: 'Tickets' },
        { index: '/teacher/exam-records', title: '考核记录', icon: 'DataAnalysis' },
        { index: '/logs', title: '调用日志', icon: 'List' },
      ]
    : []),
])

function go(idx: string) {
  router.push(idx)
}
</script>

<template>
  <el-container class="app-layout">
    <el-aside width="220px" class="app-aside">
      <div class="menu-title">C语言课程智能体</div>
      <el-menu
        :default-active="route.path"
        background-color="#001529"
        text-color="#bfcbd9"
        active-text-color="#409eff"
        @select="go"
      >
        <el-menu-item v-for="m in menus" :key="m.index" :index="m.index">
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="app-header">
        <div>{{ route.meta.title || 'C语言程序设计课程智能体' }}</div>
        <div>
          <el-tag v-if="auth.user" type="info" style="margin-right: 12px">
            {{ auth.user.display_name }}（{{ roleLabel }}）
          </el-tag>
          <el-button text @click="router.push('/login'); auth.logout()">退出</el-button>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

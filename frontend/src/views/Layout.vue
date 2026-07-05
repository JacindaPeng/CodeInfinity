<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const isTeacher = computed(() => ['teacher', 'admin'].includes(auth.user?.role || ''))

const menus = computed(() => [
  { index: '/home', title: '首页', icon: 'HomeFilled' },
  { index: '/chat', title: '大模型对话', icon: 'ChatDotRound' },
  { index: '/course-qa', title: '课程问答', icon: 'Reading' },
  { index: '/chapters', title: '章节学习路线', icon: 'Guide' },
  { index: '/agents', title: '智能体管理', icon: 'Cpu' },
  ...(isTeacher.value
    ? [
        { index: '/llm-config', title: '大模型配置', icon: 'Setting' },
        { index: '/teacher/materials', title: '资料管理', icon: 'FolderOpened' },
        { index: '/teacher/exam-config', title: '考核配置', icon: 'Document' },
        { index: '/teacher/question-bank', title: '题库管理', icon: 'Tickets' },
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
            {{ auth.user.display_name }}（{{ auth.user.role }}）
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

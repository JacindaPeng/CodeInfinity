<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Reading,
  Guide,
  FolderOpened,
  Document,
  Tickets,
  DataAnalysis,
  UserFilled,
} from '@element-plus/icons-vue'
import http from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useCourseAgentStore, type CourseAgentInfo } from '@/stores/courseAgent'

interface FeatureCard {
  title: string
  desc: string
  path: string
  icon: object
  color: string
  disabled?: boolean
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const agentStore = useCourseAgentStore()
const agent = ref<CourseAgentInfo | null>(null)

const isTeacher = computed(() => auth.user?.role === 'teacher')
const isStudent = computed(() => auth.user?.role === 'student')
const isActive = computed(() => agent.value?.status === 'active')

const learnFeatures = computed<FeatureCard[]>(() => {
  if (!isActive.value) return []
  return [
    {
      title: '课程问答',
      desc: 'RAG 检索本课程 PPT/PDF/视频，按班级推荐学习资源',
      path: '/course-qa',
      icon: Reading,
      color: '#409eff',
    },
    {
      title: '章节学习路线',
      desc: '按章节学习、参加考核，查看完成进度',
      path: '/chapters',
      icon: Guide,
      color: '#67c23a',
    },
  ]
})

const teachFeatures = computed<FeatureCard[]>(() => {
  if (!isTeacher.value || !isActive.value) return []
  return [
    { title: '资料管理', desc: '上传并索引本课程教学资料', path: '/teacher/materials', icon: FolderOpened, color: '#e6a23c' },
    { title: '考核配置', desc: '按班级配置章节考核', path: '/teacher/exam-config', icon: Document, color: '#f56c6c' },
    { title: '题库管理', desc: '维护本课程章节题库', path: '/teacher/question-bank', icon: Tickets, color: '#9c27b0' },
    { title: '考核记录', desc: '查看学生答卷与报告', path: '/teacher/exam-records', icon: DataAnalysis, color: '#607d8b' },
    { title: '班级管理', desc: '管理班级与学生', path: '/teacher/classes', icon: UserFilled, color: '#409eff' },
  ]
})

async function load() {
  const id = Number(route.params.id)
  const { data } = await http.get<CourseAgentInfo>(`/agents/${id}`)
  agent.value = data
  agentStore.setAgent(data)
}

function go(path: string) {
  router.push(path)
}

onMounted(load)
</script>

<template>
  <div v-if="agent" class="course-agent-home">
    <el-card shadow="never" class="hero-card">
      <div class="hero-row">
        <div>
          <el-button text @click="router.push(`/agents/${agent.id}`)">← 智能体介绍</el-button>
          <h2 class="hero-title">{{ agent.name }}</h2>
          <p class="hero-sub">{{ agent.course_name || '课程资料筹备中' }}</p>
        </div>
        <el-tag :type="isActive ? 'success' : 'info'" size="large">
          {{ isActive ? '已上线' : '筹备中' }}
        </el-tag>
      </div>
      <p class="hero-desc">{{ agent.intro }}</p>
    </el-card>

    <el-alert
      v-if="!isActive"
      type="info"
      :closable="false"
      title="该课程智能体正在筹备中"
      description="可先浏览智能体介绍；待接入教材、章节与题库后，将开放课程问答与章节考核功能。"
      style="margin-bottom: 16px"
    />

    <section v-if="learnFeatures.length" class="section">
      <h3 class="section-title">学习功能</h3>
      <el-row :gutter="16">
        <el-col v-for="f in learnFeatures" :key="f.path" :xs="24" :sm="12" :md="8">
          <el-card shadow="hover" class="feature-card" @click="go(f.path)">
            <div class="feature-icon" :style="{ background: f.color + '18', color: f.color }">
              <el-icon :size="26"><component :is="f.icon" /></el-icon>
            </div>
            <h4>{{ f.title }}</h4>
            <p>{{ f.desc }}</p>
            <span class="link">进入 →</span>
          </el-card>
        </el-col>
      </el-row>
    </section>

    <section v-if="teachFeatures.length" class="section">
      <h3 class="section-title">教学管理</h3>
      <el-row :gutter="16">
        <el-col v-for="f in teachFeatures" :key="f.path" :xs="24" :sm="12" :md="8" :lg="6">
          <el-card shadow="hover" class="feature-card" @click="go(f.path)">
            <div class="feature-icon" :style="{ background: f.color + '18', color: f.color }">
              <el-icon :size="26"><component :is="f.icon" /></el-icon>
            </div>
            <h4>{{ f.title }}</h4>
            <p>{{ f.desc }}</p>
            <span class="link">进入 →</span>
          </el-card>
        </el-col>
      </el-row>
    </section>
  </div>
</template>

<style scoped>
.course-agent-home {
  max-width: 1100px;
}
.hero-card {
  margin-bottom: 20px;
  background: linear-gradient(135deg, #f0f7ff 0%, #fff 65%);
}
.hero-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.hero-title {
  margin: 8px 0 4px;
  font-size: 24px;
}
.hero-sub {
  margin: 0;
  color: #409eff;
  font-size: 14px;
}
.hero-desc {
  margin: 12px 0 0;
  color: #606266;
  line-height: 1.7;
}
.section {
  margin-bottom: 24px;
}
.section-title {
  margin: 0 0 12px 4px;
  font-size: 15px;
  font-weight: 600;
}
.feature-card {
  cursor: pointer;
  margin-bottom: 16px;
  transition: transform 0.15s;
  height: calc(100% - 16px);
}
.feature-card:hover {
  transform: translateY(-2px);
}
.feature-card h4 {
  margin: 10px 0 6px;
}
.feature-card p {
  margin: 0;
  font-size: 13px;
  color: #909399;
  line-height: 1.5;
  min-height: 40px;
}
.feature-icon {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.link {
  display: inline-block;
  margin-top: 10px;
  font-size: 13px;
  color: #409eff;
}
</style>

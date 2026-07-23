<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  ChatDotRound,
  Reading,
  User,
  UserFilled,
  Document,
  List,
  Setting,
  Promotion,
  DataAnalysis,
  Cpu,
  Bell,
  TrendCharts,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

interface FeatureCard {
  title: string
  desc: string
  path: string
  icon: object
  color: string
}

const auth = useAuthStore()
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

const learnFeatures = computed<FeatureCard[]>(() => {
  if (isAdmin.value) return []
  return [
    {
      title: '大模型对话',
      desc: '通用 AI 对话，支持上传文件与语音输入',
      path: '/chat',
      icon: ChatDotRound,
      color: '#409eff',
    },
    {
      title: '课程智能体',
      desc: '选择 C/Java/Python 等课程智能体，进入专属问答与章节学习',
      path: '/agents',
      icon: Reading,
      color: '#67c23a',
    },
    ...(isStudent.value
      ? [
          {
            title: '我的班级',
            desc: '查看已加入的班级，进入各课程智能体',
            path: '/my-class',
            icon: User,
            color: '#909399',
          },
          {
            title: '知识推送',
            desc: '根据薄弱点从白名单博客推荐延伸阅读',
            path: '/knowledge-push',
            icon: Bell,
            color: '#e6a23c',
          },
        ]
      : []),
  ]
})

const teachFeatures = computed<FeatureCard[]>(() => {
  if (!isTeacher.value) return []
  return [
    { title: '班级管理', desc: '创建班级、管理学生与任课教师', path: '/teacher/classes', icon: UserFilled, color: '#409eff' },
    { title: '课程智能体', desc: '选择课程后管理资料、题库与考核', path: '/agents', icon: Reading, color: '#67c23a' },
    { title: '调用日志', desc: '查看课程问答与大模型调用记录', path: '/logs', icon: List, color: '#607d8b' },
  ]
})

const adminFeatures = computed<FeatureCard[]>(() => {
  if (!isAdmin.value) return []
  return [
    { title: '用户管理', desc: '管理系统用户、重置密码与角色', path: '/admin/users', icon: UserFilled, color: '#409eff' },
    { title: '智能体管理', desc: '新增、编辑、删除课程智能体及上线状态', path: '/admin/agents', icon: Cpu, color: '#00bcd4' },
    { title: '大模型配置', desc: '配置 DeepSeek 等 LLM 提供商与默认模型', path: '/llm-config', icon: Setting, color: '#67c23a' },
    { title: '全站考核记录', desc: '查看所有班级学生的考核情况', path: '/admin/exam-records', icon: DataAnalysis, color: '#e6a23c' },
    { title: '知识推送记录', desc: '查看全站学生推送、阅读状态与 RSS 源', path: '/admin/knowledge-push', icon: Bell, color: '#f56c6c' },
    { title: 'AI反馈监控', desc: '查看学生/教师对 AI 判卷的反馈与介入处理情况', path: '/admin/ai-feedback', icon: TrendCharts, color: '#9c27b0' },
    { title: '全站调用日志', desc: '审计全站 API 与对话调用', path: '/admin/logs', icon: List, color: '#909399' },
  ]
})

const highlightFeatures = computed<FeatureCard[]>(() => {
  const items: FeatureCard[] = [
    {
      title: '多课程智能体',
      desc: 'C 语言、Java、Python 等课程独立知识库，选课后进入专属问答与章节考核',
      path: '/agents',
      icon: Promotion,
      color: '#00bcd4',
    },
  ]
  if (isTeacher.value) {
    items.push({
      title: '班级隔离',
      desc: '资料、题库、考核按班级隔离，教师可为不同班级配置独立教学内容',
      path: '/teacher/classes',
      icon: Document,
      color: '#ff9800',
    })
  } else if (isStudent.value) {
    items.push({
      title: '我的班级',
      desc: '加入班级后使用本班资料与考核配置',
      path: '/my-class',
      icon: User,
      color: '#ff9800',
    })
  }
  return items
})

function go(path: string) {
  router.push(path)
}
</script>

<template>
  <div class="home-page">
    <el-card shadow="never" class="welcome-card">
      <div class="welcome-inner">
        <div>
          <h2 class="welcome-title">欢迎使用 CodeInfinity</h2>
          <p class="welcome-sub">
            你好，{{ auth.user?.display_name }}
            <el-tag size="small" type="info" style="margin-left: 8px">{{ roleLabel }}</el-tag>
          </p>
        </div>
        <p class="welcome-hint">点击下方卡片快速进入对应功能</p>
      </div>
    </el-card>

    <section v-if="learnFeatures.length" class="feature-section">
      <h3 class="section-title">学习与问答</h3>
      <el-row :gutter="16">
        <el-col v-for="f in learnFeatures" :key="f.path" :xs="24" :sm="12" :md="8" :lg="6">
          <el-card shadow="hover" class="feature-card" @click="go(f.path)">
            <div class="feature-icon" :style="{ background: f.color + '18', color: f.color }">
              <el-icon :size="28"><component :is="f.icon" /></el-icon>
            </div>
            <h4>{{ f.title }}</h4>
            <p>{{ f.desc }}</p>
            <span class="feature-link">进入 →</span>
          </el-card>
        </el-col>
      </el-row>
    </section>

    <section v-if="!isAdmin" class="feature-section">
      <h3 class="section-title">核心能力</h3>
      <el-row :gutter="16">
        <el-col v-for="f in highlightFeatures" :key="f.path" :xs="24" :sm="12">
          <el-card shadow="hover" class="feature-card feature-card-wide" @click="go(f.path)">
            <div class="feature-row">
              <div class="feature-icon" :style="{ background: f.color + '18', color: f.color }">
                <el-icon :size="28"><component :is="f.icon" /></el-icon>
              </div>
              <div class="feature-body">
                <h4>{{ f.title }}</h4>
                <p>{{ f.desc }}</p>
                <span class="feature-link">进入 →</span>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </section>

    <section v-if="teachFeatures.length" class="feature-section">
      <h3 class="section-title">教学管理</h3>
      <el-row :gutter="16">
        <el-col v-for="f in teachFeatures" :key="f.path" :xs="24" :sm="12" :md="8" :lg="6">
          <el-card shadow="hover" class="feature-card" @click="go(f.path)">
            <div class="feature-icon" :style="{ background: f.color + '18', color: f.color }">
              <el-icon :size="28"><component :is="f.icon" /></el-icon>
            </div>
            <h4>{{ f.title }}</h4>
            <p>{{ f.desc }}</p>
            <span class="feature-link">进入 →</span>
          </el-card>
        </el-col>
      </el-row>
    </section>

    <section v-if="adminFeatures.length" class="feature-section">
      <h3 class="section-title">系统管理</h3>
      <el-row :gutter="16">
        <el-col v-for="f in adminFeatures" :key="f.path" :xs="24" :sm="12" :md="8" :lg="6">
          <el-card shadow="hover" class="feature-card" @click="go(f.path)">
            <div class="feature-icon" :style="{ background: f.color + '18', color: f.color }">
              <el-icon :size="28"><component :is="f.icon" /></el-icon>
            </div>
            <h4>{{ f.title }}</h4>
            <p>{{ f.desc }}</p>
            <span class="feature-link">进入 →</span>
          </el-card>
        </el-col>
      </el-row>
    </section>
  </div>
</template>

<style scoped>
.home-page {
  max-width: 1200px;
}
.welcome-card {
  margin-bottom: 20px;
  background: linear-gradient(135deg, #f0f7ff 0%, #fff 60%);
}
.welcome-inner {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 12px;
}
.welcome-title {
  margin: 0;
  font-size: 22px;
  color: #303133;
}
.welcome-sub {
  margin: 8px 0 0;
  color: #606266;
}
.welcome-hint {
  margin: 0;
  font-size: 13px;
  color: #909399;
}
.feature-section {
  margin-bottom: 24px;
}
.section-title {
  margin: 0 0 12px 4px;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.feature-card {
  cursor: pointer;
  margin-bottom: 16px;
  transition: transform 0.15s, box-shadow 0.15s;
  height: calc(100% - 16px);
}
.feature-card:hover {
  transform: translateY(-2px);
}
.feature-card h4 {
  margin: 12px 0 6px;
  font-size: 16px;
  color: #303133;
}
.feature-card p {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: #909399;
  min-height: 40px;
}
.feature-link {
  display: inline-block;
  margin-top: 10px;
  font-size: 13px;
  color: #409eff;
}
.feature-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.feature-card-wide .feature-row {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.feature-body {
  flex: 1;
}
.feature-body h4 {
  margin-top: 0;
}
.feature-body p {
  min-height: auto;
}
</style>

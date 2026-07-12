<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '@/api'

interface Agent {
  id: number
  name: string
  intro: string
  endpoint: string
  course_id: number | null
  course_name: string
  slug: string
  status: string
}

const SLUG_THEME: Record<string, { color: string; bg: string }> = {
  'c-lang': { color: '#409eff', bg: '#ecf5ff' },
  java: { color: '#e6a23c', bg: '#fdf6ec' },
  python: { color: '#67c23a', bg: '#f0f9eb' },
}

const list = ref<Agent[]>([])
const router = useRouter()

function theme(slug: string) {
  return SLUG_THEME[slug] || { color: '#909399', bg: '#f4f4f5' }
}

function statusTag(status: string) {
  return status === 'active' ? { type: 'success' as const, label: '已上线' } : { type: 'info' as const, label: '筹备中' }
}

async function load() {
  const { data } = await http.get<Agent[]>('/agents')
  list.value = data
}

function openAgent(id: number) {
  router.push(`/agents/${id}`)
}

onMounted(load)
</script>

<template>
  <div class="agent-manage">
    <el-card shadow="never" class="header-card">
      <h2 class="page-title">课程智能体</h2>
      <p class="page-desc">
        选择一门课程智能体，进入专属介绍页与课程首页。每门课程拥有独立的知识库、章节路线与考核体系。
      </p>
    </el-card>

    <el-row :gutter="16">
      <el-col v-for="a in list" :key="a.id" :xs="24" :sm="12" :md="8">
        <el-card shadow="hover" class="agent-card" @click="openAgent(a.id)">
          <div class="agent-card-head" :style="{ background: theme(a.slug).bg }">
            <div class="agent-icon" :style="{ color: theme(a.slug).color }">
              {{ a.name.charAt(0) }}
            </div>
            <el-tag :type="statusTag(a.status).type" size="small">{{ statusTag(a.status).label }}</el-tag>
          </div>
          <h3>{{ a.name }}</h3>
          <p class="agent-intro">{{ a.intro }}</p>
          <div class="agent-meta">
            <span v-if="a.course_name" class="course-name">{{ a.course_name }}</span>
            <span v-else class="course-name muted">课程资料待接入</span>
          </div>
          <span class="enter-hint">查看介绍 →</span>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="!list.length" description="暂无课程智能体" />
  </div>
</template>

<style scoped>
.agent-manage {
  max-width: 1100px;
}
.header-card {
  margin-bottom: 20px;
  background: linear-gradient(135deg, #f5f7fa 0%, #fff 70%);
}
.page-title {
  margin: 0 0 8px;
  font-size: 22px;
}
.page-desc {
  margin: 0;
  color: #606266;
  line-height: 1.6;
}
.agent-card {
  cursor: pointer;
  margin-bottom: 16px;
  transition: transform 0.15s;
  height: calc(100% - 16px);
}
.agent-card:hover {
  transform: translateY(-3px);
}
.agent-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: -20px -20px 12px;
  padding: 16px 20px;
  border-radius: 4px 4px 0 0;
}
.agent-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: 700;
}
.agent-card h3 {
  margin: 0 0 8px;
  font-size: 17px;
}
.agent-intro {
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
  min-height: 62px;
  margin: 0;
}
.agent-meta {
  margin-top: 10px;
}
.course-name {
  font-size: 12px;
  color: #409eff;
}
.course-name.muted {
  color: #909399;
}
.enter-hint {
  display: inline-block;
  margin-top: 12px;
  font-size: 13px;
  color: #409eff;
}
</style>

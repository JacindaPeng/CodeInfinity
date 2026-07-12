<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api'
import { useCourseAgentStore, type CourseAgentInfo } from '@/stores/courseAgent'

const route = useRoute()
const router = useRouter()
const agentStore = useCourseAgentStore()
const agent = ref<CourseAgentInfo | null>(null)

const isActive = computed(() => agent.value?.status === 'active')

async function load() {
  const { data } = await http.get<CourseAgentInfo>(`/agents/${route.params.id}`)
  agent.value = data
}

function enterHome() {
  if (!agent.value) return
  agentStore.setAgent(agent.value)
  router.push(`/agents/${agent.value.id}/home`)
}

onMounted(load)
</script>

<template>
  <el-card shadow="never" v-if="agent">
    <template #header>
      <div class="header-row">
        <span>{{ agent.name }}</span>
        <el-button text @click="router.push('/agents')">返回列表</el-button>
      </div>
    </template>

    <el-tag v-if="isActive" type="success" style="margin-bottom: 12px">已上线</el-tag>
    <el-tag v-else type="info" style="margin-bottom: 12px">筹备中</el-tag>

    <h3>智能体介绍</h3>
    <p class="intro-text">{{ agent.intro }}</p>

    <el-divider />

    <h3>绑定课程</h3>
    <p v-if="agent.course_name" class="meta-line">
      <el-tag type="primary">{{ agent.course_name }}</el-tag>
    </p>
    <p v-else class="meta-line muted">尚未接入课程资料，教师可在资料管理中上传并索引后启用。</p>

    <el-divider />

    <h3>核心能力</h3>
    <ul class="ability-list">
      <li>课程问答：基于 RAG 检索课程知识库并流式回答</li>
      <li>资源推荐：根据问题推荐相关 PPT / PDF / 视频（含页码与时间戳）</li>
      <li>章节考核：动态生成试卷、自动评分、生成评价报告</li>
      <li>班级隔离：按班级检索资料管理中的专属资源</li>
    </ul>

    <div class="actions">
      <el-button type="primary" :disabled="!isActive" @click="enterHome">
        {{ isActive ? '进入课程首页' : '筹备中，暂不可用' }}
      </el-button>
      <el-button v-if="!isActive" @click="router.push('/agents')">浏览其他智能体</el-button>
    </div>
  </el-card>
</template>

<style scoped>
.header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.intro-text {
  color: #444;
  line-height: 1.8;
  margin: 0;
}
.meta-line {
  margin: 0;
}
.meta-line.muted {
  color: #909399;
}
.ability-list {
  line-height: 2;
  color: #444;
  padding-left: 20px;
  margin: 0 0 16px;
}
.actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
</style>

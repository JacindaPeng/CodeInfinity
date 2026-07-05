<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api'

const route = useRoute()
const router = useRouter()
const agent = ref<{ id: number; name: string; intro: string; endpoint: string } | null>(null)

async function load() {
  const { data } = await http.get(`/agents/${route.params.id}`)
  agent.value = data
}
onMounted(load)
</script>

<template>
  <el-card shadow="never" v-if="agent">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>{{ agent.name }}</span>
        <el-button text @click="router.push('/agents')">返回列表</el-button>
      </div>
    </template>
    <h3>智能体介绍</h3>
    <p style="color: #444; line-height: 1.8">{{ agent.intro }}</p>
    <el-divider />
    <h3>调用入口</h3>
    <p><el-tag>{{ agent.endpoint }}</el-tag></p>
    <el-divider />
    <h3>核心能力</h3>
    <ul style="line-height: 2; color: #444">
      <li>课程问答：基于 RAG 检索课程知识库并流式回答</li>
      <li>资源推荐：根据问题推荐相关 PPT / PDF / 视频（含时间戳）</li>
      <li>章节考核：动态生成试卷、自动评分、生成评价报告</li>
    </ul>
    <el-button type="primary" @click="router.push('/course-qa')">进入课程问答</el-button>
  </el-card>
</template>

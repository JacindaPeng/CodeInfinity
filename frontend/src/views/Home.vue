<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
const auth = useAuthStore()
const features = [
  { title: '课程问答', desc: '基于 RAG，从 PPT/PDF/视频字幕中检索答案', icon: 'Reading' },
  { title: '学习资源推荐', desc: '根据当前问题/章节推荐 PPT、PDF、视频（带时间戳）', icon: 'Promotion' },
  { title: '章节考核', desc: '题库+LLM 动态生成试卷，自动评价生成报告', icon: 'Document' },
]
</script>

<template>
  <div>
    <el-card shadow="never" style="margin-bottom: 16px">
      <h2 style="margin: 0">欢迎使用 C语言程序设计课程智能体</h2>
      <p style="color: #666; margin: 8px 0 0">
        你好，{{ auth.user?.display_name }}（{{ auth.user?.role }}）
      </p>
    </el-card>

    <el-row :gutter="16">
      <el-col v-for="f in features" :key="f.title" :span="8">
        <el-card shadow="hover">
          <el-icon size="32"><component :is="f.icon" /></el-icon>
          <h3>{{ f.title }}</h3>
          <p style="color: #666">{{ f.desc }}</p>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

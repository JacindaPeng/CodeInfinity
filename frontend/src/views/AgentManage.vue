<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '@/api'

interface Agent { id: number; name: string; intro: string; endpoint: string }
const list = ref<Agent[]>([])
const router = useRouter()

async function load() {
  const { data } = await http.get<Agent[]>('/agents')
  list.value = data
}
onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>智能体管理</template>
    <el-row :gutter="16">
      <el-col v-for="a in list" :key="a.id" :span="8" style="margin-bottom: 16px">
        <el-card shadow="hover" @click="router.push(`/agents/${a.id}`)" style="cursor: pointer">
          <h3 style="margin: 0 0 8px">{{ a.name }}</h3>
          <p style="color: #666; min-height: 60px">{{ a.intro }}</p>
          <el-tag size="small">{{ a.endpoint }}</el-tag>
        </el-card>
      </el-col>
    </el-row>
    <el-empty v-if="!list.length" description="暂无智能体" />
  </el-card>
</template>

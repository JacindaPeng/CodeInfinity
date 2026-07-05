<script setup lang="ts">
import { onMounted, ref } from 'vue'
import http from '@/api'

interface LogRow {
  id: number; user_id: number | null; endpoint: string
  req_summary: string; resp_summary: string
  tokens: number; latency_ms: number; created_at: string | null
}

const list = ref<LogRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const endpoint = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/logs', {
      params: { page: page.value, size: size.value, endpoint: endpoint.value || undefined },
    })
    list.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}
function onPage(p: number) { page.value = p; load() }
onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>系统调用历史与日志</span>
        <div>
          <el-input v-model="endpoint" placeholder="按 endpoint 过滤" style="width: 200px; margin-right: 8px" clearable @clear="load" />
          <el-button @click="load">查询</el-button>
        </div>
      </div>
    </template>

    <el-table :data="list" v-loading="loading" border size="small">
      <el-table-column label="ID" prop="id" width="70" />
      <el-table-column label="用户" prop="user_id" width="70" />
      <el-table-column label="接口" prop="endpoint" width="200" show-overflow-tooltip />
      <el-table-column label="请求摘要" prop="req_summary" show-overflow-tooltip />
      <el-table-column label="响应摘要" prop="resp_summary" show-overflow-tooltip />
      <el-table-column label="tokens" prop="tokens" width="80" />
      <el-table-column label="耗时(ms)" prop="latency_ms" width="100" />
      <el-table-column label="时间" prop="created_at" width="180" />
    </el-table>

    <el-pagination
      style="margin-top: 12px; justify-content: flex-end; display: flex"
      v-model:current-page="page"
      :page-size="size"
      :total="total"
      layout="prev, pager, next, total"
      @current-change="onPage"
    />
  </el-card>
</template>

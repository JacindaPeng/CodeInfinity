<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import http from '@/api'
import { useCourseAgentStore } from '@/stores/courseAgent'
import { useAgentBoundClasses } from '@/composables/useAgentBoundClasses'

interface LogRow {
  id: number; user_id: number | null; username: string; display_name: string
  endpoint: string
  req_summary: string; resp_summary: string
  model_name: string; latency_ms: number; created_at: string | null
}
interface ClassItem { id: number; name: string }

const route = useRoute()
const isAdminMode = computed(() => route.path.includes('/admin/'))

const list = ref<LogRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const endpoint = ref('')
const filterClass = ref<number | undefined>(undefined)
const classes = ref<ClassItem[]>([])
const loading = ref(false)
const agentStore = useCourseAgentStore()
const { loadScopedClasses, pickClassId } = useAgentBoundClasses()

async function loadClasses() {
  if (isAdminMode.value) {
    const { data } = await http.get<ClassItem[]>('/admin/classes')
    classes.value = data
    return
  }
  await agentStore.restoreAgent()
  const data = await loadScopedClasses()
  classes.value = data
  filterClass.value = pickClassId(data, filterClass.value)
}

async function load() {
  loading.value = true
  try {
    const url = isAdminMode.value ? '/admin/logs' : '/logs'
    const { data } = await http.get(url, {
      params: {
        page: page.value, size: size.value,
        endpoint: endpoint.value || undefined,
        class_id: filterClass.value || undefined,
      },
    })
    list.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}
function onPage(p: number) { page.value = p; load() }
function onFilter() { page.value = 1; load() }
onMounted(async () => {
  await loadClasses()
  await load()
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>{{ isAdminMode ? '全站调用历史与日志' : '学生系统调用日志' }}</span>
        <div>
          <el-select v-model="filterClass" placeholder="按班级筛选" clearable @change="onFilter" style="width: 180px; margin-right: 8px">
            <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-input v-model="endpoint" placeholder="按 endpoint 过滤" style="width: 200px; margin-right: 8px" clearable @clear="load" />
          <el-button @click="load">查询</el-button>
        </div>
      </div>
    </template>

    <el-table :data="list" v-loading="loading" border size="small">
      <el-table-column label="ID" prop="id" width="70" />
      <el-table-column label="用户" width="140">
        <template #default="{ row }">
          {{ row.display_name || row.username || row.user_id || '—' }}
        </template>
      </el-table-column>
      <el-table-column label="接口" prop="endpoint" width="200" show-overflow-tooltip />
      <el-table-column label="请求摘要" prop="req_summary" show-overflow-tooltip />
      <el-table-column label="响应摘要" prop="resp_summary" show-overflow-tooltip />
      <el-table-column label="模型" prop="model_name" width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ row.model_name || '（此时未开启模型日志记录）' }}</template>
      </el-table-column>
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

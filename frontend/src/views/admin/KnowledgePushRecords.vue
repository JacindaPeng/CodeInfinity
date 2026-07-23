<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api'

interface Stats {
  total: number
  unread: number
  read: number
  dismissed: number
  articles: number
  enabled_sources: number
  pushes_last_24h: number
}

interface RecordRow {
  id: number
  status: string
  reason: string
  kp_names: string[]
  user_id: number
  username: string
  display_name: string
  course_name: string
  agent_name: string
  pushed_at: string | null
  read_at: string | null
  article: {
    title: string
    url: string
    source_name: string
    summary: string
  }
}

interface SourceRow {
  id: number
  name: string
  base_url: string
  rss_url: string
  enabled: boolean
  tags: string
  resource_type: 'article' | 'podcast' | 'video' | 'twitter'
}

const stats = ref<Stats | null>(null)
const records = ref<RecordRow[]>([])
const sources = ref<SourceRow[]>([])
const total = ref(0)
const loading = ref(false)
const sourceDialogVisible = ref(false)
const sourceSaving = ref(false)
const importingBestBlogs = ref(false)
const editingSourceId = ref<number | null>(null)
const sourceForm = reactive({
  name: '',
  base_url: '',
  rss_url: '',
  tags: '',
  resource_type: 'article' as SourceRow['resource_type'],
  enabled: true,
})
const filters = reactive({
  status: '' as string,
  q: '',
  page: 1,
  size: 20,
})

function statusLabel(s: string) {
  return ({ unread: '未读', read: '已读', dismissed: '已忽略' } as Record<string, string>)[s] || s
}

function statusType(s: string) {
  return ({ unread: 'danger', read: 'success', dismissed: 'info' } as Record<string, string>)[s] || 'info'
}

function formatTime(t: string | null) {
  if (!t) return '—'
  return t.replace('T', ' ').slice(0, 19)
}

async function loadStats() {
  const { data } = await http.get<Stats>('/knowledge-push/admin/stats')
  stats.value = data
}

async function loadRecords() {
  loading.value = true
  try {
    const params: Record<string, string | number> = {
      page: filters.page,
      size: filters.size,
    }
    if (filters.status) params.status = filters.status
    if (filters.q.trim()) params.q = filters.q.trim()
    const { data } = await http.get<{ items: RecordRow[]; total: number }>(
      '/knowledge-push/admin/records',
      { params },
    )
    records.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

async function loadSources() {
  const { data } = await http.get<SourceRow[]>('/knowledge-push/sources')
  sources.value = data
}

function openSourceDialog(source?: SourceRow) {
  editingSourceId.value = source?.id ?? null
  sourceForm.name = source?.name ?? ''
  sourceForm.base_url = source?.base_url ?? ''
  sourceForm.rss_url = source?.rss_url ?? ''
  sourceForm.tags = source?.tags ?? ''
  sourceForm.resource_type = source?.resource_type ?? 'article'
  sourceForm.enabled = source?.enabled ?? true
  sourceDialogVisible.value = true
}

async function saveSource() {
  if (!sourceForm.name.trim() || !sourceForm.rss_url.trim()) {
    ElMessage.warning('请填写名称和 RSS 地址')
    return
  }
  sourceSaving.value = true
  try {
    const payload = { ...sourceForm }
    if (editingSourceId.value) {
      await http.put(`/knowledge-push/sources/${editingSourceId.value}`, payload)
    } else {
      await http.post('/knowledge-push/sources', payload)
    }
    sourceDialogVisible.value = false
    ElMessage.success(editingSourceId.value ? '白名单源已更新' : '白名单源已添加')
    await Promise.all([loadSources(), loadStats()])
  } finally {
    sourceSaving.value = false
  }
}

async function toggleSource(source: SourceRow, enabled: boolean) {
  const previous = source.enabled
  source.enabled = enabled
  try {
    await http.put(`/knowledge-push/sources/${source.id}`, { ...source })
    await loadStats()
  } catch {
    source.enabled = previous
  }
}

async function importBestBlogs() {
  importingBestBlogs.value = true
  try {
    const { data } = await http.post<{
      created: number
      updated: number
    }>('/knowledge-push/sources/import-bestblogs')
    ElMessage.success(`BestBlogs 白名单已导入：新增 ${data.created}，更新 ${data.updated}`)
    await Promise.all([loadSources(), loadStats()])
  } finally {
    importingBestBlogs.value = false
  }
}

function search() {
  filters.page = 1
  void loadRecords()
}

onMounted(async () => {
  await Promise.all([loadStats(), loadRecords(), loadSources()])
})
</script>

<template>
  <div>
    <div style="margin-bottom: 16px">
      <h3 style="margin: 0 0 8px">知识推送记录</h3>
      <p style="color: #888; font-size: 13px; margin: 0">
        查看全站学生推送记录、阅读状态与白名单 RSS 源。推送由学生端自行刷新或定时任务生成（管理员不可手动推送）。
      </p>
    </div>

    <el-row v-if="stats" :gutter="16" style="margin-bottom: 16px">
      <el-col :span="4"><el-statistic title="推送总数" :value="stats.total" /></el-col>
      <el-col :span="4"><el-statistic title="未读" :value="stats.unread" /></el-col>
      <el-col :span="4"><el-statistic title="已读" :value="stats.read" /></el-col>
      <el-col :span="4"><el-statistic title="已忽略" :value="stats.dismissed" /></el-col>
      <el-col :span="4"><el-statistic title="近 24h" :value="stats.pushes_last_24h" /></el-col>
      <el-col :span="4"><el-statistic title="启用源 / 文章" :value="`${stats.enabled_sources} / ${stats.articles}`" /></el-col>
    </el-row>

    <el-card shadow="never" style="margin-bottom: 16px">
      <el-form inline @submit.prevent="search">
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width: 120px">
            <el-option label="未读" value="unread" />
            <el-option label="已读" value="read" />
            <el-option label="已忽略" value="dismissed" />
          </el-select>
        </el-form-item>
        <el-form-item label="搜索">
          <el-input
            v-model="filters.q"
            clearable
            placeholder="学生姓名/用户名/文章标题"
            style="width: 240px"
            @keyup.enter="search"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="records" v-loading="loading" stripe style="width: 100%">
        <el-table-column label="学生" min-width="120">
          <template #default="{ row }">
            {{ row.display_name || row.username }}
            <div style="color: #909399; font-size: 12px">{{ row.username }}</div>
          </template>
        </el-table-column>
        <el-table-column label="文章" min-width="220">
          <template #default="{ row }">
            <a v-if="row.article?.url" :href="row.article.url" target="_blank" rel="noopener">
              {{ row.article.title || '无标题' }}
            </a>
            <span v-else>{{ row.article?.title || '—' }}</span>
            <div style="color: #909399; font-size: 12px">{{ row.article?.source_name }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="course_name" label="课程" width="120" show-overflow-tooltip />
        <el-table-column prop="agent_name" label="智能体" width="120" show-overflow-tooltip />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="推荐理由" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.reason }}</template>
        </el-table-column>
        <el-table-column label="推送时间" width="160">
          <template #default="{ row }">{{ formatTime(row.pushed_at) }}</template>
        </el-table-column>
        <el-table-column label="已读时间" width="160">
          <template #default="{ row }">{{ formatTime(row.read_at) }}</template>
        </el-table-column>
      </el-table>

      <div style="display: flex; justify-content: flex-end; margin-top: 12px">
        <el-pagination
          v-model:current-page="filters.page"
          v-model:page-size="filters.size"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadRecords"
        />
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <div>
            <span style="font-weight: 600">白名单 RSS 源</span>
            <span style="margin-left: 10px; color: #909399; font-size: 12px">
              仅启用的来源会参与文章拉取
            </span>
          </div>
          <div style="display: flex; gap: 8px">
            <el-button :loading="importingBestBlogs" @click="importBestBlogs">
              导入 BestBlogs 精选
            </el-button>
            <el-button type="primary" @click="openSourceDialog()">添加 RSS 源</el-button>
          </div>
        </div>
      </template>
      <el-table :data="sources" stripe>
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column prop="rss_url" label="RSS" min-width="280" show-overflow-tooltip />
        <el-table-column prop="tags" label="标签" width="140" />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            {{ ({ article: '文章', podcast: '播客', video: '视频', twitter: '推文' } as Record<string, string>)[row.resource_type] || '文章' }}
          </template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled"
              @change="toggleSource(row, Boolean($event))"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button text type="primary" @click="openSourceDialog(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="sourceDialogVisible"
      :title="editingSourceId ? '编辑白名单源' : '添加白名单源'"
      width="620px"
    >
      <el-form label-width="90px">
        <el-form-item label="名称" required>
          <el-input v-model="sourceForm.name" placeholder="例如：课程技术博客" />
        </el-form-item>
        <el-form-item label="站点地址">
          <el-input v-model="sourceForm.base_url" placeholder="https://example.com" />
        </el-form-item>
        <el-form-item label="RSS 地址" required>
          <el-input v-model="sourceForm.rss_url" placeholder="https://example.com/feed.xml" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="sourceForm.tags" placeholder="逗号分隔，例如：c,python,zh" />
        </el-form-item>
        <el-form-item label="资源类型">
          <el-select v-model="sourceForm.resource_type" style="width: 180px">
            <el-option label="文章" value="article" />
            <el-option label="播客" value="podcast" />
            <el-option label="视频" value="video" />
            <el-option label="推文" value="twitter" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="sourceForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="sourceDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="sourceSaving" @click="saveSource">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

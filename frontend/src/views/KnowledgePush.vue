<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api'

interface PushItem {
  id: number
  status: string
  reason: string
  kp_names: string[]
  agent_id: number | null
  course_id: number | null
  pushed_at: string | null
  article: {
    id: number | null
    title: string
    summary: string
    url: string
    published_at: string | null
    source_name: string
    resource_type: 'article' | 'podcast' | 'video' | 'twitter'
  }
}

const loading = ref(false)
const running = ref(false)
const list = ref<PushItem[]>([])
const weakPoints = ref<string[]>([])
const lang = ref<'zh' | 'en'>('zh')
const resourceType = ref<'all' | 'article' | 'podcast' | 'video' | 'twitter'>('all')
const limit = ref(3)

const resourceLabels = {
  article: '文章',
  podcast: '播客',
  video: '视频',
  twitter: '推文',
} as const

function resourceLabel(type: string) {
  return resourceLabels[type as keyof typeof resourceLabels] || '文章'
}

/** 仅展示考核报告中的完整薄弱点；否则显示课程延伸阅读 */
function displayKpNames(row: PushItem): string[] {
  const official = new Set(weakPoints.value)
  const valid = (row.kp_names || []).filter(k => official.has(k))
  return valid.length ? valid : ['课程延伸阅读']
}

async function load() {
  loading.value = true
  try {
    const [pushRes, weakRes] = await Promise.all([
      http.get<PushItem[]>('/knowledge-push/today', {
        params: { resource_type: resourceType.value },
      }),
      http.get<{ items: { kp_name: string }[] }>('/knowledge-push/weak-points').catch(() => ({ data: { items: [] } })),
    ])
    list.value = pushRes.data
    weakPoints.value = (weakRes.data.items || []).map(x => x.kp_name).slice(0, 12)
  } finally {
    loading.value = false
  }
}

async function markRead(row: PushItem) {
  await http.post(`/knowledge-push/${row.id}/read`)
  row.status = 'read'
  window.dispatchEvent(new CustomEvent('knowledge-push-changed'))
  ElMessage.success('已标记已读')
}

async function dismiss(row: PushItem) {
  await http.post(`/knowledge-push/${row.id}/dismiss`)
  list.value = list.value.filter(x => x.id !== row.id)
  window.dispatchEvent(new CustomEvent('knowledge-push-changed'))
  ElMessage.success('已忽略')
}

function openArticle(row: PushItem) {
  if (row.article?.url) window.open(row.article.url, '_blank')
  if (row.status === 'unread') markRead(row)
}

async function runNow() {
  running.value = true
  try {
    const { data } = await http.post<{
      pushes_created: number
      weak_points?: string[]
      fetch?: { upserted?: number; failed?: number; error?: string; started_background?: boolean }
    }>(
      '/knowledge-push/run',
      {
        fetch: true,
        for_me: true,
        lang: lang.value,
        resource_type: resourceType.value,
        limit: limit.value,
      },
      { timeout: 60000, skipGlobalError: true },
    )
    if (data.weak_points?.length) weakPoints.value = data.weak_points
    const typeText = resourceType.value === 'all' ? '综合' : resourceLabel(resourceType.value)
    ElMessage.success(`已生成 ${data.pushes_created || 0} 条${lang.value === 'zh' ? '中文' : '英文'}${typeText}推送`)
    if (!(data.pushes_created > 0)) {
      ElMessage.warning(
        lang.value === 'zh'
          ? '暂无更多可推中文内容。可先「忽略」旧推送后再刷新；系统会在后台继续拉取外网 RSS。'
          : '暂无更多可推英文内容。可忽略旧推送后再刷新。',
      )
    } else if (data.fetch?.started_background) {
      ElMessage.info('外网源正在后台更新，稍后再刷新可看到更新内容')
    } else if ((data.fetch?.failed || 0) > 0 || data.fetch?.error) {
      ElMessage.info('部分外网 RSS 拉取失败，已使用本地文库完成推荐')
    }
    window.dispatchEvent(new CustomEvent('knowledge-push-changed'))
    await load()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '刷新失败'
    ElMessage.error(typeof msg === 'string' ? msg : '刷新今日推荐失败，请稍后重试')
  } finally {
    running.value = false
  }
}

onMounted(load)
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>
      <div class="header-row">
        <div>
          <div style="font-weight: 600; font-size: 16px">知识推送</div>
          <div style="color: #909399; font-size: 13px; margin-top: 4px">
            根据薄弱点进行推荐，或从白名单博客推荐课外延伸阅读
          </div>
        </div>
        <div class="controls">
          <span class="ctrl-label">语言</span>
          <el-radio-group v-model="lang" size="small">
            <el-radio-button value="zh">中文</el-radio-button>
            <el-radio-button value="en">英文</el-radio-button>
          </el-radio-group>
          <span class="ctrl-label">类型</span>
          <el-select v-model="resourceType" size="small" style="width: 100px" @change="load">
            <el-option label="全部" value="all" />
            <el-option label="文章" value="article" />
            <el-option label="播客" value="podcast" />
            <el-option label="视频" value="video" />
            <el-option label="推文" value="twitter" />
          </el-select>
          <span class="ctrl-label">条数</span>
          <el-input-number v-model="limit" :min="1" :max="10" size="small" controls-position="right" />
          <el-button :loading="running" type="primary" @click="runNow">刷新今日推荐</el-button>
        </div>
      </div>
    </template>

    <div v-if="weakPoints.length" class="weak-box">
      <div class="weak-title">来自考核报告的薄弱点（全课程汇总）</div>
      <el-tag v-for="k in weakPoints" :key="k" size="small" type="warning" style="margin: 0 6px 6px 0">{{ k }}</el-tag>
    </div>
    <el-alert
      v-else
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
      title="暂无考核报告薄弱点。完成章节测试后，将根据报告自动匹配推荐。"
    />

    <el-empty v-if="!list.length" description="暂无推送，可选择语言与条数后点击「刷新今日推荐」" />

    <div v-for="row in list" :key="row.id" class="push-card" :class="{ unread: row.status === 'unread' }">
      <div class="push-head">
        <el-tag v-if="row.status === 'unread'" type="danger" size="small">未读</el-tag>
        <el-tag v-else type="info" size="small">已读</el-tag>
        <el-tag size="small" type="success">{{ resourceLabel(row.article.resource_type) }}</el-tag>
        <span v-if="row.article.source_name" class="source">{{ row.article.source_name }}</span>
      </div>
      <h3 class="title" @click="openArticle(row)">{{ row.article.title || '无标题' }}</h3>
      <p class="summary">{{ row.article.summary }}</p>
      <div class="kps">
        <el-tag v-for="k in displayKpNames(row)" :key="k" size="small" style="margin: 0 6px 6px 0">{{ k }}</el-tag>
      </div>
      <div class="actions">
        <el-button type="primary" link @click="openArticle(row)">
          打开{{ resourceLabel(row.article.resource_type) }}
        </el-button>
        <el-button v-if="row.status === 'unread'" link @click="markRead(row)">标记已读</el-button>
        <el-button link type="info" @click="dismiss(row)">忽略</el-button>
      </div>
    </div>
  </el-card>
</template>

<style scoped>
.header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}
.controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.ctrl-label {
  color: #909399;
  font-size: 13px;
}
.weak-box {
  margin-bottom: 14px;
  padding: 10px 12px;
  background: #fdf6ec;
  border-radius: 8px;
}
.weak-title {
  font-size: 13px;
  color: #e6a23c;
  margin-bottom: 8px;
  font-weight: 500;
}
.push-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 12px;
  background: #fff;
}
.push-card.unread {
  border-color: #fab6b6;
  background: #fff8f8;
}
.push-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.source { color: #909399; font-size: 12px; }
.title {
  margin: 0 0 6px;
  font-size: 16px;
  cursor: pointer;
  color: #303133;
}
.title:hover { color: #409eff; }
.summary {
  margin: 0 0 8px;
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.actions { margin-top: 4px; }
</style>

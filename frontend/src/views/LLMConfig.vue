<script setup lang="ts">
import { onMounted, ref, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'

interface Cfg {
  id: number; provider: string; api_key: string; base_url: string; model: string; is_default: boolean
}
interface Prov { provider: string; label: string; default_model: string; base_url: string }

const list = ref<Cfg[]>([])
const providers = ref<Prov[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(false)
const form = reactive({
  id: 0, provider: 'deepseek', api_key: '', base_url: '', model: '', is_default: false,
})

async function load() {
  loading.value = true
  try {
    const [a, b] = await Promise.all([
      http.get<Cfg[]>('/llm-configs'),
      http.get<Prov[]>('/llm-configs/providers'),
    ])
    list.value = a.data
    providers.value = b.data
  } finally {
    loading.value = false
  }
}

function openAdd() {
  editing.value = false
  Object.assign(form, { id: 0, provider: 'deepseek', api_key: '', base_url: '', model: '', is_default: list.value.length === 0 })
  dialogVisible.value = true
}

function openEdit(row: Cfg) {
  editing.value = true
  Object.assign(form, row)
  dialogVisible.value = true
}

function onProviderChange() {
  const p = providers.value.find(x => x.provider === form.provider)
  if (p && !editing.value) {
    form.base_url = p.base_url
    form.model = p.default_model
  }
}

async function submit() {
  if (!form.api_key) { ElMessage.warning('请填写 API Key'); return }
  try {
    if (editing.value) {
      await http.put(`/llm-configs/${form.id}`, form)
      ElMessage.success('已更新')
    } else {
      await http.post('/llm-configs', form)
      ElMessage.success('已新增')
    }
    dialogVisible.value = false
    load()
  } catch {}
}

async function setDefault(row: Cfg) {
  if (row.is_default) return
  try {
    await http.put(`/llm-configs/${row.id}`, {
      provider: row.provider,
      api_key: row.api_key,
      base_url: row.base_url,
      model: row.model,
      is_default: true,
    })
    ElMessage.success(`已将 ${providerLabel(row.provider)} 设为默认模型`)
    await load()
  } catch {}
}

async function remove(row: Cfg) {
  const tip = row.is_default
    ? `「${providerLabel(row.provider)}」是当前默认模型，删除后系统将无默认配置，确定删除？`
    : `删除 ${providerLabel(row.provider)} 配置？`
  await ElMessageBox.confirm(tip, '提示', { type: 'warning' })
  await http.delete(`/llm-configs/${row.id}`)
  ElMessage.success('已删除')
  load()
}

const providerLabel = (p: string) => providers.value.find(x => x.provider === p)?.label || p

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>大模型配置</span>
        <el-button type="primary" @click="openAdd">新增配置</el-button>
      </div>
    </template>

    <el-table :data="list" v-loading="loading" border>
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="提供商">
        <template #default="{ row }">{{ providerLabel(row.provider) }}</template>
      </el-table-column>
      <el-table-column label="模型" prop="model" />
      <el-table-column label="Base URL" prop="base_url" show-overflow-tooltip />
      <el-table-column label="API Key" >
        <template #default="{ row }">
          <span>{{ row.api_key ? row.api_key.slice(0, 6) + '••••' : '未设置' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="默认" width="100" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.is_default" type="success">默认</el-tag>
          <el-button v-else text type="primary" @click="setDefault(row)">设为默认</el-button>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button text type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑配置' : '新增配置'" width="500px">
      <el-form label-width="90px">
        <el-form-item label="提供商">
          <el-select v-model="form.provider" :disabled="editing" @change="onProviderChange">
            <el-option v-for="p in providers" :key="p.provider" :label="p.label" :value="p.provider" />
          </el-select>
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.api_key" placeholder="sk-..." show-password />
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" />
        </el-form-item>
        <el-form-item label="模型">
          <el-input v-model="form.model" />
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="form.is_default" />
          <span style="margin-left: 8px; color: #909399; font-size: 12px">开启后，对话/问答/考核将优先使用此模型</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

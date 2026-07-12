<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { useAuthStore } from '@/stores/auth'

interface Teacher {
  id: number
  username: string
  display_name: string
}

interface MyClassData {
  class_id: number | null
  class_name: string | null
  teachers: Teacher[]
}

const auth = useAuthStore()
const loading = ref(false)
const joining = ref(false)
const classInfo = ref<MyClassData | null>(null)
const inviteCode = ref('')

async function load() {
  loading.value = true
  try {
    const { data } = await http.get<MyClassData>('/classes/my')
    classInfo.value = data
  } finally {
    loading.value = false
  }
}

async function join() {
  const code = inviteCode.value.trim()
  if (!code) {
    ElMessage.warning('请输入邀请码')
    return
  }
  joining.value = true
  try {
    const { data } = await http.post('/classes/join', { invite_code: code })
    ElMessage.success(`已加入班级：${data.class_name}`)
    inviteCode.value = ''
    await auth.fetchMe()
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加入失败')
  } finally {
    joining.value = false
  }
}

async function leave() {
  await ElMessageBox.confirm('确定退出当前班级吗？', '提示', { type: 'warning' })
  try {
    await http.post('/classes/leave')
    ElMessage.success('已退出班级')
    await auth.fetchMe()
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '退出失败')
  }
}

onMounted(load)
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>
      <span>我的班级</span>
    </template>

    <template v-if="classInfo?.class_id">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="班级名称">{{ classInfo.class_name }}</el-descriptions-item>
        <el-descriptions-item label="管理教师">
          <el-tag
            v-for="t in classInfo.teachers"
            :key="t.id"
            style="margin-right: 6px"
            type="info"
          >
            {{ t.display_name || t.username }}
          </el-tag>
          <span v-if="!classInfo.teachers.length">暂无</span>
        </el-descriptions-item>
      </el-descriptions>
      <div style="margin-top: 16px">
        <el-button type="danger" plain @click="leave">退出班级</el-button>
      </div>
    </template>

    <template v-else>
      <el-alert
        title="您尚未加入任何班级"
        description="请输入教师提供的邀请码加入班级。加入后，教师可查看您的考核记录与学习日志。"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      />
      <el-form inline @submit.prevent="join">
        <el-form-item label="邀请码">
          <el-input
            v-model="inviteCode"
            placeholder="请输入6位邀请码"
            style="width: 200px"
            maxlength="8"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="joining" @click="join">加入班级</el-button>
        </el-form-item>
      </el-form>
    </template>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useCourseAgentStore, type CourseAgentInfo } from '@/stores/courseAgent'

interface Teacher {
  id: number
  username: string
  display_name: string
}

interface Enrollment {
  class_id: number
  class_name: string
  course_id: number
  course_name: string
  teachers: Teacher[]
}

const auth = useAuthStore()
const agentStore = useCourseAgentStore()
const router = useRouter()
const loading = ref(false)
const joining = ref(false)
const enrollments = ref<Enrollment[]>([])
const agents = ref<CourseAgentInfo[]>([])
const inviteCode = ref('')

async function load() {
  loading.value = true
  try {
    const [en, ag] = await Promise.all([
      http.get<Enrollment[]>('/classes/my'),
      http.get<CourseAgentInfo[]>('/agents').catch(() => ({ data: [] as CourseAgentInfo[] })),
    ])
    enrollments.value = en.data
    agents.value = ag.data
  } finally {
    loading.value = false
  }
}

function agentForEnrollment(row: Enrollment) {
  return agents.value.find(a => a.course_id === row.course_id && a.status === 'active')
}

function enterCourse(row: Enrollment) {
  const a = agentForEnrollment(row)
  if (!a) {
    ElMessage.warning('该班级尚未分配已上线的课程智能体，请联系教师')
    return
  }
  agentStore.setAgent(a)
  router.push(`/agents/${a.id}/home`)
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
    ElMessage.success(`已加入班级：${data.class_name}（${data.course_name || '课程'}）`)
    inviteCode.value = ''
    await auth.fetchMe()
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加入失败')
  } finally {
    joining.value = false
  }
}

async function leave(row: Enrollment) {
  await ElMessageBox.confirm(
    `确定退出「${row.class_name}」（${row.course_name}）吗？`,
    '提示',
    { type: 'warning' },
  )
  try {
    await http.post('/classes/leave', { class_id: row.class_id })
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

    <el-alert
      title="学生可加入多个班级的不同课程"
      description="每门课程最多只能加入一个班级。加入后，可使用该班级分配的课程智能体与考核功能。"
      type="info"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <el-table v-if="enrollments.length" :data="enrollments" border size="small" style="margin-bottom: 16px">
      <el-table-column label="课程" prop="course_name" min-width="140" />
      <el-table-column label="班级" prop="class_name" min-width="160" />
      <el-table-column label="管理教师" min-width="200">
        <template #default="{ row }">
          <el-tag
            v-for="t in row.teachers"
            :key="t.id"
            style="margin-right: 6px"
            type="info"
          >
            {{ t.display_name || t.username }}
          </el-tag>
          <span v-if="!row.teachers.length">暂无</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" align="center">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            :disabled="!agentForEnrollment(row)"
            @click="enterCourse(row)"
          >
            进入课程
          </el-button>
          <el-button link type="danger" @click="leave(row)">退出</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-else description="您尚未加入任何班级" style="margin-bottom: 16px" />

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
  </el-card>
</template>

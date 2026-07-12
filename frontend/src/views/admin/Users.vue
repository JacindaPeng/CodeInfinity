<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '@/api'

interface UserRow {
  id: number
  username: string
  display_name: string
  role: string
  class_id: number | null
  class_name: string | null
  created_at: string
}

const list = ref<UserRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const filterRole = ref('')
const filterUsername = ref('')

const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const form = reactive({
  id: 0,
  username: '',
  password: '',
  role: 'student',
  display_name: '',
})

const resetDialogVisible = ref(false)
const resetUserId = ref(0)
const resetPassword = ref('')

const roleLabel: Record<string, string> = {
  student: '学生',
  teacher: '教师',
  admin: '系统管理员',
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/admin/users', {
      params: {
        page: page.value,
        size: size.value,
        role: filterRole.value || undefined,
        username: filterUsername.value || undefined,
      },
    })
    list.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function onPage(p: number) {
  page.value = p
  load()
}

function onFilter() {
  page.value = 1
  load()
}

function openCreate() {
  dialogMode.value = 'create'
  form.id = 0
  form.username = ''
  form.password = ''
  form.role = 'student'
  form.display_name = ''
  dialogVisible.value = true
}

function openEdit(row: UserRow) {
  dialogMode.value = 'edit'
  form.id = row.id
  form.username = row.username
  form.password = ''
  form.role = row.role
  form.display_name = row.display_name
  dialogVisible.value = true
}

async function submitForm() {
  if (dialogMode.value === 'create') {
    if (form.username.length < 3 || form.password.length < 6) {
      ElMessage.warning('用户名≥3位，密码≥6位')
      return
    }
    await http.post('/admin/users', {
      username: form.username,
      password: form.password,
      role: form.role,
      display_name: form.display_name || form.username,
    })
    ElMessage.success('用户已创建')
  } else {
    await http.put(`/admin/users/${form.id}`, {
      role: form.role,
      display_name: form.display_name,
    })
    ElMessage.success('用户已更新')
  }
  dialogVisible.value = false
  await load()
}

function openReset(row: UserRow) {
  resetUserId.value = row.id
  resetPassword.value = ''
  resetDialogVisible.value = true
}

async function submitReset() {
  if (resetPassword.value.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  await http.post(`/admin/users/${resetUserId.value}/reset-password`, {
    password: resetPassword.value,
  })
  ElMessage.success('密码已重置')
  resetDialogVisible.value = false
}

async function remove(row: UserRow) {
  await ElMessageBox.confirm(`确定删除用户「${row.display_name || row.username}」？`, '确认删除', {
    type: 'warning',
  })
  await http.delete(`/admin/users/${row.id}`)
  ElMessage.success('用户已删除')
  await load()
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span>用户管理</span>
        <div>
          <el-select v-model="filterRole" placeholder="按角色筛选" clearable @change="onFilter" style="width: 140px; margin-right: 8px">
            <el-option label="学生" value="student" />
            <el-option label="教师" value="teacher" />
            <el-option label="系统管理员" value="admin" />
          </el-select>
          <el-input
            v-model="filterUsername"
            placeholder="搜索用户名"
            clearable
            style="width: 180px; margin-right: 8px"
            @clear="onFilter"
            @keyup.enter="onFilter"
          />
          <el-button @click="onFilter">查询</el-button>
          <el-button type="primary" @click="openCreate">新建用户</el-button>
        </div>
      </div>
    </template>

    <el-table :data="list" v-loading="loading" border size="small">
      <el-table-column label="ID" prop="id" width="60" />
      <el-table-column label="用户名" prop="username" width="140" />
      <el-table-column label="昵称" prop="display_name" width="140" />
      <el-table-column label="角色" width="120">
        <template #default="{ row }">
          <el-tag :type="row.role === 'admin' ? 'danger' : row.role === 'teacher' ? 'warning' : 'info'" size="small">
            {{ roleLabel[row.role] || row.role }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="班级" width="160">
        <template #default="{ row }">{{ row.class_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="注册时间" prop="created_at" width="180" />
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button text type="warning" @click="openReset(row)">重置密码</el-button>
          <el-button text type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
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

  <el-dialog v-model="dialogVisible" :title="dialogMode === 'create' ? '新建用户' : '编辑用户'" width="420px">
    <el-form label-width="80px">
      <el-form-item v-if="dialogMode === 'create'" label="用户名">
        <el-input v-model="form.username" />
      </el-form-item>
      <el-form-item v-if="dialogMode === 'create'" label="密码">
        <el-input v-model="form.password" type="password" show-password />
      </el-form-item>
      <el-form-item label="角色">
        <el-select v-model="form.role" style="width: 100%">
          <el-option label="学生" value="student" />
          <el-option label="教师" value="teacher" />
          <el-option label="系统管理员" value="admin" />
        </el-select>
      </el-form-item>
      <el-form-item label="昵称">
        <el-input v-model="form.display_name" placeholder="可选" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" @click="submitForm">确定</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="resetDialogVisible" title="重置密码" width="400px">
    <el-form label-width="80px">
      <el-form-item label="新密码">
        <el-input v-model="resetPassword" type="password" show-password />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="resetDialogVisible = false">取消</el-button>
      <el-button type="primary" @click="submitReset">确定</el-button>
    </template>
  </el-dialog>
</template>

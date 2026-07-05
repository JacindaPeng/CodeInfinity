<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api/auth'

const router = useRouter()
const form = reactive({
  username: '',
  password: '',
  role: 'student' as 'student' | 'teacher',
  display_name: '',
})
const loading = ref(false)

async function submit() {
  if (form.username.length < 3 || form.password.length < 6) {
    ElMessage.warning('用户名≥3位，密码≥6位')
    return
  }
  loading.value = true
  try {
    await authApi.register(form)
    ElMessage.success('注册成功，请登录')
    router.push('/login')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <template #header>
        <div style="text-align: center; font-size: 18px; font-weight: 600">注册新账号</div>
      </template>
      <el-form>
        <el-form-item label="用户名">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="form.role">
            <el-radio value="student">学生</el-radio>
            <el-radio value="teacher">教师</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="昵称">
          <el-input v-model="form.display_name" placeholder="可选" />
        </el-form-item>
        <el-button type="primary" :loading="loading" style="width: 100%" @click="submit">
          注册
        </el-button>
        <div style="margin-top: 12px; text-align: center">
          <el-link type="primary" @click="router.push('/login')">已有账号？去登录</el-link>
        </div>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
}
.login-card { width: 380px; }
</style>

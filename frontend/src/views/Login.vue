<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api/auth'

const auth = useAuthStore()
const router = useRouter()

const loginTab = ref<'password' | 'phone'>('password')
const passwordForm = reactive({ username: '', password: '' })
const phoneForm = reactive({ phone: '', code: '' })
const loading = ref(false)
const smsLoading = ref(false)
const smsCooldown = ref(0)
let cooldownTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  if (!auth.token) return
  if (auth.user) {
    router.replace('/home')
    return
  }
  const me = await auth.fetchMe()
  if (me) router.replace('/home')
})

onUnmounted(() => {
  if (cooldownTimer) clearInterval(cooldownTimer)
})

function startCooldown(seconds: number) {
  smsCooldown.value = seconds
  if (cooldownTimer) clearInterval(cooldownTimer)
  cooldownTimer = setInterval(() => {
    smsCooldown.value -= 1
    if (smsCooldown.value <= 0 && cooldownTimer) {
      clearInterval(cooldownTimer)
      cooldownTimer = null
    }
  }, 1000)
}

async function sendLoginSms() {
  if (!/^1\d{10}$/.test(phoneForm.phone.trim())) {
    ElMessage.warning('请输入有效的11位手机号')
    return
  }
  smsLoading.value = true
  try {
    const res = await authApi.sendSms({ phone: phoneForm.phone.trim(), scene: 'login' })
    startCooldown(res.cooldown || 60)
    ElMessage.success(res.dev_hint || '验证码已发送')
  } catch {
    // 错误由拦截器展示
  } finally {
    smsLoading.value = false
  }
}

async function submitPassword() {
  if (!passwordForm.username || !passwordForm.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const user = await auth.login(passwordForm.username, passwordForm.password)
    ElMessage.success(`欢迎，${user.display_name}`)
    router.push('/home')
  } catch {
    // 错误提示由 http 拦截器统一展示
  } finally {
    loading.value = false
  }
}

async function submitPhone() {
  if (!/^1\d{10}$/.test(phoneForm.phone.trim())) {
    ElMessage.warning('请输入有效的11位手机号')
    return
  }
  if (!/^\d{4,8}$/.test(phoneForm.code.trim())) {
    ElMessage.warning('请输入验证码')
    return
  }
  loading.value = true
  try {
    const user = await auth.loginByPhone(phoneForm.phone.trim(), phoneForm.code.trim())
    ElMessage.success(`欢迎，${user.display_name}`)
    router.push('/home')
  } catch {
    // 错误由拦截器展示
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-bg" aria-hidden="true" />

    <header class="auth-top">
      <button type="button" class="auth-brand" @click="router.push('/welcome')">
        <span class="auth-brand__mark" aria-hidden="true">∞</span>
        <span>CodeInfinity</span>
      </button>
      <button type="button" class="auth-back" @click="router.push('/welcome')">← 返回首页</button>
    </header>

    <main class="auth-shell">
      <aside class="auth-aside">
        <p class="auth-aside__eyebrow">多课程智能教学平台</p>
        <h2 class="auth-aside__title">把问、学、测连成一条线</h2>
        <ul class="auth-aside__list">
          <li>课程资料一键入库，随时检索答疑</li>
          <li>章节考核自动组卷，弱项一目了然</li>
          <li>智能体可共享采纳，班级独立运行</li>
        </ul>
      </aside>

      <section class="auth-card">
        <h1 class="auth-title">欢迎回来</h1>
        <p class="auth-sub">支持用户名密码，或手机号验证码登录</p>

        <div class="auth-tabs" role="tablist">
          <button
            type="button"
            class="auth-tab"
            :class="{ 'auth-tab--active': loginTab === 'password' }"
            @click="loginTab = 'password'"
          >
            密码登录
          </button>
          <button
            type="button"
            class="auth-tab"
            :class="{ 'auth-tab--active': loginTab === 'phone' }"
            @click="loginTab = 'phone'"
          >
            验证码登录
          </button>
        </div>

        <el-form
          v-if="loginTab === 'password'"
          class="auth-form"
          label-position="top"
          @keyup.enter="submitPassword"
        >
          <el-form-item label="用户名">
            <el-input
              v-model="passwordForm.username"
              size="large"
              placeholder="请输入用户名"
              autocomplete="username"
            />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="passwordForm.password"
              type="password"
              size="large"
              show-password
              placeholder="请输入密码"
              autocomplete="current-password"
            />
          </el-form-item>
          <el-button class="auth-submit" type="primary" size="large" :loading="loading" @click="submitPassword">
            登录
          </el-button>
        </el-form>

        <el-form v-else class="auth-form" label-position="top" @keyup.enter="submitPhone">
          <el-form-item label="手机号">
            <el-input
              v-model="phoneForm.phone"
              size="large"
              maxlength="11"
              placeholder="请输入11位手机号"
              autocomplete="tel"
            />
          </el-form-item>
          <el-form-item label="验证码">
            <div class="code-row">
              <el-input
                v-model="phoneForm.code"
                size="large"
                maxlength="8"
                placeholder="请输入验证码"
                autocomplete="one-time-code"
              />
              <el-button
                class="code-btn"
                size="large"
                :loading="smsLoading"
                :disabled="smsCooldown > 0"
                @click="sendLoginSms"
              >
                {{ smsCooldown > 0 ? `${smsCooldown}s` : '获取验证码' }}
              </el-button>
            </div>
          </el-form-item>
          <el-button class="auth-submit" type="primary" size="large" :loading="loading" @click="submitPhone">
            登录
          </el-button>
        </el-form>

        <p class="auth-footer">
          还没有账号？
          <button type="button" class="auth-footer__link" @click="router.push('/register')">免费注册</button>
        </p>
      </section>
    </main>
  </div>
</template>

<style scoped>
.auth-page {
  --bg: #f5f7fa;
  --ink: #303133;
  --muted: #606266;
  --line: #e4e7ed;
  --accent: #409eff;
  --accent-hover: #66b1ff;
  --surface: #ffffff;

  position: relative;
  min-height: 100vh;
  overflow: hidden;
  background: var(--bg);
  color: var(--ink);
  font-family: 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.auth-bg {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 70% 50% at 15% 20%, rgba(64, 158, 255, 0.12), transparent 55%),
    radial-gradient(ellipse 50% 40% at 90% 80%, rgba(64, 158, 255, 0.08), transparent 50%),
    linear-gradient(180deg, #f8fbff 0%, #f5f7fa 55%, #eef2f6 100%);
  pointer-events: none;
}

.auth-top {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 920px;
  margin: 0 auto;
  padding: 22px 24px;
}

.auth-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 0;
  border: none;
  background: none;
  cursor: pointer;
  font-weight: 700;
  font-size: 1.05rem;
  letter-spacing: -0.02em;
  color: var(--ink);
}

.auth-brand__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(64, 158, 255, 0.12);
  color: var(--accent);
  font-size: 0.95rem;
}

.auth-back {
  padding: 8px 12px;
  border: none;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 0.9rem;
  color: var(--muted);
  transition: background 0.2s ease, color 0.2s ease;
}

.auth-back:hover {
  background: rgba(64, 158, 255, 0.08);
  color: var(--accent);
}

.auth-shell {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 28px;
  max-width: 920px;
  margin: 0 auto;
  padding: 28px 24px 64px;
  animation: fade-up 0.5s ease both;
}

.auth-aside {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 12px 8px 12px 4px;
}

.auth-aside__eyebrow {
  margin: 0 0 12px;
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--accent);
}

.auth-aside__title {
  margin: 0 0 20px;
  font-size: clamp(1.6rem, 3vw, 2rem);
  font-weight: 700;
  line-height: 1.25;
  letter-spacing: -0.02em;
}

.auth-aside__list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.auth-aside__list li {
  position: relative;
  padding-left: 18px;
  font-size: 0.95rem;
  line-height: 1.55;
  color: var(--muted);
}

.auth-aside__list li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.55em;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
}

.auth-card {
  padding: 36px 36px 32px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  box-shadow: 0 1px 2px rgba(48, 49, 51, 0.04), 0 12px 32px rgba(48, 49, 51, 0.06);
}

.auth-title {
  margin: 0 0 8px;
  font-size: 1.65rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.auth-sub {
  margin: 0 0 22px;
  color: var(--muted);
  line-height: 1.55;
  font-size: 0.95rem;
}

.auth-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  margin-bottom: 22px;
  padding: 4px;
  border-radius: 12px;
  background: #f0f2f5;
}

.auth-tab {
  border: none;
  border-radius: 10px;
  padding: 10px 12px;
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  color: var(--muted);
  transition: background 0.2s ease, color 0.2s ease, box-shadow 0.2s ease;
}

.auth-tab--active {
  background: var(--surface);
  color: var(--accent);
  box-shadow: 0 1px 3px rgba(48, 49, 51, 0.08);
}

.auth-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

.auth-form :deep(.el-form-item__label) {
  color: var(--muted);
  font-weight: 500;
}

.auth-form :deep(.el-input__wrapper) {
  border-radius: 10px;
  background: #fafbfc;
  box-shadow: 0 0 0 1px var(--line) inset;
  transition: box-shadow 0.2s ease, background 0.2s ease;
}

.auth-form :deep(.el-input__wrapper:hover) {
  background: var(--surface);
}

.auth-form :deep(.el-input__wrapper.is-focus) {
  background: var(--surface);
  box-shadow: 0 0 0 1px var(--accent) inset, 0 0 0 3px rgba(64, 158, 255, 0.12);
}

.code-row {
  display: flex;
  gap: 10px;
  width: 100%;
}

.code-row .el-input {
  flex: 1;
}

.code-btn {
  flex-shrink: 0;
  min-width: 112px;
  border-radius: 10px !important;
}

.auth-submit {
  width: 100%;
  height: 46px;
  margin-top: 6px;
  border: none;
  border-radius: 10px;
  font-weight: 600;
  font-size: 0.98rem;
  background: var(--accent) !important;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.28);
}

.auth-submit:hover {
  background: var(--accent-hover) !important;
}

.auth-footer {
  margin: 22px 0 0;
  text-align: center;
  font-size: 0.9rem;
  color: var(--muted);
}

.auth-footer__link {
  padding: 0;
  border: none;
  background: none;
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  color: var(--accent);
}

.auth-footer__link:hover {
  text-decoration: underline;
  text-underline-offset: 3px;
}

@keyframes fade-up {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 780px) {
  .auth-shell {
    grid-template-columns: 1fr;
    gap: 20px;
    padding-top: 12px;
  }

  .auth-aside {
    padding: 0 4px;
  }

  .auth-aside__title {
    margin-bottom: 14px;
  }

  .auth-card {
    padding: 28px 22px 24px;
  }
}
</style>

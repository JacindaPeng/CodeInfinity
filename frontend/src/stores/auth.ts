import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi, type UserOut } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('token') || '')
  const user = ref<UserOut | null>(null)

  function setToken(t: string) {
    token.value = t
    localStorage.setItem('token', t)
  }

  async function login(username: string, password: string) {
    const data = await authApi.login({ username, password })
    setToken(data.access_token)
    user.value = data.user
    return data.user
  }

  async function loginByPhone(phone: string, code: string) {
    const data = await authApi.loginByPhone({ phone, code })
    setToken(data.access_token)
    user.value = data.user
    return data.user
  }

  async function fetchMe() {
    if (!token.value) return null
    try {
      user.value = await authApi.me()
      return user.value
    } catch {
      token.value = ''
      user.value = null
      localStorage.removeItem('token')
      return null
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
  }

  return { token, user, login, loginByPhone, fetchMe, logout, setToken }
})

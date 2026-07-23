import http from './index'

export interface EnrollmentOut {
  class_id: number
  class_name: string
  course_id: number
  course_name: string
}

export interface UserOut {
  id: number
  username: string
  role: string
  display_name: string
  phone?: string | null
  class_id: number | null
  class_name: string | null
  enrollments?: EnrollmentOut[]
  created_at: string
}

export type SmsScene = 'register' | 'login'

export interface SmsSendResult {
  ok: boolean
  phone: string
  expires_in: number
  cooldown: number
  dev_hint?: string
}

export const authApi = {
  sendSms: (data: { phone: string; scene: SmsScene }) =>
    http.post<SmsSendResult>('/auth/sms/send', data).then((r) => r.data),
  register: (data: {
    username: string
    password: string
    role?: string
    display_name?: string
    phone: string
    code: string
  }) => http.post<UserOut>('/auth/register', data).then((r) => r.data),
  login: (data: { username: string; password: string }) =>
    http.post<{ access_token: string; user: UserOut }>('/auth/login', data).then((r) => r.data),
  loginByPhone: (data: { phone: string; code: string }) =>
    http.post<{ access_token: string; user: UserOut }>('/auth/login/phone', data).then((r) => r.data),
  me: () => http.get<UserOut>('/users/me').then((r) => r.data),
}

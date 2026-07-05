import http from './index'

export interface UserOut {
  id: number
  username: string
  role: string
  display_name: string
  created_at: string
}

export const authApi = {
  register: (data: { username: string; password: string; role?: string; display_name?: string }) =>
    http.post<UserOut>('/auth/register', data).then((r) => r.data),
  login: (data: { username: string; password: string }) =>
    http.post<{ access_token: string; user: UserOut }>('/auth/login', data).then((r) => r.data),
  me: () => http.get<UserOut>('/users/me').then((r) => r.data),
}

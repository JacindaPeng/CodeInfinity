import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  { path: '/login', component: () => import('@/views/Login.vue'), meta: { public: true } },
  { path: '/register', component: () => import('@/views/Register.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('@/views/Layout.vue'),
    children: [
      { path: '', redirect: '/home' },
      { path: 'home', component: () => import('@/views/Home.vue') },
      { path: 'chat', component: () => import('@/views/Chat.vue'), meta: { roles: 'student,teacher' } },
      { path: 'agents', component: () => import('@/views/AgentManage.vue') },
      { path: 'agents/:id', component: () => import('@/views/AgentIntro.vue') },
      { path: 'agents/:id/home', component: () => import('@/views/CourseAgentHome.vue') },
      { path: 'course-qa', component: () => import('@/views/CourseQA.vue'), meta: { roles: 'student,teacher' } },
      { path: 'chapters', component: () => import('@/views/ChapterRoute.vue'), meta: { roles: 'student,teacher' } },
      { path: 'my-class', component: () => import('@/views/MyClass.vue'), meta: { roles: 'student' } },
      { path: 'exams/:id', component: () => import('@/views/ExamRunner.vue') },
      { path: 'exams/:id/report', component: () => import('@/views/ExamReport.vue') },
      { path: 'llm-config', component: () => import('@/views/LLMConfig.vue'), meta: { roles: 'admin' } },
      { path: 'logs', component: () => import('@/views/CallLogs.vue'), meta: { roles: 'teacher' } },
      { path: 'teacher/materials', component: () => import('@/views/teacher/Materials.vue'), meta: { roles: 'teacher' } },
      { path: 'teacher/classes', component: () => import('@/views/teacher/Classes.vue'), meta: { roles: 'teacher' } },
      { path: 'teacher/exam-config', component: () => import('@/views/teacher/ExamConfig.vue'), meta: { roles: 'teacher' } },
      { path: 'teacher/question-bank', component: () => import('@/views/teacher/QuestionBank.vue'), meta: { roles: 'teacher' } },
      { path: 'teacher/exam-records', component: () => import('@/views/teacher/ExamRecords.vue'), meta: { roles: 'teacher' } },
      { path: 'teacher/exams/:id/report', component: () => import('@/views/ExamReport.vue'), meta: { roles: 'teacher' } },
      { path: 'admin/users', component: () => import('@/views/admin/Users.vue'), meta: { roles: 'admin' } },
      { path: 'admin/exam-records', component: () => import('@/views/teacher/ExamRecords.vue'), meta: { roles: 'admin' } },
      { path: 'admin/exams/:id/report', component: () => import('@/views/ExamReport.vue'), meta: { roles: 'admin' } },
      { path: 'admin/logs', component: () => import('@/views/CallLogs.vue'), meta: { roles: 'admin' } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (!auth.token) return '/login'
  if (!auth.user) await auth.fetchMe()
  if (!auth.user) return '/login'
  const roles = (to.meta.roles as string | undefined)?.split(',')
  if (roles && !roles.includes(auth.user.role)) {
    return '/home'
  }
  return true
})

export default router

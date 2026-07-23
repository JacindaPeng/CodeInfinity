import { defineStore } from 'pinia'
import { ref } from 'vue'
import http from '@/api'

export interface CourseAgentInfo {
  id: number
  name: string
  intro: string
  endpoint: string
  course_id: number | null
  course_name: string
  slug: string
  status: 'active' | 'planned' | string
  owner_id?: number | null
  owner_name?: string
  source_agent_id?: number | null
  is_adopted?: boolean
  is_shared?: boolean
  is_owner?: boolean
  /** 拥有者或已绑定班级的任课教师可维护资料/题库/考核 */
  can_manage_content?: boolean
  bound_class_ids?: number[]
  shared_content_class_ids?: number[]
  uses_preset_chapters?: boolean
}

/** 仅「共享广场只读体验」：非拥有者、非采纳副本、且无权管理内容 */
export function isAgentSharedPreview(agent: CourseAgentInfo | null | undefined): boolean {
  if (!agent) return false
  if (agent.can_manage_content || agent.is_owner) return false
  return !!agent.is_shared && !agent.source_agent_id
}

const STORAGE_KEY = 'course_agent_id'

export const useCourseAgentStore = defineStore('courseAgent', () => {
  const current = ref<CourseAgentInfo | null>(null)
  const restoring = ref(false)

  function setAgent(agent: CourseAgentInfo) {
    current.value = agent
    localStorage.setItem(STORAGE_KEY, String(agent.id))
  }

  function clearAgent() {
    current.value = null
    localStorage.removeItem(STORAGE_KEY)
  }

  function isActive() {
    return current.value?.status === 'active'
  }

  async function restoreAgent(): Promise<CourseAgentInfo | null> {
    if (current.value) return current.value
    const saved = localStorage.getItem(STORAGE_KEY)
    if (!saved) return null
    restoring.value = true
    try {
      const { data } = await http.get<CourseAgentInfo>(`/agents/${saved}`)
      current.value = data
      return data
    } catch {
      localStorage.removeItem(STORAGE_KEY)
      return null
    } finally {
      restoring.value = false
    }
  }

  return { current, restoring, setAgent, clearAgent, isActive, restoreAgent }
})

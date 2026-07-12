import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface CourseAgentInfo {
  id: number
  name: string
  intro: string
  endpoint: string
  course_id: number | null
  course_name: string
  slug: string
  status: 'active' | 'planned' | string
}

const STORAGE_KEY = 'course_agent_id'

export const useCourseAgentStore = defineStore('courseAgent', () => {
  const current = ref<CourseAgentInfo | null>(null)

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

  return { current, setAgent, clearAgent, isActive }
})

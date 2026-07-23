import { computed, type Ref } from 'vue'
import { useCourseAgentStore } from '@/stores/courseAgent'

interface CourseItem {
  id: number
  name: string
}

/** 课程智能体上下文中锁定当前课程，教学页仅展示课程名、不可切换。 */
export function useAgentCourseScope() {
  const agentStore = useCourseAgentStore()

  const lockedCourse = computed(() => {
    const agent = agentStore.current
    if (!agent?.course_id) return null
    return {
      id: agent.course_id,
      name: agent.course_name || '当前课程',
    }
  })

  function applyLockedCourse(
    selectedCourseId: Ref<number | undefined>,
    courses: Ref<CourseItem[]>,
  ): boolean {
    const locked = lockedCourse.value
    if (!locked) return false
    selectedCourseId.value = locked.id
    courses.value = [{ id: locked.id, name: locked.name }]
    return true
  }

  /** 章节列表/进度 API 参数：动态课程按智能体隔离章节。 */
  function chapterListParams(extra: Record<string, number> = {}) {
    const params: Record<string, number> = { ...extra }
    const agent = agentStore.current
    if (agent?.course_id) params.course_id = agent.course_id
    if (agent?.id) params.agent_id = agent.id
    return params
  }

  return { lockedCourse, applyLockedCourse, chapterListParams }
}

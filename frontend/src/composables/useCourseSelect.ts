import type { Ref } from 'vue'
import { ElMessage } from 'element-plus'
import http from '@/api'

export interface CourseItem {
  id: number
  name: string
  description?: string
}

/** 课程下拉：选择已有课程，或输入名称创建新课程。 */
export function useCourseSelect(courses: Ref<CourseItem[]>) {
  async function resolveCourseSelection(
    val: number | string | null | undefined,
    onResolved: (id: number | null) => void,
  ) {
    if (val === null || val === undefined || val === '') {
      onResolved(null)
      return
    }
    if (typeof val === 'number') {
      onResolved(val)
      return
    }
    const name = String(val).trim()
    if (!name) {
      onResolved(null)
      return
    }
    const existing = courses.value.find(c => c.name === name)
    if (existing) {
      onResolved(existing.id)
      return
    }
    try {
      const { data } = await http.post<CourseItem>('/courses', { name })
      courses.value = [...courses.value, data]
      onResolved(data.id)
      ElMessage.success(`已创建课程「${data.name}」`)
    } catch {
      onResolved(null)
    }
  }

  return { resolveCourseSelection }
}

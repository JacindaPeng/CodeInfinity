import { computed } from 'vue'
import http from '@/api'
import {
  useCourseAgentStore,
  isAgentSharedPreview,
  type CourseAgentInfo,
} from '@/stores/courseAgent'

export interface ScopedClassItem {
  id: number
  name: string
  course_id?: number | null
}

/** 智能体上下文中班级列表 = 教师所管班级 ∩ 智能体已绑定班级 */
export function useAgentBoundClasses() {
  const agentStore = useCourseAgentStore()

  const inAgentContext = computed(() => !!agentStore.current?.id)

  /** 共享广场只读体验（任课教师可管理内容时不算预览） */
  const isSharedPreview = computed(() => isAgentSharedPreview(agentStore.current))

  async function refreshAgentBindings() {
    const agent = agentStore.current
    if (!agent?.id) return
    try {
      const { data } = await http.get<CourseAgentInfo>(`/agents/${agent.id}`)
      if (data) agentStore.setAgent(data)
    } catch {
      /* keep cached */
    }
  }

  async function loadScopedClasses(): Promise<ScopedClassItem[]> {
    const { data: all } = await http.get<ScopedClassItem[]>('/classes/mine')
    if (!agentStore.current?.id) return all
    await refreshAgentBindings()
    const agent = agentStore.current
    if (!agent) return all

    // 体验共享广场：源绑定班 + 源资料/题库所在班（可非本人班级）
    if (isAgentSharedPreview(agent)) {
      const ids = [
        ...new Set([
          ...(agent.shared_content_class_ids || []).map(Number),
          ...(agent.bound_class_ids || []).map(Number),
        ].filter(Boolean)),
      ]
      if (!ids.length) return []
      return ids.map(id => {
        const hit = all.find(c => c.id === id)
        return hit || { id, name: `共享班级 #${id}` }
      })
    }

    const bound = new Set((agent.bound_class_ids || []).map(Number))
    if (!bound.size) return []
    return all.filter(c => bound.has(c.id))
  }

  function pickClassId(
    classes: ScopedClassItem[],
    current: number | undefined,
    storageKey?: string,
  ): number | undefined {
    const saved = storageKey ? Number(localStorage.getItem(storageKey) || 0) : 0
    if (saved && classes.some(c => c.id === saved)) return saved
    if (current && classes.some(c => c.id === current)) return current
    return classes[0]?.id
  }

  function syncMultiClassIds(classes: ScopedClassItem[], selected: number[]): number[] {
    const allowed = new Set(classes.map(c => c.id))
    const kept = selected.filter(id => allowed.has(id))
    if (kept.length) return kept
    // 共享只读：默认只选第一个标签，便于加载考核配置
    if (isSharedPreview.value) {
      return classes[0] ? [classes[0].id] : []
    }
    return classes.map(c => c.id)
  }

  return {
    inAgentContext,
    isSharedPreview,
    loadScopedClasses,
    pickClassId,
    syncMultiClassIds,
    refreshAgentBindings,
  }
}

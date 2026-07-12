<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ content: string }>()

const html = computed(() => renderMarkdown(props.content || ''))
</script>

<template>
  <div class="markdown-body" v-html="html"></div>
</template>

<style scoped>
.markdown-body {
  line-height: 1.7;
  font-size: 14px;
}
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 12px 0 6px;
  font-weight: 600;
}
.markdown-body :deep(h1) { font-size: 18px; }
.markdown-body :deep(h2) { font-size: 16px; }
.markdown-body :deep(h3) { font-size: 15px; }
.markdown-body :deep(h4) { font-size: 14px; }
.markdown-body :deep(p) { margin: 6px 0; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) { margin: 6px 0; padding-left: 20px; }
.markdown-body :deep(li) { margin: 2px 0; }
.markdown-body :deep(code) {
  background: #f5f5f5;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: Consolas, Monaco, monospace;
  font-size: 13px;
}
.markdown-body :deep(pre) {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 8px 0;
}
.markdown-body :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
}
.markdown-body :deep(blockquote) {
  border-left: 3px solid #ddd;
  padding-left: 12px;
  margin: 8px 0;
  color: #666;
}
.markdown-body :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #ddd;
  padding: 6px 12px;
}
.markdown-body :deep(th) {
  background: #f5f5f5;
  font-weight: 600;
}
.markdown-body :deep(strong) { font-weight: 600; }
.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid #eee;
  margin: 12px 0;
}
.markdown-body :deep(a) {
  color: #409eff;
  text-decoration: none;
}
</style>

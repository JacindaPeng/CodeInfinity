import { marked } from 'marked'

// 配置 marked：禁用原始 HTML，换行转 <br>
marked.setOptions({
  breaks: true,
  gfm: true,
})

let _div: HTMLDivElement | null = null
function getDiv(): HTMLDivElement {
  if (!_div) _div = document.createElement('div')
  return _div
}

/** 将 Markdown 文本渲染为安全的 HTML */
export function renderMarkdown(text: string): string {
  if (!text) return ''
  const html = marked.parse(text, { async: false }) as string
  // 用浏览器 DOM 做基本清洗：移除 script/style 标签
  const div = getDiv()
  div.innerHTML = html
  div.querySelectorAll('script, style, iframe, object, embed').forEach(el => el.remove())
  return div.innerHTML
}

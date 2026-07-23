/** 智能体编程语言 slug（与后端 Agent.slug 一致，小写+连字符） */
export interface AgentLanguage {
  slug: string
  label: string
  color: string
  bg: string
}

export const AGENT_LANGUAGES: AgentLanguage[] = [
  { slug: 'c', label: 'C', color: '#409eff', bg: '#ecf5ff' },
  { slug: 'cpp', label: 'C++', color: '#00599c', bg: '#e8f4fc' },
  { slug: 'csharp', label: 'C#', color: '#68217a', bg: '#f3eaf5' },
  { slug: 'python', label: 'Python', color: '#67c23a', bg: '#f0f9eb' },
  { slug: 'java', label: 'Java', color: '#e6a23c', bg: '#fdf6ec' },
  { slug: 'javascript', label: 'JavaScript', color: '#f7df1e', bg: '#fefce8' },
  { slug: 'typescript', label: 'TypeScript', color: '#3178c6', bg: '#eef4fb' },
  { slug: 'go', label: 'Go', color: '#00add8', bg: '#e6f7fb' },
  { slug: 'rust', label: 'Rust', color: '#dea584', bg: '#faf3ed' },
  { slug: 'kotlin', label: 'Kotlin', color: '#7f52ff', bg: '#f2edff' },
  { slug: 'swift', label: 'Swift', color: '#f05138', bg: '#fef0ed' },
  { slug: 'ruby', label: 'Ruby', color: '#cc342d', bg: '#fceeed' },
  { slug: 'php', label: 'PHP', color: '#777bb4', bg: '#f0f0f8' },
  { slug: 'scala', label: 'Scala', color: '#dc322f', bg: '#fceeed' },
  { slug: 'r', label: 'R', color: '#276dc3', bg: '#eaf2fb' },
  { slug: 'julia', label: 'Julia', color: '#9558b2', bg: '#f5eef8' },
  { slug: 'matlab', label: 'MATLAB', color: '#e16737', bg: '#fdf0ea' },
  { slug: 'lua', label: 'Lua', color: '#000080', bg: '#ececf8' },
  { slug: 'perl', label: 'Perl', color: '#39457e', bg: '#ecedf5' },
  { slug: 'haskell', label: 'Haskell', color: '#5e5086', bg: '#efedf5' },
  { slug: 'elixir', label: 'Elixir', color: '#6e4a7e', bg: '#f1edf4' },
  { slug: 'erlang', label: 'Erlang', color: '#a90533', bg: '#fceef2' },
  { slug: 'dart', label: 'Dart', color: '#0175c2', bg: '#e8f4fb' },
  { slug: 'objc', label: 'Objective-C', color: '#438eff', bg: '#edf4ff' },
  { slug: 'assembly', label: 'Assembly', color: '#5c6bc0', bg: '#eef0f9' },
  { slug: 'sql', label: 'SQL', color: '#336791', bg: '#ebf2f7' },
  { slug: 'shell', label: 'Shell', color: '#4eaa25', bg: '#edf8ea' },
  { slug: 'bash', label: 'Bash', color: '#3d3d3d', bg: '#f0f0f0' },
  { slug: 'powershell', label: 'PowerShell', color: '#012456', bg: '#e8edf5' },
  { slug: 'groovy', label: 'Groovy', color: '#4298b8', bg: '#ecf6f9' },
  { slug: 'clojure', label: 'Clojure', color: '#5881d8', bg: '#eef3fb' },
  { slug: 'fsharp', label: 'F#', color: '#378bba', bg: '#ebf4f9' },
  { slug: 'vbnet', label: 'VB.NET', color: '#945499', bg: '#f5eef5' },
  { slug: 'zig', label: 'Zig', color: '#f7a41d', bg: '#fef6ea' },
  { slug: 'nim', label: 'Nim', color: '#ffe953', bg: '#fffef0' },
  { slug: 'ocaml', label: 'OCaml', color: '#ec6813', bg: '#fdf0e8' },
  { slug: 'prolog', label: 'Prolog', color: '#74283c', bg: '#f5ecef' },
  { slug: 'fortran', label: 'Fortran', color: '#734f96', bg: '#f2edf6' },
  { slug: 'cobol', label: 'COBOL', color: '#005ca5', bg: '#e8f2f9' },
  { slug: 'pascal', label: 'Pascal / Delphi', color: '#e3a849', bg: '#fdf8ed' },
  { slug: 'verilog', label: 'Verilog', color: '#c792ea', bg: '#f8f0fd' },
  { slug: 'vhdl', label: 'VHDL', color: '#0d7377', bg: '#e7f4f4' },
  { slug: 'solidity', label: 'Solidity', color: '#363636', bg: '#f0f0f0' },
  { slug: 'racket', label: 'Racket', color: '#9f1d20', bg: '#fceeee' },
  { slug: 'lisp', label: 'Lisp / Scheme', color: '#3fb68b', bg: '#ecf9f4' },
  { slug: 'wasm', label: 'WebAssembly', color: '#654ff0', bg: '#f0edfe' },
  { slug: 'c-lang', label: 'C（旧 slug）', color: '#409eff', bg: '#ecf5ff' },
]

const THEME_MAP = Object.fromEntries(
  AGENT_LANGUAGES.flatMap(l => [[l.slug, { color: l.color, bg: l.bg }]]),
)

/** 筛选时 slug 别名（如 c 包含历史 c-lang） */
export const LANG_FILTER_ALIASES: Record<string, string[]> = {
  c: ['c', 'c-lang'],
}

export function slugTheme(slug: string) {
  return THEME_MAP[slug] || { color: '#909399', bg: '#f4f4f5' }
}

export function slugLabel(slug: string) {
  return AGENT_LANGUAGES.find(l => l.slug === slug)?.label || slug
}

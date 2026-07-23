"""智能体编程语言 slug 与筛选别名。"""

# 筛选「C」时同时匹配历史 c-lang
LANG_FILTER_ALIASES: dict[str, list[str]] = {
    "c": ["c", "c-lang"],
}

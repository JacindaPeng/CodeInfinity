"""按章节标题切分 PDF 页面归属。

输入：PDF 全页文本 + 已知章节列表（来自 DB chapters 表）
输出：[{chapter_id, chapter_title, start_page, end_page}]

算法：
1. 跳过目录页（含点引导符 ... 或 ．．的页面）
2. 对每个非目录页，先匹配 "第N章" 模式；若无，匹配章节标题文本（如"数据类型与输入输出"）
3. 每章在非目录页中的首次检测位置 = 该章起始页
4. 无匹配的页面回溯到最近检测到的章节（carry-forward）
"""
from __future__ import annotations

import re
from typing import Any

# 匹配 "第0章" / "第 1 章" / "第12章 概述" 等
_CHAPTER_PATTERN = re.compile(r"第\s*(\d+)\s*章")

# 点引导符（目录页特征）：英文省略号或中文全角点
_DOT_LEADER_PATTERN = re.compile(r"\.{3,}|．．+|…+")


def _is_toc_page(text: str) -> bool:
    """检测是否为目录页：含点引导符。"""
    if not text:
        return False
    # 只看前 800 字符（目录条目集中在页面前部）
    head = text[:800]
    return bool(_DOT_LEADER_PATTERN.search(head))


def _extract_title_text(full_title: str) -> str:
    """从 "第5章 数据类型与输入输出" 提取 "数据类型与输入输出"。"""
    m = _CHAPTER_PATTERN.match(full_title.strip())
    if m:
        rest = full_title.strip()[m.end():].strip()
        return rest
    return full_title.strip()


def split_pdf_by_chapters(
    pages_text: list[str],
    chapters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """将 PDF 每页归到对应章节。

    Args:
        pages_text: 每页提取的文本，索引即页码(0-based)
        chapters: [{id, title, order_idx}] 来自 DB，按 order_idx 排序

    Returns:
        [{chapter_id, chapter_title, order_idx, start_page, end_page}]
        start_page/end_page 为 1-based 页码，end_page 含本页
    """
    if not chapters or not pages_text:
        return []

    chapters_sorted = sorted(chapters, key=lambda c: c["order_idx"])
    chapter_map = {c["order_idx"]: c for c in chapters_sorted}

    # 构造 order_idx -> title_text 映射（用于标题文本匹配）
    title_to_order: dict[str, int] = {}
    for c in chapters_sorted:
        title_text = _extract_title_text(c["title"])
        # 只对长度>=3的标题文本做匹配，避免"数组"等短词误判
        if len(title_text) >= 3:
            title_to_order[title_text] = c["order_idx"]

    # 第一遍：为每个非目录页检测所属章节
    # 只检查页面最顶部 80 字符（页眉区域），避免正文交叉引用误判
    HEADER_LEN = 80
    page_chapter: dict[int, int] = {}  # page_idx(0-based) -> order_idx
    for i, text in enumerate(pages_text):
        if not text:
            continue
        if _is_toc_page(text):
            continue  # 跳过目录页

        head = text[:HEADER_LEN]
        # 1) 先匹配 "第N章" 模式（页眉）
        m = _CHAPTER_PATTERN.search(head)
        if m:
            order = int(m.group(1))
            if order in chapter_map:
                page_chapter[i] = order
                continue

        # 2) 匹配章节标题文本（如 "数据类型与输入输出"）——仅限页眉区域
        for title_text, order in title_to_order.items():
            if title_text in head:
                page_chapter[i] = order
                break

    # 第二遍：carry-forward 填充无检测的页面
    # 单调推进：一旦进入第N章，不再回退到更早的章节（避免正文交叉引用"见第1章"误判）
    last_order: int | None = None
    for i in range(len(pages_text)):
        if _is_toc_page(pages_text[i] or ""):
            continue  # 目录页不分配
        if i in page_chapter:
            order = page_chapter[i]
            # 只接受 >= 当前章节的匹配（单调推进）
            if last_order is None or order >= last_order:
                last_order = order
            # 否则忽略这个匹配（视为交叉引用/页眉残留）
        if last_order is not None and i not in page_chapter:
            page_chapter[i] = last_order
        elif last_order is not None and page_chapter.get(i) != last_order:
            # 该页匹配的章节 < 当前章节，修正为当前章节
            page_chapter[i] = last_order

    # 第三遍：构建每章的页码区间
    if not page_chapter:
        # 全部未识别，归到第一章
        first = chapters_sorted[0]
        return [{
            "chapter_id": first["id"],
            "chapter_title": first["title"],
            "order_idx": first["order_idx"],
            "start_page": 1,
            "end_page": len(pages_text),
        }]

    # 按章节分组
    chapter_pages: dict[int, list[int]] = {}
    for page_idx, order in page_chapter.items():
        chapter_pages.setdefault(order, []).append(page_idx)

    # 构建结果，按 order_idx 排序
    result = []
    for order in sorted(chapter_pages.keys()):
        if order not in chapter_map:
            continue
        pages = sorted(chapter_pages[order])
        ch = chapter_map[order]
        result.append({
            "chapter_id": ch["id"],
            "chapter_title": ch["title"],
            "order_idx": order,
            "start_page": pages[0] + 1,  # 1-based
            "end_page": pages[-1] + 1,
            "page_count": len(pages),
        })

    # 处理第一章节起始页之前的非目录页（前言/序言）：归到第一章
    if result:
        first_start = result[0]["start_page"]
        if first_start > 1:
            # 找到 first_start 之前是否有非目录页
            has_preface = any(
                not _is_toc_page(pages_text[i] or "")
                for i in range(first_start - 1)
                if i < len(pages_text)
            )
            if has_preface:
                result[0]["start_page"] = 1

    return result


def detect_chapters_in_pdf(pages_text: list[str]) -> list[tuple[int, int]]:
    """检测 PDF 中出现的章节标题，返回 [(order_idx, page_number), ...]。
    用于单章上传时判断是否含多章内容。跳过目录页。
    """
    found = []
    seen = set()
    for page_idx, text in enumerate(pages_text):
        if not text or _is_toc_page(text):
            continue
        head = text[:250]
        m = _CHAPTER_PATTERN.search(head)
        if m:
            order = int(m.group(1))
            if order not in seen:
                seen.add(order)
                found.append((order, page_idx + 1))
    return found

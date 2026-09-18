"""WebUI 顶部生成进度条的日志解析（纯函数，不依赖 gradio，便于单测）。

被解析的标记都由 audiobook_generator / web_ui 写入同一个日志文件：
- `📚 [i/n] 开始转换: 书名`  → 当前书籍，并把解析范围限定在这一本书内
- `Converting chapters from X to Y` / `Chapters count: N` → 章节总数
- `✅ Converted chapter X` → 已完成章节数
- `chapter-3_标题_chunk_2_of_16` → 章内块级进度（Chatterbox 等按块生成的引擎，
  单章耗时很长，靠它让进度条在章内也能往前走）
- `🎉 全部处理完毕` → 整个批次结束
"""

import re

# 当前书籍标记：[1/2] 开始转换: 书名
_BOOK_PATTERN = re.compile(r"\[\d+/\d+\] 开始转换: (.+)$", re.MULTILINE)
# 章节总数：优先用实际转换范围，其次用总章节数
_RANGE_PATTERN = re.compile(r"Converting chapters from (\d+) to (\d+)", re.MULTILINE)
_COUNT_PATTERN = re.compile(r"Chapters count: (\d+)", re.MULTILINE)
# 已完成章节
_DONE_PATTERN = re.compile(r"✅ Converted chapter (\d+)", re.MULTILINE)
# 块级进度：chapter-<章节号>_<标题>_chunk_<当前块>_of_<总块数>
_CHUNK_PATTERN = re.compile(r"chapter-(\d+)_.+?_chunk_(\d+)_of_(\d+)")
# 批次结束标记
_FINISHED_MARKER = "全部处理完毕"


def parse_progress(log_content: str) -> dict:
    """解析日志文本，返回当前进度状态。

    返回 dict：
    - book:     当前书名（未开始为空串）
    - total:    当前书籍要转换的章节数
    - done:     已完成章节数
    - pct:      进度百分比（0~100，含章内块级插值）
    - extra:    附加说明，例如「第 1 章 2/16 块」
    - finished: 整批是否结束
    - has_markers: 是否已经出现当前书籍的进度标记（用于区分"尚未启动"和"已开始"）
    """
    if not log_content:
        return {"book": "", "total": 0, "done": 0, "pct": 0, "extra": "",
                "finished": False, "has_markers": False}

    # 只解析当前这本书：从最后一次「开始转换」标记之后开始
    start_matches = list(_BOOK_PATTERN.finditer(log_content))
    if start_matches:
        current_book = start_matches[-1].group(1).strip()
        segment = log_content[start_matches[-1].end():]
    else:
        current_book = ""
        segment = log_content

    # 章节总数：优先用实际转换范围（例如只转第 3~5 章）
    total_chapters = 0
    range_match = _RANGE_PATTERN.findall(segment)
    if range_match:
        chapter_start, chapter_end = int(range_match[-1][0]), int(range_match[-1][1])
        total_chapters = max(0, chapter_end - chapter_start + 1)
    else:
        count_match = _COUNT_PATTERN.findall(segment)
        if count_match:
            total_chapters = int(count_match[-1])

    completed_indices = {int(x) for x in _DONE_PATTERN.findall(segment)}
    completed = len(completed_indices)

    # 章内块级进度插值
    extra = ""
    chunk_fraction = 0.0
    chunk_match = _CHUNK_PATTERN.findall(segment)
    if chunk_match:
        chapter_idx, current_chunk, total_chunks = (int(x) for x in chunk_match[-1])
        # 只在该章还没完成时参与插值，避免与「Converted chapter」重复计数
        # （worker_count>1 时章节完成顺序不固定，因此按章节号判断）
        if total_chunks > 0 and chapter_idx not in completed_indices:
            # 当前块刚打印「处理 …」还没结束，因此已完成块数按 current_chunk - 1 计
            chunk_fraction = max(0, current_chunk - 1) / total_chunks
            extra = f"第 {chapter_idx} 章 {current_chunk}/{total_chunks} 块"

    pct = 0
    if total_chapters > 0:
        pct = min(100, int((completed + chunk_fraction) / total_chapters * 100))

    return {
        "book": current_book,
        "total": total_chapters,
        "done": completed,
        "pct": pct,
        "extra": extra,
        "finished": _FINISHED_MARKER in log_content,
        "has_markers": bool(current_book) or total_chapters > 0,
    }

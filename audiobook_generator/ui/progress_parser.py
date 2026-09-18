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
        # 只在"当前这本书"的日志片段里找结束标记：日志文件是整个 UI 会话共用的，
        # 若用全文件搜索，上一批的"全部处理完毕"会让下一次生成的进度条一直停在已完成。
        "finished": _FINISHED_MARKER in segment,
        "has_markers": bool(current_book) or total_chapters > 0,
    }


# 进度条展示模式 → 前端样式类（见 web_ui.CUSTOM_CSS / HEAD_HTML 中的脚本）
MODE_IDLE = "idle"              # 还没开始
MODE_STARTING = "starting"      # 批次已启动，日志还没写出标记（chatterbox 加载模型期间）
MODE_RUNNING = "running"        # 正在生成
MODE_BOOK_DONE = "book_done"    # 当前这本书完成（批次里可能还有下一本）
MODE_FINISHED = "finished"      # 整批完成
MODE_INTERRUPTED = "interrupted"  # 中途失败/被中断
MODE_FAILED = "failed"          # 启动阶段就失败（日志里没有任何标记）


def decide_progress_state(state: dict, run_alive: bool, batch_started: bool = False,
                          manually_stopped: bool = False) -> dict:
    """把「日志解析结果 + 批次是否还在跑」映射为进度条展示状态（纯函数，便于单测）。

    batch_started 表示"启动过批次（running_process 不为 None）"，
    用于区分「从未启动（空闲）」和「启动后进程已退出（中断/失败）」。
    manually_stopped 表示这次结束是用户点了「停止转换」，文案要显示成"已停止"。

    返回 dict：
    - mode:   展示模式（上面的 MODE_* 常量）
    - status: 状态文案
    - pct:    0~100
    - detail: 细节文案，例如「章节 1/3 · 第 2 章 1/4 块」
    - book:   书名
    - active: 是否继续保持轮询
    """
    if state is None:
        state = {"book": "", "total": 0, "done": 0, "pct": 0, "extra": "",
                 "finished": False, "has_markers": False}

    book = state["book"]
    total = state["total"]
    done = state["done"]
    extra = state["extra"]

    # 批次还在跑，但当前日志片段里已经有"全部处理完毕" → 那是上一批留下的内容，
    # 说明新批次刚启动、还没写出自己的标记：此时要重置进度条（从 0 开始）。
    if run_alive and state["finished"]:
        return {"mode": MODE_STARTING, "status": "正在启动...", "pct": 0,
                "detail": "", "book": "", "active": True}

    if state["finished"] and total > 0:
        return {"mode": MODE_FINISHED, "status": "✅ 全部完成", "pct": 100,
                "detail": f"章节 {total}/{total}", "book": book, "active": False}

    # 批次已结束但日志里没有结束标记 → 中断/失败
    if not run_alive:
        if state["has_markers"]:
            status = "⏹ 已停止（可再次点击开始）" if manually_stopped else "⚠️ 生成已中断，详见日志"
            return {"mode": MODE_INTERRUPTED, "status": status,
                    "pct": state["pct"], "detail": _detail(total, done, extra),
                    "book": book, "active": False}
        if batch_started:
            # 启动过批次但连日志标记都没写出来（例如启动阶段就报错）
            return {"mode": MODE_FAILED, "status": "⚠️ 启动失败，详见日志", "pct": 0,
                    "detail": "", "book": "", "active": False}
        # 从未启动：正常空闲，不报错
        return {"mode": MODE_IDLE, "status": "等待开始生成...", "pct": 0,
                "detail": "", "book": "", "active": False}

    # 批次在跑
    if not state["has_markers"]:
        return {"mode": MODE_STARTING, "status": "正在启动...", "pct": 0,
                "detail": "", "book": "", "active": True}

    if total > 0:
        if done >= total:
            return {"mode": MODE_BOOK_DONE, "status": "✅ 本书完成", "pct": state["pct"],
                    "detail": _detail(total, done, extra), "book": book, "active": True}
        return {"mode": MODE_RUNNING, "status": "正在生成...", "pct": state["pct"],
                "detail": _detail(total, done, extra), "book": book, "active": True}

    return {"mode": MODE_STARTING, "status": "正在初始化...", "pct": 0,
            "detail": "", "book": book, "active": True}


def _detail(total: int, done: int, extra: str) -> str:
    detail = f"章节 {done}/{total}" if total > 0 else ""
    if extra:
        detail = f"{detail} · {extra}" if detail else extra
    return detail

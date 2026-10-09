"""角色分段模式的稳定进度标记。"""
from __future__ import annotations


def role_segment_marker(chapter_index: int, segment_index: int, segment_count: int) -> str:
    return f"role_chapter_{chapter_index}_segment_{segment_index}_of_{segment_count}"

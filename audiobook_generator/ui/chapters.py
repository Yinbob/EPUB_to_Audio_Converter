"""章节范围的显示数据与动效；不实例化语音引擎。"""
from __future__ import annotations

import html
import json


def chapter_catalog(chapters):
    return [
        {"index": index, "title": " ".join((title or "未命名章节").replace("_", " ").split()),
         "chars": len(text)}
        for index, (title, text) in enumerate(chapters, 1)
    ]


def chapter_choices(catalog):
    return [(f'{item["index"]:02d} · {item["title"]}', item["index"]) for item in catalog]


def range_payload(catalog, start=1, end=None, *, message="上传书籍后，这里会显示章节目录。"):
    if not catalog:
        value = {"total": 0, "message": message}
    else:
        end = len(catalog) if end is None or end == -1 else int(end)
        start = int(start)
        if not 1 <= start <= end <= len(catalog):
            raise ValueError("请选择有效的起止章节")
        count = end - start + 1
        value = {
            "total": len(catalog), "start": start, "end": end,
            "count": count, "chars": sum(item["chars"] for item in catalog[start - 1:end]),
            "first": catalog[start - 1]["title"], "last": catalog[end - 1]["title"],
            "message": f"已选 {count} 章 / 共 {len(catalog)} 章",
        }
    return '<span data-chapter-range="' + html.escape(json.dumps(value, ensure_ascii=False), quote=True) + '"></span>'


CHAPTER_OVERVIEW_HTML = '''<div class="chapter-overview" aria-live="polite" aria-atomic="true">
  <div class="chapter-overview-top"><strong data-range-heading>等待书籍目录</strong><span data-range-count></span></div>
  <div class="chapter-track" aria-hidden="true"><span class="chapter-fill"></span></div>
  <p data-range-detail>上传书籍后，这里会显示章节目录。</p>
</div>'''

CHAPTER_CSS = '''
#chapter_catalog_panel { gap: 14px; }
#chapter_named_range { gap: 16px; }
#chapter_named_range > .form { flex: 1; min-width: 0; }
#chapter_named_range input { text-overflow: ellipsis; }
#chapter_named_range .wrap { min-width: 0; }
#chapter_named_range ul.options { max-height: 310px; }
#chapter_named_range ul.options li { white-space: normal; overflow-wrap: anywhere; line-height: 1.5; }
#chapter_range_state { display: none !important; }
.chapter-overview { padding: 16px 0 2px; color: var(--apple-text); }
.chapter-overview-top { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.chapter-overview-top strong { font-size: .95rem; font-weight: 600; }
.chapter-overview-top span { color: var(--apple-text-2); font-size: .8rem; font-variant-numeric: tabular-nums; flex-shrink: 0; }
.chapter-track { position: relative; height: 6px; margin: 14px 0 12px; border-radius: 6px; background-color: var(--ata-track); overflow: hidden; }
.chapter-fill { display: block; width: 100%; height: 100%; border-radius: inherit; background-color: var(--apple-blue); transform: scaleX(0); transform-origin: left center; }
.chapter-overview p { margin: 0; color: var(--apple-text-2); font-size: .85rem; line-height: 1.6; overflow-wrap: anywhere; }
@media (max-width: 600px) {
  #chapter_named_range { flex-direction: column; }
  .chapter-overview-top { flex-wrap: wrap; gap: 4px 12px; }
}
'''

CHAPTER_HEAD_HTML = '''<script>
(function () {
  let last = '', barAnimation = null, revealAnimation = null, textAnimation = null;
  let previousTotal = 0;
  function sync() {
    const source = document.querySelector('#chapter_range_state [data-chapter-range]');
    const overview = document.querySelector('#chapter_overview .chapter-overview');
    if (!source || !overview) return;
    const raw = source.dataset.chapterRange;
    if (last === raw) return;
    let data;
    try { data = JSON.parse(raw); } catch (_) { return; }
    last = raw;
    const heading = overview.querySelector('[data-range-heading]');
    const count = overview.querySelector('[data-range-count]');
    const detail = overview.querySelector('[data-range-detail]');
    const bar = overview.querySelector('.chapter-fill');
    // 取消上一帧的目标动画，从当前显示位置继续，快速换章时不排队。
    const from = getComputedStyle(bar).transform;
    if (barAnimation) barAnimation.cancel();
    const target = data.total ? `translateX(${(data.start - 1) / data.total * 100}%) scaleX(${data.count / data.total})` : 'scaleX(0)';
    bar.style.transform = target;
    heading.textContent = data.total ? (data.count === 1 ? '单章试生成' : '本次生成范围') : '等待书籍目录';
    count.textContent = data.total ? data.message : '';
    detail.textContent = data.total ? (data.count === 1 ? data.first : data.first + ' → ' + data.last) + ' · ' + data.chars.toLocaleString() + ' 字符' : data.message;
    if (bar.animate) {
      barAnimation = bar.animate([{transform: from}, {transform: target}], {duration: 480, easing: 'cubic-bezier(0.16,1,0.3,1)'});
      if (textAnimation) textAnimation.cancel();
      textAnimation = detail.animate([{opacity: .45, transform: 'translateY(3px)'}, {opacity: 1, transform: 'translateY(0)'}], {duration: 260, easing: 'cubic-bezier(0.16,1,0.3,1)'});
      if (data.total && !previousTotal) {
        const fields = document.getElementById('chapter_named_range');
        if (fields) {
          if (revealAnimation) revealAnimation.cancel();
          revealAnimation = fields.animate([{opacity: .4}, {opacity: 1}], {duration: 420, easing: 'cubic-bezier(0.16,1,0.3,1)'});
          overview.animate([{clipPath: 'inset(0 0 65% 0 round 6px)'}, {clipPath: 'inset(0 0 0 0 round 6px)'}], {duration: 420, easing: 'cubic-bezier(0.16,1,0.3,1)'});
        }
      }
    }
    previousTotal = data.total;
  }
  function boot() {
    sync();
    new MutationObserver(sync).observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['data-chapter-range']});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
</script>'''

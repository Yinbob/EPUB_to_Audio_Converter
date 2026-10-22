"""从现有主题与浮点光场导出 Vue 资源，保留原算法及参数。"""
import runpy
from pathlib import Path
root = Path(__file__).resolve().parents[2]
theme = runpy.run_path(str(root / 'audiobook_generator/ui/theme.py'))
ambient = runpy.run_path(str(root / 'audiobook_generator/ui/ambient_background.py'))
(root / 'frontend/src/styles/tokens.css').write_text(theme['THEME_TOKENS_CSS'], encoding='utf-8')
js = ambient['_AMBIENT_JS'].strip()
js = js.replace('(function () {', 'export function mountAmbient() {', 1)
js = js.rsplit('})();', 1)[0] + '\nreturn window.__ataAmbient;\n}\n'
import json
js = js.replace('var CFG = window.__ATA_AMBIENT_CONFIG || {};', 'var CFG = ' + json.dumps(ambient['_CONFIG']) + ';')
js = js.replace('if (window.__ataAmbient) return;', 'if (window.__ataAmbient) return window.__ataAmbient;')
start, end = js.index('  function progressBox()'), js.index('  // ── 交互 ──')
js = js[:start] + js[end:]
js = js.replace('    bindObservers();', '').replace('    syncFromProgress();', '')
js = js.replace('    document.addEventListener("click", onClick, true);', '')
start = js.index('    // Gradio 是渐进渲染的')
end = js.index('\n  }', start)
js = js[:start] + js[end:]
js = js.replace('  function cleanup() {', '  function cleanup() {\n    if (layer) layer.remove();\n    delete window.__ataAmbient;')
# 可重复的视觉回归不影响正常随机布局。
seed = 'var seed = Number(new URLSearchParams(location.search).get("ata-seed")) || 0;\n  function random(){if(!seed)return Math.random();seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;}\n  '
js = js.replace('Math.random()', 'random()')
js = js.replace('  var TAU', '  ' + seed + 'var TAU', 1)
(root / 'frontend/src/ambient.ts').write_text('// @ts-nocheck\n// 由 tools/export_visuals.py 从原版光场生成。\n' + js, encoding='utf-8')
css = ambient['AMBIENT_CSS']
css = css[:css.index('/* 高级设置弹窗')]
(root / 'frontend/src/styles/ambient.css').write_text(css, encoding='utf-8')

"""在项目 Python 环境执行，导出契约，不启动服务或加载模型。"""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
from audiobook_generator.api.app import create_app

(root / 'frontend/openapi.json').write_text(
    json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

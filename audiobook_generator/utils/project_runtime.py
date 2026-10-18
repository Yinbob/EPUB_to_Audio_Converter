"""入口脚本的解释器选择；只使用本项目已经存在的环境，不安装依赖。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def select_project_python(project_root, entry, argv=None):
    """显式激活的环境优先；普通网页启动优先使用已配置的质检环境。"""
    root = Path(project_root)
    # 用 prefix 而非可执行文件的 realpath 判断，避免 venv 中 python 符号链接误判。
    if sys.prefix != sys.base_prefix:
        return None
    conda_prefix = os.environ.get('CONDA_PREFIX')
    if conda_prefix and Path(conda_prefix).resolve() == Path(sys.prefix).resolve():
        return None
    argv = list(sys.argv[1:] if argv is None else argv)
    local_engine = any(
        value in ('--tts=chatterbox', '--tts=voxcpm')
        or (value == '--tts' and index + 1 < len(argv) and argv[index + 1] in ('chatterbox', 'voxcpm'))
        for index, value in enumerate(argv)
    )
    quality_first = entry == 'ui' or ('--audio_core_enabled' in argv and not local_engine)
    environments = ('venv_audio_quality', 'venv_chatterbox') if quality_first else ('venv_chatterbox',)
    for name in environments:
        env = root / name
        if not (env / 'pyvenv.cfg').is_file():
            continue
        for relative in ('bin/python3', 'bin/python', 'Scripts/python.exe'):
            executable = env / relative
            if executable.is_file() and os.access(executable, os.X_OK):
                return executable
    return None


def bootstrap_project_python(project_root, entry):
    """仅由 __main__ 调用；导入模块和 spawn worker 不切换解释器。"""
    executable = select_project_python(project_root, entry)
    if executable is None:
        return
    cache = executable.parent.parent / '.cache'
    defaults = {
        'NUMBA_CACHE_DIR': str(cache / 'numba'),
        'HF_HOME': str(cache / 'huggingface'),
        'HUGGINGFACE_HUB_CACHE': str(cache / 'huggingface' / 'hub'),
        'MODELSCOPE_CACHE': str(cache / 'modelscope'),
        'TORCHINDUCTOR_CACHE_DIR': str(cache / 'torchinductor'),
        'HF_ENDPOINT': 'https://hf-mirror.com',
        'HF_HUB_DISABLE_XET': '1',
        'OMP_WAIT_POLICY': 'PASSIVE',
    }
    for name, value in defaults.items():
        os.environ.setdefault(name, value)
    for name in ('NUMBA_CACHE_DIR', 'HUGGINGFACE_HUB_CACHE', 'MODELSCOPE_CACHE', 'TORCHINDUCTOR_CACHE_DIR'):
        Path(os.environ[name]).mkdir(parents=True, exist_ok=True)
    os.execv(str(executable), [str(executable), *sys.argv])

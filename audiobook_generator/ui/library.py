"""资源库文件选择、下载与打包；只处理当前批次内的真实文件。"""
import html
import re
import tempfile
import zipfile
from pathlib import Path

AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.opus'}


def selected_paths(root, folder, selected):
    base = Path(root).resolve()
    if not folder:
        return []
    batch = (base / folder).resolve()
    if batch.parent != base or not batch.is_dir() or batch.name.startswith('.'):
        return []
    paths = []
    for name in dict.fromkeys([selected] if isinstance(selected, str) else (selected or [])):
        path = (batch / name).resolve()
        if path.parent == batch and path.is_file() and not path.name.startswith('.'):
            paths.append(path)
    return paths


def selection_details(root, folder, selected):
    paths = selected_paths(root, folder, selected)
    size = sum(path.stat().st_size for path in paths)
    size_label = f'{size / 1024 / 1024:.1f} MB' if size >= 1024 * 1024 else f'{size / 1024:.1f} KB'
    title = html.escape(str(folder or '尚未选择书籍'))
    message = f'已选择 {len(paths)} 个文件 · {size_label}' if paths else '勾选左侧文件，即可试听或下载。'
    summary = f'<div class="library-selection"><h3>{title}</h3><p>{message}</p></div>'
    audio = [path.name for path in paths if path.suffix.lower() in AUDIO_EXTENSIONS]
    return summary, [str(path) for path in paths], audio


def create_archive(root, folder, selected):
    paths = selected_paths(root, folder, selected)
    if not paths:
        raise ValueError('没有可下载的文件，请刷新列表后重新选择。')
    temp = Path(root) / '.temp_downloads'
    temp.mkdir(parents=True, exist_ok=True)
    # 独立目录避免并发覆盖，文件名无需混入时间戳。
    destination = Path(tempfile.mkdtemp(prefix='export-', dir=temp))
    safe_name = re.sub(r'[^\w.\-\u4e00-\u9fff]', '_', str(folder))[:100]
    archive = destination / f'{safe_name}.zip'
    try:
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
            for path in paths:
                output.write(path, arcname=path.name)
    except OSError:
        archive.unlink(missing_ok=True)
        destination.rmdir()
        raise
    return str(archive), len(paths)

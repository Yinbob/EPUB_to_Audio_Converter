"""解析报告所绑定的章节 PCM；不通过报告副本的位置猜测音频身份。"""
import hashlib
from pathlib import Path


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_reference_pcm(report, report_path, *, require_hash=False):
    metrics = report.get("final_verification", {}).get("metrics", {})
    expected = metrics.get("reference_pcm_sha256")
    explicit = metrics.get("reference_pcm_path")
    if require_hash and not expected:
        raise ValueError("章节 PCM 缺少来源校验值")
    if explicit is not None:
        if not isinstance(explicit, str) or not Path(explicit).is_absolute() or not expected:
            raise ValueError("章节 PCM 来源声明需要绝对路径和校验值")
        candidates = [Path(explicit)]
    else:
        path = Path(report_path).resolve()
        candidates = [path.parent / "chapter.wav"]
        # 兼容历史报告：从已记录分块所在项目恢复，仍必须核对哈希和完整 PCM 时间表。
        parents = list(path.parents)
        if report.get("chunks") and report["chunks"][0].get("rendered_path"):
            parents += list(Path(report["chunks"][0]["rendered_path"]).resolve().parents)
        if report.get("run_id") and report.get("chapter_index"):
            for parent in dict.fromkeys(parents):
                if (parent / "project.sqlite").is_file():
                    candidates.append(parent / "reports" / report["run_id"] /
                                      f"chapter_{report['chapter_index']:06d}" / "chapter.wav")
        if metrics.get("decoded_path"):
            candidates.append(Path(metrics["decoded_path"]).parent.parent / "chapter.wav")
    for candidate in candidates:
        if candidate.is_file() and (not expected or _sha(candidate) == expected):
            return candidate.resolve()
    raise ValueError("章节 PCM 缺失或来源校验不一致，请恢复原始音频后再操作")

"""显式执行的真实接口检查；固定自编文本，不读取书籍。"""
from pathlib import Path

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.role_script.models import ChapterSynthesisPlan, SynthesisUnit, VoiceProfile

from .models import CoreOptions, ResourceLimits
from .pipeline import run_chapter
from .store import ArtifactStore


def live_smoke(output, *, max_requests=4, max_seconds=240):
    from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
    root = Path(output).resolve()
    store = ArtifactStore(root / ".audio_projects" / "authored_smoke")
    options = CoreOptions(limits=ResourceLimits(max_requests=max_requests, max_repair_requests=0,
                                                max_seconds=max_seconds))
    run_id = store.start_run(options.limits)
    results = []
    texts = ["清晨的阳光穿过窗户，落在安静的书桌上。他轻轻打开旧书，开始讲述昨天的故事。",
             "到了2026年10月16日，记录显示增长了3.5%。他放下笔，认真核对每一项数据。",
             "你还记得昨天约定的时间吗？请先把地址说清楚，我们会在桥边等你一起出发。",
             "不用着急，先把手头的事情处理好。等到雨停以后，我们再沿着这条小路慢慢走回家。"]
    summary = {"kind": "real_mimo_transport_and_assembly_smoke", "source": "authored_test_text",
               "run_id": run_id, "results": results,
               "model_quality_validation": "requires_models_and_human_validation"}
    try:
        for chapter, streaming in ((1, False), (2, True)):
            config = GeneralConfig(None)
            config.tts, config.language, config.voice_name = "openai", "zh-CN", "冰糖"
            config.model_name, config.speed, config.stream = "mimo-v2.5-tts", 1.0, streaming
            config.output_format = "wav"
            provider = OpenAITTSProvider(config)
            units = []
            for index in range(2):
                role = "narrator" if chapter == 1 else ("hero" if index == 0 else "other")
                voice = "冰糖" if chapter == 1 or index == 1 else "茉莉"
                units.append(SynthesisUnit(f"{chapter}:{index + 1}:{role}", chapter, "真实接口验证", index + 1, 2,
                    role, role, texts[(chapter - 1) * 2 + index], VoiceProfile(role, role, {"voice": voice, "speed": 1.0}),
                    pause_after_ms=250 if index == 0 else 0))
            result = run_chapter(ChapterSynthesisPlan(chapter, "真实接口验证", tuple(units), "mp3", "openai"),
                provider, root / f"chapter_{chapter}.mp3", AudioTags("真实接口验证", "项目测试", "统一核心冒烟验证", chapter),
                store.root, options=options, run_id=run_id)
            results.append({"chapter": chapter, "streaming": streaming, "quality_status": result["quality_status"],
                "duration_seconds": result["assembly"]["total_samples"] / result["assembly"]["sample_rate"],
                "chunks": len(result["chunks"]), "boundaries": len(result["boundaries"])})
        summary["execution_status"] = "completed"
    except Exception as exc:
        summary["execution_status"], summary["error_type"] = "failed", type(exc).__name__
        raise
    finally:
        summary["resources"] = store.summary(run_id)
        store.write_json("validation_summary.json", summary)
    return {**summary, "summary_path": str(store.root / "validation_summary.json")}

import logging
import multiprocessing
import os
import hashlib
import shutil
from pathlib import Path
from typing import Optional, Tuple

from audiobook_generator.book_parsers.base_book_parser import get_book_parser
from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.tts_providers.base_tts_provider import get_tts_provider
from audiobook_generator.utils.log_handler import setup_logging
from audiobook_generator.utils.filename_sanitizer import make_safe_filename

logger = logging.getLogger(__name__)


# 角色模式必须在父进程解析章节，不能先实例化 Provider（MiMo/MiniMax 会读取凭证）。
# 这两个字符串必须与对应 Provider.get_break_string() 保持一致。
ROLE_BREAK_STRINGS = {
    "openai": "   ",
    "minimax": " @BRK#",
}
ROLE_DEFAULT_OUTPUT_FORMATS = {
    "openai": "wav",
    "minimax": "mp3",
}


def confirm_conversion():
    logger.info("Do you want to continue? (y/n)")
    answer = input()
    if answer.lower() != "y":
        logger.info("Aborted.")
        exit(0)


def get_total_chars(chapters):
    total_characters = 0
    for title, text in chapters:
        total_characters += len(text)
    return total_characters


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _format_validation_report(report) -> str:
    lines = ["角色剧本校验失败："]
    for item in report.errors:
        lines.append(f"  - [{item.code}] {item.path}: {item.message}")
    if report.warnings:
        lines.append("警告：")
        for item in report.warnings:
            lines.append(f"  - [{item.code}] {item.path}: {item.message}")
    return "\n".join(lines)


class AudiobookGenerator:
    def __init__(self, config: GeneralConfig):
        self.config = config

    def __str__(self) -> str:
        return f"{self.config}"

    def process_chapter(self, idx, title, text, book_parser):
        """Process a single chapter: write text (if needed) and convert to audio."""
        try:
            logger.info(f"Processing chapter {idx}: {title}")
            tts_provider = get_tts_provider(self.config)

            # Save chapter text if required
            if self.config.output_text:
                safe_txt_name = make_safe_filename(
                    title=title,
                    idx=idx,
                    output_dir=self.config.output_folder,
                    ext=".txt",
                    collision_check=False,
                )
                text_file = os.path.join(self.config.output_folder, safe_txt_name)
                with open(text_file, "w", encoding="utf-8") as f:
                    f.write(text)

            # Skip audio generation in preview mode
            if self.config.preview:
                return True

            # Generate audio file (safe, length-limited, cross-platform)
            audio_ext = "." + tts_provider.get_output_file_extension()
            safe_audio_name = make_safe_filename(
                title=title,
                idx=idx,
                output_dir=self.config.output_folder,
                ext=audio_ext,
                collision_check=False,
            )
            output_file = os.path.join(self.config.output_folder, safe_audio_name)

            audio_tags = AudioTags(
                title, book_parser.get_book_author(), book_parser.get_book_title(), idx
            )
            tts_provider.text_to_speech(text, output_file, audio_tags)

            logger.info(f"✅ Converted chapter {idx}: {title}, output file: {output_file}")

            return True
        except Exception as e:
            logger.exception(f"Error processing chapter {idx}, error: {e}")
            return False

    def process_chapter_wrapper(self, args):
        """Wrapper for process_chapter to handle unpacking args for imap."""
        idx, title, text, book_parser = args
        return idx, self.process_chapter(idx, title, text, book_parser)

    def process_role_chapter(self, plan, book_author: str, book_title: str):
        """在 spawn worker 内合成一个角色章节。"""
        work_dir: Optional[str] = None
        try:
            logger.info(
                f"Processing role chapter {plan.chapter_index}: {plan.title} "
                f"({plan.segment_count} segments)"
            )
            output_dir = self.config.output_folder
            os.makedirs(output_dir, exist_ok=True)
            work_dir = os.path.join(
                output_dir,
                ".role_tmp",
                f"chapter_{plan.chapter_index:06d}",
            )
            os.makedirs(work_dir, exist_ok=True)

            # Provider 在 worker 内创建，避免父进程读取 API 凭证或初始化网络客户端。
            tts_provider = get_tts_provider(self.config)
            if getattr(tts_provider, "provider_id", None) != plan.provider:
                raise ValueError(
                    f"角色章节 provider={plan.provider!r} 与 worker Provider="
                    f"{getattr(tts_provider, 'provider_id', None)!r} 不一致"
                )

            if self.config.output_text:
                from audiobook_generator.role_script.planner import render_proofing_text

                safe_txt_name = make_safe_filename(
                    title=plan.title,
                    idx=plan.chapter_index,
                    output_dir=output_dir,
                    ext=".txt",
                    collision_check=False,
                )
                text_file = os.path.join(output_dir, safe_txt_name)
                with open(text_file, "w", encoding="utf-8") as file_obj:
                    file_obj.write(render_proofing_text(plan))

            audio_ext = "." + tts_provider.get_output_file_extension()
            safe_audio_name = make_safe_filename(
                title=plan.title,
                idx=plan.chapter_index,
                output_dir=output_dir,
                ext=audio_ext,
                collision_check=False,
            )
            output_file = os.path.join(output_dir, safe_audio_name)
            audio_tags = AudioTags(
                plan.title,
                book_author,
                book_title,
                plan.chapter_index,
            )

            from audiobook_generator.role_script.audio_pipeline import assemble_chapter_audio
            from audiobook_generator.role_script.progress import role_segment_marker

            artifacts = []
            for unit in plan.units:
                marker = role_segment_marker(
                    unit.chapter_index,
                    unit.segment_index,
                    unit.segment_count,
                )

                def report_progress(_message: str, marker: str = marker) -> None:
                    # 外层 segment 进度必须优先于 Provider 内部分块标记。
                    logger.info(marker)

                artifacts.append(
                    tts_provider.synthesize_segment(
                        unit.text,
                        unit.profile,
                        work_dir,
                        report_progress,
                    )
                )

            assemble_chapter_audio(
                plan,
                artifacts,
                output_file,
                audio_tags,
                work_dir,
            )
            logger.info(
                f"✅ Converted chapter {plan.chapter_index}: {plan.title}, "
                f"output file: {output_file}"
            )
            return plan.chapter_index, True
        except Exception as exc:
            logger.exception(
                f"Error processing role chapter {plan.chapter_index}, error: {exc}"
            )
            return plan.chapter_index, False
        finally:
            if work_dir:
                shutil.rmtree(work_dir, ignore_errors=True)

    def process_role_chapter_wrapper(self, args):
        plan, book_author, book_title = args
        return self.process_role_chapter(plan, book_author, book_title)

    def _load_role_script(self):
        from audiobook_generator.role_script.loader import load_role_script
        from audiobook_generator.role_script.models import RoleScriptV1

        value = self.config.role_script
        if isinstance(value, RoleScriptV1):
            return value, None
        if isinstance(value, (str, os.PathLike, Path)):
            script, report = load_role_script(value)
            return script, report
        raise ValueError("role_script 必须是 RoleScriptV1 对象或 JSON 文件路径")

    def _validate_role_plans(
        self,
        chapters,
        *,
        chapter_start: int,
        chapter_end: int,
    ) -> Tuple[tuple, object]:
        from audiobook_generator.role_script.planner import (
            build_default_provider_params,
            build_synthesis_plans,
        )

        if self.config.tts not in ROLE_BREAK_STRINGS:
            raise ValueError("角色模式首版只支持 MiMo（openai）和 MiniMax")
        if not self.config.input_file or not os.path.isfile(self.config.input_file):
            raise FileNotFoundError(f"输入文件不存在：{self.config.input_file}")

        script, load_report = self._load_role_script()
        if script is None:
            raise ValueError(_format_validation_report(load_report))

        planning = build_synthesis_plans(
            script,
            chapters,
            expected_book_sha256=_sha256_file(self.config.input_file),
            provider=self.config.tts,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
            output_format=self.config.output_format,
            allow_text_override=bool(self.config.allow_role_text_override),
            allow_title_mismatch=bool(self.config.allow_role_title_mismatch),
            allow_fallback=bool(self.config.allow_role_fallback),
            fallback_profile=build_default_provider_params(self.config.tts, self.config),
        )
        if not planning.ok:
            raise ValueError(_format_validation_report(planning.report))
        return planning.plans, planning.report

    def run(self):
        try:
            logger.info("Starting audiobook generation...")
            role_mode = self.config.role_script is not None
            if role_mode and self.config.use_pydub_merge:
                logger.warning("角色模式使用独立音频管线，已忽略 --use_pydub_merge")
            book_parser = get_book_parser(self.config)
            tts_provider = None if role_mode else get_tts_provider(self.config)

            if role_mode and not self.config.output_format:
                self.config.output_format = ROLE_DEFAULT_OUTPUT_FORMATS.get(
                    self.config.tts, ""
                )

            os.makedirs(self.config.output_folder, exist_ok=True)
            if role_mode:
                if self.config.tts not in ROLE_BREAK_STRINGS:
                    raise ValueError("角色模式首版只支持 MiMo（openai）和 MiniMax")
                break_string = ROLE_BREAK_STRINGS[self.config.tts]
            else:
                break_string = tts_provider.get_break_string()
            chapters = book_parser.get_chapters(break_string)
            # Filter out empty or very short chapters
            chapters = [(title, text) for title, text in chapters if text.strip()]

            logger.info(f"Chapters count: {len(chapters)}.")

            # Check chapter start and end args
            if self.config.chapter_start < 1 or self.config.chapter_start > len(chapters):
                raise ValueError(
                    f"Chapter start index {self.config.chapter_start} is out of range. Check your input."
                )
            if self.config.chapter_end < -1 or self.config.chapter_end > len(chapters):
                raise ValueError(
                    f"Chapter end index {self.config.chapter_end} is out of range. Check your input."
                )
            if self.config.chapter_end == -1:
                self.config.chapter_end = len(chapters)
            if self.config.chapter_start > self.config.chapter_end:
                raise ValueError(
                    f"Chapter start index {self.config.chapter_start} is larger than chapter end index {self.config.chapter_end}. Check your input."
                )

            logger.info(
                f"Converting chapters from {self.config.chapter_start} to {self.config.chapter_end}."
            )

            # Initialize total_characters to 0
            total_characters = get_total_chars(
                chapters[self.config.chapter_start - 1 : self.config.chapter_end]
            )
            logger.info(f"Total characters in selected book chapters: {total_characters}")
            if role_mode:
                logger.info("角色模式费用将在各章节 worker 内按 Provider 配置计算。\n")
            else:
                rough_price = tts_provider.estimate_cost(total_characters)
                logger.info(f"Estimate book voiceover would cost you roughly: ${rough_price:.2f}\n")

            # Prompt user to continue if not in preview mode
            if self.config.no_prompt:
                logger.info("Skipping prompt as passed parameter no_prompt")
            elif self.config.preview:
                logger.info("Skipping prompt as in preview mode")
            else:
                confirm_conversion()

            # Prepare chapters for processing
            chapters_to_process = chapters[self.config.chapter_start - 1 : self.config.chapter_end]
            role_plans = None
            if role_mode:
                role_plans, planning_report = self._validate_role_plans(
                    chapters,
                    chapter_start=self.config.chapter_start,
                    chapter_end=self.config.chapter_end,
                )
                for warning in planning_report.warnings:
                    logger.warning(
                        f"角色剧本警告 [{warning.code}] {warning.path}: {warning.message}"
                    )
                if self.config.preview:
                    role_names = {
                        role_id: role.display_name
                        for role_id, role in self.config.role_script.roles.items()
                    } if hasattr(self.config.role_script, "roles") else {}
                    logger.info(
                        "角色剧本校验通过："
                        f"provider={self.config.tts}, "
                        f"章节={len(role_plans)}, "
                        f"段落={sum(plan.segment_count for plan in role_plans)}, "
                        f"角色={len(role_names)}"
                    )
                    for plan in role_plans:
                        logger.info(
                            f"  - 第 {plan.chapter_index} 章 {plan.title}: "
                            f"{plan.segment_count} 段"
                        )
                    return

                from audiobook_generator.role_script.audio_pipeline import require_ffmpeg_tools

                require_ffmpeg_tools()

                tasks = [
                    (plan, book_parser.get_book_author(), book_parser.get_book_title())
                    for plan in role_plans
                ]
                worker_target = self.process_role_chapter_wrapper
            else:
                tasks = [
                    (idx, title, text, book_parser)
                    for idx, (title, text) in enumerate(
                        chapters_to_process, start=self.config.chapter_start
                    )
                ]
                worker_target = self.process_chapter_wrapper

            # Track failed chapters
            failed_chapters = []

            # 并行转换章节。
            #
            # 这里必须用 spawn 启动方式：Linux 的 multiprocessing 默认是 fork，
            # 子进程会继承父进程里已经初始化过的 CUDA 状态（父进程在 argparse 校验
            # 设备、构造 TTS provider 时就会调用 torch.cuda），之后子进程再使用 GPU
            # 会被 PyTorch 直接拒绝：
            #   RuntimeError: Cannot re-initialize CUDA in forked subprocess.
            # spawn 让每个 worker 以全新解释器启动，可以独立初始化 CUDA。
            # 代价是每个 worker 会各自加载一份模型（GPU 显存随 worker_count 增长），
            # 且首次启动需要重新 import 依赖，故 GPU 场景建议 worker_count=1。
            worker_count = self.config.worker_count or 1
            if (
                not role_mode
                and worker_count > 1
                and getattr(tts_provider, "device", None) == "cuda"
            ):
                logger.warning(
                    f"检测到 CUDA + worker_count={worker_count}：每个 worker 都会独立加载一份 TTS 模型，"
                    "显存占用随并行数成倍增加。GPU 场景建议使用 --worker_count 1。"
                )

            mp_context = multiprocessing.get_context("spawn")
            with mp_context.Pool(
                processes=worker_count,
                initializer=setup_logging,
                initargs=(self.config.log, self.config.log_file, True)
            ) as pool:
                # Process chapters and collect results
                results = list(pool.imap_unordered(worker_target, tasks))

                # Check for failed chapters
                for idx, success in results:
                    if not success:
                        chapter_title = chapters_to_process[idx - self.config.chapter_start][0]
                        failed_chapters.append((idx, chapter_title))

            if failed_chapters:
                logger.warning("The following chapters failed to convert:")
                for idx, title in failed_chapters:
                    logger.warning(f"  - Chapter {idx}: {title}")
                logger.info(f"Conversion completed with {len(failed_chapters)} failed chapters. Check your output directory: {self.config.output_folder} and log file: {self.config.log_file} for more details.")
            else:
                logger.info(f"All chapters converted successfully. Check your output directory: {self.config.output_folder}")

        except KeyboardInterrupt:
            logger.info("Audiobook generation process interrupted by user (Ctrl+C).")
        except Exception as e:
            logger.exception(f"Error during audiobook generation: {e}")
        finally:
            logger.debug("AudiobookGenerator.run() method finished.")

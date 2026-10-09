import io
import math
import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.role_script import audio_pipeline
from audiobook_generator.role_script.models import (
    ChapterSynthesisPlan,
    SynthesisUnit,
    VoiceProfile,
)
from audiobook_generator.role_script.audio_pipeline import atempo_chain


def _write_constant_wav(path, *, sample_rate, channels, duration_ms, value):
    frame_count = max(1, int(sample_rate * duration_ms / 1000))
    sample = struct.pack("<h", value)
    frames = sample * channels * frame_count
    with wave.open(path, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    return frame_count


def _read_wav_mono(path):
    with wave.open(path, "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if width != 2:
        raise AssertionError(f"测试仅支持 16-bit WAV，实际 {width * 8}-bit")
    values = struct.unpack("<" + "h" * (len(frames) // 2), frames)
    if channels > 1:
        values = tuple(
            int(sum(values[index : index + channels]) / channels)
            for index in range(0, len(values), channels)
        )
    return values, sample_rate, channels


def _artifact(path, cache_key):
    return audio_pipeline.build_audio_artifact(path, cache_key=cache_key)


def _unit(index, count, pause_ms, role_id="narrator", speed=1.0):
    return SynthesisUnit(
        unit_id=f"1:{index}:{role_id}",
        chapter_index=1,
        chapter_title="第一章",
        segment_index=index,
        segment_count=count,
        role_id=role_id,
        display_name="旁白",
        text=f"第 {index} 段",
        profile=VoiceProfile(
            role_id=role_id,
            display_name="旁白",
            provider_params={
                "voice_id": "male-qn-qingse",
                "speed": speed,
                "pitch": 0,
                "volume": 1,
            }
            if role_id == "narrator"
            else {"voice": "冰糖", "speed": speed},
        ),
        pause_after_ms=pause_ms,
    )


def _plan(units, provider="minimax", output_format="wav"):
    return ChapterSynthesisPlan(
        chapter_index=1,
        title="第一章",
        units=tuple(units),
        output_format=output_format,
        provider=provider,
    )


FFMPEG_AVAILABLE = bool(
    audio_pipeline.resolve_ffmpeg_binary("ffmpeg")
    and audio_pipeline.resolve_ffmpeg_binary("ffprobe")
)


@unittest.skipUnless(FFMPEG_AVAILABLE, "需要 ffmpeg/ffprobe")
class AudioPipelineTest(unittest.TestCase):
    def _make_segment(self, root, name, *, sample_rate=24000, channels=1, duration_ms=200, value=9000):
        path = os.path.join(root, name)
        _write_constant_wav(
            path,
            sample_rate=sample_rate,
            channels=channels,
            duration_ms=duration_ms,
            value=value,
        )
        return path

    def test_atempo_chain_supports_extreme_speed(self):
        self.assertEqual(atempo_chain(1.0), [])
        self.assertEqual(atempo_chain(2.0), ["atempo=2.00000000"])
        self.assertEqual(atempo_chain(4.0), ["atempo=2.0", "atempo=2.00000000"])
        self.assertEqual(atempo_chain(0.25), ["atempo=0.5", "atempo=0.50000000"])
        for speed in (0.25, 0.5, 1.0, 1.5, 2.0, 4.0):
            self.assertTrue(all("atempo=" in item for item in atempo_chain(speed)))

    def test_preview_and_chapter_apply_mimo_speed_once(self):
        with tempfile.TemporaryDirectory() as root:
            source = self._make_segment(root, "raw.wav", duration_ms=2000)
            artifact = _artifact(source, "source")
            unit = _unit(1, 1, 0, role_id="hero", speed=1.5)
            preview = audio_pipeline.render_role_preview(
                artifact, unit.profile, "openai", os.path.join(root, "preview.wav")
            )
            chapter = audio_pipeline.assemble_chapter_audio(
                _plan([unit], provider="openai"), [artifact],
                os.path.join(root, "chapter.wav"), AudioTags("第一章", "作者", "书", 1),
                os.path.join(root, "chapter-work"),
            )
            self.assertAlmostEqual(preview.duration_ms, 2000 / 1.5, delta=80)
            self.assertAlmostEqual(chapter.duration_ms, preview.duration_ms, delta=10)

    def test_minimax_preview_does_not_apply_speed_twice(self):
        with tempfile.TemporaryDirectory() as root:
            source = self._make_segment(root, "raw.wav", duration_ms=1000)
            artifact = _artifact(source, "source")
            unit = _unit(1, 1, 0, speed=1.5)
            preview = audio_pipeline.render_role_preview(
                artifact, unit.profile, "minimax", os.path.join(root, "preview.wav")
            )
            self.assertAlmostEqual(preview.duration_ms, 1000, delta=10)

    def test_merges_in_order_inserts_250ms_and_honors_explicit_zero(self):
        with tempfile.TemporaryDirectory() as root:
            first = self._make_segment(root, "first.wav", value=8000)
            second = self._make_segment(root, "second.wav", value=-8000)
            plan = _plan(
                [
                    _unit(1, 2, 250),
                    _unit(2, 2, 0),
                ]
            )
            output = os.path.join(root, "merged.wav")
            work_dir = os.path.join(root, "work")
            original_final_encode = audio_pipeline._final_encode
            original_silence = audio_pipeline._write_silence
            with patch.object(
                audio_pipeline, "_final_encode", wraps=original_final_encode
            ) as final_encode, patch.object(
                audio_pipeline, "_write_silence", wraps=original_silence
            ) as silence:
                result = audio_pipeline.assemble_chapter_audio(
                    plan,
                    [_artifact(first, "a"), _artifact(second, "b")],
                    output,
                    AudioTags("第一章", "作者", "书名", 1),
                    work_dir,
                )
            self.assertEqual(final_encode.call_count, 1)
            self.assertEqual(silence.call_count, 1)
            self.assertEqual(result.format, "wav")
            values, sample_rate, channels = _read_wav_mono(output)
            self.assertEqual((sample_rate, channels), (24000, 1))
            self.assertEqual(len(values), 4800 + 6000 + 4800)
            self.assertGreater(values[100], 0)
            self.assertLess(values[-100], 0)
            middle = values[4800:10800]
            self.assertTrue(all(abs(value) <= 2 for value in middle))

    def test_relative_work_dir_uses_absolute_concat_paths(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as root:
            first = self._make_segment(root, "first.wav", value=8000)
            second = self._make_segment(root, "second.wav", value=-8000)
            output = os.path.relpath(os.path.join(root, "merged.wav"), os.getcwd())
            work_dir = os.path.relpath(os.path.join(root, "work"), os.getcwd())
            plan = _plan([_unit(1, 2, 0), _unit(2, 2, 0)])

            result = audio_pipeline.assemble_chapter_audio(
                plan,
                [_artifact(first, "a"), _artifact(second, "b")],
                output,
                AudioTags("第一章", "作者", "书名", 1),
                work_dir,
            )

            self.assertTrue(os.path.isfile(output))
            self.assertEqual(result.duration_ms, 400)
            with open(os.path.join(work_dir, "concat.txt"), encoding="utf-8") as file_obj:
                lines = [line for line in file_obj if line.strip()]
            self.assertEqual(len(lines), 2)
            self.assertTrue(all(line.startswith("file '/") for line in lines))

    def test_normalizes_later_segment_to_first_segment_rate_and_channels(self):
        with tempfile.TemporaryDirectory() as root:
            first = self._make_segment(
                root, "first.wav", sample_rate=44100, channels=1, value=7000
            )
            second = self._make_segment(
                root, "second.wav", sample_rate=16000, channels=2, value=-7000
            )
            plan = _plan([_unit(1, 2, 0), _unit(2, 2, 0)])
            output = os.path.join(root, "normalized.wav")
            result = audio_pipeline.assemble_chapter_audio(
                plan,
                [_artifact(first, "a"), _artifact(second, "b")],
                output,
                AudioTags("第一章", "作者", "书名", 1),
                os.path.join(root, "work"),
            )
            self.assertEqual(result.sample_rate, 44100)
            self.assertEqual(result.channels, 1)
            values, sample_rate, channels = _read_wav_mono(output)
            self.assertEqual((sample_rate, channels), (44100, 1))
            self.assertGreater(values[100], 0)
            self.assertLess(values[-100], 0)

    def test_writes_tags_for_mp3_wav_and_flac(self):
        from mutagen.flac import FLAC
        from mutagen.id3 import ID3, TALB, TIT2, TPE1, TRCK
        from mutagen.wave import WAVE

        with tempfile.TemporaryDirectory() as root:
            first = self._make_segment(root, "segment.wav")
            for output_format in ("mp3", "wav", "flac"):
                output = os.path.join(root, f"chapter.{output_format}")
                plan = _plan([_unit(1, 1, 0)], output_format=output_format)
                audio_pipeline.assemble_chapter_audio(
                    plan,
                    [_artifact(first, f"cache-{output_format}")],
                    output,
                    AudioTags("章节标题", "作者", "书名", 7),
                    os.path.join(root, f"work-{output_format}"),
                )
                self.assertTrue(os.path.isfile(output))
                if output_format == "mp3":
                    tags = ID3(output)
                    self.assertEqual(tags["TIT2"].text[0], "章节标题")
                    self.assertEqual(tags["TPE1"].text[0], "作者")
                    self.assertEqual(tags["TALB"].text[0], "书名")
                elif output_format == "wav":
                    tags = WAVE(output).tags
                    self.assertEqual(tags["TIT2"].text[0], "章节标题")
                    self.assertEqual(tags["TPE1"].text[0], "作者")
                    self.assertEqual(tags["TALB"].text[0], "书名")
                else:
                    tags = FLAC(output)
                    self.assertEqual(tags["title"][0], "章节标题")
                    self.assertEqual(tags["artist"][0], "作者")
                    self.assertEqual(tags["album"][0], "书名")

    def test_tag_failure_removes_final_output(self):
        with tempfile.TemporaryDirectory() as root:
            first = self._make_segment(root, "segment.wav")
            output = os.path.join(root, "chapter.wav")
            plan = _plan([_unit(1, 1, 0)])
            with patch(
                "audiobook_generator.role_script.audio_pipeline.set_audio_tags",
                side_effect=RuntimeError("tag fail"),
            ):
                with self.assertRaisesRegex(RuntimeError, "tag fail"):
                    audio_pipeline.assemble_chapter_audio(
                        plan,
                        [_artifact(first, "cache")],
                        output,
                        AudioTags("章节标题", "作者", "书名", 1),
                        os.path.join(root, "work"),
                    )
            self.assertFalse(os.path.exists(output))

    def test_encode_failure_removes_temporary_output(self):
        with tempfile.TemporaryDirectory() as root:
            first = self._make_segment(root, "segment.wav")
            output = os.path.join(root, "chapter.wav")
            work_dir = os.path.join(root, "work")
            plan = _plan([_unit(1, 1, 0)])

            def fail_after_partial_write(_concat_list, temp_output, _output_format, _ffmpeg):
                with open(temp_output, "wb") as file_obj:
                    file_obj.write(b"partial")
                raise RuntimeError("encode fail")

            with patch.object(audio_pipeline, "_final_encode", side_effect=fail_after_partial_write):
                with self.assertRaisesRegex(RuntimeError, "encode fail"):
                    audio_pipeline.assemble_chapter_audio(
                        plan,
                        [_artifact(first, "cache")],
                        output,
                        AudioTags("章节标题", "作者", "书名", 1),
                        work_dir,
                    )

            self.assertFalse(os.path.exists(output))
            self.assertEqual(
                list(Path(work_dir).glob("chapter_final.*")),
                [],
            )

    def test_missing_segment_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as root:
            output = os.path.join(root, "chapter.wav")
            plan = _plan([_unit(1, 1, 0)])
            from audiobook_generator.role_script.models import AudioArtifact

            with self.assertRaises(FileNotFoundError):
                audio_pipeline.assemble_chapter_audio(
                    plan,
                    [AudioArtifact(os.path.join(root, "missing.wav"), "wav", 24000, 1, 1, "x", "c")],
                    output,
                    AudioTags("章节标题", "作者", "书名", 1),
                    os.path.join(root, "work"),
                )
            self.assertFalse(os.path.exists(output))


if __name__ == "__main__":
    unittest.main()

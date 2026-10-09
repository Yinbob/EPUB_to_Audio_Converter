"""角色模式 Provider 共用临时文件辅助函数的回归测试。"""

import os
import tempfile
import unittest

from audiobook_generator.tts_providers.segment_synthesis import (
    atomic_export_audio,
    atomic_write_bytes,
)


class _FakeAudio:
    def __init__(self, content=b"new-audio", error=None):
        self.content = content
        self.error = error

    def export(self, path, *, format, **kwargs):
        with open(path, "wb") as file_obj:
            file_obj.write(self.content)
        if self.error is not None:
            raise self.error


class TestAtomicFileHelpers(unittest.TestCase):
    def test_atomic_export_replaces_destination_without_leftovers(self):
        with tempfile.TemporaryDirectory() as root:
            destination = os.path.join(root, "segment.wav")
            atomic_export_audio(_FakeAudio(), destination, format="wav")
            with open(destination, "rb") as file_obj:
                self.assertEqual(file_obj.read(), b"new-audio")
            self.assertEqual(
                [name for name in os.listdir(root) if name.endswith(".tmp")],
                [],
            )

    def test_atomic_export_failure_preserves_old_file_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as root:
            destination = os.path.join(root, "segment.wav")
            atomic_write_bytes(destination, b"old-audio")
            with self.assertRaisesRegex(RuntimeError, "export failed"):
                atomic_export_audio(
                    _FakeAudio(error=RuntimeError("export failed")),
                    destination,
                    format="wav",
                )
            with open(destination, "rb") as file_obj:
                self.assertEqual(file_obj.read(), b"old-audio")
            self.assertEqual(
                [name for name in os.listdir(root) if name.endswith(".tmp")],
                [],
            )


if __name__ == "__main__":
    unittest.main()

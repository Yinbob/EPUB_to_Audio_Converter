"""队列轮询不触发 422 名称警告，且不影响其他警告。"""
import unittest
import warnings
from types import ModuleType
from unittest.mock import patch

from audiobook_generator.utils.gradio_compat import configure_gradio_status_compat


class GradioStatusCompatTest(unittest.TestCase):
    def test_new_starlette_alias_avoids_repeated_warnings(self):
        from starlette import status

        with patch.dict(vars(status), clear=False):
            vars(status).pop("HTTP_422_UNPROCESSABLE_ENTITY", None)
            status.HTTP_422_UNPROCESSABLE_CONTENT = 422
            with warnings.catch_warnings(record=True) as emitted:
                warnings.simplefilter("always")
                configure_gradio_status_compat()
                configure_gradio_status_compat()
                for _ in range(10):
                    self.assertEqual(status.HTTP_422_UNPROCESSABLE_ENTITY, 422)
                self.assertEqual(emitted, [])
                warnings.warn("其他弃用提醒", DeprecationWarning)
                self.assertEqual(len(emitted), 1)

    def test_older_starlette_keeps_existing_constant(self):
        status = ModuleType("starlette.status")
        status.HTTP_422_UNPROCESSABLE_ENTITY = 422
        with patch("starlette.status", status, create=True):
            configure_gradio_status_compat()
        self.assertEqual(status.HTTP_422_UNPROCESSABLE_ENTITY, 422)
        self.assertNotIn("HTTP_422_UNPROCESSABLE_CONTENT", vars(status))

    def test_existing_alias_is_not_overwritten(self):
        status = ModuleType("starlette.status")
        status.HTTP_422_UNPROCESSABLE_ENTITY = 422
        status.HTTP_422_UNPROCESSABLE_CONTENT = 422
        with patch("starlette.status", status, create=True):
            configure_gradio_status_compat()
        self.assertEqual(status.HTTP_422_UNPROCESSABLE_ENTITY, 422)

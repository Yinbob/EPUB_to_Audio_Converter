"""入口与spawn的解释器身份检查，不启动模型或安装环境。"""
import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audiobook_generator.utils import project_runtime


class ProjectRuntimeTest(unittest.TestCase):
    def make_env(self, root, name):
        env = root / name
        (env / 'bin').mkdir(parents=True)
        (env / 'pyvenv.cfg').write_text('home = /unused\n')
        executable = env / 'bin' / 'python3'
        executable.write_text('test fixture; never execute\n')
        executable.chmod(0o700)
        return executable

    def setUp(self):
        for mock in (patch.object(sys, 'prefix', '/system'), patch.object(sys, 'base_prefix', '/system'),
                     patch.dict(os.environ, {}, clear=True)):
            mock.start()
            self.addCleanup(mock.stop)

    def test_ui_prefers_quality_and_cli_keeps_engine_routing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            quality = self.make_env(root, 'venv_audio_quality')
            local = self.make_env(root, 'venv_chatterbox')
            self.assertEqual(project_runtime.select_project_python(root, 'ui', []), quality)
            self.assertEqual(project_runtime.select_project_python(root, 'cli', ['--audio_core_enabled', '--tts', 'openai']), quality)
            for args in (['--tts', 'chatterbox'], ['--tts=voxcpm'], ['--audio_core_enabled', '--tts=chatterbox']):
                self.assertEqual(project_runtime.select_project_python(root, 'cli', args), local)
            self.assertEqual(project_runtime.select_project_python(root, 'cli', ['--tts', 'edge']), local)

    def test_explicit_venv_and_conda_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_env(root, 'venv_audio_quality')
            with patch.object(sys, 'prefix', '/chosen/venv'):
                self.assertIsNone(project_runtime.select_project_python(root, 'ui', []))
            with patch.dict(os.environ, {'CONDA_PREFIX': '/system'}):
                self.assertIsNone(project_runtime.select_project_python(root, 'ui', []))

    def test_missing_or_broken_environment_falls_back_without_installing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertIsNone(project_runtime.select_project_python(root, 'ui', []))
            quality = self.make_env(root, 'venv_audio_quality')
            quality.unlink()
            local = self.make_env(root, 'venv_chatterbox')
            self.assertEqual(project_runtime.select_project_python(root, 'ui', []), local)
            local.chmod(0o600)
            self.assertIsNone(project_runtime.select_project_python(root, 'ui', []))

    def test_exec_preserves_arguments_and_user_cache_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = self.make_env(root, 'venv_audio_quality')
            argv = [str(root / 'main_ui.py'), '--host', '127.0.0.1', '--port', '7999']
            with patch.object(sys, 'argv', argv), patch.object(os, 'execv') as execute, \
                 patch.dict(os.environ, {'HF_HOME': str(root / 'chosen-cache'), 'HF_ENDPOINT': 'https://example.test'}):
                project_runtime.bootstrap_project_python(root, 'ui')
                execute.assert_called_once_with(str(target), [str(target), *argv])
                self.assertEqual(os.environ['HF_HOME'], str(root / 'chosen-cache'))
                self.assertEqual(os.environ['HF_ENDPOINT'], 'https://example.test')
                self.assertTrue(Path(os.environ['NUMBA_CACHE_DIR']).is_dir())

    def test_only_entry_execution_bootstraps_not_import_or_spawn(self):
        root = Path(__file__).resolve().parents[3]
        for file, entry in (('main.py', 'cli'), ('main_ui.py', 'ui')):
            tree = ast.parse((root / file).read_text())
            prefix = []
            for node in tree.body:
                if isinstance(node, ast.Import) and any(alias.name == 'argparse' for alias in node.names):
                    break
                prefix.append(node)
            executable = compile(ast.Module(body=prefix, type_ignores=[]), file, 'exec')
            for module_name in ('main', 'main_ui', '__mp_main__', '__main__'):
                with self.subTest(file=file, name=module_name), \
                     patch.object(project_runtime, 'bootstrap_project_python') as bootstrap:
                    exec(executable, {'__name__': module_name, '__file__': str(root / file)})
                    if module_name == '__main__':
                        bootstrap.assert_called_once_with(str(root), entry)
                    else:
                        bootstrap.assert_not_called()


if __name__ == '__main__':
    unittest.main()

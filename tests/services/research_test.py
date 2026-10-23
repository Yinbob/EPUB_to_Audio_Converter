import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from audiobook_generator.services.projects import Projects
from audiobook_generator.services.files import FileStore
from audiobook_generator.services.models import ProjectEdit
from tests.audiobook_generator.role_script.v2_io_test import _script


class ResearchServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.projects = Projects(self.root, FileStore(self.root))
        self.p = self.projects.put(_script()[0])

    def test_atomic_enable_export_and_recovery(self):
        r = self.projects.research
        value = r.enable(self.p['id'], self.p['revision'], 'enable01')
        self.assertFalse(value['project']['confirmed'])
        self.assertEqual(r.enable(self.p['id'], 0, 'enable01')['state']['revision'], value['state']['revision'])
        key = self.p['id']
        backup = self.projects.entries[key]['path']
        before = Path(backup).read_bytes()
        decision = {'segment_id': 'ch1_s2', 'entity_id': 'narrator'}
        with patch('audiobook_generator.services.research.atomic_json', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                r.decide(key, value['state']['revision'], 'change01', 'segment', decision)
        self.assertEqual(r.read(key)['revision'], value['state']['revision'])
        r.decide(key, value['state']['revision'], 'change01', 'segment', decision)
        self.assertEqual(Path(backup).read_bytes(), before)
        self.projects.meta.unlink()
        recovered = Projects(self.root, FileStore(self.root))
        self.assertEqual(recovered.get(key)['script']['chapters'][0]['segments'][1]['role_id'], 'narrator')
        self.assertEqual([p['id'] for p in recovered.list()], [key])

    def test_existing_edit_is_routed_and_idempotent(self):
        r = self.projects.research
        v = r.enable(self.p['id'], self.p['revision'], 'enable01')['project']
        v = self.projects.edit(v['id'], ProjectEdit(revision=v['revision'], operation='segment',
            data={'segment_id': 'ch1_s2', 'entity_id': 'narrator', 'operation_id': 'change01'}))
        again = r.decide(v['id'], 0, 'change01', 'segment', {'segment_id': 'ch1_s2', 'entity_id': 'narrator'})
        self.assertEqual(again['state']['revision'], v['revision'])
        self.assertTrue(self.projects.edit(v['id'], ProjectEdit(revision=v['revision'], operation='confirm'))['confirmed'])

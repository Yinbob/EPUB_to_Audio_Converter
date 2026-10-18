import hashlib
import tempfile
import unittest
from pathlib import Path
import numpy as np
import soundfile as sf
from audiobook_generator.audio_core.reviewed_edits import crop_confirmed_extra_suffix, compact_confirmed_silence


class ReviewedEditsTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.rate=16000
        speech=(3000*np.sin(np.arange(16000)*.1)).astype(np.int16)
        self.pcm=np.r_[speech,np.ones(32000,dtype=np.int16),speech]
        self.source=self.root/'source.wav'
        sf.write(self.source,self.pcm,self.rate,subtype='PCM_16')
        self.sha=hashlib.sha256(self.source.read_bytes()).hexdigest()

    def review(self,defect):
        return {'confirmed_defect':defect,'audio_sha256':self.sha,'user_reply':'已确认有问题'}

    def test_suffix_candidate_preserves_exact_prefix_and_requires_quiet_cut(self):
        target=self.root/'candidate.wav'
        result=crop_confirmed_extra_suffix(self.source,target,end_sample=32000,expected_sha256=self.sha,
                                          review=self.review('extra_suffix'))
        np.testing.assert_array_equal(sf.read(target,dtype='int16')[0],self.pcm[:32000])
        self.assertEqual(result['human_candidate_review'],'pending')
        with self.assertRaises(ValueError):
            crop_confirmed_extra_suffix(self.source,self.root/'bad.wav',end_sample=8000,
                                        expected_sha256=self.sha,review=self.review('extra_suffix'))

    def test_pause_edit_keeps_all_speech_and_removes_only_quiet_center(self):
        target=self.root/'shorter.wav'
        result=compact_confirmed_silence(self.source,target,quiet_start=16000,quiet_end=48000,
            remove_samples=16000,expected_sha256=self.sha,review=self.review('long_pause'))
        actual=sf.read(target,dtype='int16')[0]
        a,b=result['removed_start_sample'],result['removed_end_sample']
        np.testing.assert_array_equal(actual,np.r_[self.pcm[:a],self.pcm[b:]])
        np.testing.assert_array_equal(actual[:16000],self.pcm[:16000])
        np.testing.assert_array_equal(actual[-16000:],self.pcm[-16000:])
        self.assertEqual(len(actual),48000)

    def test_unconfirmed_wrong_hash_overwrite_and_speech_removal_are_rejected(self):
        for review in ({},self.review('extra_suffix'),{**self.review('long_pause'),'audio_sha256':'wrong'}):
            with self.subTest(review=review),self.assertRaises(ValueError):
                compact_confirmed_silence(self.source,self.root/'bad.wav',quiet_start=16000,quiet_end=48000,
                    remove_samples=16000,expected_sha256=self.sha,review=review)
        with self.assertRaises(ValueError):
            compact_confirmed_silence(self.source,self.source,quiet_start=16000,quiet_end=48000,
                remove_samples=16000,expected_sha256=self.sha,review=self.review('long_pause'))
        with self.assertRaises(ValueError):
            compact_confirmed_silence(self.source,self.root/'bad.wav',quiet_start=0,quiet_end=48000,
                remove_samples=16000,expected_sha256=self.sha,review=self.review('long_pause'))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.sha)


if __name__=='__main__':unittest.main()

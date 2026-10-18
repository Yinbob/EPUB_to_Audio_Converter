"""离线评估适配器；只读取用户配置的本地模型，不隐式下载。"""
from pathlib import Path

import numpy as np

from .audio import frame_rms, load_audio, mono_resampled
from .model_identity import local_model_identity


class SenseVoiceBackend:
    def __init__(self, model_dir=None):
        self.model_dir = model_dir

    def cache_identity(self):
        return local_model_identity('asr', self.model_dir)

    def __call__(self, path):
        if not self.model_dir or not Path(self.model_dir).is_dir():
            raise RuntimeError("请配置本地 SenseVoice 模型目录；尚未评估内容完整性")
        from audiobook_generator.utils.voxcpm_asr import transcribe_audio
        return transcribe_audio(str(path), model_id=str(Path(self.model_dir).resolve()), device="cpu",
                                model_revision=self.cache_identity()['fingerprint'])


class SpeakerEncoder:
    def __init__(self, model_dir=None):
        self.model_dir, self.model, self.model_revision = model_dir, None, None

    def cache_identity(self):
        return local_model_identity('speaker', self.model_dir)

    def __call__(self, path):
        if not self.model_dir or not Path(self.model_dir, "hyperparams.yaml").is_file():
            raise RuntimeError("请配置完整的本地 ECAPA 模型目录；尚未评估音色一致性")
        required = ("embedding_model.ckpt", "mean_var_norm_emb.ckpt", "classifier.ckpt", "label_encoder.txt")
        if any(not Path(self.model_dir, name).is_file() for name in required):
            raise RuntimeError("ECAPA 本地权重不完整，禁止自动下载")
        samples, rate = load_audio(path)
        mono = mono_resampled(samples, rate)
        if min(len(mono) / 16000, float(np.sum(frame_rms(mono, 16000) >= .003)) * .02) < 3:
            raise ValueError("音色判断需要至少三秒有效语音，短片段待复核")
        revision = self.cache_identity()['fingerprint']
        if self.model is None or self.model_revision != revision:
            from speechbrain.inference.speaker import EncoderClassifier
            self.model = EncoderClassifier.from_hparams(
                source=str(Path(self.model_dir).resolve()), savedir=str(Path(self.model_dir).resolve()),
                overrides={"pretrained_path": str(Path(self.model_dir).resolve())},
                run_opts={"device": "cpu"})
            self.model_revision = revision
        import torch
        with torch.inference_mode():
            vector = self.model.encode_batch(torch.from_numpy(mono).unsqueeze(0)).cpu().numpy().reshape(-1)
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm <= 0:
            raise ValueError("声纹向量无效")
        return vector / norm


class SileroVAD:
    def __init__(self):
        self.model = None

    def __call__(self, path):
        # 使用 pip 包随附的模型，避免 torch.hub 自动访问网络。
        from silero_vad import get_speech_timestamps, load_silero_vad
        import torch
        if self.model is None:
            self.model = load_silero_vad(onnx=True)
        samples, rate = load_audio(path)
        mono = mono_resampled(samples, rate)
        spans = get_speech_timestamps(torch.from_numpy(mono), self.model, sampling_rate=16000)
        return sum(s["end"] - s["start"] for s in spans) / 16000

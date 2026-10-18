"""跨章声音参考：区分人工核验档案与仅作机器比对的克隆输入。"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .store import fingerprint


def clone_conditioning_reference(profile):
    """复用合成输入做机器比对，不将其冒充人工核验或内容／语速参考。"""
    if profile.get('voice_mode') != 'clone':
        return None
    from audiobook_generator.tts_providers.mimo_reference import load_clone_reference
    from .audio import signal_features
    path = profile.get('reference_audio_path')
    digest = profile.get('reference_audio_sha256')
    load_clone_reference(path, digest)
    metrics = signal_features(path)
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
        raise ValueError('克隆参考在信号检查期间发生变化')
    if metrics['peak'] < .003 or metrics['clipped_fraction'] > .002:
        return None
    metrics.update(audio_sha256=digest, fixed_reference_sha256=digest,
                   fixed_reference_kind='clone_conditioning_reference',
                   rate_estimate_usable_for_heuristics=False)
    return str(Path(path).resolve()), metrics


def reference_key(role_id, profile, language, route):
    if not profile.get('voice_profile_id') or not profile.get('voice_version'):
        raise ValueError('固定参考需要带版本和档案ID的角色声音')
    return fingerprint({'role': role_id, 'profile': profile, 'language': language, 'request': route})


def make_reference(role_id, profile, language, route, path, metrics, review):
    source = Path(path).resolve()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if (review.get('audio_sha256') != digest or review.get('role_id') != role_id
            or review.get('voice_version') != profile.get('voice_version')
            or any(review.get(k) is not True for k in ('content_complete', 'signal_acceptable', 'identity_accepted'))):
        raise ValueError('固定参考必须有匹配音频／角色／声音版本的三项人工确认')
    if not metrics or metrics.get('peak', 0) < .003 or metrics.get('clipped_fraction', 1) > .002:
        raise ValueError('固定参考的实际信号检查尚未合格')
    key = reference_key(role_id, profile, language, route)
    return key, {'role_id': role_id, 'profile': profile, 'language': language, 'request': route,
                 'path': str(source), 'audio_sha256': digest, 'metrics': metrics,
                 'human_review': review, 'status': 'human_confirmed_fixed_reference'}


def load_reference(registry_path, role_id, profile, language, route):
    key = reference_key(role_id, profile, language, route)
    registry = json.loads(Path(registry_path).read_text(encoding='utf-8'))
    if registry.get('schema_version') != 'mimo-role-references-v1':
        raise ValueError('角色固定参考文件版本无效')
    record = registry.get('references', {}).get(key)
    if record is None:
        return None
    checked_key, checked = make_reference(role_id, profile, language, route, record['path'],
                                         record['metrics'], record['human_review'])
    if checked_key != key or checked['audio_sha256'] != record.get('audio_sha256'):
        raise ValueError('固定参考音频内容已变更，不能继续作为人工核验锚点')
    metrics = {**checked['metrics'], 'fixed_reference_kind': 'human_confirmed_fixed_reference',
               'fixed_reference_sha256': checked['audio_sha256']}
    return checked['path'], metrics

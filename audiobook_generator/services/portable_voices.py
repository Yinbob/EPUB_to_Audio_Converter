"""可迁移声音卡：逻辑身份与服务端音色分开，版本及参考文件不可静默替换。"""
import copy
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from .common import ServiceError, atomic_json, read_json

SCHEMA = 'portable-voice-v1'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def provider_id(provider):
    # openai 是本项目 MiMo 的历史配置别名，不代表 OpenAI 官方音色通用。
    return 'mimo' if provider == 'openai' else provider


def endpoint_for(provider):
    from .settings import credentials
    if provider_id(provider) == 'minimax':
        return 'https://api.minimaxi.com'
    return credentials('openai')['base_url'].rstrip('/')


def valid_endpoint(value):
    parts = urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('声音绑定需使用不含凭据、查询参数的 HTTPS 服务地址')
    return value.rstrip('/')


class PortableVoices:
    def __init__(self, root):
        self.root = Path(root)
        self.directory = self.root / '.studio' / 'portable_voices'
        self.index = self.directory / 'index.json'

    def list(self):
        return [self.get(key, version) for key, version in read_json(self.index, {}).items()]

    def get(self, key, version):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', str(key)) or not re.fullmatch(r'[0-9a-f]{64}', str(version)):
            raise ServiceError('voice_version', '请选择有效的声音卡和固定版本。')
        value = read_json(self.directory / key / (version + '.json'), None)
        if value is None:
            raise ServiceError('voice_missing', '声音卡版本不存在，请重新导入。', 404)
        if fingerprint({k: v for k, v in value.items() if k != 'version'}) != version:
            raise ServiceError('voice_changed', '声音卡内容与版本摘要不一致。')
        return value

    def _asset(self, path):
        path = Path(path)
        if path.stat().st_size > 25 * 1024 * 1024:
            raise ValueError('声音卡参考与试听文件每份不能超过 25 MB')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        target = self.directory / 'assets' / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(path, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('声音资源摘要不一致')
        return digest

    def _validate(self, value):
        if not isinstance(value, dict):
            raise ValueError('声音卡必须是 JSON 对象')
        if set(value) - {'schema_version', 'id', 'label', 'language', 'bindings', 'version'}:
            raise ValueError('声音卡包含未识别字段')
        if value.get('schema_version') != SCHEMA or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', str(value.get('id', ''))):
            raise ValueError('声音卡格式或逻辑 ID 无效')
        if not isinstance(value.get('label'), str) or not 1 <= len(value['label']) <= 128 or value.get('language') not in ('zh', 'en'):
            raise ValueError('请填写声音名称和中文／英语语言')
        if not isinstance(value.get('bindings'), list) or not value['bindings'] or len(value['bindings']) > 32:
            raise ValueError('声音卡需要 1～32 个提供商绑定')
        seen = set()
        for binding in value['bindings']:
            required = {'provider', 'model', 'endpoint', 'params', 'audition_sha256', 'confirmed'}
            if not isinstance(binding, dict) or not required <= set(binding) or set(binding) - required - {'reference'}:
                raise ValueError('声音绑定字段不完整或含未识别字段')
            binding['provider'] = provider_id(binding['provider'])
            if binding['provider'] not in ('mimo', 'minimax') or binding['confirmed'] is not True:
                raise ValueError('首批仅支持经试听确认的 MiMo / MiniMax 绑定')
            if not isinstance(binding['model'], str) or not 1 <= len(binding['model']) <= 200:
                raise ValueError('绑定缺少模型')
            binding['endpoint'] = valid_endpoint(binding['endpoint'])
            scope = (binding['provider'], binding['model'], binding['endpoint'])
            if scope in seen:
                raise ValueError('同一提供商、模型和地址只能有一个绑定')
            seen.add(scope)
            params = copy.deepcopy(binding['params'])
            if not isinstance(params, dict):
                raise ValueError('声音参数必须是对象')
            reference = params.pop('reference_audio_sha256', None)
            if reference:
                asset = self._reference(reference)
                # 校验器仍使用实际路径；可迁移 JSON 内只存摘要。
                params['reference_audio_sha256'] = reference
                params['reference_audio_path'] = str(asset)
            if 'reference_audio_path' in binding['params']:
                raise ValueError('可迁移声音卡不能包含本地绝对路径')
            from audiobook_generator.role_script.validator import _normalize_params
            from audiobook_generator.role_script.errors import ValidationReport
            report = ValidationReport()
            _normalize_params('portable', params, 'openai' if binding['provider'] == 'mimo' else 'minimax', report)
            if not report.ok:
                raise ValueError('声音绑定参数无效：' + '；'.join(e.message for e in report.errors))
            self._checked_asset(binding['audition_sha256'])
            if 'reference' in binding:
                reference = binding['reference']
                if (not isinstance(reference, dict) or set(reference) != {'sha256', 'format'}
                        or reference['format'] not in ('wav', 'mp3', 'm4a')):
                    raise ValueError('克隆源参考格式无效')
                self._checked_asset(reference['sha256'])

    def _checked_asset(self, digest):
        if not re.fullmatch(r'[0-9a-f]{64}', str(digest)):
            raise ValueError('声音资源摘要无效')
        path = self.directory / 'assets' / digest
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('声音资源缺失或摘要已变化，请导入完整 ZIP 声音卡')
        return path

    def _reference(self, digest):
        path = self.root / '.voice_references' / (digest + '.wav')
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._checked_asset(digest), path)
        return path.resolve()

    def put(self, value):
        value = copy.deepcopy(value)
        value.pop('version', None)
        self._validate(value)
        value['version'] = fingerprint(value)
        atomic_json(self.directory / value['id'] / (value['version'] + '.json'), value)
        index = read_json(self.index, {})
        index[value['id']] = value['version']
        atomic_json(self.index, index)
        return value

    def from_preview(self, manager, task_id, *, key, label, language, confirmed, previous_version=None):
        if confirmed is not True:
            raise ValueError('请听完试听并确认后保存绑定')
        task = manager.get(task_id)
        if task['status'] != 'succeeded' or task['kind'] not in ('preview', 'voice_clone'):
            raise ValueError('只能保存已成功完成的试听')
        binding = read_json(manager.directory / task_id / 'voice_binding.json', {})
        if not binding:
            raise ValueError('此试听缺少提供商参数快照，请重新试听')
        audio = manager.files.resolve(task['result']['audio']['id'])
        if self._asset(audio) != binding.pop('audio_sha256', None):
            raise ValueError('试听音频已变化，请重新生成')
        params = binding['params']
        source_reference = binding.pop('reference_path', None)
        if source_reference:
            binding['reference'] = {'sha256': self._asset(source_reference), 'format': Path(source_reference).suffix.lstrip('.').lower()}
        path = params.pop('reference_audio_path', None)
        if path:
            if self._asset(path) != params.get('reference_audio_sha256'):
                raise ValueError('参考音频已变化')
        if binding['provider'] == 'mimo' and params.get('voice_mode') == 'design':
            # 描述生成具有随机性，保存试听时固定这一份实际声音作为克隆参考。
            digest = self._asset(audio)
            reference = self._reference(digest)
            from audiobook_generator.tts_providers.mimo_reference import load_clone_reference
            load_clone_reference(str(reference), digest)
            params.pop('voice_description', None)
            params.update(voice_mode='clone', reference_audio_sha256=digest)
            params['voice_version'] = fingerprint(params)
        binding.update(audition_sha256=self._asset(audio), confirmed=True)
        bindings = []
        if previous_version:
            previous = self.get(key, previous_version)
            if read_json(self.index, {}).get(key) != previous_version:
                raise ServiceError('voice_conflict', '声音卡已变化，请刷新后再保存。', 409)
            bindings = previous['bindings']
        elif key in read_json(self.index, {}):
            raise ServiceError('voice_conflict', '此逻辑 ID 已存在，请选择已有声音卡添加绑定。', 409)
        scope = lambda b: (b['provider'], b['model'], b['endpoint'])
        bindings = [b for b in bindings if scope(b) != scope(binding)] + [binding]
        return self.put(dict(schema_version=SCHEMA, id=key, label=label, language=language, bindings=bindings))

    def resolve(self, key, version, provider, model, endpoint=None):
        value = self.get(key, version)
        self._validate(value)
        scope = (provider_id(provider), model, valid_endpoint(endpoint or endpoint_for(provider)))
        binding = next((b for b in value['bindings'] if (b['provider'], b['model'], b['endpoint']) == scope), None)
        if not binding:
            raise ServiceError('voice_binding_missing', '此声音卡没有当前模型和服务地址的已确认绑定，请先试听并添加替代声音。')
        params = copy.deepcopy(binding['params'])
        if params.get('reference_audio_sha256'):
            # MiMo 要求 WAV 扩展名；复制到正式引用库且保留摘要。
            digest = params['reference_audio_sha256']
            params['reference_audio_path'] = str(self._reference(digest))
        return params, value

    def export(self, key, version):
        value = self.get(key, version)
        self._validate(value)
        target = self.directory / (key + '-' + version[:12] + '.zip')
        digests = {b['audition_sha256'] for b in value['bindings']}
        digests.update(b['params']['reference_audio_sha256'] for b in value['bindings'] if b['params'].get('reference_audio_sha256'))
        digests.update(b['reference']['sha256'] for b in value['bindings'] if b.get('reference'))
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('voice.json', json.dumps(value, ensure_ascii=False, indent=2))
            for digest in sorted(digests):
                archive.write(self._checked_asset(digest), 'assets/' + digest)
        return target

    def import_file(self, path):
        try:
            return self._import_zip(path)
        except (zipfile.BadZipFile, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            raise ValueError('声音卡 ZIP 格式错误或内容不完整') from exc

    def _import_zip(self, path):
        with zipfile.ZipFile(path) as archive:
            items = archive.infolist()
            if len(items) > 66 or sum(i.file_size for i in items) > 100 * 1024 * 1024:
                raise ValueError('声音卡内容超过限制')
            if len({i.filename for i in items}) != len(items):
                raise ValueError('声音卡包含重复文件')
            for item in items:
                if item.filename != 'voice.json' and not re.fullmatch(r'assets/[0-9a-f]{64}', item.filename):
                    raise ValueError('声音卡包含无效文件路径')
                if item.file_size > (1024 * 1024 if item.filename == 'voice.json' else 25 * 1024 * 1024):
                    raise ValueError('声音卡单个资源超过大小限制')
            value = json.loads(archive.read('voice.json'))
            expected = value.get('version')
            if fingerprint({k: v for k, v in value.items() if k != 'version'}) != expected:
                raise ValueError('声音卡版本摘要不一致')
            for item in items:
                if item.filename.startswith('assets/'):
                    raw = archive.read(item)
                    digest = item.filename[7:]
                    if hashlib.sha256(raw).hexdigest() != digest:
                        raise ValueError('声音资源摘要不一致')
                    target = self.directory / 'assets' / digest
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
        return self.put(value)

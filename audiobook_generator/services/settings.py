"""沿用已有凭证文件；不通过初始化接口泄漏密钥。"""
import hashlib
import hmac
import importlib
import os
import secrets
import threading
from .common import ROOT, ServiceError, atomic_json, read_json

DEFAULTS = dict(output_text=False, preview=False, remove_endnotes=False,
                remove_reference_numbers=False, show_voice_instructions=False)
PROVIDERS = {'openai': 'mimo', 'minimax': 'minimax', 'qwen': 'qwen', 'deepseek': 'deepseek'}


def verify_hash(encoded, password):
    if encoded.startswith('pbkdf2$'):
        _, salt, digest = encoded.split('$')
        candidate = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000).hex()
    else:
        candidate, digest = hashlib.sha256(password.encode()).hexdigest(), encoded
    return hmac.compare_digest(candidate, digest)


class Settings:
    def __init__(self, root=ROOT):
        self.path = root / '.webui_settings.json'
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            return {**DEFAULTS, **read_json(self.path, {})}

    def save(self, values):
        with self.lock:
            current = self.read()
            current.update(values)
            atomic_json(self.path, current)

    def verify(self, password):
        encoded = self.read().get('admin_password_hash', hashlib.sha256(b'admin').hexdigest())
        valid = verify_hash(encoded, password)
        if valid and not encoded.startswith('pbkdf2$'):
            self.password(password)
        return valid

    def password(self, password):
        if len(password) < 4:
            raise ServiceError('password_short', '新密码至少需要 4 位。')
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 260000).hex()
        self.save({'admin_password_hash': f'pbkdf2${salt.hex()}${digest}'})


def module(provider):
    if provider not in PROVIDERS:
        raise ServiceError('provider_unknown', '不支持此配置提供商。')
    name = PROVIDERS[provider]
    return importlib.import_module(f'audiobook_generator.utils.{name}_config'), name


def credentials(provider):
    mod, name = module(provider)
    value = getattr(mod, f'load_{name}_config')().copy()
    env_name = {'openai': 'OPENAI', 'minimax': 'MINIMAX', 'qwen': 'QWEN_TTS', 'deepseek': 'DEEPSEEK'}[provider]
    # 与现有 resolve 函数相同：文件优先于环境。
    for key in ('api_key', 'base_url', 'model'):
        value[key] = value.get(key) or os.getenv(f'{env_name}_{key.upper()}') or ''
    if provider == 'openai':
        value['base_url'] = value['base_url'] or mod.DEFAULT_BASE_URL
    if provider in ('qwen', 'deepseek'):
        value['base_url'] = value['base_url'] or mod.DEFAULT_BASE_URL
        value['model'] = value['model'] or mod.DEFAULT_MODEL
    return value


def config_view(provider, reveal=False):
    value = credentials(provider)
    key = value.pop('api_key', '')
    value.update(configured=bool(key), masked_key=('••••••••' + key[-4:] if key else ''))
    if reveal:
        value['api_key'] = key
    return value


def save_config(provider, value):
    mod, name = module(provider)
    current = credentials(provider)
    key = '' if value.get('clear_key') else (value.get('api_key') or current['api_key'])
    if '•' in key:
        raise ServiceError('masked_key', '请填写真实 API Key，或留空保留现有密钥。')
    args = [key]
    if provider != 'minimax':
        args.append(value.get('base_url') or current['base_url'])
    if provider in ('qwen', 'deepseek'):
        args.append(value.get('model') or current.get('model'))
    getattr(mod, f'save_{name}_config')(*args)
    return config_view(provider)


def require_credentials(provider):
    if provider in PROVIDERS and not credentials(provider)['api_key']:
        raise ServiceError('credentials_missing', f'请先在设置中配置 {provider} 的 API Key。')

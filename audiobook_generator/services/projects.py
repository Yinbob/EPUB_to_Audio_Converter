"""角色项目版本、确认签名和原子操作。"""
import hashlib
import json
import threading
from pathlib import Path
from .common import ServiceError, atomic_json, read_json


def encode(script):
    from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
    return role_script_to_dict(script)


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def decode(value):
    from audiobook_generator.role_script.loader import parse_role_script
    from audiobook_generator.role_script.errors import ValidationReport
    from audiobook_generator.role_script.validator import validate_role_script
    report = ValidationReport()
    script = parse_role_script(value, report)
    if not report.ok or script is None:
        raise ServiceError('script_invalid', json.dumps(report.to_dict(), ensure_ascii=False))
    result = validate_role_script(script)
    if not result.ok:
        raise ServiceError('script_invalid', json.dumps(result.report.to_dict(), ensure_ascii=False))
    return result.script


class Projects:
    def __init__(self, root, files):
        self.root = Path(root)
        self.files = files
        self.lock = threading.RLock()
        self.manager = None
        self.meta = self.root / '.studio' / 'projects.json'
        self.entries = read_json(self.meta, {})
        # 已有 V2 项目原地登记，不改写用户文件。
        for path in (self.root / '.role_projects').glob('*.json'):
            key = signature(str(path.resolve()))[:32]
            self.entries.setdefault(key, {'path': str(path.resolve()), 'revision': 1, 'confirmed': '', 'generated': True})

    def list(self):
        with self.lock:
            return [{'id': key, **{k: v for k, v in meta.items() if k != 'path'}} for key, meta in self.entries.items()]

    def get(self, key):
        with self.lock:
            if key not in self.entries:
                raise ServiceError('project_missing', '找不到角色项目，请重新载入。', 404)
            meta = self.entries[key]
            data = read_json(meta['path'])
            current_hash = signature(data)
            if not meta.get('content_hash'):
                meta['content_hash'] = current_hash
                atomic_json(self.meta, self.entries)
            elif meta['content_hash'] != current_hash:
                meta.update(revision=meta['revision'] + 1, confirmed='', content_hash=current_hash)
                atomic_json(self.meta, self.entries)
            return {'id': key, 'revision': meta['revision'], 'confirmed': meta.get('confirmed') == signature(data),
                    'script': data, 'file': self.files.register(meta['path'])}

    def put(self, script, key=None, confirmed=False):
        from audiobook_generator.role_script.project_store import save_project
        data = encode(script)
        with self.lock:
            if key is None:
                key = signature(data['book_sha256'] + data['provider'])[:32]
            previous = self.entries.get(key, {})
            path = previous.get('path') or str(self.root / '.role_projects' / (key + '.json'))
            save_project(script, path)
            self.entries[key] = {'path': path, 'revision': previous.get('revision', 0) + 1,
                                 'confirmed': signature(data) if confirmed else '', 'generated': not confirmed, 'content_hash': signature(data)}
            atomic_json(self.meta, self.entries)
            return self.get(key)

    def invalidate(self, key):
        if key:
            self.entries[key]['confirmed'] = ''
            atomic_json(self.meta, self.entries)

    def check_revision(self, key, revision):
        value = self.get(key)
        if value['revision'] != revision:
            raise ServiceError('revision_conflict', '项目已被其他操作修改，请刷新后重试。', 409)
        return value

    def for_generation(self, key, revision, provider):
        value = self.check_revision(key, revision)
        if not value['confirmed']:
            raise ServiceError('confirmation_required', '剧本已变化，请复核并重新确认后生成。', 409)
        script = decode(value['script'])
        if script.provider != provider:
            raise ServiceError('role_provider', '剧本提供商与当前引擎不一致。')
        return script

    def edit(self, key, request):
        from dataclasses import replace
        from audiobook_generator.role_script.review import (
            assign_chapter_narrator, confirm_segment_speaker, merge_entities, lock_entity_voice)
        with self.lock:
            if self.manager:
                self.manager.require_idle()
            value = self.check_revision(key, request.revision)
            script = decode(value['script'])
            data, operation = request.data, request.operation
            if operation in ('narrator', 'segment', 'merge', 'lock', 'casting_apply') and script.schema_version != 2:
                raise ServiceError('v2_required', '此操作需要 V2 剧本，请重新拆分后使用。')
            if operation == 'confirm':
                self.entries[key]['confirmed'] = signature(value['script'])
                atomic_json(self.meta, self.entries)
                return self.get(key)
            if operation == 'replace':
                replacement = decode(data)
                if replacement.book_sha256 != script.book_sha256 or replacement.provider != script.provider:
                    raise ServiceError('project_identity', '不能通过编辑改变书籍或提供商。')
                script = replacement
            elif operation == 'narrator':
                script, _ = assign_chapter_narrator(script, data['chapter_index'], data['entity_id'])
            elif operation == 'segment':
                script = confirm_segment_speaker(script, data['segment_id'], data['entity_id'])
            elif operation == 'merge':
                script = merge_entities(script, data['source_id'], data['target_id'])
            elif operation == 'lock':
                script = lock_entity_voice(script, data['entity_id'], data.get('locked', True))
            elif operation == 'voice':
                from audiobook_generator.ui.role_voices import make_voice_profile
                role_id = data['role_id']
                if role_id not in script.roles:
                    raise ServiceError('role_missing', '人物不存在。')
                if script.provider == 'openai':
                    reference = str(self.files.resolve(data['reference_id'])) if data.get('reference_id') else script.roles[role_id].provider_params.get('reference_audio_path')
                    params = make_voice_profile(role_id, data.get('mode', 'preset'), data.get('voice'),
                        data.get('description'), reference,
                        data.get('language', 'zh'), data.get('speed', 1), data.get('instructions', ''), self.root)
                else:
                    params = {'voice_id': data['voice'], 'speed': data.get('speed', 1),
                              'pitch': data.get('pitch', 0), 'volume': data.get('volume', 1)}
                roles = dict(script.roles)
                roles[role_id] = replace(roles[role_id], provider_params=params)
                script = replace(script, roles=roles)
            elif operation == 'casting_apply':
                from audiobook_generator.ui.book_casting import load_bank
                controller = self.casting(key, data['book'])
                bank = load_bank(self.files.resolve(data['bank_id']), data.get('language', 'zh'))
                script = controller.apply(bank, data['draft_id'], data.get('rows'))
            return self.put(decode(encode(script)), key)

    def casting(self, key, book):
        from audiobook_generator.ui.book_casting import BookCasting
        from .models import BookRequest
        from .books import read_book
        book = BookRequest.model_validate(book)
        catalog, chapters = read_book(book, self.files)
        value = self.get(key)
        script = decode(value['script'])
        if script.book_sha256 != catalog['book_sha256']:
            raise ServiceError('book_mismatch', '请选择此项目对应的书籍。')
        return BookCasting(self.root, chapters, catalog['parser_fingerprint'], script,
                           source_revision=str(value['revision']))

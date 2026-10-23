"""全书声音草案的离线控制层：检查覆盖、逐章续做、分批保存，正式项目只在应用时更新。"""
from __future__ import annotations

import json
import math
import os
import tempfile
import uuid
from dataclasses import asdict, replace
from pathlib import Path

from audiobook_generator.audio_core.hybrid_casting import (
    apply_hybrid, generate_voice_cards, hybrid_casting, role_usage, script_identity,
)
from audiobook_generator.audio_core.casting import voice_distance
from audiobook_generator.audio_core.store import fingerprint
from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
from audiobook_generator.role_script.errors import ValidationReport
from audiobook_generator.role_script.loader import parse_role_script
from audiobook_generator.role_script.models import RoleScriptV2
from audiobook_generator.role_script.normalization import normalize_coverage_text, normalize_gender
from audiobook_generator.role_script.project_store import chapter_hashes
from audiobook_generator.role_script.split_control import current_split_control
from audiobook_generator.role_script.v2_generation import generate_v2_for_book
from audiobook_generator.tts_providers.voice_catalog import get_voice_entry


REASONS = {
    'user_locked': '保留已锁定声音', 'dialogue_rank': '朗读量排名靠前，优先使用适合的内置声音',
    'narrator_reserved': '独立旁白有实际内容，先预留一个内置声音',
    'no_acceptable_preset': '无合适内置声音', 'preset_capacity_exhausted': '适合的内置名额已用完',
    'preset_fit_capacity_conflict': '剩余内置声音不适合', 'no_spoken_text': '没有实际朗读内容，保留原配置',
}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.casting-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def decode_script(payload):
    report = ValidationReport()
    script = parse_role_script(payload, report)
    if not report.ok or not isinstance(script, RoleScriptV2):
        raise ValueError('保存的全书分析无效，请重新分析：' + str(report.to_dict()))
    return script


def check_task():
    control = current_split_control()
    if control:
        control.check()


def coverage(script, chapters, parser_fp, book_sha):
    """名单完整或哈希表完整都不能证明段落已分析；逐章核对实际正文。"""
    total = len(chapters)
    matching = (isinstance(script, RoleScriptV2) and script.book_sha256 == book_sha
                and script.parser_fingerprint == parser_fp and script.chapter_hashes == chapter_hashes(chapters))
    complete = []
    if matching:
        indexed = {}
        for chapter in script.chapters:
            indexed.setdefault(chapter.chapter_index, []).append(chapter)
        for index, (_title, text) in enumerate(chapters, 1):
            items = indexed.get(index, [])
            if (len(items) == 1 and items[0].segments
                    and normalize_coverage_text(''.join(s.text for s in items[0].segments)) == normalize_coverage_text(text)):
                complete.append(index)
    return {'total': total, 'complete': complete,
            'missing': [i for i in range(1, total + 1) if i not in complete],
            'full_book': total > 0 and len(complete) == total}


def load_bank(path, language):
    from audiobook_generator.tts_providers.openai_tts_provider import get_openai_supported_voices
    bank = read_json(path)
    voices = bank.get('voices', {})
    if (bank.get('provider') != 'openai' or language not in {'en', 'zh'}
            or language not in bank.get('languages', []) or not isinstance(voices, dict) or not voices):
        raise ValueError('请选择对应中文或英文、含实际探针的已核验 MiMo 声音库')
    if any(v == 'mimo_default' or v not in get_openai_supported_voices()
           or not isinstance(data, dict) or data.get('verified') is not True for v, data in voices.items()):
        raise ValueError('声音库包含未核验或不支持的声音')
    for a in voices:
        # 单声音库也验证特征；两条共同探针是现有声纹比较的最低要求。
        for b in voices:
            voice_distance(voices[a], voices[b])
    return bank


def discover_banks(output_root):
    roots = [Path(output_root), Path(__file__).resolve().parents[2] / 'audiobook_output']
    choices, seen = [], set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob('*voice_bank*.json')):
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            for language, label in [('zh', '中文'), ('en', '英文')]:
                try:
                    bank = load_bank(path, language)
                    choices.append((f'{label} · {len(bank["voices"])} 个已核验声音 · {path.parent.name}/{path.name}', resolved))
                except (ValueError, KeyError, TypeError, OSError):
                    continue
    return choices


def fit_matrix(script, bank, language):
    manual = bank.get('fit_penalties')
    if manual is not None and (set(manual) != set(script.roles)
            or any(set(row) != set(bank['voices']) for row in manual.values())):
        raise ValueError('导入库的人工适配表须完整覆盖当前角色和声音')
    fit = {}
    for role, definition in script.roles.items():
        fit[role] = {}
        gender = normalize_gender(definition.gender)
        for voice, data in bank['voices'].items():
            entry = get_voice_entry('openai', voice)
            known_gender = normalize_gender(entry.gender if entry else None)
            # 探针库可补充人工核验属性，未知属性不从声音名称猜测。
            known_gender = normalize_gender(data.get('gender')) or known_gender
            declared_language = data.get('language') or (entry.language if entry else '')
            if declared_language:
                from audiobook_generator.audio_core.language import normalize_language
                try:
                    declared_language = normalize_language(declared_language)
                except ValueError:
                    pass  # 已知为其他语言也排除，未知／未填写则不猜。
            penalty = 0 if manual is None else manual[role][voice]
            if isinstance(penalty, bool) or not isinstance(penalty, (int, float)) or penalty < 0 or not math.isfinite(penalty):
                raise ValueError('人工适配评分必须为有限非负数')
            if (gender and known_gender and gender != known_gender) or (
                    declared_language and declared_language not in {'auto', 'unknown', 'mixed', '未知'} and declared_language != language):
                penalty = max(2., penalty)
            fit[role][voice] = penalty
    return fit


class BookCasting:
    def __init__(self, output_root, chapters, parser_fp, source, *, source_revision=''):
        if not isinstance(source, RoleScriptV2) or source.provider != 'openai':
            raise ValueError('全书自动分配需要本书的 MiMo V2 角色剧本，请先生成或载入剧本')
        self.chapters = chapters
        self.parser_fp = parser_fp
        self.source = source
        self.binding = fingerprint({'script': script_identity(source), 'revision': source_revision,
                                    'chapters': chapter_hashes(chapters), 'parser': parser_fp})
        analysis_source = asdict(source)
        for definition in analysis_source['roles'].values():
            definition.pop('provider_params', None)
        for entity in analysis_source['entities'].values():
            entity.pop('voice_locked', None)
            entity.pop('voice_profile_id', None)
        # 调音色、锁声音不重新发送已分析的章节；归属、人物合并变化仍要求重算。
        self.analysis_binding = fingerprint({'source': analysis_source, 'chapters': chapter_hashes(chapters), 'parser': parser_fp})
        self.root = Path(output_root) / '.role_casting' / source.book_sha256
        self.analysis_path = self.root / 'analysis.json'
        self.draft_path = self.root / 'draft.json'

    def analyzed_script(self):
        script = self.source
        if self.analysis_path.is_file():
            saved = read_json(self.analysis_path)
            if (saved.get('analysis_binding') == self.analysis_binding
                    or saved.get('source_binding') == self.binding):
                script = decode_script(saved['script'])
                script = replace(script, roles={**script.roles, **{
                    r: replace(script.roles.get(r, d), provider_params=d.provider_params) for r, d in self.source.roles.items()}},
                    entities={**script.entities, **{r: replace(script.entities.get(r, e),
                        voice_locked=e.voice_locked, voice_profile_id=e.voice_profile_id) for r,e in self.source.entities.items()}})
        proof = coverage(script, self.chapters, self.parser_fp, self.source.book_sha256)
        # 不兼容的原项目只能贡献稳定人物和声音，不能贡献旧正文。
        valid = set(proof['complete'])
        return replace(script, chapters=tuple(c for c in script.chapters if c.chapter_index in valid))

    def progress(self):
        return coverage(self.analyzed_script(), self.chapters, self.parser_fp, self.source.book_sha256)

    def analyze(self, *, api_key, base_url, model, progress=None, generate=None):
        generate = generate or generate_v2_for_book
        script = self.analyzed_script()
        proof = self.progress()
        for index in proof['missing']:
            check_task()
            if progress:
                progress(None, desc=f'全书分析：已完成 {len(script.chapters)}/{len(self.chapters)} 章，正在分析第 {index} 章')
            result = generate(self.chapters, index, index, 'openai', self.source.book_sha256,
                              api_key, base_url, model, parser_fingerprint=self.parser_fp,
                              previous=script, index_full_book=False,
                              progress=(lambda message: progress(None, desc=str(message))) if progress else None)
            check_task()
            verified = coverage(result, self.chapters, self.parser_fp, self.source.book_sha256)
            if index not in verified['complete']:
                raise ValueError(f'第 {index} 章未覆盖原文，未计为已完成')
            # 累积结果逐章原子保存；失败只损失尚未完成的这一章。
            script = replace(result, registry_complete=verified['full_book'] and not result.registry_warnings)
            atomic_json(self.analysis_path, {'source_binding': self.binding, 'analysis_binding': self.analysis_binding,
                                             'script': role_script_to_dict(script)})
        return self.progress()

    def usage(self, language):
        script = self.analyzed_script()
        proof = self.progress()
        if not script.chapters:
            return None, proof
        value = role_usage(script, language=language, full_book=proof['full_book'], attribution_policy='draft')
        value['scope_evidence'] = 'parsed_chapter_text_verified' if proof['full_book'] else 'incomplete_chapter_coverage'
        value['coverage'] = proof
        return value, proof

    def read_draft(self):
        if not self.draft_path.is_file():
            return None
        value = read_json(self.draft_path)
        return value if value.get('source_binding') == self.binding else None

    def make_draft(self, bank, language, *, client, model, progress=None):
        script = self.analyzed_script()
        usage, proof = self.usage(language)
        if not proof['full_book']:
            raise ValueError(f'全书尚缺 {len(proof["missing"])} 章，请先点击“分析全书”')
        manifest = hybrid_casting(script, bank, language=language, full_book=True,
                                  attribution_policy='draft', fit_penalties=fit_matrix(script, bank, language))
        manifest['usage'] = usage
        draft = {'schema_version': 'book-casting-draft-v1', 'draft_id': uuid.uuid4().hex,
                 'source_binding': self.binding, 'bank_sha256': fingerprint(bank),
                 'script': role_script_to_dict(script), 'manifest': manifest, 'cards': {}, 'card_keys': {}}
        needed = [r for r, p in manifest['profiles'].items() if p['voice_mode'] == 'design' and not p['locked']]
        for role in needed:
            # 只绑定实际送入模型的角色上下文；应用声音本身不让描述卡无故失效。
            key = fingerprint({'version': 1, 'role': role, 'model': model, 'language': language,
                'name': script.roles[role].display_name, 'gender': script.roles[role].gender,
                'samples': [s.text[:250] for c in script.chapters for s in c.segments if s.role_id == role][:3],
                'neighbors': [e for e in manifest['usage']['edges'] if role in (e['left'], e['right'])],
                'risk_tier': manifest['profiles'][role]['risk_tier'],
                'presets': {r: p['provider_params'].get('voice') for r, p in manifest['profiles'].items() if p['voice_mode'] == 'preset'}})
            draft['card_keys'][role] = key
            path = self.root / 'cards' / (key + '.json')
            if path.is_file():
                draft['cards'][role] = read_json(path)['card']
        atomic_json(self.draft_path, draft)
        missing = [r for r in needed if r not in draft['cards']]
        for start in range(0, len(missing), 8):
            check_task()
            batch = missing[start:start + 8]
            if progress:
                progress(None, desc=f'生成声音描述：已保存 {len(draft["cards"])}/{len(needed)} 人，本批 {len(batch)} 人')
            cards, receipt = generate_voice_cards(script, manifest, client=client, model=model, role_ids=batch)
            check_task()
            for role, card in cards.items():
                atomic_json(self.root / 'cards' / (draft['card_keys'][role] + '.json'), {'card': card, 'receipt': receipt})
                draft['cards'][role] = card
            atomic_json(self.draft_path, draft)
        return draft

    def apply(self, bank, draft_id, edited_rows=None):
        draft = self.read_draft()
        if not draft or draft['draft_id'] != draft_id:
            raise ValueError('书籍、归属、人物或声音设置已改变，旧方案已失效，请重新生成方案')
        if draft['bank_sha256'] != fingerprint(bank):
            raise ValueError('声音库已改变，请重新生成方案')
        script = self.analyzed_script()
        if not self.progress()['full_book'] or script_identity(script) != draft['manifest']['script_sha256']:
            raise ValueError('全书分析或归属已改变，请重新生成方案')
        cards = dict(draft['cards'])
        if edited_rows is not None:
            rows = edited_rows.values.tolist() if hasattr(edited_rows, 'values') else edited_rows
            expected = set(draft['manifest']['profiles'])
            if len(rows) != len(expected) or {str(row[0]) for row in rows} != expected:
                raise ValueError('声音方案人物列表已改变，请重新生成方案')
            original_rows = {row[0]: row for row in draft_rows(draft)}
            for row in rows:
                role = str(row[0])
                profile = draft['manifest']['profiles'][role]
                original = original_rows[role]
                if len(row) != 7 or any(str(row[i] or '') != str(original[i] or '') for i in (0, 1, 2, 3, 6)):
                    raise ValueError('草案表只可编辑声音描述和朗读要求；改内置声音请应用后使用人物设置')
                if profile['voice_mode'] == 'design' and not profile['locked']:
                    cards[role] = {'voice_description': str(row[4] or '').strip(), 'instructions': str(row[5] or '').strip()}
                elif any(str(row[i] or '') != str(original[i] or '') for i in (4, 5)):
                    raise ValueError('已锁定或非描述声音请使用现有人物设置调整，不在草案中覆盖')
        result = apply_hybrid(script, draft['manifest'], cards)
        for role, card in cards.items():
            if card != draft['cards'].get(role):
                # 人工修改的有效卡同样跨章复用，不在下次生成方案时退回旧模型描述。
                atomic_json(self.root / 'cards' / (draft['card_keys'][role] + '.json'),
                            {'card': card, 'receipt': {'source': 'user_edited_draft', 'draft_id': draft_id}})
        # 不触碰 speaker.status，仍需现有逐段复核与最终确认。
        return result


def stats_rows(usage):
    if not usage:
        return []
    order = sorted(usage['roles'], key=lambda r: (-usage['roles'][r]['reading_count'], r))
    rows = [[r, usage['roles'][r]['display_name'], usage['roles'][r]['reading_count'],
             round(usage['roles'][r]['estimated_seconds'] / 60, 2), usage['roles'][r]['active_chapters'],
             usage['roles'][r]['max_absent_chapters'], usage['roles'][r]['pending_segments']] for r in order]
    unknown = usage['unassigned']
    if unknown['segments']:
        rows.append(['__unknown__', '未知归属（不参与人物排名）', unknown['reading_count'], '', '', '', unknown['segments']])
    return rows


def draft_rows(draft):
    if not draft:
        return []
    manifest = draft['manifest']
    order = sorted(manifest['profiles'], key=lambda r: (-manifest['usage']['roles'][r]['reading_count'], r))
    rows = []
    for role in order:
        profile = manifest['profiles'][role]
        card = draft['cards'].get(role, profile['provider_params'])
        rows.append([role, manifest['usage']['roles'][role]['display_name'],
                     {'preset': '内置声音', 'design': '描述声音', 'clone': '参考音克隆'}[profile['voice_mode']],
                     profile['provider_params'].get('voice', ''), card.get('voice_description', ''),
                     card.get('instructions', ''), REASONS.get(profile['reason'], profile['reason'])])
    return rows

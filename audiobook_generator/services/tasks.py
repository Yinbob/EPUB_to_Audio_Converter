"""单任务调度、幂等启动、进程组终止和恢复记录。"""
import copy
import hashlib
import json
import multiprocessing
import os
import signal
import threading
import time
import uuid
from pathlib import Path

from .books import configs_for, read_book
from .common import ServiceError, atomic_json, read_json
from .models import BookRequest
from .projects import decode, signature
from .settings import credentials, require_credentials
from .worker import run_task

ACTIVE = {'starting', 'running', 'stopping'}


class TaskManager:
    def __init__(self, root, files, projects, runner=run_task):
        self.runner = runner
        self.root, self.files, self.projects = Path(root), files, projects
        self.lock = projects.lock  # 项目编辑、确认和启动共用一把锁，消除检查后使用竞态。
        self.directory = self.root / '.studio' / 'tasks'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.tasks = {}
        self.processes, self.ready = {}, {}
        self.mirrors = {}
        self.stopping = set()
        self.closed = threading.Event()
        for path in self.directory.glob('*/task.json'):
            task = read_json(path)
            if task['status'] in ACTIVE:
                task.update(status='failed', error='服务已重启，上次任务已中断。', finished_at=time.time())
                atomic_json(path, task)
            self.tasks[task['id']] = task
        projects.manager = self
        self.monitor = threading.Thread(target=self._monitor, daemon=True)
        self.monitor.start()

    def _monitor(self):
        while not self.closed.wait(.3):
            with self.lock:
                for key in list(self.processes):
                    self._refresh(key)

    def _save(self, task):
        atomic_json(self.directory / task['id'] / 'task.json', task)

    def require_idle(self):
        if self.current():
            raise ServiceError('task_busy', '已有任务正在运行，请等待完成或停止后重试。', 409)

    def current(self):
        with self.lock:
            for key in list(self.processes):
                self._refresh(key)
            return next((self.get(key) for key, task in self.tasks.items() if task['status'] in ACTIVE), None)

    def list(self):
        with self.lock:
            return [self.get(t['id']) for t in sorted(self.tasks.values(), key=lambda t: t['created_at'], reverse=True)]

    def _refresh(self, key):
        proc = self.processes.get(key)
        if proc is None or key in self.stopping:
            return
        task = self.tasks[key]
        if key in self.mirrors:
            destination, offset = self.mirrors[key]
            source = self.directory / key / 'EtA_task.log'
            if source.exists():
                with source.open('rb') as stream:
                    stream.seek(offset)
                    data = stream.read()
                    offset = stream.tell()
                with destination.open('ab') as stream:
                    stream.write(data)
                self.mirrors[key] = destination, offset
        if proc.is_alive():
            if self.ready[key].is_set() and task['status'] == 'starting':
                task['status'] = 'running'
                self._save(task)
            return
        proc.join(timeout=0)
        result = read_json(self.directory / key / 'result.json', {})
        try:
            if task['status'] == 'stopping':
                task.update(status='stopped', result={})
            elif result.get('ok') and proc.exitcode == 0:
                value = result.get('result', {})
                if 'research_proposal' in value:
                    value.update(self.projects.research.store_proposal(task['project_id'], task['revision'],
                                                                       value.pop('research_proposal')))
                if 'script' in value:
                    project_id = task.get('project_id')
                    if project_id:
                        self.projects.check_revision(project_id, task['revision'])
                    value['project'] = self.projects.put(decode(value.pop('script')), project_id)
                if value.get('audio_path'):
                    value['audio'] = self.files.register(value.pop('audio_path'))
                    voice_path = self.directory / key / 'voice_binding.json'
                    voice_binding = read_json(voice_path, {})
                    if voice_binding:
                        voice_binding['audio_sha256'] = hashlib.sha256(self.files.resolve(value['audio']['id']).read_bytes()).hexdigest()
                        atomic_json(voice_path, voice_binding)
                    binding_path = self.directory / key / 'preview_binding.json'
                    binding = read_json(binding_path, {})
                    if binding:
                        binding['audio_id'] = value['audio']['id']
                        binding['audio_sha256'] = hashlib.sha256(self.files.resolve(binding['audio_id']).read_bytes()).hexdigest()
                        atomic_json(binding_path, binding)
                        value['preview_binding'] = binding
                task.update(status='succeeded', result=value)
            else:
                task.update(status='failed', error=self.redact(result.get('error', '任务意外退出，请查看日志。')),
                            result=json.loads(self.redact(json.dumps(result.get('result', {}), ensure_ascii=False))))
        except Exception:
            task.update(status='failed', error='任务结果无法提交，请刷新项目后重试。')
        if task['kind'] in ('generate', 'research_regenerate'):
            from .provenance import finalize
            for output in task.get('output_dirs', []):
                try:
                    status = {'succeeded': 'succeeded', 'stopped': 'interrupted'}.get(task['status'], 'failed')
                    if status == 'succeeded' and task.get('result', {}).get('books') and all(
                            'chapters' in b for b in task['result']['books']):
                        status = 'parsed'
                    finalize(output, status=status)
                except (OSError, ValueError, KeyError):
                    # 报告刷新失败不覆盖已记录的合成结果。
                    pass
        task['finished_at'] = time.time()
        self._save(task)
        del self.processes[key]
        self.ready.pop(key, None)
        self.mirrors.pop(key, None)

    def redact(self, text):
        text = str(text)
        for name in ('openai', 'minimax', 'qwen', 'deepseek'):
            secret = credentials(name).get('api_key')
            if secret:
                text = text.replace(secret, '[密钥已隐藏]')
        return text

    def get(self, key):
        with self.lock:
            if key not in self.tasks:
                raise ServiceError('task_missing', '找不到任务。', 404)
            self._refresh(key)
            task = copy.deepcopy(self.tasks[key])
            log = self.directory / key / 'EtA_task.log'
            from audiobook_generator.ui.progress_parser import parse_progress, decide_progress_state
            content = log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''
            task['progress'] = decide_progress_state(parse_progress(content), task['status'] in ACTIVE,
                batch_started=True, manually_stopped=task['status'] == 'stopped')
            if task['kind'] != 'generate' and task['status'] in ACTIVE:
                labels = {'split': '拆分角色', 'preview': '生成试听', 'calibrate': '校准语速',
                          'voice_clone': '上传并克隆声音', 'casting_analyze': '分析全书人物', 'casting_draft': '准备声音分配草稿'}
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                task['progress'].update(mode='starting' if task['status'] == 'starting' else 'running',
                    status='正在' + labels.get(task['kind'], '处理任务'),
                    detail=self.redact(lines[-1][-240:]) if lines else '', active=True)
            if task['status'] == 'stopping':
                task['progress']['status'] = '正在停止并清理后台进程…'
            if task['status'] == 'succeeded':
                task['progress'].update(mode='finished', pct=100, status='任务已完成', active=False)
            elif task['status'] == 'failed':
                task['progress'].update(mode='failed', status=task['error'] or '任务失败', active=False)
            elif task['status'] == 'stopped':
                task['progress'].update(mode='interrupted', status='已停止（可再次点击开始）', active=False)
            return task

    def start(self, request):
        with self.lock:
            for task in self.tasks.values():
                if task['request_id'] == request.request_id:
                    return self.get(task['id'])
            self.require_idle()
            generation = request.generation
            if request.kind not in ('generate', 'research_regenerate'):
                generation = generation.model_copy(update={'audio_core_enabled': False, 'audio_core_repair': False,
                    'audio_core_settings_file': None, 'audio_core_casting_file': None,
                    'catalog_fingerprint': generation.catalog_fingerprint if generation.file_ids else None})
            key = uuid.uuid4().hex
            project_id = request.project_id or generation.project_id
            revision = request.revision if request.revision is not None else generation.project_revision
            research_analysis = request.kind in ('research_analyze', 'research_reanalyze')
            research_generation = request.kind == 'research_regenerate'
            script = None
            role_voice_snapshots = {}
            if project_id:
                value = self.projects.check_revision(project_id, revision)
                script = decode(value['script'])
                if script.provider != generation.engine.provider:
                    raise ServiceError('project_provider', '角色项目与当前引擎不一致，请切回项目对应引擎。', 409)
                if request.role_id and request.role_id not in script.roles:
                    raise ServiceError('role_missing', '人物不存在，请重新选择。')
                from .portable_voices import PortableVoices
                for role_id, role in (() if research_analysis else script.roles.items()):
                    saved = read_json(self.root / '.studio' / 'project_voice_bindings' / project_id / (role_id + '.json'), {})
                    if saved.get('params_signature') == signature(role.provider_params):
                        card = saved['snapshot']
                        PortableVoices(self.root).resolve(card['id'], card['version'], script.provider, generation.engine.model_name)
                        role_voice_snapshots[role_id] = card
            if request.kind not in ('preview', 'voice_clone') and not generation.file_ids:
                raise ServiceError('book_required', '请先上传书籍文件。')
            if request.kind == 'voice_clone':
                if generation.engine.provider != 'minimax' or project_id or not request.reference_id or not request.clone_voice_id:
                    raise ServiceError('clone_parameters', 'MiniMax 克隆需要参考音和新音色 ID，不能附带角色项目。')
                self.files.resolve(request.reference_id)
                generation = generation.model_copy(update={'engine': generation.engine.model_copy(update={'voice_name': request.clone_voice_id})})
            if request.kind in ('generate', 'research_regenerate') and project_id:
                script = self.projects.for_generation(project_id, revision, generation.engine.provider)
            if request.kind.startswith('research_') and (not project_id or not self.projects.research.exists(project_id)):
                raise ServiceError('research_disabled', '请先为角色项目启用研究审阅。', 409)
            if project_id and self.projects.research.exists(project_id) and len(generation.file_ids) != 1:
                raise ServiceError('research_single_book', '研究项目仅支持对应的单本书籍。')
            if request.kind == 'split' and project_id and self.projects.research.exists(project_id):
                raise ServiceError('research_resplit', '研究审阅保留固定分段；请使用研究分析或建立独立项目。', 409)
            if request.kind in ('calibrate', 'casting_analyze', 'casting_draft') and script is None:
                raise ServiceError('project_required', '请先载入角色项目。')
            if request.kind in ('calibrate', 'casting_analyze', 'casting_draft') and generation.engine.provider != 'openai':
                raise ServiceError('task_provider', '此操作仅支持 MiMo 角色项目。')
            if request.kind in ('split', 'casting_analyze', 'casting_draft') or research_analysis:
                require_credentials('deepseek')
            elif not generation.preview or project_id or request.kind != 'generate':
                require_credentials(generation.engine.provider)
            if not generation.output_dir:
                from datetime import datetime
                name = Path(self.files.register(self.files.resolve(generation.file_ids[0]))['name']).stem if generation.file_ids else '试听'
                name = ''.join(c if c.isalnum() or c in '._-' else '_' for c in name)[:80]
                generation = generation.model_copy(update={'output_dir': str(self.root / (datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + '_' + name + '_' + key[:6]))})
            from .capabilities import capabilities
            capability = next(c for c in capabilities() if c['id'] == generation.engine.provider)
            engine = generation.engine
            if engine.output_format not in capability['formats']:
                raise ServiceError('output_format', '当前引擎不支持此输出格式。')
            voice_ids = [v['value'] if isinstance(v, dict) else v for v in capability['voices']]
            if (hasattr(engine, 'voice_name') and voice_ids and engine.voice_name not in voice_ids
                    and 'voice_name' not in capability.get('custom_fields', [])):
                raise ServiceError('voice_invalid', '音色目录已变化，请重新选择声音。')
            configs = configs_for(generation, self.files, self.root, script if request.kind in ('generate', 'research_regenerate') else None,
                                  allow_empty=request.kind in ('preview', 'voice_clone'))
            for config in configs:
                config.role_portable_voice_snapshots = role_voice_snapshots
            if request.kind in ('generate', 'research_regenerate') and script:
                # 提交前验证覆盖和正文，不能仅凭人物表或确认标记开始生成。
                from audiobook_generator.role_script.planner import build_synthesis_plans, build_default_provider_params
                catalog, chapters = read_book(BookRequest(file_id=generation.file_ids[0],
                    provider=generation.engine.provider, parser=generation.parser), self.files)
                if self.projects.research.exists(project_id):
                    from .research_render import validate_sources
                    validate_sources(self.projects.research.read(project_id), catalog, chapters)
                planning = build_synthesis_plans(script, chapters,
                    expected_book_sha256=catalog['book_sha256'], provider=generation.engine.provider,
                    chapter_start=generation.chapter_start,
                    chapter_end=len(chapters) if generation.chapter_end == -1 else generation.chapter_end,
                    output_format=generation.engine.output_format,
                    allow_text_override=generation.allow_role_text_override and not self.projects.research.exists(project_id),
                    allow_title_mismatch=generation.allow_role_title_mismatch and not self.projects.research.exists(project_id),
                    allow_fallback=generation.allow_role_fallback and not self.projects.research.exists(project_id),
                    fallback_profile=build_default_provider_params(generation.engine.provider, configs[0]))
                if not planning.ok:
                    raise ServiceError('project_coverage', '剧本正文或章节覆盖不匹配，请重新拆分或检查高级校验选项。', 409)
                if self.projects.research.exists(project_id):
                    from .research_render import render_snapshot, prepare_regeneration
                    snapshot = render_snapshot(planning.plans, generation, self.projects.research.read(project_id), configs[0])
                    if research_generation:
                        baseline = self.tasks.get(request.baseline_task_id)
                        if not baseline or baseline.get('project_id') != project_id or not baseline.get('render_snapshot'):
                            raise ServiceError('baseline_missing', '请选择同一项目包含合成快照的历史批次。', 409)
                        configs = prepare_regeneration(configs[0], snapshot, baseline, key)
                        rendered = {str(i) for cfg in configs for i in range(cfg.chapter_start, cfg.chapter_end + 1)}
                        snapshot['chapters'] = {i: c for i, c in snapshot['chapters'].items() if i in rendered}
                    for cfg in configs:
                        cfg.allow_role_text_override = cfg.allow_role_title_mismatch = cfg.allow_role_fallback = False
                        cfg.research_render_snapshot = {**snapshot, 'chapters': {i: c for i, c in snapshot['chapters'].items()
                            if cfg.chapter_start <= int(i) <= (len(chapters) if cfg.chapter_end == -1 else cfg.chapter_end)}}
            payload = dict(kind=request.kind, configs=configs, script=script, text=request.text,
                role_id=request.role_id, full_book=request.full_book, root=str(self.root), revision=revision,
                language=request.language)
            if research_analysis:
                catalog, chapters = read_book(BookRequest(file_id=generation.file_ids[0],
                    provider=generation.engine.provider, parser=generation.parser), self.files)
                state = self.projects.research.read(project_id)
                from .research_render import validate_sources
                validate_sources(state, catalog, chapters)
                targets = request.segment_ids
                if request.kind == 'research_reanalyze' and not targets:
                    targets = sorted(set(sid for sid, d in state['decisions'].items() if d['status'] == 'stale') | set(state['context_checks']))
                    if not targets:
                        raise ServiceError('research_no_stale', '没有需要重新检查的片段，可使用完整研究分析。', 409)
                payload.update(research_state=state, chapters=chapters, segment_ids=targets)
            if request.kind in ('split', 'casting_analyze', 'casting_draft'):
                if len(generation.file_ids) != 1 or generation.engine.provider not in ('openai', 'minimax'):
                    raise ServiceError('split_provider', '角色分析仅支持单本书与 MiMo / MiniMax。')
                catalog, chapters = read_book(BookRequest(file_id=generation.file_ids[0],
                    provider=generation.engine.provider, parser=generation.parser), self.files)
                if request.kind == 'split' and script is None:
                    for existing_id in self.projects.entries:
                        existing = self.projects.get(existing_id)
                        if existing['script']['book_sha256'] == catalog['book_sha256'] and existing['script']['provider'] == generation.engine.provider:
                            if self.projects.research.exists(existing_id):
                                raise ServiceError('research_resplit', '这本书已启用研究审阅，请载入项目进行研究分析。', 409)
                            project_id, revision = existing_id, existing['revision']
                            script = decode(existing['script'])
                            payload.update(script=script, revision=revision)
                            break
                if script and script.book_sha256 != catalog['book_sha256']:
                    raise ServiceError('book_mismatch', '项目与当前书籍不一致。')
                if configs[0].chapter_end == -1:
                    configs[0].chapter_end = len(chapters)
                payload.update(catalog=catalog, chapters=chapters)
                if request.bank_id:
                    payload['bank_path'] = str(self.files.resolve(request.bank_id))
            if request.kind == 'split' and project_id:
                self.projects.invalidate(project_id)
            directory = self.directory / key
            directory.mkdir()
            if request.kind in ('preview', 'voice_clone') and engine.provider in ('openai', 'minimax'):
                from .portable_voices import endpoint_for, provider_id
                from audiobook_generator.role_script.planner import build_default_provider_params
                params = dict(script.roles[request.role_id].provider_params) if script and request.role_id else build_default_provider_params(engine.provider, configs[0])
                voice_binding = {'provider': provider_id(engine.provider),
                    'model': engine.model_name, 'endpoint': endpoint_for(engine.provider), 'params': params}
                if request.kind == 'voice_clone':
                    voice_binding['reference_path'] = str(self.files.resolve(request.reference_id))
                atomic_json(directory / 'voice_binding.json', voice_binding)
            if request.kind == 'voice_clone':
                payload.update(reference_path=str(self.files.resolve(request.reference_id)), clone_voice_id=request.clone_voice_id)
            if request.kind == 'preview' and script and request.role_id:
                atomic_json(directory / 'preview_binding.json', {
                    'task_id': key, 'project_id': project_id, 'revision': revision, 'role_id': request.role_id,
                    'script_signature': signature(value['script']),
                    'voice_signature': signature(script.roles[request.role_id].provider_params),
                })
            task = dict(id=key, request_id=request.request_id, kind=request.kind, status='starting',
                        created_at=time.time(), project_id=project_id, revision=revision, role_id=request.role_id,
                        result={}, error='', finished_at=None, output_dirs=[cfg.output_folder for cfg in configs])
            if request.kind in ('generate', 'research_regenerate') and project_id and self.projects.research.exists(project_id):
                task.update(render_snapshot=snapshot, baseline_task_id=request.baseline_task_id)
            self.tasks[key] = task
            self._save(task)
            context = multiprocessing.get_context('spawn')
            ready = context.Event()
            proc = context.Process(target=self.runner, args=(payload, str(directory / 'result.json'),
                                                           str(directory / 'EtA_task.log'), ready))
            try:
                proc.start()
            except Exception:
                task.update(status='failed', error='无法启动任务进程。', finished_at=time.time())
                self._save(task)
                raise ServiceError('spawn_failed', task['error'], 500)
            self.processes[key], self.ready[key] = proc, ready
            return self.get(key)

    def start_configs(self, configs, log_path=None):
        """旧界面的薄适配入口，复用调度和进程生命周期。"""
        with self.lock:
            self.require_idle()
            key = uuid.uuid4().hex
            directory = self.directory / key
            directory.mkdir()
            task = dict(id=key, request_id=key, kind='generate', status='starting', created_at=time.time(),
                        project_id=None, revision=None, result={}, error='', finished_at=None,
                        output_dirs=[cfg.output_folder for cfg in configs])
            if log_path:
                self.mirrors[key] = (Path(log_path), 0)
            self.tasks[key] = task
            self._save(task)
            context = multiprocessing.get_context('spawn')
            ready = context.Event()
            proc = context.Process(target=self.runner, args=(dict(kind='generate', configs=configs),
                      str(directory / 'result.json'), str(directory / 'EtA_task.log'), ready))
            try:
                proc.start()
            except Exception:
                task.update(status='failed', error='无法启动任务进程。', finished_at=time.time())
                self._save(task)
                raise
            self.processes[key], self.ready[key] = proc, ready
            return key, proc

    def stop(self, key):
        with self.lock:
            task = self.get(key)
            if task['status'] not in ACTIVE:
                return task
            self.stopping.add(key)
            self.tasks[key]['status'] = 'stopping'
            self._save(self.tasks[key])
            proc, ready = self.processes[key], self.ready[key]
        # 不持锁等待子进程；先确认 setsid，绝不向服务进程组发送信号。
        ready.wait(1)
        pgid = proc.pid if ready.is_set() else None
        if pgid:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        elif proc.is_alive():
            proc.terminate()
        proc.join(timeout=3)
        # 即使组长已退出，也清理仍存活的后代。
        if pgid:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif proc.is_alive():
            proc.kill()
        proc.join(timeout=2)
        with self.lock:
            self.stopping.discard(key)
            self._refresh(key)
            return self.get(key)

    def freeze_preview(self, project_id, revision, role_id, task_id):
        """固定试听必须仍属于当前人物、剧本和声音版本。普通上传克隆不走此入口。"""
        with self.lock:
            self.require_idle()
            value = self.projects.check_revision(project_id, revision)
            task = self.get(task_id)
            binding = read_json(self.directory / task_id / 'preview_binding.json', {})
            role = value['script']['roles'].get(role_id)
            expected = dict(task_id=task_id, project_id=project_id, revision=revision, role_id=role_id,
                            script_signature=signature(value['script']),
                            voice_signature=signature(role['provider_params']) if role else '')
            if (task['kind'] != 'preview' or task['status'] != 'succeeded' or not role
                    or any(binding.get(k) != v for k, v in expected.items())):
                raise ServiceError('preview_stale', '试听已失效，请为当前人物和声音参数重新试听。', 409)
            path = self.files.resolve(binding.get('audio_id', ''))
            if hashlib.sha256(path.read_bytes()).hexdigest() != binding.get('audio_sha256'):
                raise ServiceError('preview_changed', '试听音频已变化，请重新试听。', 409)
            return path

    def logs(self, key, cursor=None, before=None):
        self.get(key)
        path = self.directory / key / 'EtA_task.log'
        if not path.exists():
            return {'text': '', 'cursor': 0}
        with path.open('rb') as stream:
            if before is not None or cursor is None:
                end = min(max(before, 0), path.stat().st_size) if before is not None else path.stat().st_size
                stream.seek(max(0, end - 1024 * 1024))
                base = stream.tell()
                content = stream.read(end - base)
                text = b''.join(content.splitlines(keepends=True)[-3000:])
                start = end - len(text)
            else:
                stream.seek(min(max(cursor, 0), path.stat().st_size))
                start = stream.tell()
                text = stream.read(1024 * 1024)
            position = stream.tell()
        return {'text': self.redact(text.decode('utf-8', errors='replace')), 'cursor': position,
                'start_cursor': start, 'has_more': start > 0}

    def close(self):
        current = self.current()
        if current:
            self.stop(current['id'])
        self.closed.set()
        self.monitor.join(timeout=2)

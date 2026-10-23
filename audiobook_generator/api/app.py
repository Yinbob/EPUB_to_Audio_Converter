"""Vue 工作台 API。启动时不导入 Gradio，不加载语音模型。"""
import hashlib
import secrets
import shutil
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from audiobook_generator.services.common import ROOT, RuntimeLock, ServiceError
from audiobook_generator.services.files import FileStore
from audiobook_generator.services.projects import Projects, decode
from audiobook_generator.services.settings import Settings, config_view, save_config, module, credentials, PROVIDERS
from audiobook_generator.services.models import BookRequest, TaskRequest, ProjectEdit, ConfigUpdate, Selection, TaskSnapshot
from audiobook_generator.services.books import read_book
from audiobook_generator.services.tasks import TaskManager


def create_app(root=None, *, acquire_lock=True, frontend=None):
    root = Path(root or ROOT / 'audiobook_output').resolve()
    sessions, failures = {}, {}
    session_lock = threading.RLock()

    @asynccontextmanager
    async def lifespan(app):
        runtime = RuntimeLock().acquire() if acquire_lock else None
        try:
            files = FileStore(root)
            projects = Projects(root, files)
            app.state.files, app.state.projects = files, projects
            app.state.settings = Settings()
            app.state.tasks = TaskManager(root, files, projects)
            yield
        finally:
            if hasattr(app.state, 'tasks'):
                app.state.tasks.close()
            if runtime:
                runtime.close()

    app = FastAPI(title='有声书工坊', version='1.0.0', lifespan=lifespan)
    prefix = '/api/v1'
    from .research import register_research_routes
    register_research_routes(app, prefix)

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        return JSONResponse({'error': {'code': exc.code, 'message': exc.message}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'error': {'code': 'validation_error', 'message': '参数格式或范围不正确，请检查后重试。',
                                      'fields': ['.'.join(map(str, e['loc'])) for e in exc.errors()]}}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing_field(request, exc):
        return JSONResponse({'error': {'code': 'field_required', 'message': '缺少操作参数，请刷新后重试。'}}, status_code=422)

    @app.exception_handler(FileNotFoundError)
    async def missing_file(request, exc):
        return JSONResponse({'error': {'code': 'file_missing', 'message': '文件已移除，请刷新后重试。'}}, status_code=404)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({'error': {'code': 'invalid_operation', 'message': app.state.tasks.redact(str(exc))}}, status_code=422)

    @app.middleware('http')
    async def request_origin(request, call_next):
        if request.url.path.startswith(prefix) and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            # Vite 必须代理到同源；不开放任意跨站写入。
            if origin and urlsplit(origin).netloc != request.headers.get('host'):
                return JSONResponse({'error': {'code': 'origin_denied', 'message': '请求来源不匹配。'}}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith(prefix):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def admin(request: Request):
        token = request.cookies.get('studio_admin', '')
        with session_lock:
            expired = [key for key, expiry in sessions.items() if expiry <= time.time()]
            for key in expired:
                del sessions[key]
            if token not in sessions:
                raise ServiceError('login_required', '请先输入管理员密码。', 401)

    @app.get(prefix + '/bootstrap')
    def bootstrap():
        from audiobook_generator.services.capabilities import capabilities
        from audiobook_generator.ui.audio_quality import apply_local_quality_defaults, local_quality_status
        from types import SimpleNamespace
        models = SimpleNamespace()
        apply_local_quality_defaults(models)
        return {'providers': capabilities(), 'settings': {key: value for key, value in app.state.settings.read().items()
                    if key != 'admin_password_hash'}, 'current_task': app.state.tasks.current(),
                'projects': app.state.projects.list(), 'output_root': str(root),
                'quality_models': {'asr': bool(getattr(models, 'audio_core_asr_model', None)),
                    'speaker': bool(getattr(models, 'audio_core_speaker_model', None)), 'message': local_quality_status()}}

    @app.post(prefix + '/uploads')
    def upload(file: UploadFile = File(...)):
        return app.state.files.upload(file.filename, file.file)

    @app.get(prefix + '/files/{key}')
    def file(key: str, download: bool = False):
        path = app.state.files.resolve(key)
        return FileResponse(path, filename=path.name if download else None)

    @app.post(prefix + '/books/chapters')
    def chapters(body: BookRequest):
        return read_book(body, app.state.files)[0]

    @app.get(prefix + '/tasks/current', response_model=TaskSnapshot | None)
    def current():
        return app.state.tasks.current()

    @app.get(prefix + '/tasks', response_model=list[TaskSnapshot])
    def tasks():
        return app.state.tasks.list()

    @app.post(prefix + '/tasks', response_model=TaskSnapshot)
    def start(body: TaskRequest):
        return app.state.tasks.start(body)

    @app.get(prefix + '/tasks/{key}', response_model=TaskSnapshot)
    def task(key: str):
        return app.state.tasks.get(key)

    @app.post(prefix + '/tasks/{key}/stop', response_model=TaskSnapshot)
    def stop(key: str):
        return app.state.tasks.stop(key)

    @app.get(prefix + '/tasks/{key}/logs')
    def logs(key: str, cursor: int | None = None, before: int | None = None):
        return app.state.tasks.logs(key, cursor, before)

    @app.get(prefix + '/projects')
    def projects():
        return app.state.projects.list()

    @app.post(prefix + '/projects/import')
    def import_project(body: dict):
        with app.state.projects.lock:
            app.state.tasks.require_idle()
            path = app.state.files.resolve(body['file_id'])
            import json
            return app.state.projects.put(decode(json.loads(path.read_text(encoding='utf-8'))), confirmed=True)

    @app.get(prefix + '/projects/{key}')
    def project(key: str):
        with app.state.projects.lock:
            return app.state.projects.get(key)

    @app.patch(prefix + '/projects/{key}')
    def edit_project(key: str, body: ProjectEdit):
        return app.state.projects.edit(key, body)

    @app.post(prefix + '/projects/{key}/casting')
    def casting(key: str, body: BookRequest, language: str = 'zh'):
        from audiobook_generator.ui.book_casting import discover_banks, draft_rows
        if language not in ('zh', 'en'):
            raise ServiceError('language_invalid', '请选择中文或英语。')
        with app.state.projects.lock:
            controller = app.state.projects.casting(key, body.model_dump())
            usage, coverage = controller.usage(language)
            draft = controller.read_draft()
            return {'coverage': coverage, 'usage': usage,
                    'banks': [{'label': label, **app.state.files.register(path)} for label, path in discover_banks(root)],
                    'draft': {'draft_id': draft['draft_id'], 'rows': draft_rows(draft)} if draft else None}

    @app.post(prefix + '/casting/bank')
    def casting_bank(body: dict):
        from audiobook_generator.ui.book_casting import load_bank
        language = body.get('language', 'zh')
        path = app.state.files.resolve(body['file_id'])
        bank = load_bank(path, language)
        return {'bank_id': body['file_id'], 'language': language,
                'voices': [{'value': name, 'label': name} for name in bank['voices']],
                'summary': f'{len(bank["voices"])} 个已核验声音 · {language}'}

    @app.get(prefix + '/voices')
    def voices():
        from dataclasses import asdict
        from audiobook_generator.tts_providers.voice_catalog import list_catalog_entries
        return [asdict(item) for item in list_catalog_entries()]

    @app.post(prefix + '/voices/import')
    def import_voices(body: dict):
        from audiobook_generator.tts_providers.voice_catalog import import_voice_catalog_document, save_user_voice_entries
        with app.state.projects.lock:
            app.state.tasks.require_idle()
            path = app.state.files.resolve(body['file_id']) if body.get('file_id') else None
            result = import_voice_catalog_document(str(path) if path else None, text=body.get('text', ''),
                      provider=body.get('provider'), default_language=body.get('language', 'zh'))
            if result.errors or not result.entries:
                raise ServiceError('voice_import_invalid', '；'.join(result.errors) or '未找到有效音色条目。')
            save_user_voice_entries(result.entries)
            return {'count': len(result.entries), 'entries': [item.to_dict() for item in result.entries],
                    'warnings': list(result.warnings), 'source_name': result.source_name}

    @app.delete(prefix + '/voices')
    def clear_voices():
        from audiobook_generator.tts_providers.voice_catalog import clear_user_voice_entries
        with app.state.projects.lock:
            app.state.tasks.require_idle()
            clear_user_voice_entries()
        return {'ok': True}

    @app.get(prefix + '/voice-profiles')
    def voice_profiles():
        from audiobook_generator.services.portable_voices import PortableVoices
        return PortableVoices(root).list()

    @app.post(prefix + '/voice-profiles')
    def save_voice_profile(body: dict):
        from audiobook_generator.services.portable_voices import PortableVoices
        with app.state.projects.lock:
            app.state.tasks.require_idle()
            return PortableVoices(root).from_preview(app.state.tasks, body['task_id'],
                key=body['id'], label=body['label'], language=body['language'],
                confirmed=body.get('confirmed'), previous_version=body.get('previous_version'))

    @app.post(prefix + '/voice-profiles/import')
    def import_voice_profile(body: dict):
        from audiobook_generator.services.portable_voices import PortableVoices
        with app.state.projects.lock:
            app.state.tasks.require_idle()
            return PortableVoices(root).import_file(app.state.files.resolve(body['file_id']))

    @app.get(prefix + '/voice-profiles/{key}/{version}/export')
    def export_voice_profile(key: str, version: str):
        from audiobook_generator.services.portable_voices import PortableVoices
        with app.state.projects.lock:
            path = PortableVoices(root).export(key, version)
        return FileResponse(path, filename=path.name, media_type='application/zip')

    def batches():
        result = {p.name: p.resolve() for p in root.iterdir() if p.is_dir() and not p.name.startswith('.') and p.resolve().parent == root}
        for task in app.state.tasks.list():
            for raw in task.get('output_dirs', []):
                path = Path(raw).resolve()
                if path.is_dir() and path.parent != root:
                    key = 'custom-' + hashlib.sha256(str(path).encode()).hexdigest()[:16]
                    result[key] = path
        return result

    def batch(folder):
        path = batches().get(folder)
        if path is None:
            raise ServiceError('batch_missing', '批次不存在，请刷新资源库。', 404)
        return path

    @app.get(prefix + '/library')
    def library():
        return [{'name': key, 'label': path.name, 'modified': path.stat().st_mtime}
                for key, path in sorted(batches().items(), key=lambda item: item[1].stat().st_mtime, reverse=True)]

    @app.get(prefix + '/library/files')
    def library_files(folder: str):
        from audiobook_generator.ui.library import selected_paths
        directory = batch(folder)
        names = [p.name for p in directory.iterdir() if not p.name.startswith('.')]
        return [app.state.files.register(p) for p in selected_paths(directory.parent, directory.name, names)]

    @app.get(prefix + '/library/source')
    def source_trace(folder: str):
        from audiobook_generator.services.common import read_json
        from audiobook_generator.services.provenance import sha256
        directory = batch(folder)
        manifest = read_json(directory / 'manifest.json', {})
        if not manifest:
            return {'available': False}
        original = (directory / manifest.get('source_file', '.source/missing')).resolve()
        original_file = None
        if (original.parent == (directory / '.source').resolve() and original.is_file()
                and sha256(original) == manifest.get('book_sha256')):
            original_file = app.state.files.register(original)
        timeline = read_json(directory / 'timeline.json', {'chapters': []})
        for chapter in timeline['chapters']:
            audio = (directory / chapter['audio']).resolve()
            if audio.parent != directory or not audio.is_file() or sha256(audio) != chapter['audio_sha256']:
                chapter['audio_file'] = None
                chapter['stale'] = True
            else:
                chapter['audio_file'] = app.state.files.register(audio)
        return {'available': True, 'manifest': manifest, 'source_file': original_file,
                'chapters': read_json(directory / 'chapters.json', {}).get('chapters', []),
                'paragraphs': read_json(directory / 'source_map.json', {}).get('paragraphs', []),
                'timeline': timeline}

    @app.post(prefix + '/library/archive')
    def archive(body: Selection):
        from audiobook_generator.ui.library import create_archive
        directory = batch(body.folder)
        path, count = create_archive(directory.parent, directory.name, body.names)
        return {'file': app.state.files.register(path), 'count': count}

    @app.post(prefix + '/library/delete')
    def delete(body: Selection):
        from audiobook_generator.ui.library import selected_paths
        if not body.acknowledged:
            raise ServiceError('delete_ack', '请先确认删除操作。')
        with app.state.projects.lock:
            app.state.tasks.require_idle()
            if body.names:
                directory = batch(body.folder)
                for path in selected_paths(directory.parent, directory.name, body.names):
                    path.unlink()
            else:
                shutil.rmtree(batch(body.folder))
        return {'ok': True}

    @app.get(prefix + '/quality/reports')
    def quality_reports():
        from audiobook_generator.ui.audio_quality import find_quality_reports
        roots = {str(root)}
        for t in app.state.tasks.list():
            roots.update(t.get('output_dirs', []))
        paths = {path for directory in roots for path in find_quality_reports(directory)}
        return [app.state.files.register(path) for path in sorted(paths, reverse=True)]

    @app.get(prefix + '/quality/reports/{key}')
    def quality_report(key: str):
        from audiobook_generator.ui.audio_quality import load_quality_report, resource_summary_text
        summary, rows, previews = load_quality_report(str(app.state.files.resolve(key)))
        return {'summary': summary, 'message': resource_summary_text(summary), 'rows': rows,
                'previews': [{'label': label, **app.state.files.register(path)} for label, path in previews.items()]}

    @app.get(prefix + '/settings')
    def settings():
        return {name: config_view(name) for name in PROVIDERS}

    @app.get(prefix + '/settings/{provider}', dependencies=[Depends(admin)])
    def reveal(provider: str):
        return config_view(provider, reveal=True)

    @app.put(prefix + '/settings/{provider}', dependencies=[Depends(admin)])
    def save(provider: str, body: ConfigUpdate):
        with app.state.projects.lock:
            app.state.tasks.require_idle()
            return save_config(provider, body.model_dump())

    @app.post(prefix + '/settings/{provider}/test', dependencies=[Depends(admin)])
    def test_config(provider: str, body: ConfigUpdate):
        mod, name = module(provider)
        current = credentials(provider)
        args = [body.api_key or current['api_key']]
        if provider != 'minimax':
            args.append(body.base_url or current['base_url'])
        if provider in ('qwen', 'deepseek'):
            args.append(body.model or current['model'])
        ok, message = getattr(mod, f'test_{name}_connection')(*args)
        return {'ok': ok, 'message': app.state.tasks.redact(message)}

    @app.patch(prefix + '/preferences')
    def preferences(body: dict):
        from audiobook_generator.services.settings import DEFAULTS
        if set(body) - DEFAULTS.keys() or any(type(v) is not bool for v in body.values()):
            raise ServiceError('preference_invalid', '偏好设置无效。')
        app.state.settings.save(body)
        return {'ok': True}

    @app.post(prefix + '/admin/login')
    def login(request: Request, body: dict):
        address = request.client.host if request.client else 'local'
        with session_lock:
            recent = [t for t in failures.get(address, []) if time.time() - t < 60]
            if len(recent) >= 10:
                raise ServiceError('login_throttled', '尝试次数过多，请一分钟后重试。', 429)
            if not app.state.settings.verify(str(body.get('password', ''))):
                failures[address] = recent + [time.time()]
                raise ServiceError('password_invalid', '密码错误。', 401)
            token = secrets.token_urlsafe(32)
            sessions[token] = time.time() + 8 * 3600
        response = JSONResponse({'ok': True})
        response.set_cookie('studio_admin', token, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', max_age=8 * 3600)
        return response

    @app.post(prefix + '/admin/logout')
    def logout(request: Request):
        with session_lock:
            sessions.pop(request.cookies.get('studio_admin'), None)
        response = JSONResponse({'ok': True})
        response.delete_cookie('studio_admin')
        return response

    @app.post(prefix + '/admin/password', dependencies=[Depends(admin)])
    def password(body: dict):
        if not app.state.settings.verify(str(body.get('old_password', ''))):
            raise ServiceError('password_invalid', '原密码错误。', 401)
        app.state.settings.password(str(body.get('new_password', '')))
        with session_lock:
            sessions.clear()
        return {'ok': True}

    frontend = Path(frontend or ROOT / 'frontend' / 'dist')
    if (frontend / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=frontend / 'assets'), name='assets')

    @app.get('/{path:path}')
    def spa(path: str):
        if path.startswith('api/'):
            raise ServiceError('route_missing', '接口不存在。', 404)
        index = frontend / 'index.html'
        if not index.exists():
            raise ServiceError('frontend_missing', '缺少前端构建文件，请在 frontend 目录执行 npm ci 与 npm run build。', 503)
        return FileResponse(index, headers={'Cache-Control': 'no-cache'})

    return app

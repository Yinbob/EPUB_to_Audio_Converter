"""读取书籍内嵌封面并生成安全缩略图；缺少封面不影响上传和正文解析。"""
import io
import posixpath
import warnings
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET
from zipfile import ZipFile

IMAGE_LIMIT = 8 * 1024 * 1024
XML_LIMIT = 1024 * 1024


def _read(archive, name, limit):
    info = archive.getinfo(name)
    if info.file_size > limit:
        raise ValueError('封面资源过大')
    with archive.open(info) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('封面资源过大')
    return data


def _relative(base, href):
    url = urlsplit(href)
    if url.scheme or url.netloc:
        raise ValueError('封面必须来自书籍内部')
    name = posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(url.path)))
    if name.startswith(('/', '../')) or name == '..':
        raise ValueError('封面路径无效')
    return name


def _epub_image(archive):
    container = ET.fromstring(_read(archive, 'META-INF/container.xml', XML_LIMIT))
    rootfile = container.find('.//{*}rootfile')
    if rootfile is None:
        return None
    opf = _relative('', rootfile.attrib['full-path'])
    package = ET.fromstring(_read(archive, opf, XML_LIMIT))
    items = list(package.findall('.//{*}manifest/{*}item'))
    cover_meta = next((m.get('content') for m in package.findall('.//{*}meta') if m.get('name', '').lower() == 'cover'), None)
    candidates = [i for i in items if 'cover-image' in i.get('properties', '').split()]
    candidates += [i for i in items if cover_meta and i.get('id') == cover_meta]
    candidates += [i for i in items if 'cover' in i.get('id', '').lower() and i.get('media-type', '').startswith('image/')]
    for item in candidates:
        try:
            return _read(archive, _relative(opf, item.attrib['href']), IMAGE_LIMIT)
        except (KeyError, ValueError):
            continue
    # EPUB 2 常通过 guide 指向封面页，页内才引用真正的图像。
    for reference in package.findall('.//{*}guide/{*}reference'):
        if reference.get('type') != 'cover':
            continue
        page = _relative(opf, reference.attrib['href'])
        from bs4 import BeautifulSoup
        document = BeautifulSoup(_read(archive, page, XML_LIMIT), 'html.parser')
        image = document.find('img') or document.find('image')
        if image:
            href = image.get('src') or image.get('xlink:href') or image.get('href')
            if href:
                return _read(archive, _relative(page, href), IMAGE_LIMIT)
    return None


def _docx_image(archive):
    # Office 保存的文档缩略图优先；否则使用正文首张嵌入图片。
    names = archive.namelist()
    for name in names:
        if name.lower().startswith('docprops/thumbnail.'):
            return _read(archive, name, IMAGE_LIMIT)
    document = ET.fromstring(_read(archive, 'word/document.xml', XML_LIMIT))
    image = document.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip')
    if image is None:
        return None
    key = image.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
    relations = ET.fromstring(_read(archive, 'word/_rels/document.xml.rels', XML_LIMIT))
    for relation in relations:
        if relation.get('Id') == key and relation.get('TargetMode') != 'External':
            return _read(archive, _relative('word/document.xml', relation.attrib['Target']), IMAGE_LIMIT)
    return None


def create_cover(path):
    path = Path(path)
    if path.suffix.lower() not in ('.epub', '.docx'):
        return None
    try:
        with ZipFile(path) as archive:
            if len(archive.infolist()) > 20000:
                return None
            raw = _epub_image(archive) if path.suffix.lower() == '.epub' else _docx_image(archive)
        if not raw:
            return None
        from PIL import Image, ImageOps
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as original:
                if original.width * original.height > 24_000_000:
                    return None
                original.thumbnail((320, 440))
                image = ImageOps.exif_transpose(original).convert('RGB')
                target = path.parent / '.covers' / (path.stem + '.jpg')
                target.parent.mkdir(exist_ok=True)
                image.save(target, format='JPEG', quality=86)
                return target
    except Exception:
        # 损坏、无封面、旧 DOC 或不支持的图片格式一律交给前端占位展示。
        return None

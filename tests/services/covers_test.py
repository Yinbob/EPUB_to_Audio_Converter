"""内嵌封面验证：真实压缩包、图片清洗及路径边界，不依赖网络。"""
import io
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from PIL import Image
from audiobook_generator.services.files import FileStore
from audiobook_generator.services.covers import IMAGE_LIMIT, _relative


def image_bytes():
    image = Image.new('RGB', (600, 900), '#5377a0')
    stream = io.BytesIO()
    image.save(stream, 'PNG')
    return stream.getvalue()


def epub_bytes(*, epub2=False, guide=False, href='images/front.png', picture=None):
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as archive:
        archive.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
        meta = '<meta name="cover" content="front"/>' if epub2 else ''
        properties = '' if epub2 or guide else 'properties="cover-image"'
        item_id = 'picture' if guide else 'front'
        archive.writestr('OPS/book.opf', f'<package><metadata>{meta}</metadata><manifest><item id="{item_id}" href="{href}" media-type="image/png" {properties}/></manifest>' + ('<guide><reference type="cover" href="cover.xhtml"/></guide>' if guide else '') + '</package>')
        if guide:
            archive.writestr('OPS/cover.xhtml', '<html><img src="images/front.png" /></html>')
        archive.writestr('OPS/images/front.png', image_bytes() if picture is None else picture)
    return stream.getvalue()


class CoverTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = FileStore(Path(self.temp.name))

    def test_epub2_epub3_and_guide_produce_registered_thumbnail(self):
        for options in ({}, {'epub2': True}, {'guide': True}):
            with self.subTest(options=options):
                result = self.store.upload('一本书.epub', io.BytesIO(epub_bytes(**options)))
                cover = self.store.resolve(result['cover_id'])
                self.assertEqual(result['name'], '一本书.epub')
                with Image.open(cover) as image:
                    self.assertEqual(image.format, 'JPEG')
                    self.assertLessEqual(image.width, 320)
                    self.assertLessEqual(image.height, 440)

    def test_docx_first_embedded_image(self):
        stream = io.BytesIO()
        with ZipFile(stream, 'w') as archive:
            archive.writestr('word/document.xml', '<document xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><a:blip r:embed="r1"/></document>')
            archive.writestr('word/_rels/document.xml.rels', '<Relationships><Relationship Id="r1" Target="media/image1.png" /></Relationships>')
            archive.writestr('word/media/image1.png', image_bytes())
        result = self.store.upload('文稿.docx', io.BytesIO(stream.getvalue()))
        self.assertTrue(self.store.resolve(result['cover_id']).is_file())

    def test_missing_corrupt_oversized_and_external_cover_preserve_upload(self):
        payloads = [b'broken', epub_bytes(picture=b'invalid image'),
                    epub_bytes(picture=b'x' * (IMAGE_LIMIT + 1)),
                    epub_bytes(href='https://example.com/cover.png'), epub_bytes(href='../../private.png')]
        for data in payloads:
            result = self.store.upload('无封面.epub', io.BytesIO(data))
            self.assertIsNone(result['cover_id'])
            self.assertTrue(self.store.resolve(result['id']).is_file())
        self.assertIsNone(self.store.upload('旧文档.doc', io.BytesIO(b'legacy'))['cover_id'])

    def test_archive_paths_cannot_escape(self):
        for href in ('../../etc/passwd', '/etc/passwd', 'https://example.com/pic', '%2e%2e/%2e%2e/private'):
            with self.assertRaises(ValueError):
                _relative('OPS/book.opf', href)

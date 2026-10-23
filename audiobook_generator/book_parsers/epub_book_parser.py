import logging
import re
from typing import List, Tuple

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from audiobook_generator.book_parsers.base_book_parser import BaseBookParser
from audiobook_generator.config.general_config import GeneralConfig
from .source_map import TrackedText, epub_source

logger = logging.getLogger(__name__)


class EpubBookParser(BaseBookParser):
    def __init__(self, config: GeneralConfig):
        super().__init__(config)
        self.book = epub.read_epub(self.config.input_file, {"ignore_ncx": True})

    def __str__(self) -> str:
        return super().__str__()

    def validate_config(self):
        if self.config.input_file is None:
            raise ValueError("Epub Parser: Input file cannot be empty")
        if not self.config.input_file.endswith(".epub"):
            raise ValueError(f"Epub Parser: Unsupported file format: {self.config.input_file}")

    def get_book(self):
        return self.book

    def get_book_title(self) -> str:
        if self.book.get_metadata('DC', 'title'):
            return self.book.get_metadata("DC", "title")[0][0]
        return "Untitled"

    def get_book_author(self) -> str:
        if self.book.get_metadata('DC', 'creator'):
            return self.book.get_metadata("DC", "creator")[0][0]
        return "Unknown"

    def get_chapters(self, break_string) -> List[Tuple[str, str]]:
        chapters = []
        self.source_chapters = []
        search_and_replaces = self.get_search_and_replaces()
        for item in self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            content = item.get_content()
            soup = BeautifulSoup(content, "lxml-xml")
            raw, source_records = epub_source(soup, item.get_name())
            tracked = TrackedText(raw).strip()
            logger.debug(f"Raw text: <{raw[:]}>")

            # Replace excessive whitespaces and newline characters based on the mode
            if self.config.newline_mode == "single":
                tracked.sub(r"[\n]+", break_string)
            elif self.config.newline_mode == "double":
                tracked.sub(r"[\n]{2,}", break_string)
            elif self.config.newline_mode == "none":
                tracked.sub(r"[\n]+", " ")
            else:
                raise ValueError(f"Invalid newline mode: {self.config.newline_mode}")

            cleaned_text = tracked.text
            logger.debug(f"Cleaned text step 1: <{cleaned_text[:]}>")
            cleaned_text = tracked.sub(r"\s+", " ").text
            logger.debug(f"Cleaned text step 2: <{cleaned_text[:100]}>")

            # Removes end-note numbers
            if self.config.remove_endnotes:
                cleaned_text = tracked.sub(r'(?<=[a-zA-Z.,!?;”")])\d+', "").text
                logger.debug(f"Cleaned text step 4: <{cleaned_text[:100]}>")

            # Removes references numbers like [1] or [2.3]
            if self.config.remove_reference_numbers:
                cleaned_text = tracked.sub(r'\[\d+(\.\d+)?\]', '').text
                logger.debug(f"Cleaned text step 4.1 (removed brackets): <{cleaned_text[:100]}>")

            # Does user defined search and replaces
            for search_and_replace in search_and_replaces:
                cleaned_text = tracked.sub(search_and_replace['search'], search_and_replace['replace']).text
            logger.debug(f"Cleaned text step 5: <{cleaned_text[:100]}>")

            # Get proper chapter title
            if self.config.title_mode == "auto":
                title = ""
                title_levels = ['title', 'h1', 'h2', 'h3']
                for level in title_levels:
                    if soup.find(level):
                        title = soup.find(level).text
                        break
                if title.strip() == "" or re.match(r'^\d{1,3}$',title) is not None:
                    title = cleaned_text[:60]
            elif self.config.title_mode == "tag_text":
                title = ""
                title_levels = ['title', 'h1', 'h2', 'h3']
                for level in title_levels:
                    if soup.find(level):
                        title = soup.find(level).text
                        break
                if title.strip() == "":
                    title = "<blank>"
            elif self.config.title_mode == "first_few":
                title = cleaned_text[:60]
            else:
                raise ValueError("Unsupported title_mode")
            logger.debug(f"Raw title: <{title}>")
            title = self._sanitize_title(title, break_string)
            logger.debug(f"Sanitized title: <{title}>")

            chapters.append((title, cleaned_text))
            self.source_chapters.append({'title': title, 'text': cleaned_text,
                'paragraphs': tracked.paragraphs(source_records, len(chapters))})
            soup.decompose()
        return chapters

    def get_search_and_replaces(self):
        search_and_replaces = []
        if self.config.search_and_replace_file:
            with open(self.config.search_and_replace_file) as fp:
                search_and_replace_content = fp.readlines()
                for search_and_replace in search_and_replace_content:
                    if '==' in search_and_replace and not search_and_replace.startswith('==') and not search_and_replace.endswith('==') and not search_and_replace.startswith('#'):
                        search_and_replaces = search_and_replaces + [ {'search': r"{}".format(search_and_replace.split('==')[0]), 'replace': r"{}".format(search_and_replace.split('==')[1][:-1])} ]
        return search_and_replaces

    @staticmethod
    def _sanitize_title(title, break_string) -> str:
        # replace MAGIC_BREAK_STRING with a blank space
        # strip incase leading bank is missing
        title = title.replace(break_string, " ")
        sanitized_title = re.sub(r"[^\w\s]", "", title, flags=re.UNICODE)
        sanitized_title = re.sub(r"\s+", "_", sanitized_title.strip())
        return sanitized_title

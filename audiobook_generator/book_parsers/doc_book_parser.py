import logging
import re
from typing import List, Tuple

from audiobook_generator.book_parsers.base_book_parser import BaseBookParser
from audiobook_generator.config.general_config import GeneralConfig

logger = logging.getLogger(__name__)


class DocBookParser(BaseBookParser):
    """Parser for .doc and .docx files.
    
    Unlike the EPUB parser, this parser treats the entire document as a single chapter.
    All text is extracted and sent directly to TTS without chapter splitting.
    """
    
    def __init__(self, config: GeneralConfig):
        super().__init__(config)
        self._book_title = None
        self._book_author = None
        self._text_content = None
        self._load_document()
    
    def _load_document(self):
        """Load and extract text from the document."""
        input_file = self.config.input_file
        
        if input_file.endswith('.docx'):
            self._load_docx(input_file)
        elif input_file.endswith('.doc'):
            self._load_doc(input_file)
        else:
            raise ValueError(f"Doc Parser: Unsupported file format: {input_file}")
    
    def _load_docx(self, file_path: str):
        """Load .docx file using python-docx."""
        try:
            from docx import Document
            doc = Document(file_path)
            
            # Extract title from document properties or first paragraph
            if doc.core_properties.title:
                self._book_title = doc.core_properties.title
            else:
                # Use filename as title
                import os
                self._book_title = os.path.splitext(os.path.basename(file_path))[0]
            
            # Extract author
            if doc.core_properties.author:
                self._book_author = doc.core_properties.author
            else:
                self._book_author = "Unknown"
            
            # Extract all text from paragraphs
            paragraphs = []
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    paragraphs.append(text)
            
            self._text_content = '\n\n'.join(paragraphs)
            logger.info(f"Loaded DOCX file: {len(paragraphs)} paragraphs, {len(self._text_content)} characters")
            
        except ImportError:
            raise ImportError(
                "python-docx is required for .docx files. "
                "Install it with: pip install python-docx"
            )
    
    def _load_doc(self, file_path: str):
        """Load .doc file using textract or antiword fallback."""
        import os
        
        # Use filename as title
        self._book_title = os.path.splitext(os.path.basename(file_path))[0]
        self._book_author = "Unknown"
        
        # Try multiple methods to extract text from .doc files
        text = None
        
        # Method 1: Try textract
        try:
            import textract
            text = textract.process(file_path).decode('utf-8')
            logger.info("Used textract to extract .doc file")
        except (ImportError, Exception) as e:
            logger.debug(f"textract failed: {e}")
        
        # Method 2: Try antiword (common on macOS/Linux)
        if text is None:
            try:
                import subprocess
                result = subprocess.run(['antiword', file_path], capture_output=True, text=True)
                if result.returncode == 0:
                    text = result.stdout
                    logger.info("Used antiword to extract .doc file")
            except FileNotFoundError:
                logger.debug("antiword not found")
        
        # Method 3: Try textutil (macOS built-in)
        if text is None:
            try:
                import subprocess
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as tmp:
                    tmp_path = tmp.name
                result = subprocess.run(
                    ['textutil', '-convert', 'txt', '-output', tmp_path, file_path],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    with open(tmp_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                    os.unlink(tmp_path)
                    logger.info("Used textutil to extract .doc file")
            except Exception as e:
                logger.debug(f"textutil failed: {e}")
        
        if text is None:
            raise RuntimeError(
                "Cannot extract text from .doc file. Please install one of:\n"
                "- python-docx (convert .doc to .docx first)\n"
                "- textract: pip install textract\n"
                "- antiword: brew install antiword (macOS) or apt-get install antiword (Linux)\n"
                "Or convert the .doc file to .docx format first."
            )
        
        # Clean up the text
        self._text_content = text.strip()
        logger.info(f"Loaded DOC file: {len(self._text_content)} characters")
    
    def __str__(self) -> str:
        return f"DocBookParser(input_file={self.config.input_file}, title={self._book_title})"
    
    def validate_config(self):
        if self.config.input_file is None:
            raise ValueError("Doc Parser: Input file cannot be empty")
        if not (self.config.input_file.endswith('.doc') or self.config.input_file.endswith('.docx')):
            raise ValueError(f"Doc Parser: Unsupported file format: {self.config.input_file}")
    
    def get_book(self):
        return None  # No book object for doc files
    
    def get_book_title(self) -> str:
        return self._book_title or "Untitled"
    
    def get_book_author(self) -> str:
        return self._book_author or "Unknown"
    
    def get_chapters(self, break_string) -> List[Tuple[str, str]]:
        """Return the entire document as a single chapter.
        
        For doc/docx files, we don't split by chapters - the entire content
        is treated as one chapter and sent directly to TTS.
        """
        if not self._text_content:
            return []
        
        # Apply search and replaces if configured
        cleaned_text = self._text_content
        search_and_replaces = self.get_search_and_replaces()
        for search_and_replace in search_and_replaces:
            cleaned_text = re.sub(
                search_and_replace['search'],
                search_and_replace['replace'],
                cleaned_text
            )
        
        # Remove excessive whitespace while preserving paragraph structure
        # Replace multiple newlines with double newline
        cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
        
        # Remove endnotes if configured
        if self.config.remove_endnotes:
            cleaned_text = re.sub(r'(?<=[a-zA-Z.,!?;"")])\d+', "", cleaned_text)
        
        # Remove reference numbers if configured
        if self.config.remove_reference_numbers:
            cleaned_text = re.sub(r'\[\d+(\.\d+)?\]', '', cleaned_text)
        
        # Generate title
        title = self._book_title or "Full Document"
        title = self._sanitize_title(title, break_string)
        
        return [(title, cleaned_text)]
    
    def get_search_and_replaces(self):
        """Load search and replace rules from file if configured."""
        search_and_replaces = []
        if self.config.search_and_replace_file:
            with open(self.config.search_and_replace_file) as fp:
                for line in fp:
                    if ('==' in line and 
                        not line.startswith('==') and 
                        not line.endswith('==') and 
                        not line.startswith('#')):
                        parts = line.split('==', 1)
                        search_and_replaces.append({
                            'search': r"{}".format(parts[0]),
                            'replace': r"{}".format(parts[1].rstrip('\n'))
                        })
        return search_and_replaces
    
    @staticmethod
    def _sanitize_title(title: str, break_string: str) -> str:
        """Sanitize title for use as filename."""
        title = title.replace(break_string, " ")
        sanitized_title = re.sub(r"[^\w\s]", "", title, flags=re.UNICODE)
        sanitized_title = re.sub(r"\s+", "_", sanitized_title.strip())
        return sanitized_title or "Untitled"

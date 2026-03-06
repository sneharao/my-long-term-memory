"""Change detection using SHA256 hashing for PDFs and images."""

import hashlib
from typing import List, Optional
import fitz

from .state import StateDB


class ChangeDetector:
    """Detects page changes by comparing SHA256 hashes."""

    def __init__(self, state_db: StateDB):
        self.state_db = state_db

    def _compute_page_hash(self, page: fitz.Page, dpi: int = 150) -> str:
        """Compute SHA256 hash of rendered PDF page."""
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix)
        return hashlib.sha256(pixmap.samples).hexdigest()

    def _compute_image_file_hash(self, image_path: str) -> str:
        """Compute SHA256 hash of image file."""
        with open(image_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()

    def detect_changed_pages(self, doc_id: str, pdf_path: str) -> List[int]:
        """Detect changed PDF pages. Returns 0-indexed page numbers."""
        changed = []
        doc = fitz.open(pdf_path)

        try:
            stored = self.state_db.get_page_hashes(doc_id)
            for page_num in range(len(doc)):
                current = self._compute_page_hash(doc[page_num])
                if stored.get(page_num) != current:
                    changed.append(page_num)
        finally:
            doc.close()

        return changed

    def detect_changed_images(self, doc_id: str, image_paths: List[str]) -> List[int]:
        """Detect changed images. Returns 0-indexed page numbers."""
        changed = []
        stored = self.state_db.get_page_hashes(doc_id)

        for page_num, path in enumerate(image_paths):
            current = self._compute_image_file_hash(path)
            if stored.get(page_num) != current:
                changed.append(page_num)

        return changed

    def update_page_hashes(self, doc_id: str, pdf_path: str, page_numbers: Optional[List[int]] = None) -> None:
        """Update stored hashes for PDF pages."""
        doc = fitz.open(pdf_path)
        try:
            pages = page_numbers or list(range(len(doc)))
            for page_num in pages:
                if page_num < len(doc):
                    h = self._compute_page_hash(doc[page_num])
                    self.state_db.set_page_hash(doc_id, page_num, h)
        finally:
            doc.close()

    def update_image_hashes(self, doc_id: str, image_paths: List[str], page_numbers: Optional[List[int]] = None) -> None:
        """Update stored hashes for images."""
        pages = page_numbers or list(range(len(image_paths)))
        for page_num in pages:
            if page_num < len(image_paths):
                h = self._compute_image_file_hash(image_paths[page_num])
                self.state_db.set_page_hash(doc_id, page_num, h)

    def is_first_sync(self, doc_id: str) -> bool:
        """Check if document has no stored hashes (first sync)."""
        return len(self.state_db.get_page_hashes(doc_id)) == 0

    def get_page_count(self, pdf_path: str) -> int:
        """Get PDF page count."""
        doc = fitz.open(pdf_path)
        try:
            return len(doc)
        finally:
            doc.close()

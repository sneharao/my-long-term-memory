"""Remarkable Cloud integration via rmapi CLI."""

import json
import subprocess
import tempfile
import shutil
import zipfile
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from io import StringIO
import logging

os.environ.setdefault('DYLD_FALLBACK_LIBRARY_PATH', '/opt/homebrew/opt/cairo/lib')

import cairosvg
from rmc.cli import convert_rm

logger = logging.getLogger(__name__)


@dataclass
class RemarkableDocument:
    """Document metadata from Remarkable Cloud."""
    id: str
    name: str
    doc_type: str
    parent: str
    modified_client: str
    modified_timestamp: int
    version: int


class RemarkableError(Exception):
    """Raised when rmapi command fails."""
    pass


class RemarkableClient:
    """Python wrapper for rmapi CLI tool."""

    def __init__(self, sync_folder: str = "/"):
        self.sync_folder = sync_folder
        self._verify_rmapi_installed()

    def _verify_rmapi_installed(self) -> None:
        if not shutil.which("rmapi"):
            raise RemarkableError("rmapi not found. Install from github.com/ddvk/rmapi/releases")

    def _run_rmapi(self, *args: str) -> str:
        """Execute rmapi command and return output."""
        cmd = ["rmapi", "-ni"] + list(args)
        logger.debug(f"Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                raise RemarkableError(f"rmapi failed: {result.stderr or result.stdout}")
            return result.stdout
        except subprocess.TimeoutExpired:
            raise RemarkableError("rmapi timed out after 60s")
        except FileNotFoundError:
            raise RemarkableError("rmapi not found in PATH")

    def _parse_timestamp(self, iso_timestamp: str) -> int:
        """Parse ISO timestamp to Unix timestamp."""
        if not iso_timestamp:
            return 0
        try:
            if "." in iso_timestamp:
                base, frac = iso_timestamp.split(".")
                frac = frac.rstrip("Z")[:6]
                iso_timestamp = f"{base}.{frac}Z"
            dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except (ValueError, AttributeError) as e:
            logger.warning(f"Failed to parse timestamp '{iso_timestamp}': {e}")
            return 0

    def list_documents(self) -> list[RemarkableDocument]:
        """List all documents at sync folder level."""
        output = self._run_rmapi("ls", self.sync_folder)
        documents = []

        for line in output.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("[d]"):
                continue
            if line.startswith("[f]"):
                name = line[4:].strip()
                doc = RemarkableDocument(
                    id=name, name=name, doc_type="DocumentType",
                    parent="", modified_client="", modified_timestamp=0, version=0
                )
                documents.append(doc)

        logger.info(f"Found {len(documents)} documents in {self.sync_folder}")
        return documents

    def get_document_metadata(self, doc_name: str) -> dict:
        """Get document metadata via rmapi stat (returns JSON)."""
        doc_path = f"{self.sync_folder.rstrip('/')}/{doc_name}"
        output = self._run_rmapi("stat", doc_path)
        return json.loads(output)

    def get_modification_timestamp(self, doc_name: str) -> int:
        """Get Unix timestamp of last modification."""
        try:
            metadata = self.get_document_metadata(doc_name)
            return self._parse_timestamp(metadata.get("ModifiedClient", ""))
        except (RemarkableError, json.JSONDecodeError) as e:
            logger.warning(f"Could not get mod time for '{doc_name}': {e}")
            return 0

    def filter_modified_since(self, documents: list, since_timestamp: int) -> list:
        """Filter documents modified after given timestamp."""
        modified = []
        for doc in documents:
            mod_time = self.get_modification_timestamp(doc.name)
            if mod_time > since_timestamp:
                doc.modified_timestamp = mod_time
                modified.append(doc)
        return modified

    def download_document_images(self, doc_name: str, output_dir: Optional[str] = None) -> List[str]:
        """Download document and convert pages to PNG images."""
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="remarkable_")

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        doc_path = f"{self.sync_folder.rstrip('/')}/{doc_name}"
        logger.info(f"Downloading '{doc_name}' to {output_dir}")

        # Download .rmdoc
        cmd = ["rmapi", "-ni", "get", doc_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(output_path))
            if result.returncode != 0:
                raise RemarkableError(f"Failed to download '{doc_name}': {result.stderr or result.stdout}")
        except subprocess.TimeoutExpired:
            raise RemarkableError(f"Download of '{doc_name}' timed out")

        # Extract zip
        rmdoc_files = list(output_path.glob("*.rmdoc"))
        if not rmdoc_files:
            raise RemarkableError(f"No .rmdoc file found for '{doc_name}'")

        extract_dir = output_path / "extracted"
        extract_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(rmdoc_files[0], 'r') as z:
            z.extractall(extract_dir)

        # Get page order from .content file
        content_files = list(extract_dir.glob("*.content"))
        if not content_files:
            raise RemarkableError(f"No .content file found in {doc_name}")

        with open(content_files[0], 'r') as f:
            content_data = json.load(f)

        page_ids = []
        if "cPages" in content_data and "pages" in content_data["cPages"]:
            page_ids = [p["id"] for p in content_data["cPages"]["pages"]]

        # Find .rm directory
        rm_dirs = [d for d in extract_dir.iterdir() if d.is_dir()]
        if not rm_dirs:
            raise RemarkableError(f"No .rm directory found in {doc_name}")
        rm_dir = rm_dirs[0]

        # Convert each page to PNG
        png_paths = []
        images_dir = output_path / "images"
        images_dir.mkdir(exist_ok=True)

        for idx, page_id in enumerate(page_ids):
            rm_file = rm_dir / f"{page_id}.rm"
            if not rm_file.exists():
                logger.warning(f"Page {idx+1} .rm file not found")
                continue

            png_path = images_dir / f"page_{idx+1:03d}.png"
            try:
                self._convert_rm_to_png(rm_file, png_path)
                png_paths.append(str(png_path))
            except Exception as e:
                logger.warning(f"Page {idx+1} conversion failed: {e}")

        logger.info(f"Converted {len(png_paths)} pages to PNG")
        return png_paths

    def _convert_rm_to_png(self, rm_file: Path, png_path: Path, scale: float = 3.0) -> None:
        """Convert .rm to PNG with white background."""
        from PIL import Image
        import io

        svg_buffer = StringIO()
        convert_rm(rm_file, 'svg', svg_buffer)
        svg_content = svg_buffer.getvalue()

        png_bytes = cairosvg.svg2png(bytestring=svg_content.encode('utf-8'), scale=scale)
        img = Image.open(io.BytesIO(png_bytes))

        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            background.save(png_path, 'PNG')
        else:
            img.save(png_path, 'PNG')

    def get_all_document_names(self) -> list[str]:
        """Get list of all document names."""
        return [doc.name for doc in self.list_documents()]

    def download_and_extract(self, doc_name: str, output_dir: Optional[str] = None) -> 'ExtractedDocument':
        """Download document and extract without converting to PNG.

        Returns an ExtractedDocument object that supports lazy page conversion.
        This allows checking the last page first before converting all pages.

        Note: Cleanup of output_dir is handled by the caller (remarkable_sync.py's finally block).
        """
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="remarkable_")

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        doc_path = f"{self.sync_folder.rstrip('/')}/{doc_name}"
        logger.info(f"Downloading '{doc_name}' to {output_dir}")

        # Download .rmdoc
        cmd = ["rmapi", "-ni", "get", doc_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(output_path))
            if result.returncode != 0:
                raise RemarkableError(f"Failed to download '{doc_name}': {result.stderr or result.stdout}")
        except subprocess.TimeoutExpired:
            raise RemarkableError(f"Download of '{doc_name}' timed out")

        # Extract zip
        rmdoc_files = list(output_path.glob("*.rmdoc"))
        if not rmdoc_files:
            raise RemarkableError(f"No .rmdoc file found for '{doc_name}'")

        extract_dir = output_path / "extracted"
        extract_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(rmdoc_files[0], 'r') as z:
            z.extractall(extract_dir)

        # Get page order from .content file
        content_files = list(extract_dir.glob("*.content"))
        if not content_files:
            raise RemarkableError(f"No .content file found in {doc_name}")

        with open(content_files[0], 'r') as f:
            content_data = json.load(f)

        page_ids = []
        if "cPages" in content_data and "pages" in content_data["cPages"]:
            page_ids = [p["id"] for p in content_data["cPages"]["pages"]]

        # Find .rm directory
        rm_dirs = [d for d in extract_dir.iterdir() if d.is_dir()]
        if not rm_dirs:
            raise RemarkableError(f"No .rm directory found in {doc_name}")
        rm_dir = rm_dirs[0]

        images_dir = output_path / "images"
        images_dir.mkdir(exist_ok=True)

        logger.info(f"Extracted {len(page_ids)} pages (lazy conversion enabled)")
        return ExtractedDocument(
            page_ids=page_ids,
            rm_dir=rm_dir,
            images_dir=images_dir,
            convert_func=self._convert_rm_to_png
        )


class ExtractedDocument:
    """Extracted Remarkable document with lazy PNG conversion.

    Allows converting only specific pages to PNG on demand,
    enabling "last page first" optimization to check for changes
    before converting all pages.
    """

    def __init__(self, page_ids: List[str], rm_dir: Path, images_dir: Path, convert_func: callable):
        self.page_ids = page_ids
        self.rm_dir = rm_dir
        self.images_dir = images_dir
        self.convert_func = convert_func
        self._converted_pages = {}

    @property
    def page_count(self) -> int:
        """Total number of pages in the document."""
        return len(self.page_ids)

    def convert_page(self, page_num: int) -> Optional[str]:
        """Convert a single page (zero-indexed) to PNG. Returns path or None."""
        if page_num in self._converted_pages:
            return self._converted_pages[page_num]

        if page_num < 0 or page_num >= len(self.page_ids):
            return None

        page_id = self.page_ids[page_num]
        rm_file = self.rm_dir / f"{page_id}.rm"

        if not rm_file.exists():
            return None

        png_path = self.images_dir / f"page_{page_num+1:03d}.png"

        try:
            self.convert_func(rm_file, png_path)
            self._converted_pages[page_num] = str(png_path)
            return str(png_path)
        except Exception as e:
            logger.warning(f"Page {page_num} conversion failed: {e}")
            return None

    def convert_pages(self, page_nums: List[int]) -> List[str]:
        """Convert specific pages to PNG. Returns list of paths."""
        return [p for p in (self.convert_page(n) for n in page_nums) if p]

    def convert_all_pages(self) -> List[str]:
        """Convert all pages to PNG."""
        return self.convert_pages(list(range(self.page_count)))

    def get_all_converted_paths(self) -> List[str]:
        """Get all converted PNG paths sorted by page number."""
        return [self._converted_pages[k] for k in sorted(self._converted_pages.keys())]

"""
Obsidian Note Manager Module

This module provides functionality for reading and writing Obsidian markdown notes
with support for appending content with session markers.

Classes:
    ObsidianWriter: Handles all operations related to Obsidian vault notes

Example:
    >>> writer = ObsidianWriter(vault_path="/Users/spidugu/Documents/Obsidian Vault")
    >>> writer.create_note("AWS cloud practitioner", "# AWS Notes\\n\\nInitial content")
    >>> writer.append_to_note("AWS cloud practitioner", "New learnings", "2026-03-06")
"""

import os
import re
import shutil
from pathlib import Path
from datetime import datetime, date
from typing import List, Optional

# Supported image formats for screenshot detection
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}

# macOS screenshot naming: "Screenshot YYYY-MM-DD at HH.MM.SS AM/PM.png"
MACOS_SCREENSHOT_PATTERN = re.compile(
    r'^Screenshot (\d{4}-\d{2}-\d{2}) at .*\.(png|jpg|jpeg)$',
    re.IGNORECASE
)


class ObsidianWriter:
    """
    A class to manage reading and writing Obsidian markdown notes.

    This class provides methods to create, read, and append to markdown notes
    in an Obsidian vault, with automatic session markers for tracking when
    content was added.

    Attributes:
        vault_path (Path): The absolute path to the Obsidian vault directory
    """

    def __init__(self, vault_path: str):
        """
        Initialize the ObsidianWriter with a vault path.

        Args:
            vault_path (str): The absolute path to the Obsidian vault directory

        Raises:
            ValueError: If the vault path doesn't exist or is not a directory
        """
        self.vault_path = Path(vault_path)

        # Validate that the vault path exists and is a directory
        if not self.vault_path.exists():
            raise ValueError(f"Vault path does not exist: {vault_path}")
        if not self.vault_path.is_dir():
            raise ValueError(f"Vault path is not a directory: {vault_path}")

    def get_note_path(self, notebook_name: str) -> Path:
        """
        Convert a notebook name to its full file path in the vault.

        This method takes a notebook name and converts it to a markdown file path
        within the Obsidian vault. The .md extension is automatically added.

        Args:
            notebook_name (str): The name of the notebook (e.g., "AWS cloud practitioner")

        Returns:
            Path: The full absolute path to the note file

        Example:
            >>> writer = ObsidianWriter("/Users/spidugu/Documents/Obsidian Vault")
            >>> path = writer.get_note_path("AWS cloud practitioner")
            >>> print(path)
            /Users/spidugu/Documents/Obsidian Vault/AWS cloud practitioner.md
        """
        # Ensure the notebook name has .md extension
        if not notebook_name.endswith('.md'):
            notebook_name = f"{notebook_name}.md"

        return self.vault_path / notebook_name

    def note_exists(self, notebook_name: str) -> bool:
        """
        Check if a note already exists in the vault.

        Args:
            notebook_name (str): The name of the notebook to check

        Returns:
            bool: True if the note exists, False otherwise

        Example:
            >>> writer = ObsidianWriter("/Users/spidugu/Documents/Obsidian Vault")
            >>> if writer.note_exists("AWS cloud practitioner"):
            ...     print("Note already exists")
        """
        note_path = self.get_note_path(notebook_name)
        return note_path.exists() and note_path.is_file()

    def read_existing_note(self, notebook_name: str) -> str:
        """
        Read the current content of an existing note.

        Args:
            notebook_name (str): The name of the notebook to read

        Returns:
            str: The complete content of the note

        Raises:
            FileNotFoundError: If the note doesn't exist

        Example:
            >>> writer = ObsidianWriter("/Users/spidugu/Documents/Obsidian Vault")
            >>> content = writer.read_existing_note("AWS cloud practitioner")
            >>> print(content)
        """
        note_path = self.get_note_path(notebook_name)

        if not note_path.exists():
            raise FileNotFoundError(f"Note does not exist: {notebook_name}")

        # Read the entire note content
        with open(note_path, 'r', encoding='utf-8') as f:
            return f.read()

    def append_to_note(self, notebook_name: str, new_content: str, date: str) -> None:
        """
        Append new content to an existing note with a session marker.

        This method adds new content to an existing note, prefixed with a session
        marker that includes the date. The session marker helps track when different
        content was added to the note.

        Args:
            notebook_name (str): The name of the notebook to append to
            new_content (str): The content to append to the note
            date (str): The date string for the session marker (e.g., "2026-03-06")

        Raises:
            FileNotFoundError: If the note doesn't exist

        Example:
            >>> writer = ObsidianWriter("/Users/spidugu/Documents/Obsidian Vault")
            >>> writer.append_to_note(
            ...     "AWS cloud practitioner",
            ...     "EC2 instance types: t2.micro, t2.small",
            ...     "2026-03-06"
            ... )

        Note:
            The session marker format is:
            ---
            ## Session: 2026-03-06

            [new content]
        """
        note_path = self.get_note_path(notebook_name)

        if not note_path.exists():
            raise FileNotFoundError(f"Note does not exist: {notebook_name}")

        # Create the session marker and content block
        session_marker = f"\n\n---\n## Session: {date}\n\n{new_content}"

        # Append to the existing note
        with open(note_path, 'a', encoding='utf-8') as f:
            f.write(session_marker)

    def create_note(self, notebook_name: str, content: str) -> None:
        """
        Create a new note in the vault.

        This method creates a new markdown note with the given content. If a note
        with the same name already exists, it will be overwritten.

        Args:
            notebook_name (str): The name of the notebook to create
            content (str): The initial content for the note

        Example:
            >>> writer = ObsidianWriter("/Users/spidugu/Documents/Obsidian Vault")
            >>> writer.create_note(
            ...     "AWS cloud practitioner",
            ...     "# AWS Cloud Practitioner Notes\\n\\nStarting my AWS journey!"
            ... )

        Note:
            If the note already exists, consider using append_to_note() instead
            to preserve existing content.
        """
        note_path = self.get_note_path(notebook_name)

        # Create the note with the provided content
        with open(note_path, 'w', encoding='utf-8') as f:
            f.write(content)

    def transfer_screenshots(self, source_dir: str, today: date) -> List[str]:
        """
        Find all image files taken today in source_dir, copy them to the vault's
        attachments folder, delete the originals, and return the list of filenames.

        Two strategies to identify "today's" images:
          1. macOS screenshot filename pattern (Screenshot YYYY-MM-DD at ...)
          2. mtime fallback — catches any image file last modified today

        Copy is done before delete so a failed copy never removes the original.
        shutil.copy2 is used (not copy) to preserve file metadata including mtime.
        """
        today_str = today.strftime('%Y-%m-%d')
        source = Path(source_dir).expanduser()
        attachments_dir = self.vault_path / "attachments"
        attachments_dir.mkdir(exist_ok=True)

        transferred = []
        for f in sorted(source.iterdir()):
            if f.suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            # Strategy 1: match macOS screenshot naming convention
            m = MACOS_SCREENSHOT_PATTERN.match(f.name)
            is_today = bool(m and m.group(1) == today_str)

            # Strategy 2: mtime fallback for renamed or non-macOS screenshots
            if not is_today:
                is_today = (date.fromtimestamp(f.stat().st_mtime) == today)

            if not is_today:
                continue

            dest = attachments_dir / f.name
            shutil.copy2(f, dest)  # copy first — guarantees file is safe before deletion
            f.unlink()             # then remove from Desktop
            transferred.append(f.name)

        return transferred

    def get_or_create_note(self, notebook_name: str, initial_content: Optional[str] = None) -> str:
        """
        Get the content of a note if it exists, or create it if it doesn't.

        This is a convenience method that combines checking for existence and
        creating a note if needed.

        Args:
            notebook_name (str): The name of the notebook
            initial_content (Optional[str]): Content to use if creating a new note.
                If None and note doesn't exist, an empty note will be created.

        Returns:
            str: The content of the note (empty string if newly created with no content)

        Example:
            >>> writer = ObsidianWriter("/Users/spidugu/Documents/Obsidian Vault")
            >>> content = writer.get_or_create_note(
            ...     "AWS cloud practitioner",
            ...     "# AWS Cloud Practitioner Notes"
            ... )
        """
        if self.note_exists(notebook_name):
            return self.read_existing_note(notebook_name)
        else:
            content = initial_content if initial_content is not None else ""
            self.create_note(notebook_name, content)
            return content


# Default configuration
DEFAULT_VAULT_PATH = "/Users/spidugu/Documents/Obsidian Vault"


def get_default_writer() -> ObsidianWriter:
    """
    Get an ObsidianWriter instance configured with the default vault path.

    Returns:
        ObsidianWriter: An initialized ObsidianWriter with the default vault path

    Example:
        >>> writer = get_default_writer()
        >>> writer.create_note("My Note", "# Hello World")
    """
    return ObsidianWriter(DEFAULT_VAULT_PATH)


def prompt_and_transfer_screenshots(
    obsidian_writer: ObsidianWriter,
    screenshots_cfg: dict,
    doc_modified: int,
    dry_run: bool = False,
    logger = None
) -> List[str]:
    """
    Prompt user for screenshot date and transfer matching screenshots.

    This function handles the interactive prompt for screenshot date selection
    and orchestrates the screenshot transfer process. It shows the Remarkable
    sync timestamp as reference and allows the user to specify which date's
    screenshots to retrieve.

    Args:
        obsidian_writer: ObsidianWriter instance for transferring screenshots
        screenshots_cfg: Screenshot configuration dict with 'enabled' and 'source_dir'
        doc_modified: Unix timestamp of when document was synced to Remarkable Cloud
        dry_run: If True, skip actual transfer (default: False)
        logger: Logger instance for logging messages (optional)

    Returns:
        List[str]: List of transferred screenshot filenames, empty if skipped/failed

    Example:
        >>> screenshots = prompt_and_transfer_screenshots(
        ...     writer, {'enabled': True, 'source_dir': '~/Desktop'},
        ...     1709876415, dry_run=False, logger=my_logger
        ... )
    """
    transferred_screenshots = []

    if not screenshots_cfg.get('enabled') or dry_run:
        return transferred_screenshots

    # Display prompt header
    print("\n" + "="*60)
    print("SCREENSHOT TRANSFER")
    print("="*60)

    # Show the Remarkable sync timestamp as reference
    if doc_modified > 0:
        sync_date = datetime.fromtimestamp(doc_modified).strftime('%Y-%m-%d %H:%M:%S')
        print(f"Note: Remarkable sync timestamp: {sync_date}")
        print("(This is when your tablet synced, not when you wrote the notes)")

    print("\nWhich date should screenshots be retrieved from?")
    print("Format: YYYY-MM-DD (e.g., 2026-03-08)")
    print("Press Enter to skip screenshot transfer")

    screenshot_date_input = input("\nEnter date: ").strip()

    if screenshot_date_input:
        try:
            # Parse the date
            screenshot_date = datetime.strptime(screenshot_date_input, '%Y-%m-%d').date()

            if logger:
                logger.info(f"Checking for screenshots from {screenshot_date.strftime('%Y-%m-%d')}...")

            transferred_screenshots = obsidian_writer.transfer_screenshots(
                screenshots_cfg.get('source_dir', '~/Desktop'),
                screenshot_date)

            if transferred_screenshots:
                if logger:
                    logger.info(f"Transferred {len(transferred_screenshots)} screenshot(s) from {screenshot_date.strftime('%Y-%m-%d')}")
            else:
                if logger:
                    logger.info(f"No screenshots found from {screenshot_date.strftime('%Y-%m-%d')}")

        except ValueError:
            if logger:
                logger.warning(f"Invalid date format '{screenshot_date_input}'. Expected YYYY-MM-DD. Skipping screenshot transfer.")
        except Exception as e:
            if logger:
                logger.warning(f"Screenshot transfer failed: {e}")
    else:
        if logger:
            logger.info("Screenshot transfer skipped (no date provided)")

    return transferred_screenshots

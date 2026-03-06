"""SQLite state management for sync pipeline."""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Document:
    """Remarkable notebook record."""
    id: str
    name: str
    remarkable_path: str
    obsidian_path: Optional[str]
    anki_deck: Optional[str]
    last_modified: int
    last_synced: Optional[int]
    page_count: int


@dataclass
class Page:
    """Page hash record for change detection."""
    id: str
    document_id: str
    page_number: int
    content_hash: Optional[str]
    processed_at: Optional[int]


@dataclass
class Flashcard:
    """Generated flashcard record."""
    id: str
    document_id: str
    question: str
    answer: str
    anki_note_id: Optional[int]
    created_at: int


@dataclass
class SyncRun:
    """Sync execution log."""
    id: int
    started_at: int
    completed_at: Optional[int]
    documents_processed: int
    pages_processed: int
    cards_added: int
    status: str


class StateDB:
    """SQLite database for sync state."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        remarkable_path TEXT,
        obsidian_path TEXT,
        anki_deck TEXT,
        last_modified INTEGER,
        last_synced INTEGER,
        page_count INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS pages (
        id TEXT PRIMARY KEY,
        document_id TEXT REFERENCES documents(id),
        page_number INTEGER,
        content_hash TEXT,
        processed_at INTEGER,
        UNIQUE(document_id, page_number)
    );

    CREATE TABLE IF NOT EXISTS flashcards (
        id TEXT PRIMARY KEY,
        document_id TEXT REFERENCES documents(id),
        question TEXT,
        answer TEXT,
        anki_note_id INTEGER,
        created_at INTEGER
    );

    CREATE TABLE IF NOT EXISTS sync_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at INTEGER,
        completed_at INTEGER,
        documents_processed INTEGER DEFAULT 0,
        pages_processed INTEGER DEFAULT 0,
        cards_added INTEGER DEFAULT 0,
        status TEXT DEFAULT 'running'
    );

    CREATE INDEX IF NOT EXISTS idx_pages_document ON pages(document_id);
    CREATE INDEX IF NOT EXISTS idx_flashcards_document ON flashcards(document_id);
    CREATE INDEX IF NOT EXISTS idx_documents_name ON documents(name);
    """

    def __init__(self, db_path: str = "state.db"):
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # Document operations
    def get_document(self, doc_id: str) -> Optional[Document]:
        cursor = self.conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = cursor.fetchone()
        return Document(**dict(row)) if row else None

    def get_document_by_name(self, name: str) -> Optional[Document]:
        cursor = self.conn.execute("SELECT * FROM documents WHERE name = ?", (name,))
        row = cursor.fetchone()
        return Document(**dict(row)) if row else None

    def upsert_document(self, doc_id: str, name: str, remarkable_path: str,
                        last_modified: int, page_count: int = 0) -> Document:
        existing = self.get_document(doc_id)
        if existing:
            self.conn.execute(
                "UPDATE documents SET name=?, remarkable_path=?, last_modified=?, page_count=? WHERE id=?",
                (name, remarkable_path, last_modified, page_count, doc_id))
        else:
            self.conn.execute(
                "INSERT INTO documents (id, name, remarkable_path, obsidian_path, anki_deck, last_modified, page_count) VALUES (?,?,?,?,?,?,?)",
                (doc_id, name, remarkable_path, f"{name}.md", name.replace(" ", "_"), last_modified, page_count))
        self.conn.commit()
        return self.get_document(doc_id)

    def mark_document_synced(self, doc_id: str) -> None:
        self.conn.execute("UPDATE documents SET last_synced=? WHERE id=?", (int(time.time()), doc_id))
        self.conn.commit()

    def get_all_documents(self) -> list[Document]:
        cursor = self.conn.execute("SELECT * FROM documents ORDER BY name")
        return [Document(**dict(row)) for row in cursor.fetchall()]

    # Page operations
    def get_page_hash(self, doc_id: str, page_number: int) -> Optional[str]:
        cursor = self.conn.execute(
            "SELECT content_hash FROM pages WHERE document_id=? AND page_number=?",
            (doc_id, page_number))
        row = cursor.fetchone()
        return row["content_hash"] if row else None

    def get_page_hashes(self, doc_id: str) -> dict[int, str]:
        cursor = self.conn.execute(
            "SELECT page_number, content_hash FROM pages WHERE document_id=?", (doc_id,))
        return {row["page_number"]: row["content_hash"] for row in cursor.fetchall()}

    def set_page_hash(self, doc_id: str, page_number: int, content_hash: str) -> None:
        page_id = f"{doc_id}:{page_number}"
        now = int(time.time())
        self.conn.execute(
            """INSERT INTO pages (id, document_id, page_number, content_hash, processed_at)
               VALUES (?,?,?,?,?) ON CONFLICT(document_id, page_number)
               DO UPDATE SET content_hash=?, processed_at=?""",
            (page_id, doc_id, page_number, content_hash, now, content_hash, now))
        self.conn.commit()

    def get_document_pages(self, doc_id: str) -> list[Page]:
        cursor = self.conn.execute(
            "SELECT * FROM pages WHERE document_id=? ORDER BY page_number", (doc_id,))
        return [Page(**dict(row)) for row in cursor.fetchall()]

    # Flashcard operations
    def flashcard_exists(self, card_id: str) -> bool:
        cursor = self.conn.execute("SELECT 1 FROM flashcards WHERE id=?", (card_id,))
        return cursor.fetchone() is not None

    def record_flashcard(self, card_id: str, doc_id: str, question: str, answer: str,
                         anki_note_id: Optional[int] = None) -> None:
        self.conn.execute(
            "INSERT INTO flashcards (id, document_id, question, answer, anki_note_id, created_at) VALUES (?,?,?,?,?,?)",
            (card_id, doc_id, question, answer, anki_note_id, int(time.time())))
        self.conn.commit()

    def get_document_flashcards(self, doc_id: str) -> list[Flashcard]:
        cursor = self.conn.execute(
            "SELECT * FROM flashcards WHERE document_id=? ORDER BY created_at", (doc_id,))
        return [Flashcard(**dict(row)) for row in cursor.fetchall()]

    # Sync run operations
    def start_sync_run(self) -> int:
        cursor = self.conn.execute(
            "INSERT INTO sync_runs (started_at, status) VALUES (?, ?)",
            (int(time.time()), "running"))
        self.conn.commit()
        return cursor.lastrowid

    def complete_sync_run(self, run_id: int, documents_processed: int,
                          pages_processed: int, cards_added: int, status: str = "success") -> None:
        self.conn.execute(
            "UPDATE sync_runs SET completed_at=?, documents_processed=?, pages_processed=?, cards_added=?, status=? WHERE id=?",
            (int(time.time()), documents_processed, pages_processed, cards_added, status, run_id))
        self.conn.commit()

    def get_last_sync_time(self) -> Optional[int]:
        cursor = self.conn.execute(
            "SELECT completed_at FROM sync_runs WHERE status='success' ORDER BY completed_at DESC LIMIT 1")
        row = cursor.fetchone()
        return row["completed_at"] if row else None

    def get_recent_sync_runs(self, limit: int = 10) -> list[SyncRun]:
        cursor = self.conn.execute(
            "SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT ?", (limit,))
        return [SyncRun(**dict(row)) for row in cursor.fetchall()]

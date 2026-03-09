#!/usr/bin/env python3
"""Remarkable Sync - Sync Remarkable notebooks to Obsidian and Anki."""

import argparse
import logging
import sys
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from PIL import Image

from lib.remarkable import RemarkableClient, RemarkableError
from lib.change_detector import ChangeDetector
from lib.transcriber import Transcriber
from lib.obsidian import ObsidianWriter
from lib.anki import AnkiClient
from lib.state import StateDB


def setup_logging(log_level: str = "INFO", log_dir: str = "logs") -> logging.Logger:
    """Configure logging to console and file."""
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    log_file = log_path / f"sync_{datetime.now().strftime('%Y%m%d')}.log"

    logger = logging.getLogger('remarkable_sync')
    logger.setLevel(getattr(logging, log_level))

    if logger.handlers:
        return logger

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(console)

    file_h = logging.FileHandler(log_file)
    file_h.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%Y-%m-%d %H:%M:%S'))
    logger.addHandler(file_h)

    return logger


def load_config(config_path: str = 'config.yaml') -> Dict:
    """Load configuration from YAML file."""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with open(config_file, 'r') as f:
        return yaml.safe_load(f)


def prompt_document_selection(documents: list, logger: logging.Logger) -> list:
    """Interactive prompt to select documents to sync."""
    print("\n" + "=" * 60)
    print("DOCUMENTS MODIFIED TODAY")
    print("=" * 60)

    for idx, doc in enumerate(documents, 1):
        mod_time = datetime.fromtimestamp(doc.modified_timestamp).strftime('%H:%M')
        print(f"  {idx}. {doc.name} (modified at {mod_time})")

    print(f"  A. Sync ALL ({len(documents)} documents)")
    print(f"  Q. Quit (sync nothing)")
    print("=" * 60)

    while True:
        try:
            choice = input("\nEnter number(s) to sync (comma-separated), A for all, or Q to quit: ").strip()

            if choice.upper() == 'Q':
                logger.info("User chose to quit")
                return []
            if choice.upper() == 'A':
                logger.info(f"User chose to sync all {len(documents)} documents")
                return documents

            selected = []
            for idx in [int(x.strip()) for x in choice.split(',')]:
                if 1 <= idx <= len(documents):
                    selected.append(documents[idx - 1])
            if selected:
                logger.info(f"User selected: {', '.join(d.name for d in selected)}")
                return selected
        except ValueError:
            print("Invalid input. Enter numbers, A, or Q.")


def process_document(doc_name: str, doc_id: str, doc_modified: int,
                     rm_client: RemarkableClient, change_detector: ChangeDetector,
                     transcriber: Transcriber, obsidian_writer: ObsidianWriter,
                     anki_client: AnkiClient, state_db: StateDB, temp_dir: Path,
                     logger: logging.Logger, dry_run: bool = False, force: bool = False,
                     transferred_screenshots: List[str] = None) -> Dict:
    """Process a single Remarkable document with optimized lazy page conversion.

    Optimization: Only converts pages to PNG when needed.
    1. First checks if new pages exist (beyond stored page count)
    2. Then checks last page hash to detect changes
    3. Only converts pages that need transcription
    """
    transferred_screenshots = transferred_screenshots or []
    stats = {'pages_processed': 0, 'pages_changed': 0, 'cards_created': 0, 'success': False}

    try:
        logger.info(f"\n{'='*60}\nProcessing: {doc_name}\n{'='*60}")

        doc_record = state_db.get_document_by_name(doc_name)
        if not doc_record:
            logger.info("First sync for this document")
            doc_record = state_db.upsert_document(doc_id, doc_name, "/", doc_modified, 0)

        if dry_run:
            logger.info("[DRY RUN] Would download and process")
            stats['success'] = True
            return stats

        # Download and extract (no PNG conversion yet)
        logger.info("Downloading document...")
        try:
            extracted_doc = rm_client.download_and_extract(doc_name, str(temp_dir))
        except RemarkableError as e:
            logger.error(f"Download failed: {e}")
            return stats

        current_page_count = extracted_doc.page_count
        stored_page_count = doc_record.page_count if doc_record else 0
        logger.info(f"Pages: {current_page_count} current, {stored_page_count} previously stored")

        # Update document record with new page count
        state_db.upsert_document(doc_id, doc_name, "/", doc_modified, current_page_count)

        # Force mode: convert and process all pages
        if force:
            logger.info("Force mode: converting all pages...")
            extracted_doc.convert_all_pages()
            changed_pages = list(range(current_page_count))
        else:
            changed_pages = []

            # Check for NEW pages (beyond stored count)
            if current_page_count > stored_page_count:
                new_page_nums = list(range(stored_page_count, current_page_count))
                logger.info(f"Found {len(new_page_nums)} new page(s): {[p+1 for p in new_page_nums]}")
                changed_pages.extend(new_page_nums)

            # Quick check: compare last stored page's hash
            if stored_page_count > 0:
                last_stored_page = stored_page_count - 1
                logger.info(f"Checking last stored page ({last_stored_page + 1}) for changes...")

                # Convert only the last stored page
                last_page_path = extracted_doc.convert_page(last_stored_page)
                if last_page_path:
                    stored_hash = state_db.get_page_hash(doc_id, last_stored_page)
                    current_hash = change_detector._compute_image_file_hash(last_page_path)

                    if stored_hash == current_hash:
                        logger.info("Last page unchanged - no edits to existing pages")
                    else:
                        logger.info("Last page changed - checking all existing pages...")
                        # Convert remaining existing pages and check for changes
                        for page_num in range(stored_page_count):
                            if page_num == last_stored_page:
                                # Already checked
                                if stored_hash != current_hash:
                                    changed_pages.append(page_num)
                            else:
                                page_path = extracted_doc.convert_page(page_num)
                                if page_path:
                                    stored = state_db.get_page_hash(doc_id, page_num)
                                    current = change_detector._compute_image_file_hash(page_path)
                                    if stored != current:
                                        changed_pages.append(page_num)

            # Convert new pages to PNG if not already converted
            for page_num in changed_pages:
                extracted_doc.convert_page(page_num)

        # Sort changed pages
        changed_pages = sorted(set(changed_pages))
        stats['pages_changed'] = len(changed_pages)
        logger.info(f"Found {len(changed_pages)} changed page(s)")

        if not changed_pages:
            logger.info("All pages already transcribed - no changes detected")
            state_db.mark_document_synced(doc_id)
            stats['success'] = True
            return stats

        # Build list of paths for changed pages only
        changed_page_paths = []
        for page_num in changed_pages:
            path = extracted_doc.convert_page(page_num)
            if path:
                changed_page_paths.append((page_num, path))

        logger.info(f"Transcribing {len(changed_page_paths)} page(s)...")

        # Transcribe each changed page individually
        transcriptions = {}
        for page_num, path in changed_page_paths:
            logger.info(f"  Transcribing page {page_num + 1}...")
            img = Image.open(path)
            transcriptions[page_num + 1] = transcriber._transcribe_single_image(img)
        stats['pages_processed'] = len(transcriptions)

        combined_text = "\n\n".join([f"--- Page {n} ---\n{t}" for n, t in sorted(transcriptions.items())])

        existing_context = ""
        if obsidian_writer.note_exists(doc_name):
            existing_context = obsidian_writer.read_existing_note(doc_name)[:2000]

        logger.info("Enriching content...")
        enriched = transcriber.enrich_content(combined_text, existing_context)

        if transferred_screenshots:
            embeds = "\n\n".join(f"![[{name}]]" for name in transferred_screenshots)
            screenshot_section = f"\n\n## Screenshots\n\n{embeds}\n"
            if "### 🧠 Gap Analysis" in enriched:
                enriched = enriched.replace("### 🧠 Gap Analysis", screenshot_section + "\n### 🧠 Gap Analysis", 1)
            else:
                enriched += screenshot_section

        logger.info("Updating Obsidian note...")
        today = datetime.now().strftime("%Y-%m-%d")
        if obsidian_writer.note_exists(doc_name):
            obsidian_writer.append_to_note(doc_name, enriched, today)
        else:
            obsidian_writer.create_note(doc_name, enriched)

        logger.info("Generating flashcards...")
        flashcards = transcriber.generate_flashcards(enriched)
        logger.info(f"Generated {len(flashcards)} flashcard(s)")

        if flashcards:
            deck_name = doc_record.anki_deck or doc_name.replace(" ", "_")
            cards_added = 0
            for question, answer in flashcards:
                card_id = anki_client.generate_card_id(question)
                if state_db.flashcard_exists(card_id):
                    continue
                tags = ["source:remarkable", f"notebook:{doc_name.replace(' ', '_')}", f"date:{today}"]
                anki_note_id = anki_client.add_card(deck_name, question, answer, tags)
                if anki_note_id:
                    state_db.record_flashcard(card_id, doc_id, question, answer, anki_note_id)
                    cards_added += 1
            stats['cards_created'] = cards_added
            logger.info(f"Added {cards_added} card(s) to Anki")

        # Update hashes for changed pages
        for page_num, path in changed_page_paths:
            new_hash = change_detector._compute_image_file_hash(path)
            state_db.set_page_hash(doc_id, page_num, new_hash)

        state_db.mark_document_synced(doc_id)
        stats['success'] = True
        logger.info(f"✓ Done: {stats['pages_processed']} pages, {stats['cards_created']} cards")

    except Exception as e:
        logger.error(f"✗ Error: {e}", exc_info=True)

    return stats


def run_sync(config: Dict, logger: logging.Logger, dry_run: bool = False,
             target_document: Optional[str] = None, force: bool = False,
             interactive: bool = False) -> bool:
    """Execute the main sync process."""
    temp_dir = None

    try:
        logger.info("\n" + "="*60 + "\nREMARKABLE SYNC\n" + "="*60)
        if dry_run: logger.info("⚠ DRY RUN MODE")
        if force: logger.info("⚡ FORCE MODE")
        if target_document: logger.info(f"🎯 TARGET: {target_document}")

        db_path = config.get('state', {}).get('db_path', 'state.db')

        with StateDB(db_path) as state_db:
            run_id = state_db.start_sync_run()
            logger.info(f"Sync run #{run_id}")

            last_sync = state_db.get_last_sync_time()
            if last_sync and not force:
                logger.info(f"Last sync: {datetime.fromtimestamp(last_sync).strftime('%Y-%m-%d %H:%M:%S')}")

            logger.info("\nInitializing clients...")
            sync_folder = config.get('remarkable', {}).get('sync_folder', '/')
            rm_client = RemarkableClient(sync_folder)
            change_detector = ChangeDetector(state_db)
            transcriber = Transcriber()
            vault_path = config.get('obsidian', {}).get('vault_path')
            obsidian_writer = ObsidianWriter(vault_path)
            anki_url = config.get('anki', {}).get('url', 'http://localhost:8765')
            anki_client = AnkiClient(anki_url)

            # Screenshots transfer
            transferred_screenshots = []
            screenshots_cfg = config.get('screenshots', {})
            if screenshots_cfg.get('enabled') and not dry_run:
                try:
                    transferred_screenshots = obsidian_writer.transfer_screenshots(
                        screenshots_cfg.get('source_dir', '~/Desktop'), datetime.now().date())
                    if transferred_screenshots:
                        logger.info(f"Transferred {len(transferred_screenshots)} screenshot(s)")
                except Exception as e:
                    logger.warning(f"Screenshot transfer failed: {e}")

            logger.info("\nFetching documents...")
            try:
                all_docs = rm_client.list_documents()
                logger.info(f"Found {len(all_docs)} document(s)")
            except RemarkableError as e:
                logger.error(f"Failed to list: {e}")
                return False

            docs_to_process = []
            if target_document:
                docs_to_process = [d for d in all_docs if d.name == target_document]
                if not docs_to_process:
                    logger.error(f"Document '{target_document}' not found")
                    return False
            else:
                today_ts = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
                logger.info(f"Checking for docs modified today...")
                todays_docs = rm_client.filter_modified_since(all_docs, today_ts)
                logger.info(f"Found {len(todays_docs)} doc(s) modified today")

                if todays_docs and interactive and not dry_run:
                    docs_to_process = prompt_document_selection(todays_docs, logger)
                else:
                    docs_to_process = todays_docs

            if not docs_to_process:
                logger.info("\n✓ No documents to process")
                state_db.complete_sync_run(run_id, 0, 0, 0, "success")
                return True

            temp_dir = Path(tempfile.mkdtemp(prefix='remarkable_sync_'))

            totals = {'docs': 0, 'succeeded': 0, 'pages': 0, 'cards': 0}
            for doc in docs_to_process:
                stats = process_document(
                    doc.name, doc.id, doc.modified_timestamp,
                    rm_client, change_detector, transcriber, obsidian_writer,
                    anki_client, state_db, temp_dir, logger, dry_run, force, transferred_screenshots)
                totals['docs'] += 1
                if stats['success']: totals['succeeded'] += 1
                totals['pages'] += stats['pages_processed']
                totals['cards'] += stats['cards_created']

            if not dry_run:
                status = "success" if totals['succeeded'] == totals['docs'] else "partial"
                state_db.complete_sync_run(run_id, totals['succeeded'], totals['pages'], totals['cards'], status)

            logger.info(f"\n{'='*60}\nSUMMARY: {totals['docs']} docs, {totals['pages']} pages, {totals['cards']} cards\n{'='*60}")
            return totals['succeeded'] == totals['docs']

    except KeyboardInterrupt:
        logger.info("\n⚠ Interrupted")
        return False
    except Exception as e:
        logger.error(f"✗ Fatal: {e}", exc_info=True)
        return False
    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def refresh_hashes(doc_name: str, config: Dict, logger: logging.Logger) -> bool:
    """Update page hashes without transcribing (useful after changing image settings)."""
    logger.info(f"\n{'='*60}\nREFRESHING HASHES: {doc_name}\n{'='*60}")

    try:
        sync_folder = config.get('remarkable', {}).get('sync_folder', '/')
        db_path = config.get('state', {}).get('db_path', 'state.db')

        rm_client = RemarkableClient(sync_folder)
        temp_dir = Path(tempfile.mkdtemp(prefix='remarkable_hash_'))

        logger.info("Downloading and converting to images...")
        images = rm_client.download_document_images(doc_name, str(temp_dir))
        logger.info(f"Converted {len(images)} pages")

        with StateDB(db_path) as db:
            detector = ChangeDetector(db)
            detector.update_image_hashes(doc_name, images)
            logger.info(f"✓ Updated hashes for {len(images)} pages")

        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info("Done! Hashes updated, no transcription performed.")
        return True

    except Exception as e:
        logger.error(f"✗ Failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Sync Remarkable to Obsidian and Anki')
    parser.add_argument('--config', default='config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    parser.add_argument('--document', metavar='NAME', help='Process specific notebook')
    parser.add_argument('--force', action='store_true', help='Process all pages')
    parser.add_argument('-i', '--interactive', action='store_true', help='Select documents interactively')
    parser.add_argument('--refresh-hashes', action='store_true', help='Update hashes without transcribing (requires --document)')
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        log_level = config.get('logging', {}).get('level', 'INFO')
        log_dir = config.get('logging', {}).get('log_dir', 'logs')
        logger = setup_logging(log_level, log_dir)

        if args.refresh_hashes:
            if not args.document:
                print("ERROR: --refresh-hashes requires --document", file=sys.stderr)
                sys.exit(1)
            success = refresh_hashes(args.document, config, logger)
        else:
            success = run_sync(config, logger, args.dry_run, args.document, args.force, args.interactive)
        sys.exit(0 if success else 1)

    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

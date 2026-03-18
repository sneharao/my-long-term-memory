#!/usr/bin/env python3
"""
Convert Obsidian notes to Anki flashcards.

This script reads an existing Obsidian note, extracts flashcards from its content
using AI, and adds them to Anki with automatic deduplication.

Usage:
    uv run obsidian_to_anki.py "Note Name"
    uv run obsidian_to_anki.py "Note Name" --deck "Custom Deck"
    uv run obsidian_to_anki.py --interactive
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from lib.obsidian import ObsidianWriter
from lib.transcriber import Transcriber
from lib.anki import AnkiClient


def load_config(config_path: str = 'config.yaml') -> dict:
    """Load configuration from YAML file."""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with open(config_file, 'r') as f:
        return yaml.safe_load(f)


def convert_note_to_anki(
    note_name: str,
    config: dict,
    deck_name: Optional[str] = None
) -> tuple[int, int]:
    """
    Convert an Obsidian note to Anki flashcards.

    Args:
        note_name: Name of the Obsidian note (without .md extension)
        config: Configuration dictionary from config.yaml
        deck_name: Optional custom deck name. If None, uses note name

    Returns:
        Tuple of (cards_generated, cards_added)
    """
    # Initialize clients
    vault_path = config['obsidian']['vault_path']
    obsidian_writer = ObsidianWriter(vault_path)
    transcriber = Transcriber()  # Uses default 'config.yaml'
    anki_client = AnkiClient(config['anki']['url'])

    # Read the note
    print(f"\n📖 Reading note: {note_name}")
    try:
        content = obsidian_writer.read_existing_note(note_name)
    except FileNotFoundError:
        print(f"❌ Error: Note '{note_name}' not found in vault")
        print(f"   Vault path: {vault_path}")
        return 0, 0

    if not content.strip():
        print(f"⚠️  Warning: Note '{note_name}' is empty")
        return 0, 0

    print(f"✓ Note loaded ({len(content)} characters)")

    # Generate flashcards from content
    print(f"\n🤖 Generating flashcards using AI...")
    flashcards = transcriber.generate_flashcards(content)

    if not flashcards:
        print("⚠️  No flashcards generated from note content")
        return 0, 0

    # Determine deck name
    if deck_name is None:
        deck_name = note_name

    # Add flashcards to Anki
    print(f"\n📇 Adding {len(flashcards)} flashcard(s) to Anki deck: {deck_name}")

    cards_added = 0
    today = datetime.now().strftime('%Y-%m-%d')

    for idx, (question, answer) in enumerate(flashcards, 1):
        print(f"   [{idx}/{len(flashcards)}] ", end='', flush=True)

        tags = [
            "source:obsidian",
            f"note:{note_name.replace(' ', '_')}",
            f"date:{today}"
        ]

        try:
            note_id = anki_client.add_card(deck_name, question, answer, tags)
            if note_id:
                cards_added += 1
                print("✓ Added")
            else:
                print("⊘ Skipped (duplicate)")
        except Exception as e:
            print(f"✗ Failed: {e}")

    print(f"\n✅ Complete: {cards_added}/{len(flashcards)} cards added to Anki")
    print(f"   Deck: {deck_name}")
    print(f"   Duplicates skipped: {len(flashcards) - cards_added}")

    return len(flashcards), cards_added


def list_available_notes(vault_path: str) -> list[str]:
    """List all markdown notes in the Obsidian vault."""
    vault = Path(vault_path)
    if not vault.exists():
        return []

    notes = []
    for md_file in sorted(vault.glob("*.md")):
        # Get note name without .md extension
        notes.append(md_file.stem)

    return notes


def interactive_mode(config: dict) -> None:
    """Interactive mode to select a note and convert it."""
    vault_path = config['obsidian']['vault_path']
    notes = list_available_notes(vault_path)

    if not notes:
        print(f"❌ No notes found in vault: {vault_path}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("AVAILABLE OBSIDIAN NOTES")
    print("=" * 60)

    for idx, note in enumerate(notes, 1):
        print(f"  {idx}. {note}")

    print(f"\n  Total: {len(notes)} notes")
    print("=" * 60)

    while True:
        try:
            choice = input("\nEnter note number (or Q to quit): ").strip()

            if choice.upper() == 'Q':
                print("Cancelled")
                sys.exit(0)

            idx = int(choice)
            if 1 <= idx <= len(notes):
                note_name = notes[idx - 1]
                break
            else:
                print(f"Invalid choice. Enter 1-{len(notes)}")
        except ValueError:
            print("Invalid input. Enter a number or Q")

    # Optional: ask for custom deck name
    deck_input = input(f"\nDeck name (press Enter to use '{note_name}'): ").strip()
    deck_name = deck_input if deck_input else None

    convert_note_to_anki(note_name, config, deck_name)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Convert Obsidian notes to Anki flashcards',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run obsidian_to_anki.py "AWS Cloud Practitioner"
  uv run obsidian_to_anki.py "Design Patterns" --deck "Learning::Design Patterns"
  uv run obsidian_to_anki.py --interactive
        """
    )
    parser.add_argument(
        'note_name',
        nargs='?',
        help='Name of the Obsidian note (without .md extension)'
    )
    parser.add_argument(
        '--deck',
        help='Custom Anki deck name (default: use note name)'
    )
    parser.add_argument(
        '-i', '--interactive',
        action='store_true',
        help='Interactive mode to select a note'
    )
    parser.add_argument(
        '--config',
        default='config.yaml',
        help='Config file path (default: config.yaml)'
    )

    args = parser.parse_args()

    try:
        # Load configuration
        config = load_config(args.config)

        if args.interactive:
            interactive_mode(config)
        elif args.note_name:
            convert_note_to_anki(args.note_name, config, args.deck)
        else:
            parser.print_help()
            sys.exit(1)

    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

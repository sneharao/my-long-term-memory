import os, time
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from lib.transcriber import Transcriber
from lib.anki import AnkiClient

# --- 1. CONFIGURATION ---
import yaml

with open("config.yaml", 'r') as f:
    config = yaml.safe_load(f)

OBSIDIAN_VAULT = config['obsidian']['vault_path']
INBOX_FOLDER = "/Users/spidugu/Documents/Notes"  # TODO: Add to config.yaml
DECK_NAME = "AWS_CLOUD"  # TODO: Make configurable

# Initialize clients
transcriber = Transcriber()  # Handles all AI operations
anki_client = AnkiClient(config['anki']['url'])  # Handles Anki sync


def process_new_pdf(pdf_path):
    print(f"🚀 New file detected: {pdf_path}. Starting AI processing...")
    try:
        # STEP 1: Transcribe all pages
        transcriptions = transcriber.transcribe_pages(pdf_path)
        full_transcription = "\n\n".join(
            f"--- Page {page_num} ---\n{text}"
            for page_num, text in transcriptions.items()
        )

        # STEP 2: Enrich content with gap analysis
        final_notes = transcriber.enrich_content(full_transcription)

        # STEP 3: Save to Obsidian
        out_name = os.path.basename(pdf_path).replace(".pdf", ".md")
        with open(os.path.join(OBSIDIAN_VAULT, out_name), "w", encoding="utf-8") as f:
            f.write(final_notes)
        print(f"✅ Note saved to Obsidian: {out_name}")

        # STEP 4: Generate flashcards (uses existing Transcriber logic)
        flashcards = transcriber.generate_flashcards(final_notes)

        # STEP 5: Sync to Anki (uses existing AnkiClient logic)
        print(f"\n📇 Adding {len(flashcards)} flashcard(s) to Anki deck: {DECK_NAME}")
        cards_added = 0
        today = datetime.now().strftime('%Y-%m-%d')

        for idx, (question, answer) in enumerate(flashcards, 1):
            print(f"   [{idx}/{len(flashcards)}] ", end='', flush=True)

            tags = [
                "source:automate",
                f"note:{out_name.replace('.md', '').replace(' ', '_')}",
                f"date:{today}"
            ]

            try:
                note_id = anki_client.add_card(DECK_NAME, question, answer, tags)
                if note_id:
                    cards_added += 1
                    print("✓")
                else:
                    print("⊘ duplicate")
            except Exception as e:
                print(f"✗ {e}")

        print(f"\n✅ Complete: {cards_added}/{len(flashcards)} cards added to Anki")
    except Exception as e:
        print(f"❌ Error: {e}")

# --- WATCHDOG LOGIC ---
class MyHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".pdf"):
            # Give the file a second to finish saving/copying
            time.sleep(2) 
            process_new_pdf(event.src_path)

if __name__ == "__main__":
    event_handler = MyHandler()
    observer = Observer()
    observer.schedule(event_handler, INBOX_FOLDER, recursive=False)
    
    print(f"👀 Monitoring {INBOX_FOLDER}... Drop a PDF to begin.")
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
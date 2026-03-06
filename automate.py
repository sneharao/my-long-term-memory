import os, time
import fitz  # PyMuPDF
from google.oauth2 import service_account
from google import genai
from google.genai import types
from PIL import Image
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- 1. CONFIGURATION ---
PROJECT_ID = "restro-479123" # Found on your Google Cloud Dashboard
LOCATION = "europe-west4"            # Gemini 3 models use the 'global' endpoint
OBSIDIAN_VAULT = "/Users/spidugu/Documents/Obsidian Vault"
ANKI_URL = "http://localhost:8765"
INBOX_FOLDER = "/Users/spidugu/Documents/Notes"
KEY_PATH = "restro-479123-a894c6caee74.json"  # Path to your service account key file
DECK_NAME = "AWS_CLOUD"

# Create the Credentials
creds = service_account.Credentials.from_service_account_file(
    KEY_PATH, 
    scopes=['https://www.googleapis.com/auth/cloud-platform']
)
# Initialize AI Client
client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION, credentials=creds)


def process_new_pdf(pdf_path):
    print(f"🚀 New file detected: {pdf_path}. Starting AI processing...")
    try:
        doc = fitz.open(pdf_path)
        full_transcription = ""
    
        # STEP 1: Transcribe all pages into one block of text
        for i, page in enumerate(doc):
            print(f"  📄 Transcribing page {i+1}...")
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Simple transcription prompt per page (Cheap & Fast)
            res = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=["Act as a Senior AWS expert helping thousands of students learn AWS. Understand and Transcribe this handwritten page exactly.", img]
            )
            full_transcription += f"--- Page {i+1} ---\n{res.text}\n\n"

        # STEP 2: One Single "Brain" Call for Gap Analysis
        print("🧠 Performing Final Gap Analysis...")
        final_prompt = f"""
        Act as a Senior AWS expert helping thousands of students learn AWS and clear certificate exams. You help them to remember concepts, facts and ideas from the notes.
        Here are my notes from a full document:
    #
        {full_transcription}
    
        1. Organize this into a structured Markdown document.
        2. Use your own knowledge of the concept ideas or facts identified from the document 
        to flesh out any additional details or if something I missed in my notes to ensure my notes are self-contained.
        3. You can also add diagrams or tables if you think it will help explain the concepts better. You can create diagrams using Mermaid syntax.
        4. Add one '### 🧠 AI Gap Analysis' section at the very end.
        Compare the FULL content above to industry standards and list unique concepts I missed.
        """
        
        notes_res = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[final_prompt],
            config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=2048, include_thoughts=True)
            )
        )

        final_notes = notes_res.text

        # STEP 3: Save to Obsidian
        out_name = os.path.basename(pdf_path).replace(".pdf", ".md")
        with open(os.path.join(OBSIDIAN_VAULT, out_name), "w", encoding="utf-8") as f:
            f.write(final_notes)
            print(f"✅ Finished! Note saved to Obsidian..")


        # STEP 4: Smart Anki Sync with Error Logging
        print(f"📚 Generating flashcards and syncing to Anki...")
        flash_card_prompt = f"""
        You are a world class Anki flashcard generator. You help students remember concepts, facts and ideas from the notes.
        Here are my notes from a full document:
        
        {final_notes}
    
        1. Identify key high level concepts and ideas presented.
        2. Make unique flashcards covering the important concepts in the whole document. Keep questions and answers roughly in same order as
          they appear in the notes.
        Format: FLASHCARD: Question :: Answer
        """
        final_res = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[flash_card_prompt],
            config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=2048, include_thoughts=True)
            )
        )
        print(f"📚 Generated question now syncing to Anki...")

        cards_added = 0
        for line in final_res.text.split("\n"):
            if "FLASHCARD:" in line and "::" in line:
                # Strip the prefix and split
                clean_line = line.replace("FLASHCARD:", "").strip()
                q, a = clean_line.split("::", 1)
                
                payload = {
                    "action": "addNote", "version": 6,
                    "params": {
                        "note": {
                            "deckName": DECK_NAME, "modelName": "Basic", 
                            "fields": {"Front": q.strip(), "Back": a.strip()}
                        }
                    }
                }
                resp = requests.post(ANKI_URL, json=payload).json()
                
                if resp.get("error"):
                    print(f"❌ Anki Error: {resp['error']} (Card: {q[:20]}...)")
                else:
                    cards_added += 1
                    
                print(f"✅ Finished! Note saved. {cards_added} cards added to Anki.")
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
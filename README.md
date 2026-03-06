# Remarkable Cloud to Obsidian + Anki Sync Pipeline

An automated daily sync system that transforms your Remarkable tablet handwritten notes into structured Obsidian knowledge base and Anki flashcards.

## Features

- **Automatic Daily Sync**: Runs at 8 PM daily via macOS launchd
- **Incremental Processing**: Only processes pages that have changed (saves API costs)
- **Smart Appending**: Appends to existing notes instead of creating duplicates
- **Flashcard Deduplication**: Prevents duplicate Anki cards using content hashing
- **AI-Powered Transcription**: Uses Google Gemini 2.5 Flash for handwriting recognition
- **Gap Analysis**: AI enriches notes with missing concepts and structured formatting

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              REMARKABLE SYNC PIPELINE                            │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Remarkable  │───▶│   Download   │───▶│   Convert    │───▶│    Hash      │
│    Cloud     │    │   .rmdoc     │    │  .rm → PNG   │    │   Compare    │
│   (rmapi)    │    │   (zip)      │    │ (rmc+cairo)  │    │   (SHA256)   │
└──────────────┘    └──────────────┘    └──────────────┘    └──────┬───────┘
                                                                   │
                                              Changed pages only   │
                                        ┌──────────────────────────┘
                                        ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Obsidian   │◀───│    Enrich    │◀───│  Transcribe  │◀───│  PNG Images  │
│    Vault     │    │ (Gap Analysis│    │   (Gemini    │    │ (3x scale,   │
│  (append)    │    │  + Structure)│    │   2.5 Flash) │    │ white bg)    │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
       │
       │            ┌──────────────┐    ┌──────────────┐
       └───────────▶│  Generate    │───▶│    Anki      │
                    │  Flashcards  │    │  (dedupe via │
                    │              │    │   MD5 hash)  │
                    └──────────────┘    └──────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│  SQLite State DB: tracks documents, page hashes, flashcards, sync runs          │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Download**: `rmapi get` fetches `.rmdoc` (zip archive) from Remarkable Cloud
2. **Extract**: Unzip to get `.rm` binary files (one per page)
3. **Convert**: `rmc` → SVG → `cairosvg` → PNG (3x scale, white background)
4. **Hash**: SHA256 compare with stored hashes to detect changed pages
5. **Transcribe**: Only changed pages sent to Gemini 2.5 Flash
6. **Enrich**: AI structures content, adds tables, diagrams, gap analysis
7. **Obsidian**: Append to existing note with session marker, or create new
8. **Anki**: Generate flashcards, dedupe via MD5 hash of question text

## Project Structure

```
my-long-term-memory/
├── remarkable_sync.py               # Main orchestrator
├── automate.py                      # Legacy manual PDF drop workflow
├── config.yaml                      # Configuration settings
├── com.spidugu.remarkable-sync.plist # macOS launchd schedule
├── lib/
│   ├── __init__.py
│   ├── state.py                     # SQLite state management
│   ├── remarkable.py                # rmapi wrapper + .rm to PNG conversion
│   ├── change_detector.py           # Page-level SHA256 hashing
│   ├── transcriber.py               # Gemini transcription & enrichment
│   ├── obsidian.py                  # Note read/append logic
│   └── anki.py                      # AnkiConnect integration
├── logs/                            # Sync logs
└── state.db                         # SQLite database (created on first run)
```

## Prerequisites

### 1. Google Cloud Platform Setup

You need a GCP project with Vertex AI enabled:

1. Create a GCP project
2. Enable the Vertex AI API
3. Create a service account with Vertex AI permissions
4. Download the service account JSON key
5. Update `config.yaml` with your project details

### 2. Install rmapi (Remarkable Cloud CLI)

Download from GitHub releases (homebrew tap is outdated):

```bash
# Download from https://github.com/ddvk/rmapi/releases
# Extract and move to /usr/local/bin
sudo mv rmapi /usr/local/bin/
```

### 3. Authenticate with Remarkable Cloud

```bash
rmapi
# Follow the device code authentication at https://my.remarkable.com/device/browser/connect
# Tokens are stored in ~/.rmapi
```

### 4. Install System Dependencies

```bash
# Cairo library (required for SVG to PNG conversion)
brew install cairo
```

### 5. Install Python Dependencies

```bash
uv pip install pyyaml rmc cairosvg
```

### 6. Anki Setup

1. Install [Anki](https://apps.ankiweb.net/)
2. Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) plugin
3. Ensure Anki is running when sync executes

## Configuration

Edit `config.yaml` to match your setup:

```yaml
remarkable:
  sync_folder: "/"  # Root level - all notebooks at root

obsidian:
  vault_path: "/Users/spidugu/Documents/Obsidian Vault"
  append_marker: "\n\n---\n## Session: {date}\n\n"

anki:
  url: "http://localhost:8765"
  deck_prefix: ""  # No prefix, use notebook name directly
  model_name: "Basic"

ai:
  project_id: "your-gcp-project-id"
  location: "europe-west4"
  model: "gemini-2.5-flash"
  key_path: "your-service-account-key.json"
  thinking_budget: 2048

schedule:
  time: "20:00"
  timezone: "Europe/London"

state:
  db_path: "state.db"

logging:
  level: "INFO"
  log_dir: "logs"
```

## Usage

### Manual Sync

```bash
# Set library path for cairo (add to ~/.zshrc for permanent use)
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/opt/cairo/lib

# Dry run - see what would be processed
uv run remarkable_sync.py --dry-run

# Sync a specific notebook
uv run remarkable_sync.py --document "Design Patterns"

# Force full sync (ignore change detection)
uv run remarkable_sync.py --document "Design Patterns" --force

# Normal sync (only changed documents/pages)
uv run remarkable_sync.py
```

### Scheduled Sync (Daily at 8 PM)

**Install the launchd job:**

```bash
cp com.spidugu.remarkable-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.spidugu.remarkable-sync.plist
```

**Check status:**

```bash
launchctl list | grep remarkable
```

**View logs:**

```bash
tail -f logs/sync.log
```

**Disable scheduled sync:**

```bash
launchctl unload ~/Library/LaunchAgents/com.spidugu.remarkable-sync.plist
```

## How It Works

### 1. Document Discovery & Selection
- Connects to Remarkable Cloud via `rmapi`
- Lists all notebooks at root level
- Filters to documents modified **today** (since midnight)
- In interactive mode (`-i`), prompts user to select which notebooks to sync
- Only selected notebooks are downloaded and processed (not all 31+)

### 2. Download & Convert (per notebook)
- Downloads `.rmdoc` file for each selected notebook (one at a time)
- Each `.rmdoc` is a zip archive containing all pages of that single notebook
- Extracts `.rm` files (one per page)
- Converts each `.rm` → SVG (`rmc`) → PNG (`cairosvg`, 3x scale, white background)

### 3. Change Detection
- Computes SHA256 hash of each PNG image
- Compares with stored hashes from previous sync
- Only changed pages are sent for transcription

### 4. Transcription & Enrichment
- Changed pages (as PNG images) sent to Gemini 2.5 Flash
- AI transcribes handwritten content
- Performs gap analysis and structures content
- Adds diagrams and tables where helpful

### 5. Obsidian Integration
- **First sync**: Creates new note with document name
- **Subsequent syncs**: Appends with session marker:
  ```markdown
  ---

### 6. Anki Flashcard Generation
- Generates flashcards from enriched content
- Creates MD5 hash of each question for deduplication
- Adds cards with tags: `source:remarkable`, `notebook:name`, `date:YYYY-MM-DD`
- Skips cards that already exist

### 7. State Management
- SQLite database tracks:
  - Documents and their sync status
  - Page content hashes (for incremental sync)
  - Generated flashcards (for deduplication)
  - Sync run history

## Challenges & Solutions

### 1. Remarkable Cloud API Access

| Challenge | Solution |
|-----------|----------|
| No official Remarkable API | Used `rmapi` - unofficial CLI tool that reverse-engineers the Cloud API |
| `rmapi` not in Homebrew | Downloaded binary directly from GitHub releases |
| `rmapi ls --json` flag not supported | Parsed plain text output format `[f] DocumentName` instead |

### 2. Document Format Conversion

| Challenge | Solution |
|-----------|----------|
| `rmapi geta` (PDF export) fails for native notebooks | Error: "archive does not contain a unique pagedata file" |
| `rmapi get` downloads `.rmdoc` (not PDF) | Extract zip and convert `.rm` files manually |
| `.rm` files are proprietary binary format | Used `rmc` Python library to parse and convert to SVG |
| Need PNG images for Gemini | Used `cairosvg` to convert SVG → PNG |

### 3. System Dependencies

| Challenge | Solution |
|-----------|----------|
| `cairosvg` requires Cairo C library | `brew install cairo` |
| Python can't find Cairo library | Set `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/opt/cairo/lib` |
| `rm2pdf` Go tool had "result too large" error | Switched to Python-based `rmc` + `cairosvg` approach |
| `rmrl` Python library failed to install | Dependency `reportlab 3.6.13` incompatible with Python 3.13 |

### 4. Remarkable Format Compatibility

| Challenge | Solution |
|-----------|----------|
| Newer `.rm` format (v6) not fully supported | `rmc` library handles most cases with warnings |
| Highlighter color ID 9 not in palette | Added try/except to skip pages with unsupported features |
| Deleted pages still in metadata | Check if `.rm` file exists before processing |
| Page count mismatch (metadata vs actual files) | Use actual converted images count, not metadata |

### 5. State Management

| Challenge | Solution |
|-----------|----------|
| Need incremental sync (not reprocess everything) | SHA256 hash each page image, store in SQLite |
| Flashcard deduplication across runs | MD5 hash of question text as unique ID |
| Track sync history for debugging | `sync_runs` table with timestamps and stats |

### 6. AI Transcription

| Challenge | Solution |
|-----------|----------|
| PNG images had transparent background (RGBA) | Gemini reported text as "very faded and difficult to read" |
| Transcription returned completely unrelated content | Added white background to PNG conversion using PIL |
| `rmc` + `cairosvg` outputs transparent PNGs | Composite RGBA image onto white RGB background before saving |

## Known Limitations

- **Highlighter colors**: Some newer highlighter colors (e.g., color ID 9) are not supported by the `rmc` library. Pages using these will be skipped with a warning.
- **Deleted pages**: Pages deleted on Remarkable may still appear in metadata but won't have .rm files.
- **Format warnings**: You may see "Some data has not been read" warnings - this is normal for newer Remarkable formats.

## Troubleshooting

### Cairo library not found

```bash
# Set the library path
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/opt/cairo/lib

# Or add to ~/.zshrc for permanent fix
echo 'export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/opt/cairo/lib' >> ~/.zshrc
```

### rmapi authentication issues

```bash
# Re-authenticate
rm ~/.rmapi
rmapi
```

### Anki connection refused

Ensure Anki is running and AnkiConnect plugin is installed.

### Page conversion failed

Some pages may use features not yet supported by the `rmc` library. These pages are skipped automatically.

### View recent sync runs

```python
from lib.state import StateDB
with StateDB("state.db") as db:
    for run in db.get_recent_sync_runs(5):
        print(f"Run {run.id}: {run.status} - {run.documents_processed} docs, {run.cards_added} cards")
```

### Reset and start fresh

```bash
rm state.db
uv run remarkable_sync.py --force
```

## Legacy Workflow

The original `automate.py` still works for manual PDF drops:

```bash
uv run automate.py
# Monitors ~/Documents/Notes for new PDFs
# Drop a PDF to trigger processing
```

## License

MIT

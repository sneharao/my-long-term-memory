# 📑 Project Retrospective: Handwritten AI Study Pipeline

**Date:** February 2026

**Stack:** Python (`uv`), Vertex AI (Gemini 2.5/3), Obsidian, Anki

## 🚀 Executive Summary

We successfully built an automated pipeline that monitors a local directory for handwritten PDFs, uses Multimodal LLMs to transcribe and analyze them, and synchronizes the output into a digital knowledge base (Obsidian) and a spaced-repetition system (Anki).

## 🛠 Technical Challenges & Solutions

### 1. Authentication & Infrastructure (The "Handshake")

| Challenge                         | Technical Root Cause                                                  | Resolution Strategy                                                                     |
| --------------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| **Default Credentials Not Found** | Lack of local Application Default Credentials (ADC) to use VertexAPI. | Created a dedicated **GCP Service Account** and used a JSON key file for explicit auth. |
| **Invalid OAuth Scope**           | Service account lacked a defined "access visa" for Vertex AI.         | Added `scopes=['.../auth/cloud-platform']` to the credential object.                    |
| **API Disabled (403)**            | Vertex AI API was not toggled "ON" in the specific Project ID.        | Enabled the **AI Platform API** via the GCP Console.                                    |

### 2. Model Logic & Regionality

| Challenge                    | Technical Root Cause                                                | Resolution Strategy                                                                     |
| ---------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| **Model Not Found (404)**    | Gemini 3 Preview is only accessible via the `global` endpoint.      | Switched to **Gemini 2.5 Flash** for stable deployment in the `europe-west4` region.    |
| **Thinking Config Error**    | `thinking_level` is a Gemini 3 feature; 2.5 uses `thinking_budget`. | Replaced level-based config with a numerical **Token Budget** (2048).                   |
| **Resource Exhausted (429)** | High traffic on the shared global endpoint.                         | Switched to a regional EU endpoint and implemented **Exponential Backoff** retry logic. |

### 3. Data Integrity & Context

| Challenge                | Technical Root Cause                                           | Resolution Strategy                                                                               |
| ------------------------ | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| **Fragmented Gaps**      | AI analyzed pages individually, missing the "Big Picture."     | **Batch Processing:** Transcribed all pages first, then ran one final analysis on the total text. |
| **Duplicate Flashcards** | Page-by-page generation led to repeated concepts.              | Updated the prompt to generate **5 Unique Cards** based on the entire document context.           |
| **Anki Sync Failure**    | Silent failure due to missing deck or ambiguous text patterns. | Added **JSON response logging** and a specific `FLASHCARD:` string prefix for parsing.            |

## 🎨 Diagram Strategy (The Next Evolution)

To solve the "missing sketches" issue, we moved from a **Text-Only** model to a **Multimodal Asset Pipeline**:

- **Input:** Multi-page PDF.
- **Extraction:** `PyMuPDF` renders pages to high-res JPEGs.
- **Storage:** JPEGs are moved to Obsidian's `/attachments` folder.
- **Linking:** Markdown files use `![[]]` embeds to display original sketches alongside AI analysis.

## 💡 Key Lessons

1. **Explicit > Implicit:** Always define your API scopes and regions explicitly to avoid environment-specific bugs.
2. **Context is King:** The more information you can provide the AI at once (Full PDF text), the more accurate its "Gap Analysis" becomes.
3. **Fail Gracefully:** Use `try-except` blocks with `time.sleep()` to handle 429 errors without crashing the entire watchdog.

### Final Next Step

**Would you like me to generate a "Maintenance Script" that automatically cleans up your Inbox and archives processed PDFs once they are successfully synced to Anki?**

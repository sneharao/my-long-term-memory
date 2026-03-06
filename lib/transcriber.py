"""Transcriber Module - Gemini-powered transcription, enrichment, and flashcard generation."""

import os
import yaml
import fitz
from google.oauth2 import service_account
from google import genai
from google.genai import types
from PIL import Image
from typing import Dict, List, Tuple, Optional


class Transcriber:
    """Handles transcription, enrichment, and flashcard generation using Vertex AI."""

    TRANSCRIPTION_PROMPT = """You are an expert at reading handwritten notes. Transcribe ALL content:

1. **Text**: Every word exactly as written, including abbreviations and symbols.
2. **Structure**: Preserve bullet points, numbered lists, indentation, arrows (→), hierarchies.
3. **Diagrams**: Describe diagrams/flowcharts in [brackets].
4. **Symbols**: Include math symbols, checkboxes, stars, underlines.
5. **Connections**: Note arrows and lines connecting concepts.

Mark uncertain words with [?]."""

    def __init__(self, config_path: str = "config.yaml"):
        """Initialize with Vertex AI credentials from config.yaml."""
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        ai_config = config.get('ai', {})
        self.project_id = ai_config.get('project_id')
        self.location = ai_config.get('location')
        self.model = ai_config.get('model', 'gemini-2.5-flash')
        self.thinking_budget = ai_config.get('thinking_budget', 2048)
        key_path = ai_config.get('key_path')

        if not all([self.project_id, self.location, key_path]):
            raise ValueError("Missing required AI configuration in config.yaml")

        creds = service_account.Credentials.from_service_account_file(
            key_path, scopes=['https://www.googleapis.com/auth/cloud-platform']
        )

        self.client = genai.Client(
            vertexai=True,
            project=self.project_id,
            location=self.location,
            credentials=creds
        )
        print(f"✓ Transcriber initialized with model: {self.model}")

    def _transcribe_single_image(self, img: Image.Image) -> str:
        """Send image to Gemini for transcription."""
        response = self.client.models.generate_content(
            model=self.model,
            contents=[self.TRANSCRIPTION_PROMPT, img]
        )
        return response.text

    def transcribe_images(self, image_paths: List[str], page_numbers: Optional[List[int]] = None) -> Dict[int, str]:
        """Transcribe PNG/JPG images. Returns {page_num: text}."""
        transcriptions = {}
        pages = page_numbers or range(1, len(image_paths) + 1)

        for page_num in pages:
            idx = page_num - 1
            if idx < 0 or idx >= len(image_paths):
                print(f"⚠ Page {page_num} out of range, skipping...")
                continue

            print(f"  📄 Transcribing page {page_num}...")
            img = Image.open(image_paths[idx])
            transcriptions[page_num] = self._transcribe_single_image(img)

        print(f"✓ Transcribed {len(transcriptions)} page(s)")
        return transcriptions

    def transcribe_pages(self, pdf_path: str, page_numbers: Optional[List[int]] = None) -> Dict[int, str]:
        """Transcribe PDF pages. Returns {page_num: text}."""
        doc = fitz.open(pdf_path)
        transcriptions = {}
        pages = page_numbers or range(1, len(doc) + 1)

        for page_num in pages:
            idx = page_num - 1
            if idx < 0 or idx >= len(doc):
                print(f"⚠ Page {page_num} out of range, skipping...")
                continue

            print(f"  📄 Transcribing page {page_num}...")
            page = doc[idx]
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            transcriptions[page_num] = self._transcribe_single_image(img)

        doc.close()
        print(f"✓ Transcribed {len(transcriptions)} page(s)")
        return transcriptions

    def enrich_content(self, transcription: str, existing_context: str = "") -> str:
        """Enrich transcription with structure, explanations, and gap analysis."""
        print("🧠 Performing Gap Analysis and Content Enrichment...")

        context_section = f"\nEXISTING CONTEXT:\n{existing_context}\n" if existing_context else ""

        prompt = f"""You are an expert teacher with deep knowledge in:
- **AI/ML**: LLMs, AI Agents, RAG, Prompt Engineering
- **AWS**: Cloud services, certifications (SA, Cloud Practitioner)
- **Software Architecture**: Design patterns, microservices, system design
- **German Language**: Grammar, vocabulary, Goethe/TestDaF prep
{context_section}
Handwritten notes:

{transcription}

Transform into exam-ready study material:

1. **Structure**: Clear Markdown with headings, bullets, logical flow.
2. **Expand**: Elaborate abbreviations, add context, examples, grammar rules.
3. **Visuals**: Tables for comparisons, Mermaid diagrams for architectures.
4. **Tips**: Exam tips, real-world applications, interview points.
5. **Gap Analysis** (`### 🧠 Gap Analysis`): Missing concepts, next topics, prerequisites.

Output clean Markdown for Obsidian."""

        response = self.client.models.generate_content(
            model=self.model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_budget=self.thinking_budget,
                    include_thoughts=True
                )
            )
        )
        print("✓ Content enrichment complete")
        return response.text

    def generate_flashcards(self, content: str) -> List[Tuple[str, str]]:
        """Generate Anki flashcards from content. Returns [(question, answer)]."""
        print("📚 Generating flashcards...")

        prompt = f"""Create Anki flashcards from these notes:

{content}

Instructions:
1. Identify key concepts, facts, and ideas.
2. Create clear, specific flashcards.
3. Keep order consistent with notes.

Format: FLASHCARD: Question :: Answer"""

        response = self.client.models.generate_content(
            model=self.model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_budget=self.thinking_budget,
                    include_thoughts=True
                )
            )
        )

        flashcards = []
        for line in response.text.split("\n"):
            if "FLASHCARD:" in line and "::" in line:
                parts = line.replace("FLASHCARD:", "").strip().split("::", 1)
                if len(parts) == 2:
                    flashcards.append((parts[0].strip(), parts[1].strip()))

        print(f"✓ Generated {len(flashcards)} flashcard(s)")
        return flashcards


if __name__ == "__main__":
    transcriber = Transcriber()
    print("Transcriber ready. Use: transcriber.transcribe_pages('file.pdf', [1,2,3])")

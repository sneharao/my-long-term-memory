# Claude Guidelines

1. **Explain before acting** — State what you're changing, where, and why before touching any code.

2. **No repetition** — Extract shared logic into reusable functions. If it appears twice, abstract it.

3. **Self-explanatory code** — Use clear, intention-revealing names. Comments explain _why_, not _what_.

4. **Modular** — One responsibility per file/function. Feature-based structure, typed interfaces, co-located tests.

5. **Clean up** — Delete any temporary files or directories created during the workflow before finishing.

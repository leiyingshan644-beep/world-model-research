import pdfplumber

MAX_CHARS = 12000  # ~4k tokens; enough context for most LLMs


def extract_text(pdf_path: str, max_chars: int = MAX_CHARS) -> str:
    parts = []
    total = 0
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            remaining = max_chars - total
            parts.append(text[:remaining])
            total += len(text)
            if total >= max_chars:
                break
    return "\n".join(parts)[:max_chars]

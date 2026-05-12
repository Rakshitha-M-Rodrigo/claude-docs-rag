"""Document chunking with context preservation."""
import re
from typing import List, Dict, Any
import tiktoken


class MarkdownChunker:
    """Chunks documents while preserving markdown structure and adding context."""

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 150, model: str = "cl100k_base"):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.encoder = tiktoken.get_encoding(model)

    def _token_count(self, text: str) -> int:
        return len(self.encoder.encode(text))

    def chunk_document(self, markdown: str, source: str, docset: str) -> List[Dict[str, Any]]:
        """Split markdown into contextual chunks."""
        lines = markdown.split("\n")
        sections = self._split_by_headers(lines)
        chunks = []

        for section in sections:
            header = section["header"]
            content = section["content"]
            section_text = f"{header}\n{content}" if header else content

            if self._token_count(section_text) <= self.chunk_size:
                chunks.append(self._create_chunk(section_text, source, docset, header))
            else:
                sub_chunks = self._split_large_section(section_text, source, docset, header)
                chunks.extend(sub_chunks)

        return chunks

    def _split_by_headers(self, lines: List[str]) -> List[Dict[str, str]]:
        """Split document by markdown headers."""
        sections = []
        current_header = ""
        current_lines = []

        for line in lines:
            if re.match(r"^#{1,4}\s+", line):
                if current_lines:
                    sections.append({"header": current_header, "content": "\n".join(current_lines).strip()})
                current_header = line.strip()
                current_lines = []
            else:
                current_lines.append(line)

        if current_lines:
            sections.append({"header": current_header, "content": "\n".join(current_lines).strip()})

        return [s for s in sections if s["content"]]

    def _split_large_section(self, text: str, source: str, docset: str, header: str) -> List[Dict[str, Any]]:
        """Split a large section into overlapping chunks."""
        tokens = self.encoder.encode(text)
        chunks = []
        start = 0

        while start < len(tokens):
            end = min(start + self.chunk_size, len(tokens))
            chunk_tokens = tokens[start:end]
            chunk_text = self.encoder.decode(chunk_tokens)
            chunks.append(self._create_chunk(chunk_text, source, docset, header))
            start += self.chunk_size - self.chunk_overlap

        return chunks

    def _create_chunk(self, text: str, source: str, docset: str, header: str) -> Dict[str, Any]:
        """Create a chunk with metadata."""
        context = f"Section: {header}\n" if header else ""
        contextual_text = f"{context}{text}".strip()
        keywords = extract_keywords(text)[:10]

        return {
            "text": contextual_text,
            "source": source,
            "docset": docset,
            "header": header,
            "keywords": keywords,
        }


def extract_keywords(text: str) -> List[str]:
    """Extract technical keywords from text."""
    # Code identifiers
    code_ids = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*", text)
    # CamelCase / snake_case
    identifiers = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)
    # Filter out common stop words
    stop_words = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "had", "her", "was", "one", "our", "out", "day", "get", "has", "him", "his", "how", "its", "may", "new", "now", "old", "see", "two", "who", "boy", "did", "she", "use", "her", "way", "many", "oil", "sit", "set", "run", "eat", "far", "sea", "eye", "ago", "off", "too", "any", "say", "man", "try", "ask", "end", "why", "let", "put", "say", "she", "try", "way", "own", "say", "too", "old", "tell", "very", "when", "much", "would", "there", "their", "what", "said", "each", "which", "will", "about", "could", "other", "after", "first", "never", "these", "think", "where", "being", "every", "great", "might", "shall", "still", "those", "while", "this", "that", "with", "have", "from", "they", "know", "want", "been", "good", "than", "then", "them", "well", "were", "here", "look", "more", "some", "time", "back", "call", "came", "come", "into", "just", "last", "left", "life", "like", "long", "made", "make", "most", "move", "must", "name", "need", "only", "over", "part", "play", "right", "same", "seem", "show", "such", "take", "than", "turn", "upon", "used", "want", "went", "work", "even", "find", "give", "hand", "high", "home", "keep", "kind", "next", "once", "open", "over", "pick", "read", "said", "seem", "side", "sure", "told", "took", "walk", "were", "what", "year"}
    keywords = [w for w in identifiers if len(w) > 2 and w.lower() not in stop_words]
    keywords.extend(code_ids)
    return list(dict.fromkeys(keywords))  # dedupe preserving order
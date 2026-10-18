"""Sentence boundaries and soft character targets; never split a sentence to fit."""

import re


_BOUNDARY = re.compile(r'''[.!?]+["'”’»\)\]]*(?=\s|$)|[。！？]+[」』"”’»\)\]]*''')
_ABBREVIATIONS = {
    "sr", "sra", "srta", "dr", "dra", "prof", "profa", "ud", "uds",
    "mr", "mrs", "ms", "jr", "vs", "etc", "aprox", "pág", "págs",
    "núm", "art", "av", "ee", "uu", "rr", "hh", "ss", "cc", "ej",
}


def split_sentences(text):
    """Keep common abbreviations and initials with their following text.

    A sentence without terminal punctuation is kept whole, even if it exceeds
    the desired size. Whitespace is normalized without changing the words.
    """
    text = " ".join(text.split())
    parts, start = [], 0
    for match in _BOUNDARY.finditer(text):
        terminal = match.group().rstrip('"\'”’»)]')
        if terminal == ".":
            prefix = text[:match.start()]
            token = re.search(r"([\w.]+)$", prefix)
            token = token.group(1) if token else ""
            if (token.casefold() in _ABBREVIATIONS
                    or (len(token) == 1 and token.isalpha())
                    or re.fullmatch(r"(?:[A-Za-zÁÉÍÓÚÑáéíóúñ]\.)+[A-Za-zÁÉÍÓÚÑáéíóúñ]", token)):
                continue
        end = match.end()
        part = " ".join(text[start:end].split())
        if part:
            parts.append(part)
        start = end
    last = " ".join(text[start:].split())
    if last:
        parts.append(last)
    return parts


def split_text(text, limit=160, mode="sentences"):
    if mode not in {"sentences", "characters"}:
        raise ValueError("QWEN_CHUNK_MODE debe ser sentences o characters.")
    sentences = split_sentences(text)
    if mode == "sentences":
        return sentences
    parts, current = [], ""
    for sentence in sentences:
        if current and len(current) + 1 + len(sentence) > limit:
            parts.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts

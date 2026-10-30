"""Bounded extraction windows that cover the entire selected source chunk."""


def extraction_windows(chunks: list[dict], max_chars: int) -> list[dict]:
    if max_chars < 128:
        raise ValueError("extraction window must be at least 128 characters")
    windows = []
    for chunk in chunks:
        text, start = chunk["text"], 0
        while start < len(text):
            end = min(start + max_chars, len(text))
            if end < len(text):
                newline = text.rfind("\n", start + max_chars // 2, end)
                if newline > start:
                    end = newline + 1
            windows.append(chunk | {"text": text[start:end], "window_start": start, "window_end": end})
            if end == len(text):
                break
            # Overlap retains context at a split; all quotes still cite the original chunk.
            start = max(start + 1, end - min(256, max_chars // 4))
    return windows

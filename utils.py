import re
import textwrap
from collections.abc import Iterator

SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…])\s+")

# Фрагмент текста: (разделитель перед фрагментом, текст фрагмента).
Piece = tuple[str, str]


def chunk_by_paragraphs(
    text: str, max_chunk_size: int = 1000, overlap: int = 200, splitter: str = "\n\n"
) -> list[str]:
    if max_chunk_size <= 0:
        raise ValueError("max_chunk_size must be positive")
    if not 0 <= overlap < max_chunk_size:
        raise ValueError("overlap must be in range [0, max_chunk_size)")

    chunks: list[str] = []
    window: list[Piece] = []
    for piece in _split_into_pieces(text, max_chunk_size, splitter):
        if window and len(_join([*window, piece])) > max_chunk_size:
            chunks.append(_join(window))
            window = _overlap_tail(window, piece, overlap, max_chunk_size)
        window.append(piece)

    if window:
        chunks.append(_join(window))

    return chunks


def _split_into_pieces(
    text: str, max_chunk_size: int, splitter: str
) -> Iterator[Piece]:
    for paragraph in text.split(splitter):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(paragraph) <= max_chunk_size:
            yield splitter, paragraph
            continue

        separator = splitter
        for sentence in SENTENCE_BOUNDARY.split(paragraph):
            if len(sentence) <= max_chunk_size:
                parts = [sentence]
            else:
                parts = textwrap.wrap(sentence, max_chunk_size, break_on_hyphens=False)

            for part in parts:
                yield separator, part
                separator = " "


def _split_into_sentences(piece: Piece) -> list[Piece]:
    separator, piece_text = piece
    return [
        (separator if index == 0 else " ", sentence)
        for index, sentence in enumerate(SENTENCE_BOUNDARY.split(piece_text))
    ]


def _overlap_tail(
    window: list[Piece], next_piece: Piece, overlap: int, max_chunk_size: int
) -> list[Piece]:
    sentences = [
        sentence for piece in window for sentence in _split_into_sentences(piece)
    ]
    tail: list[Piece] = []
    for sentence in reversed(sentences):
        if len(_join([sentence, *tail])) > overlap:
            break
        tail.insert(0, sentence)

    while tail and len(_join([*tail, next_piece])) > max_chunk_size:
        tail.pop(0)

    return tail


def _join(pieces: list[Piece]) -> str:
    (_, first_text), *rest = pieces
    return first_text + "".join(
        separator + piece_text for separator, piece_text in rest
    )

from typing import Literal

from pydantic import BaseModel

DocStatus = Literal["INGESTED", "SKIPPED", "FAILED"]


class SourceDoc(BaseModel):
    doc_id: str
    path: str  # relative to the repository root
    kind: str
    sha256: str
    status: DocStatus
    reason: str = ""
    pages: int | None = None
    text_path: str | None = None  # cleaned text artifact; chunk offsets index into it
    page_offsets: list[int] = []  # char offset where each page starts in the cleaned text
    authority: Literal["DOCUMENTED", "RTL_INFERRED"] = "DOCUMENTED"


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    doc_path: str
    section_number: str
    section_title: str
    section_path: list[str]
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    text: str
    text_sha256: str
    authority: Literal["DOCUMENTED", "RTL_INFERRED"] = "DOCUMENTED"


class Manifest(BaseModel):
    repo: str
    repo_revision: str | None
    created_utc: str
    include: list[str] | None = None
    documents: list[SourceDoc]
    source_authority: Literal["DOCUMENTED", "RTL_INFERRED"] = "DOCUMENTED"

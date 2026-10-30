"""Durable successful stage API responses, including empty extraction results."""
from .llm import _Base
from .progress import emit


class CheckpointLLM(_Base):
    def __init__(self, delegate, directory, *, stage="spec_graph"):
        self.delegate = delegate
        self.cache_dir = getattr(delegate, "cache_dir", None) or directory
        self.model = delegate.model
        self.stage = stage

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def _call(self, name, instructions, payload, schema):
        result = self.delegate.structured(name=name, instructions=instructions,
                                           payload=payload, schema=schema)
        emit(f"{self.stage}: checkpoint completed {name} batch")
        return result

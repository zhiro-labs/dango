"""
Temporary storage for oversized tool results.

Agno can keep a long tool result (a web page, an API response) out of the
model's context: the model gets a short preview and a result id, plus
read_result / search_result tools to fetch the parts it needs. The full
results have to live in a database. Dango gives that store its own SQLite
file in a fresh temporary directory, created when the agents are built and
deleted when the process exits; the agents themselves keep no database, so
conversations are never stored.

SQLite on a file is the only temporary option that works here: Agno accepts
only SQLite or PostgreSQL for this store, and an in-memory SQLite database
breaks under Agno's multi-threaded reads and writes.
"""

import atexit
import os
import shutil
import tempfile

from .settings import AgentSettings

_TEMP_PREFIX = "dango-tool-results-"
_temp_dir: str | None = None


def make_result_store(settings: AgentSettings):
    """An Agno ResultStore for Agent(offload_tool_results=...), or None when off."""
    if settings.tool_result_offload_chars <= 0:
        return None

    from agno.db.sqlite import SqliteDb
    from agno.offload import ResultStore

    path = os.path.join(_temp_directory(), "tool_results.db")
    ttl = settings.tool_result_ttl_seconds or None
    print(
        f"🗃️ [tools] Tool results over {settings.tool_result_offload_chars} chars are kept out of "
        f"context in {path} ({f'kept {ttl}s' if ttl else 'kept until exit'})"
    )
    return ResultStore(
        db=SqliteDb(db_file=path),
        threshold_chars=settings.tool_result_offload_chars,
        ttl_seconds=ttl,
    )


def _temp_directory() -> str:
    """This process's private temp directory, removed again at exit."""
    global _temp_dir
    if _temp_dir is None:
        _temp_dir = tempfile.mkdtemp(prefix=_TEMP_PREFIX)
        atexit.register(remove_temp_directory)
    return _temp_dir


def remove_temp_directory() -> None:
    """Delete the stored results. Runs at exit; safe to call more than once."""
    global _temp_dir
    if _temp_dir is not None:
        shutil.rmtree(_temp_dir, ignore_errors=True)
        _temp_dir = None

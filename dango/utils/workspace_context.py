"""
Workspace context manager.

workspace_sys_prompt.txt is generated once from the workspace files (if it doesn't exist
or workspace files have changed since last generation) and injected directly into the
main agent's system prompt. It contains a topic index and instructs the main agent to
call the workspace tool for related queries.

Generation uses a dedicated Workspace Agent that reads files via tool calls,
so it never dumps all file contents into a single context window.
"""

import json
from pathlib import Path

from agno.agent import Agent


_META_PROMPT = """\
You are a system prompt engineer with access to a workspace tool. Your task is to generate a system prompt block that will be injected into an AI assistant's instructions.

Steps:
1. Use the workspace tool to list ALL files in the workspace, including all subdirectories.
2. Read the content of every file you find.
3. Based on what you have read, generate the system prompt block.

CRITICAL OUTPUT RULES — read carefully before writing a single word:

1. OUTPUT ONLY A TOPIC INDEX. Do NOT copy, paraphrase, or summarise any file content.
   Each entry must be just a topic name or category (1–5 words) with a one-line description
   of what kind of information is there. Nothing more.

2. THE ENTIRE PURPOSE of this block is to tell the AI assistant: "these topics exist in the
   workspace — go read the workspace tool for the actual details." The block must NEVER serve
   as a substitute for the workspace tool. If the block contains actual content, it defeats
   its own purpose.

3. The block MUST end with an explicit, strongly-worded directive instructing the AI assistant
   to call the workspace tool whenever users ask about any of these topics. The directive must
   make clear that answering from memory or from this index alone is NOT acceptable — the AI
   must retrieve the up-to-date content via the tool every time.

Format of the output block:
- A short header line identifying this as workspace context
- One sentence summarising what this workspace is about
- A bullet list of topic entries (name — one-line description)
- The mandatory workspace-tool directive as the final paragraph

Write only the system prompt block. No meta-commentary, no document headers.\
"""

_context: str = ""
_fingerprint: dict[str, float] = {}  # {absolute path: mtime}
_root: str = ""
_sys_prompt_path: str = ""


def _compute_fingerprint(root: str) -> dict[str, float]:
    p = Path(root)
    if not p.exists():
        return {}
    return {
        str(f): f.stat().st_mtime
        for f in sorted(p.rglob("*"))
        if f.is_file() and f.suffix in {".md", ".txt"}
    }


def _fingerprint_path(sys_prompt_path: str) -> str:
    return str(Path(sys_prompt_path).with_suffix(".fingerprint.json"))


def _load_stored_fingerprint(sys_prompt_path: str) -> dict[str, float]:
    p = Path(_fingerprint_path(sys_prompt_path))
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_fingerprint(sys_prompt_path: str, fp: dict[str, float]) -> None:
    Path(_fingerprint_path(sys_prompt_path)).write_text(
        json.dumps(fp, ensure_ascii=False), encoding="utf-8"
    )


async def _generate_and_save(save_path: str) -> str:
    """Generate workspace_sys_prompt.txt using a Workspace Agent and save it."""
    # Lazy import to avoid circular: dango.agent → build_instructions → workspace_context
    from agno.tools.workspace import Workspace
    from ..agent import get_agents  # noqa: PLC0415

    agent = Agent(
        model=get_agents().fast_model,
        tools=[Workspace(_root, allowed=["read", "list", "search"])],
        instructions=_META_PROMPT,
        markdown=False,
    )
    response = await agent.arun(
        input="Explore the workspace and generate the system prompt block."
    )
    generated = (response.content or "").strip()
    if not generated:
        print("⚠️  Workspace context generation returned empty — cache not written")
        return ""
    Path(save_path).write_text(generated, encoding="utf-8")
    print(f"📝 Workspace system prompt generated and saved to {save_path}")
    return generated


async def init(root: str, sys_prompt_path: str) -> None:
    """Load workspace context. Call once from setup_hook."""
    global _context, _fingerprint, _root, _sys_prompt_path
    _root = root
    _sys_prompt_path = sys_prompt_path
    _fingerprint = _compute_fingerprint(root)
    if not _fingerprint:
        return

    path = Path(sys_prompt_path)
    stored_fp = _load_stored_fingerprint(sys_prompt_path)

    if path.exists() and stored_fp == _fingerprint:
        _context = path.read_text(encoding="utf-8").strip()
        print(f"📂 Workspace system prompt loaded from cache ({sys_prompt_path})")
    else:
        if path.exists():
            print("📂 Workspace files changed — regenerating system prompt...")
        try:
            _context = await _generate_and_save(sys_prompt_path)
        except Exception as e:
            print(f"⚠️  Workspace system prompt generation failed: {e}")
            _context = path.read_text(encoding="utf-8").strip() if path.exists() else ""
        if _context:
            _save_fingerprint(sys_prompt_path, _fingerprint)

    print(f"📂 Workspace context ready ({len(_fingerprint)} files)")


def get() -> str:
    """Return the current workspace context string for system prompt injection."""
    return _context

"""
Skills: self-contained SKILL.md folders the agent loads on demand.

One Skills bundle is built per process and shared by the fast agent, the deep
agent, the /skill autocomplete and forced-skill instructions.
"""

import os

from .settings import get_settings


def _make_skills():
    """Build a Skills bundle from SKILLS_ROOT, or None when disabled/empty.

    Skills are self-contained directories (each with a SKILL.md) that the agent
    loads on demand via Agno's built-in get_skill_* tools. Validation stays on:
    a malformed SKILL.md raises SkillValidationError, which we re-raise with a
    clear, actionable message instead of letting skills be silently dropped.
    """
    settings = get_settings()
    if not settings.enable_skills:
        return None
    root = settings.skills_root
    if not os.path.isdir(root):
        print(f"⚠️  ENABLE_SKILLS is on but SKILLS_ROOT '{root}' does not exist — skills disabled")
        return None

    from agno.skills import LocalSkills, Skills

    try:
        skills = Skills(loaders=[LocalSkills(root)])
    except Exception as e:
        raise RuntimeError(
            f"Failed to load skills from '{root}': {e}. "
            "Fix the offending SKILL.md or set ENABLE_SKILLS=off."
        ) from e

    names = skills.get_skill_names()
    if not names:
        print(f"⚠️  SKILLS_ROOT '{root}' contains no skills — skills disabled")
        return None
    print(f"🧩 [skills] Loaded {len(names)} skill(s): {', '.join(names)}")
    return skills


_skills = None
_skills_built = False


def get_skills():
    """The shared Skills bundle (None when disabled or empty), built on first call."""
    global _skills, _skills_built
    if not _skills_built:
        _skills = _make_skills()
        _skills_built = True
    return _skills


def list_skill_names() -> list[str]:
    """Skill names for the /skill autocomplete; [] when disabled or on error."""
    try:
        skills = get_skills()
        return skills.get_skill_names() if skills else []
    except Exception:
        return []


def get_forced_skill_instructions(name: str) -> str | None:
    """Full SKILL.md body for a named skill, or None if disabled/unknown."""
    try:
        skills = get_skills()
        if not skills:
            return None
        skill = skills.get_skill(name)
        return skill.instructions if skill else None
    except Exception:
        return None

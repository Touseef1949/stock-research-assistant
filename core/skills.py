"""Progressively disclosed stock-research skill registry."""

from __future__ import annotations

import importlib.util
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def _tuple_field(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    slug: str
    when_to_use: str = ""
    command: str = ""
    required_tools: tuple[str, ...] = ()
    supporting_skills: tuple[str, ...] = ()

    def catalog_entry(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "command": self.command,
        }

    def loaded_entry(self) -> dict[str, Any]:
        return {
            **self.catalog_entry(),
            "required_tools": list(self.required_tools),
            "supporting_skills": list(self.supporting_skills),
            "procedure": self.body,
        }


def parse_skill_markdown(text: str) -> tuple[dict[str, Any], str]:
    """Split a SKILL.md file into YAML frontmatter and procedure body."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text.strip()
    parts = stripped[3:].split("\n---", 1)
    if len(parts) != 2:
        return {}, text.strip()
    try:
        frontmatter = yaml.safe_load(parts[0]) or {}
    except yaml.YAMLError:
        frontmatter = {}
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, parts[1].lstrip("\n").strip()


class SkillRegistry:
    """Discover skill folders and lazily load their procedures and tools."""

    def __init__(self, skills_dir: str | Path | None = None):
        self.skills_dir = Path(skills_dir) if skills_dir else DEFAULT_SKILLS_DIR
        self._skills: dict[str, Skill] = {}
        self._tool_cache: dict[str, dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        self._skills = {}
        self._tool_cache = {}
        if not self.skills_dir.is_dir():
            return
        for directory in sorted(self.skills_dir.iterdir()):
            skill_file = directory / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                front, body = parse_skill_markdown(skill_file.read_text(encoding="utf-8"))
            except OSError:
                continue
            name = str(front.get("name") or directory.name).strip()
            description = str(front.get("description") or "").strip()
            if not name or not description or not body:
                continue
            self._skills[name] = Skill(
                name=name,
                description=description,
                body=body,
                slug=directory.name,
                when_to_use=str(front.get("when_to_use") or "").strip(),
                command=str(front.get("command") or "").strip(),
                required_tools=_tuple_field(front.get("required_tools")),
                supporting_skills=_tuple_field(front.get("supporting_skills")),
            )

    def list_skills(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda item: item.name)

    def get(self, name: str) -> Skill | None:
        target = (name or "").strip().lower().lstrip("/")
        for skill in self._skills.values():
            if target in {
                skill.name.lower(),
                skill.slug.lower(),
                skill.command.lower().lstrip("/"),
            }:
                return skill
        return None

    def catalog(self) -> list[dict[str, Any]]:
        return [skill.catalog_entry() for skill in self.list_skills()]

    def prompt_catalog(self) -> str:
        return "\n".join(f"- {skill.name}: {skill.description}" for skill in self.list_skills())

    def load(self, name: str) -> dict[str, Any] | None:
        skill = self.get(name)
        return skill.loaded_entry() if skill else None

    def bundled_tools(self, name: str) -> dict[str, Any]:
        skill = self.get(name)
        if skill is None:
            return {}
        if skill.slug in self._tool_cache:
            return self._tool_cache[skill.slug]
        path = self.skills_dir / skill.slug / "tools.py"
        found: dict[str, Any] = {}
        if path.is_file():
            try:
                spec = importlib.util.spec_from_file_location(f"research_skill_{skill.slug}", path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    found = {
                        name: fn
                        for name, fn in inspect.getmembers(module, inspect.isfunction)
                        if not name.startswith("_") and fn.__module__ == module.__name__
                    }
            except Exception:
                found = {}
        self._tool_cache[skill.slug] = found
        return found

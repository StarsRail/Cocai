"""
Game state management for syncing with the user interface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from cochar.character import Character


@dataclass
class Clue:
    """A clue discovered by the player during the game."""

    id: str
    title: str
    content: str
    found_at: str | None = None


@dataclass
class GameState:
    """In-memory game state to be shared with the UI via SSE."""

    history: str = "(start your adventure to see story progression here)"
    clues: list[Clue] = field(default_factory=list)
    illustration_url: str | None = "/public/logo_dark.png"
    pc: Character | None = None

    def to_dict(self) -> dict:
        # Map cochar.Character to the UI-friendly shape
        c = self.pc
        # cochar stores fields as private underscored names; its get_json_format exposes a flat dict
        data = c.get_json_format() if isinstance(c, Character) else {}
        first = data.get("first_name", "").strip()
        last = data.get("last_name", "").strip()
        full_name = (first + " " + last).strip() or "Create a character sheet to begin"
        stats = {
            "STR": int(data.get("strength", 0) or 0),
            "DEX": int(data.get("dexterity", 0) or 0),
            "INT": int(data.get("intelligence", 0) or 0),
            "POW": int(data.get("power", 0) or 0),
            "CON": int(data.get("condition", 0) or 0),
            "APP": int(data.get("appearance", 0) or 0),
            "SIZ": int(data.get("size", 0) or 0),
            "EDU": int(data.get("education", 0) or 0),
            "SAN": int(data.get("sanity_points", 0) or 0),
            "HP": int(data.get("hit_points", 0) or 0),
            "MP": int(data.get("magic_points", 0) or 0),
            "Luck": int(data.get("luck", 0) or 0),
        }
        skills = data.get("skills", {}) or {}

        return {
            "history": self.history,
            "clues": [asdict(c) for c in self.clues],
            "illustration_url": self.illustration_url,
            "pc": {"name": full_name, "stats": stats, "skills": skills},
        }


# Global, in-memory state (per-process). In a real app, make this per-user/session and persist it.
STATE = GameState()

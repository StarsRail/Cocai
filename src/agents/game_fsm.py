"""Game phase finite state machine using python-statemachine."""

import logging

from statemachine import State, StateMachine

logger = logging.getLogger(__name__)


class GameFSM(StateMachine):
    """
    Game phase finite state machine.

    Models the valid state transitions for a Call of Cthulhu game:
    CHARACTER_CREATION → ADVENTURE ↔ COMBAT (future)
    """

    # Define states
    character_creation = State(
        "Character Creation 📋",
        initial=True,
    )
    adventure = State(
        "Adventure 🗺️",
    )
    combat = State(
        "Combat ⚔️",
    )

    # Define transitions with guards
    start_adventure = character_creation.to(adventure, cond="has_character")
    enter_combat = adventure.to(combat, cond="is_combat_active")
    exit_combat = combat.to(adventure, cond="is_combat_over")

    # Guards (conditions for transitions)
    def has_character(self, pc_exists: bool = False) -> bool:
        """Character creation → adventure requires a PC."""
        return pc_exists

    def is_combat_active(self, combat_triggered: bool = False) -> bool:
        """Adventure → combat when combat is triggered."""
        return combat_triggered

    def is_combat_over(self, combat_finished: bool = False) -> bool:
        """Combat → adventure when combat ends."""
        return combat_finished

    # Lifecycle hooks (called automatically on enter/exit)
    def on_enter_adventure(self):
        """Called when entering ADVENTURE state."""
        logger.info("🎬 Entered Adventure Phase")

    def on_enter_combat(self):
        """Called when entering COMBAT state."""
        logger.info("⚔️  COMBAT INITIATED")

    def on_exit_combat(self):
        """Called when exiting COMBAT state."""
        logger.info("✅ Combat Resolved, returning to Adventure")

    def on_enter_character_creation(self):
        """Called when entering CHARACTER_CREATION state."""
        logger.info("📋 Character Creation Phase Started")

    def get_current_phase(self) -> str:
        """Get current state ID (e.g., 'adventure')."""
        # Check which state is active using is_active property
        if self.adventure.is_active:
            return "adventure"
        elif self.combat.is_active:
            return "combat"
        else:
            return "character_creation"

    def get_current_phase_emoji(self) -> str:
        """Get emoji for current state."""
        emojis = {
            "character_creation": "📋",
            "adventure": "🗺️",
            "combat": "⚔️",
        }
        phase = self.get_current_phase()
        return emojis.get(phase, "❓")

    def get_current_phase_name(self) -> str:
        """Get human-readable current state name."""
        names = {
            "character_creation": "Character Creation",
            "adventure": "Adventure",
            "combat": "Combat",
        }
        phase = self.get_current_phase()
        return names.get(phase, "Unknown")

    def export_diagram(self, output_path: str = "game_fsm.svg") -> str:
        """
        Export FSM as SVG or PNG diagram.

        Graphviz must be installed:
            brew install graphviz  # macOS
            apt-get install graphviz  # Linux

        Args:
            output_path: Path to save diagram file (.svg or .png)

        Returns:
            Path to generated file

        Raises:
            Exception: If diagram generation fails (e.g., Graphviz not installed)
        """
        try:
            graph = self.get_graph()
            if output_path.endswith(".png"):
                graph.write_png(output_path)
            else:
                graph.write_svg(output_path)
            logger.info(f"✅ FSM diagram exported to {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to export diagram: {e}")
            raise


# Global instance (similar to Chainlit's cl.user_session)
_fsm_instance: GameFSM | None = None


def get_game_fsm() -> GameFSM:
    """Get or create singleton FSM instance."""
    global _fsm_instance
    if _fsm_instance is None:
        _fsm_instance = GameFSM()
    return _fsm_instance

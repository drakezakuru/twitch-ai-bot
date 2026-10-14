"""Canonical widget inventory and storage architecture contracts."""
from pathlib import Path

from app.widget_inventory import WIDGET_INVENTORY


ARCHITECTURE = (Path(__file__).resolve().parents[1] / "docs" / "ARCHITECTURE.md").read_text(
    encoding="utf-8"
)


def test_widget_inventory_remains_machine_readable_and_unique():
    slugs = [widget.slug for widget in WIDGET_INVENTORY]
    routes = [widget.route for widget in WIDGET_INVENTORY]
    assert slugs and len(slugs) == len(set(slugs))
    assert len(routes) == len(set(routes))


def test_architecture_states_widget_storage_safety_invariants():
    normalized = " ".join(ARCHITECTURE.split())
    required = (
        "SQLite и существующие settings APIs остаются source of truth",
        "Widget directory не хранит secrets, SQLite copies",
        "Cache/temp никогда не является source of truth",
        "atomic rename",
        "Orphan cleanup удаляет только доказанно неиспользуемые artifacts",
    )
    for statement in required:
        assert statement in normalized

"""Stable identifiers shared by lifecycle scripts."""

STATE_SCHEMA = "easyeda.hardware-lifecycle.project-state.v1"
API_PLAN_SCHEMA = "easyeda.hardware-lifecycle.api-plan.v1"

STAGES = (
    "concept",
    "module_design",
    "schematic_review",
    "bom_selection",
    "bom_writeback",
)

STAGE_STATUSES = {"pending", "in_progress", "completed"}
GATE_STATUSES = {"pending", "passed", "blocked"}
API_RISKS = {"READ", "EPHEMERAL_WRITE", "PERSISTENT_WRITE"}
CALL_EFFECTS = {"READ", "WRITE"}

WRITE_PREFIXES = (
    "create",
    "modify",
    "delete",
    "set",
    "save",
    "open",
    "close",
    "activate",
    "move",
    "rename",
    "import",
    "place",
    "add",
    "remove",
    "clear",
    "reset",
    "route",
)

READ_PREFIXES = (
    "get",
    "is",
    "has",
    "check",
    "find",
    "search",
    "list",
    "export",
    "calculate",
    "query",
)

BOM_WRITE_FIELDS = {
    "Manufacturer",
    "Manufacturer Part",
    "Supplier",
    "Supplier Part",
}

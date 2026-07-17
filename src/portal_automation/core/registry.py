from portal_automation.core.runner import BasePortalRunnerZX
from portal_automation.portals.orangehrm.runner import OrangeHrmRunner
from portal_automation.portals.saucedemo.runner import SauceDemoRunner

# -----------------------------------------------------------------------------
# Central registry that maps CLI portal keys to their runner implementations.
# The rest of the application relies on this table instead of importing portal
# classes conditionally in multiple places.
# -----------------------------------------------------------------------------
PORTAL_RUNNERS: dict[str, type[BasePortalRunnerZX]] = {
    "orangehrm": OrangeHrmRunner,
    "saucedemo": SauceDemoRunner,
}


def get_runner(portal_name: str) -> type[BasePortalRunnerZX]:
    """Return the runner class registered for a portal key.

    Args:
        portal_name: Portal key supplied by the CLI.

    Returns:
        Runner class for the requested portal.

    Raises:
        ValueError: If the portal key is not registered.
    """
    # Fail with a user-facing message that lists valid keys for the CLI.
    try:
        return PORTAL_RUNNERS[portal_name]
    except KeyError as exc:
        available = ", ".join(sorted(PORTAL_RUNNERS))
        raise ValueError(
            f"Unknown portal '{portal_name}'. Available portals: {available}."
        ) from exc

from portal_automation.core.runner import BasePortalRunnerZX
from portal_automation.portals.orangehrm.runner import OrangeHrmRunner
from portal_automation.portals.saucedemo.runner import SauceDemoRunner

PORTAL_RUNNERS: dict[str, type[BasePortalRunnerZX]] = {
    "orangehrm": OrangeHrmRunner,
    "saucedemo": SauceDemoRunner,
}


def get_runner(portal_name: str) -> type[BasePortalRunnerZX]:
    try:
        return PORTAL_RUNNERS[portal_name]
    except KeyError as exc:
        available = ", ".join(sorted(PORTAL_RUNNERS))
        raise ValueError(
            f"Unknown portal '{portal_name}'. Available portals: {available}."
        ) from exc

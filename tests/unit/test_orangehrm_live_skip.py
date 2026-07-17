import importlib.util
from pathlib import Path

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError

ROOT = Path(__file__).resolve().parents[2]
E2E_TEST = ROOT / "tests" / "e2e" / "test_orangehrm_live.py"


def _load_orangehrm_live_tests():
    """Load orangehrm live tests.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    spec = importlib.util.spec_from_file_location("test_orangehrm_live", E2E_TEST)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_orangehrm_live_skip_helper_skips_only_portal_availability_errors() -> None:
    """Verify that orangehrm live skip helper skips only portal availability errors.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    module = _load_orangehrm_live_tests()

    assert module._should_skip_live_portal_error(  # noqa: SLF001
        PortalError(ReasonCode.PORTAL_UNAVAILABLE, "portal down")
    )
    assert module._should_skip_live_portal_error(  # noqa: SLF001
        PortalError(ReasonCode.PORTAL_TIMEOUT, "portal slow")
    )
    assert not module._should_skip_live_portal_error(  # noqa: SLF001
        PortalError(ReasonCode.LOGIN_FAILED, "bad login")
    )
    assert not module._should_skip_live_portal_error(  # noqa: SLF001
        PortalError(ReasonCode.UNEXPECTED_ERROR, "regression")
    )

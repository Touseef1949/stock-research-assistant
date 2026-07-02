"""Force REQUIRE_AUTH to True during test runs so auth-path tests are deterministic."""
import os
import sys

import pytest

os.environ["REQUIRE_AUTH"] = "true"

# Force-reload payment/app modules so REQUIRE_AUTH picks up the env var
for mod in list(sys.modules):
    if mod in ("payment", "app"):
        del sys.modules[mod]


@pytest.fixture(autouse=True)
def _restore_sys_modules():
    """Restore payment/app modules in sys.modules after each test.

    test_app_final_coverage::_fresh_modules pops 'payment' and 'app' from
    sys.modules to force reimport with a different REQUIRE_AUTH.  After the
    test those new module objects remain in sys.modules, breaking other test
    files that imported payment/app at module level (patch targets mismatch).

    This fixture snapshots the modules BEFORE each test and restores them
    AFTER, so _fresh_modules's pop/reimport stays scoped to its own test.
    """
    saved = {}
    for name in ("payment", "app"):
        if name in sys.modules:
            saved[name] = sys.modules[name]
    yield
    for name, mod in saved.items():
        if sys.modules.get(name) is not mod:
            sys.modules[name] = mod

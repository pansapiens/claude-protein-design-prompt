"""The surface this campaign does not own: the agent harness and the compute provider.

Stubbed so the reconstruction imports and its pure logic can be exercised. Every name
here corresponds to something the prompt names by hand; nothing here is invented.
"""

from __future__ import annotations

from typing import Any


class _Surface:
    """Attribute access returns another surface; calls return None.

    Stands in for `host.*`, `modal.*` and the Slack/Drive connectors so that the
    reconstruction can name the exact call the prompt names without providing a client.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attr: str) -> "_Surface":
        return _Surface(f"{self._name}.{attr}")

    def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        return None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<external {self._name}>"


# The orchestrator's only compute touchpoint (st-210), plus delegation and messaging.
host = _Surface("host")

# The provider SDK. Reachable from sub-agents and job code only; never from the
# orchestrator process (st-210), which is why this import lives here and not there.
modal = _Surface("modal")

slack = _Surface("slack")
drive = _Surface("drive")

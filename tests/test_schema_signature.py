# Description: Invariant tests binding every tool's inputSchema to its handler signature (R1.3).
# Description: A tool is callable per its schema: required params are required, properties accepted.

import inspect

import pytest

from lm_mcp.registry import AWX_TOOLS, TF_TOOLS, TOOLS, WATSONX_TOOLS, get_tool_handler
from lm_mcp.server import PORTAL_TOOLS, SESSION_TOOLS

ALL_TOOLS = [*TOOLS, *AWX_TOOLS, *WATSONX_TOOLS, *TF_TOOLS]

_NAMED = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)


def _caller_params(tool_name: str) -> list[inspect.Parameter]:
    """Return the handler parameters the caller fills from tool arguments.

    execute_tool passes the LM, AWX or watsonx client or the Terraform runner as the
    first positional argument, except for session and portal tools, which receive the
    arguments alone.
    """
    params = list(inspect.signature(get_tool_handler(tool_name)).parameters.values())
    if tool_name in SESSION_TOOLS or tool_name in PORTAL_TOOLS:
        return params
    return params[1:]


def test_invariant_covers_every_registered_tool():
    """The parametrized invariant runs over the full tool surface, one case per tool."""
    names = [t.name for t in ALL_TOOLS]
    assert len(names) == len(set(names))
    assert len(names) >= 300


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.name)
def test_tool_is_callable_per_its_schema(tool):
    """Every handler parameter without a default is required; every property is accepted."""
    params = _caller_params(tool.name)
    schema_required = set(tool.inputSchema.get("required", []))
    properties = set(tool.inputSchema.get("properties", {}))

    required_params = {
        p.name for p in params if p.kind in _NAMED and p.default is inspect.Parameter.empty
    }
    assert required_params <= schema_required, (
        f"{tool.name}: handler requires {sorted(required_params - schema_required)} "
        "but the schema does not list them as required"
    )

    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params):
        return
    named = {p.name for p in params if p.kind in _NAMED}
    assert properties <= named, (
        f"{tool.name}: schema properties {sorted(properties - named)} "
        "are not handler parameters and the handler takes no **kwargs"
    )

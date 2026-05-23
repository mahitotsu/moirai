from __future__ import annotations

import tomllib
from pathlib import Path


def test_awslabs_aws_documentation_dependency_declared() -> None:
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    deps = data["project"]["dependencies"]
    assert any("awslabs.aws-documentation-mcp-server" in d for d in deps)

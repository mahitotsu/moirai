"""zip ベース Lambda (from_asset) の import を本番環境相当の条件で検証する。

uv ワークスペースは .venv を全パッケージで共有するため、make test だけでは
pyproject.toml の依存宣言漏れを検出できない。このスクリプトは各 Lambda サービスの
requirements.txt のみをインストールした一時ディレクトリを PYTHONPATH に設定し、
lambda_function を import することで宣言漏れと bundling 設定漏れを同時に検出する。

Usage:
    uv run python scripts/check_lambda_imports.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
SERVICES = ROOT / "services"

# zip ベース Lambda (CDK from_asset でデプロイされるもの)
# format: (package_dir, env_vars_needed_for_Settings_instantiation)
LAMBDAS: list[tuple[Path, dict[str, str]]] = [
    (
        SERVICES / "knowledge-consumer",
        {
            "KNOWLEDGE_TABLE_NAME": "dummy",
            "VECTOR_BUCKET_NAME": "dummy",
            "VECTOR_INDEX_NAME": "dummy",
        },
    ),
    (SERVICES / "ticket-dispatcher", {}),
    (SERVICES / "bridge", {"TICKET_SERVICE_URL": "http://dummy", "API_KEY_SECRET_NAME": "dummy"}),
    (SERVICES / "fake-api-server", {}),
]

# boto3 はモックする (Lambda runtime に同梱されており requirements.txt 不要なため)
_MOCK_PREAMBLE = """\
import sys, os
from unittest.mock import MagicMock
_boto3_mock = MagicMock()
sys.modules.setdefault('boto3', _boto3_mock)
sys.modules.setdefault('botocore', MagicMock())
sys.modules.setdefault('botocore.exceptions', MagicMock())
"""


def check(service_dir: Path, env: dict[str, str]) -> bool:
    name = service_dir.name
    req = service_dir / "requirements.txt"

    with tempfile.TemporaryDirectory() as tmpdir:
        # requirements.txt に記載された依存のみをインストール
        if req.exists() and req.read_text().strip():
            result = subprocess.run(
                [
                    "uv", "pip", "install",
                    "-r", str(req),
                    "--target", tmpdir,
                    "--quiet",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"  FAIL  {name} — pip install failed:\n{result.stderr.strip()}")
                return False

        env_setup = "\n".join(f"os.environ.setdefault({k!r}, {v!r})" for k, v in env.items())
        code = (
            f"{_MOCK_PREAMBLE}\n"
            f"{env_setup}\n"
            f"sys.path.insert(0, {str(service_dir)!r})\n"
            "import lambda_function\n"
            "print('OK')\n"
        )

        result = subprocess.run(
            [sys.executable, "-c", code],
            env={"PYTHONPATH": tmpdir, "PATH": __import__("os").environ["PATH"]},
            capture_output=True,
            text=True,
        )

    if result.returncode == 0:
        print(f"  OK    {name}")
        return True
    else:
        error = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "(no output)"
        print(f"  FAIL  {name} — {error}")
        return False


def main() -> None:
    print("==> Checking Lambda imports (isolated from uv workspace venv) ...\n")
    results = [check(svc_dir, env) for svc_dir, env in LAMBDAS]
    print()
    if all(results):
        print("All Lambda import checks passed.")
    else:
        failed = sum(1 for r in results if not r)
        print(f"{failed} check(s) failed. Fix pyproject.toml dependencies and CDK bundling.")
        sys.exit(1)


if __name__ == "__main__":
    main()

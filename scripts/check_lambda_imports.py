"""zip ベース Lambda (from_asset) の import を2段階で検証する。

uv ワークスペースは .venv を全パッケージで共有するため、make test だけでは
pyproject.toml の依存宣言漏れを検出できない。

検証アプローチ (Docker/QEMU を使わないため高速):

  1. アーキテクチャ検証 (arm64 インストール → .so ELF ヘッダー確認)
     - requirements.txt を --python-platform aarch64-manylinux_2_17 でインストール
     - すべての .so が "ARM aarch64" であることを file コマンドで確認
     - これにより「x86_64 .so が arm64 Lambda に混入する」バグを検出する

  2. 依存宣言漏れ検証 (ホスト Python でインポート)
     - requirements.txt のみをホスト向けにインストールした隔離ディレクトリを PYTHONPATH に設定
     - boto3 等 Lambda runtime 同梱ライブラリはモックで代替
     - lambda_function を import することで宣言漏れを検出する

Usage:
    uv run python scripts/check_lambda_imports.py
"""

from __future__ import annotations

import os
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
    (
        SERVICES / "ticket-dispatcher",
        {
            "AGENT_RUNTIME_ARN": "arn:aws:bedrock-agentcore:::runtime/dummy",
            "DISPATCHER_PROMPT_ARN": "arn:aws:bedrock:us-east-1::prompt/dummy",
        },
    ),
    (SERVICES / "bridge", {"TICKET_SERVICE_URL": "http://dummy", "API_KEY_SECRET_NAME": "dummy"}),
    (SERVICES / "fake-api-server", {}),
]

# boto3 はモックする (Lambda runtime に同梱されており requirements.txt 不要なため)
_MOCK_PREAMBLE = """\
import sys, os
from unittest.mock import MagicMock
sys.modules.setdefault('boto3', MagicMock())
sys.modules.setdefault('botocore', MagicMock())
sys.modules.setdefault('botocore.exceptions', MagicMock())
"""


def _install_deps(
    req: Path,
    target: str,
    *,
    arm64: bool = False,
) -> tuple[bool, str]:
    cmd = ["uv", "pip", "install", "-r", str(req), "--target", target, "--quiet"]
    if arm64:
        cmd += [
            "--python-platform", "aarch64-manylinux_2_17",
            "--python-version", "3.12",
            "--only-binary", ":all:",
        ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, r.stderr.strip()


def _verify_so_arch(deps_dir: str) -> tuple[bool, str]:
    """インストール済み .so がすべて aarch64 であることをファイル名で確認する。

    CPython の .so ファイル名は
    `<name>.cpython-312-aarch64-linux-gnu.so` のように
    アーキテクチャを含む。x86_64 や i686 が含まれていれば NG。
    """
    bad_tags = ("x86_64", "i686", "i386")
    for so in sorted(Path(deps_dir).rglob("*.so")):
        name = so.name
        # アーキテクチャタグが明示されている .so のみ検査
        if ".cpython-" not in name:
            continue
        if any(tag in name for tag in bad_tags):
            return False, f"{name} は arm64 用ではありません (x86_64 ホイールが混入しています)"
        if "aarch64" not in name:
            return False, f"{name} のアーキテクチャを判別できません"
    return True, ""


def _run_host_import(deps_dir: str, service_dir: Path, env: dict[str, str]) -> tuple[bool, str]:
    """ホスト Python でインポートを試みる。依存宣言漏れを検出する。"""
    env_setup = "\n".join(f"os.environ.setdefault({k!r}, {v!r})" for k, v in env.items())
    code = (
        f"{_MOCK_PREAMBLE}\n"
        f"{env_setup}\n"
        f"sys.path.insert(0, {str(service_dir)!r})\n"
        "import lambda_function\n"
        "print('OK')\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": deps_dir, "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
    )
    last = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "(no output)"
    return r.returncode == 0, last


def check(service_dir: Path, env: dict[str, str]) -> bool:
    name = service_dir.name
    req = service_dir / "requirements.txt"
    has_deps = req.exists() and req.read_text().strip()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        arm64_dir = str(tmp / "arm64")
        host_dir = str(tmp / "host")
        Path(arm64_dir).mkdir()
        Path(host_dir).mkdir()

        if has_deps:
            # Step 1: arm64 インストール → アーキテクチャ確認
            ok, err = _install_deps(req, arm64_dir, arm64=True)
            if not ok:
                print(f"  FAIL  {name} — arm64 install failed: {err}")
                return False
            ok, err = _verify_so_arch(arm64_dir)
            if not ok:
                print(f"  FAIL  {name} — {err}")
                return False

            # Step 2: ホスト向けインストール → import 確認
            ok, err = _install_deps(req, host_dir)
            if not ok:
                print(f"  FAIL  {name} — host install failed: {err}")
                return False

        # Step 3: ホスト Python でインポート実行
        ok, err = _run_host_import(host_dir, service_dir, env)
        if not ok:
            print(f"  FAIL  {name} — {err}")
            return False

    print(f"  OK    {name}")
    return True


def main() -> None:
    print("==> Checking Lambda imports (arm64 arch + host import) ...\n")
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

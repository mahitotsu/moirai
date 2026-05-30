"""並列テストランナー。

直列実行の問題:
  - ticket-service (DynamoDB 統合) / infrastructure (CDK synth) / lambda-imports (Docker)
    が互いに独立しているのに直列実行されていた
  - ユニットテストも 12+ 回の uv run を直列で呼び出していた

このスクリプトは全テストグループを ThreadPoolExecutor で並列実行し、
出力を収集して完了後に順番に表示する。
"""

from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).parent.parent

# 重いグループ: 独立しているので並列実行
_SLOW_GROUPS: list[dict] = [
    {
        "name": "ticket-service",
        "cmd": [
            "uv", "run", "--package", "ticket-service",
            "pytest", "services/ticket-service/", "-v", "--tb=short",
        ],
    },
    {
        "name": "infrastructure",
        "cmd": [
            "uv", "run", "--package", "agora-infrastructure",
            "pytest", "infrastructure/tests/", "-v", "--tb=short",
        ],
    },
    {
        "name": "lambda-imports",
        "cmd": ["uv", "run", "python", "scripts/check_lambda_imports.py"],
    },
]

# 重いグループに含まれるパッケージ名 (ユニットテストループから除外)
_SLOW_PACKAGES = {"ticket-service"}

# ユニットテスト対象のルートディレクトリ
_UNIT_ROOTS = ["services", "mcp-servers", "agents"]


def _collect_unit_packages() -> list[tuple[str, str]]:
    """(svcdir_rel, pkg_name) のリストを返す。テストファイルがないディレクトリは除外。"""
    result = []
    for root in _UNIT_ROOTS:
        root_path = ROOT / root
        if not root_path.is_dir():
            continue
        for svcdir in sorted(root_path.iterdir()):
            if not svcdir.is_dir() or svcdir.name in _SLOW_PACKAGES:
                continue
            if list(svcdir.rglob("test_*.py")):
                result.append((str(svcdir.relative_to(ROOT)), svcdir.name))
    return result


def _run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def main() -> None:
    all_passed = True
    unit_pkgs = _collect_unit_packages()

    # 全グループを並列起動 (ユニットテストは per-package で独立実行)
    groups: list[tuple[str, list[str]]] = []
    for svcdir, pkg in unit_pkgs:
        groups.append((
            pkg,
            ["uv", "run", "--package", pkg, "pytest", svcdir, "-v", "--tb=short"],
        ))
    for g in _SLOW_GROUPS:
        groups.append((g["name"], g["cmd"]))

    t0 = time.monotonic()
    futures: dict[Future[tuple[int, str]], tuple[str, float]] = {}

    with ThreadPoolExecutor(max_workers=len(groups)) as executor:
        for name, cmd in groups:
            start = time.monotonic()
            f = executor.submit(_run, cmd)
            futures[f] = (name, start)

    # 結果を登録順に表示
    unit_ok = True
    slow_results: list[tuple[str, float, int, str]] = []

    for f, (name, start) in futures.items():
        rc, output = f.result()
        elapsed = time.monotonic() - start
        is_slow = name in {g["name"] for g in _SLOW_GROUPS}

        if is_slow:
            slow_results.append((name, elapsed, rc, output))
        else:
            if rc != 0:
                unit_ok = False
                # ユニットテスト失敗は即座に表示
                print(f"\n{'='*70}")
                print(f"==> FAIL: {name}  ({elapsed:.1f}s)")
                print("=" * 70)
                print(output, end="")

    total = time.monotonic() - t0

    # ユニットテスト結果サマリ
    passed = sum(1 for f, (n, _) in futures.items() if n not in {g["name"] for g in _SLOW_GROUPS} and f.result()[0] == 0)
    total_units = len(unit_pkgs)
    unit_label = f"unit tests: {passed}/{total_units} passed"
    print(f"\n{'='*70}")
    print(f"==> {'OK' if unit_ok else 'FAIL'}  {unit_label}")
    print("=" * 70)

    if not unit_ok:
        all_passed = False

    # 重いグループの結果を順番に表示
    for name, elapsed, rc, output in slow_results:
        print(f"\n{'='*70}")
        print(f"==> {name}  ({elapsed:.1f}s)")
        print("=" * 70)
        print(output, end="")
        if rc != 0:
            all_passed = False

    print(f"\nTotal wall time: {total:.1f}s")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()

"""共有バンドラーユーティリティ。

CDK スタック間で _LocalPipBundler を共有するためのモジュール。
zip ベース Lambda (from_asset) の requirements.txt を Docker なしでインストールする。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import aws_cdk as cdk
import jsii


@jsii.implements(cdk.ILocalBundling)
class LocalPipBundler:
    """Docker なしで pip install + ソースコピーを行うローカルバンドラー。

    requirements.txt に記載された依存を /asset-output にインストールし、
    .py ソースファイルをコピーする。requirements.txt が空の場合はソースのみコピー。
    try_bundle が True を返すため Docker フォールバックは不要。
    """

    def __init__(self, source_dir: Path) -> None:
        self._source = source_dir

    def try_bundle(self, output_dir: str, options: cdk.BundlingOptions) -> bool:
        req = self._source / "requirements.txt"
        if req.exists() and req.read_text().strip():
            subprocess.check_call(
                [
                    "uv", "pip", "install", "-r", str(req),
                    "--target", output_dir,
                    "--quiet",
                    "--python-platform", "aarch64-manylinux_2_17",
                    "--python-version", "3.12",
                    "--only-binary", ":all:",
                ]
            )
        for item in self._source.iterdir():
            if item.is_file() and item.name not in ("requirements.txt",):
                shutil.copy2(item, output_dir)
        return True

# /new-mcp

引数: `$ARGUMENTS` (MCPサーバー名。例: `stackoverflow`)

`mcp-servers/$ARGUMENTS/` に以下の構成でFastMCPサーバー雛形を生成する。

## 生成するファイル

```
mcp-servers/{name}/
├── server.py          # FastMCP サーバー本体
├── client.py          # 外部API呼び出しロジック
├── tests/
│   ├── __init__.py
│   └── test_server.py
├── Dockerfile
└── pyproject.toml
```

## 各ファイルの要件

### server.py
- `from __future__ import annotations`
- `from mcp.server.fastmcp import FastMCP`
- `mcp = FastMCP("{name}-mcp")` でサーバーを初期化
- `@mcp.tool()` デコレータで少なくとも1つのツールをスタブ定義
- 各ツールの docstring に「何を検索し何を返すか」を明記（tool descriptionになる）
- エラー時は `ValueError` でユーザーフレンドリーなメッセージを返す（スタックトレース露出禁止）
- ファイル末尾: `if __name__ == "__main__": mcp.run()`

### client.py
- `from __future__ import annotations`
- 外部APIを呼び出す非同期クライアントクラス
- `httpx.AsyncClient` を使用
- タイムアウト設定必須 (10秒)

### Dockerfile
```dockerfile
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY pyproject.toml .
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY server.py client.py ./
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "server.py"]
```

### pyproject.toml
- `mcp[cli]`、`httpx`、`fastmcp` を dependencies に含める
- ruff/mypyはルートの `pyproject.toml` で一元管理するため不要

### tests/test_server.py
- `responses` または `pytest-httpx` で外部APIをインターセプト
- 正常系・エラー系の基本的なテストケース

生成後、`make lint` で問題がないことを確認する。

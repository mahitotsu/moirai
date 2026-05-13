# /new-service

引数: `$ARGUMENTS` (サービス名。例: `ticket-service`)

`services/$ARGUMENTS/` に以下の構成でFastAPIサービス雛形を生成する。

## 生成するファイル

```
services/{name}/
├── app/
│   ├── __init__.py
│   ├── main.py        # FastAPI app + ルーター
│   ├── models.py      # Pydanticモデル
│   ├── repository.py  # DynamoDB操作
│   └── settings.py    # pydantic-settings による設定
├── tests/
│   ├── __init__.py
│   └── conftest.py    # pytest fixtures (DynamoDBクライアント等)
├── Dockerfile
└── pyproject.toml
```

## 各ファイルの要件

### app/main.py
- `from __future__ import annotations` を先頭に
- FastAPI インスタンスを作成し `title="{Name} Service"` を設定
- `/health` エンドポイント (GET) を実装
- `/openapi.json` は FastAPI が自動提供するが、明示的に触れるコメントを残す

### app/models.py
- `from __future__ import annotations`
- Pydantic v2 の `BaseModel` を使用
- サービスの主要エンティティのCreate/Response モデルを定義 (仮のフィールドでOK)

### app/repository.py
- `from __future__ import annotations`
- `boto3.client("dynamodb")` をコンストラクタで受け取るクラス
- CRUD の基本メソッドのスタブを定義

### app/settings.py
- `from pydantic_settings import BaseSettings`
- `table_name: str`、`aws_region: str = "us-east-1"` を定義

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
COPY app/ app/
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```
プラットフォームは `make build` 時に `--platform linux/arm64` を指定するのでDockerfile内には不要。

### pyproject.toml
- `[project]` セクションに name・version・dependencies（ruff/mypyは不要。ルートの `pyproject.toml` で一元管理）
- `uv.lock` はルートで一元管理するためこのファイルには不要

### tests/conftest.py
- `boto3.client("dynamodb", region_name="us-east-1")` のfixtureを定義
- テーブル名に `agora-test-` プレフィックスを使用
- `autouse=True` の finalizer でテストテーブルを削除

生成後、ファイルの内容を確認して `make lint` で問題がないことを確認する。

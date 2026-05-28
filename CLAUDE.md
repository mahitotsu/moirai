# Agora — 開発ガイド

設計・スコープ・デモシナリオの詳細は [PITCH.md](PITCH.md) を参照。

## リポジトリ構成

```
moirai/
├── services/           FastAPIサービス (ticket-service, asset-service)
├── mcp-servers/        FastMCPサーバー (stackoverflow, github-issues, wikipedia)
├── agents/             A2Aエージェント (gateway, triage, diagnosis, resolution)
├── skills/             AgentCore Registry Skill定義 (SKILL.md — uv workspaceスコープ外)
├── infrastructure/     AWS CDK (Python)
└── ui/                 React SPA
```

## 技術スタック

- **言語**: Python 3.12+
- **ビルドツール**: uv (パッケージ管理・仮想環境・ワークスペース)
- **Webフレームワーク**: FastAPI
- **MCPサーバー**: FastMCP (`mcp.server.fastmcp`)
- **AWSクライアント**: boto3
- **設定管理**: pydantic-settings
- **IaC**: AWS CDK (Python)
- **フロントエンド**: React
- **データストア**: DynamoDB (us-east-1)
- **コンテナ**: ARM64 Docker → ECR → AgentCore Runtime
- **モデル**: `us.anthropic.claude-sonnet-4-6`

## 開発コマンド

```bash
uv sync                             # 依存関係インストール (初回・pyproject.toml変更後)
uv add <package> --package <name>   # 特定パッケージに依存追加

make test                           # 全テスト実行
make test-service s=ticket-service  # サービス単体テスト
make lint                           # ruff + mypy
make build img=ticket-service       # ARM64 Dockerビルド (ローカル確認用)
make cdk-diff                       # CDK差分確認 (安全)
make cdk-deploy                     # CDKデプロイ (承認必要、イメージビルド&プッシュを含む)
```

## AWS環境

- **リージョン**: us-east-1
- **テスト**: 常に実AWSサンドボックスを使用。ローカルモックなし。
- **DynamoDBテーブル名**: 本番 `agora-{name}`、テスト `agora-test-{name}`
- **テスト後片付け**: pytest finalizer で `agora-test-*` テーブルを削除

## コーディング規約

### Python 共通
- 全ファイル先頭: `from __future__ import annotations`
- 型ヒント必須
- `ruff` でlint・フォーマット統一
- 環境変数は `pydantic-settings` の `Settings` クラスで管理。`os.environ` 直読み禁止

### FastAPIサービス構成
```
services/{name}/
├── app/
│   ├── main.py        # FastAPI app + ルーター
│   ├── models.py      # Pydanticモデル
│   └── repository.py  # DynamoDB操作（DIで注入）
├── tests/
├── Dockerfile
└── pyproject.toml
```
- `/openapi.json` エンドポイントを提供する（AgentCore Gateway用）
- DynamoDBクライアントはコンストラクタで注入（テスト差し替え可能にするため）

### FastMCPサーバー構成
```
mcp-servers/{name}/
├── server.py          # @mcp.tool() デコレータでツール定義
├── tests/
├── Dockerfile
└── pyproject.toml
```
- 各ツールにdocstringで説明必須（MCPのtool descriptionになる）
- エラーはユーザーフレンドリーなメッセージで返す（スタックトレース露出禁止）

### エージェント構成
```
agents/{name}/
├── agent.py           # Bedrock Converse API ループ
├── system_prompt.md   # System Prompt（独立ファイルで管理）
├── tools.py           # ツール定義（AgentCore Registry経由で動的解決）
├── tests/             # ユニットテスト（必須）
└── pyproject.toml
```
- System Promptは `system_prompt.md` として独立管理
- MCPエンドポイントのハードコード禁止。AgentCore Registryで動的解決
- **Strands `@tool` 関数のパターン**: コンストラクタDIができないため、モジュールレベルの `_Settings`（pydantic-settings）と boto3 クライアントを使う。テストでは `unittest.mock.patch.object(tools, "_dynamodb")` 等でクライアントをモックする
- テーブル名・リージョンは必ず `pydantic-settings` の `_Settings` クラスで管理し、CDK の `environment_variables` から注入する

### テスト必須ルール

新規コンポーネントを追加する際は **必ずテストを同時に作成**する。

| コンポーネント | テスト場所 | テスト方式 |
|---|---|---|
| FastAPIサービス | `services/{name}/tests/` | 実DynamoDB（`agora-test-*` テーブル）|
| FastMCPサーバー | `mcp-servers/{name}/tests/` | 実外部APIまたはモック |
| Strandsエージェント tools.py | `agents/{name}/tests/` | `unittest.mock.patch.object` |

コンポーネント追加後、`make test` がパスすることを確認してからコミットする。

### 禁止事項
- AWSクレデンシャルのハードコード（IAMロールで解決）
- MCPサーバー・AgentCoreエンドポイントのハードコード（Registry経由で解決）
- `agora-test-` プレフィックスのテーブルへの本番データ混入
- `from __future__ import annotations` の省略
- 新規コンポーネントでのテーブル名・リージョン等のハードコード（pydantic-settings + CDK env var注入で解決）

## Dockerビルド規約

- **ベースイメージ**: `python:3.12-slim`
- **プラットフォーム**: `--platform linux/arm64`（AgentCore Runtime要件）
- **マルチステージビルド**: builderでrequirements install → 本番イメージにコピー

## CDKスタック構成

```
infrastructure/
├── app.py
└── stacks/
    ├── data_stack.py     # DynamoDBテーブル
    ├── compute_stack.py  # ECR + AgentCore Runtime登録
    └── network_stack.py  # VPC（必要に応じて）
```

## コンポーネント新規作成・デプロイ時のルール

ユーザーから以下のような依頼を受けた場合、対応するコマンドファイルの仕様を**必ず読んでから**実装する。

| 状況 | 参照するファイル |
|---|---|
| 新しいFastAPIサービスを作る | `.claude/commands/new-service.md` |
| 新しいMCPサーバーを作る | `.claude/commands/new-mcp.md` |
| コミット前の品質確認・コミット | `.claude/commands/close-out.md` |
| マイルストーン完了時の深いレビュー | `.claude/commands/review.md` |

例: 「ticket-serviceを実装して」→ `.claude/commands/new-service.md` を読み、その仕様通りに生成する。

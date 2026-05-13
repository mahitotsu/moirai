# Agora — コンセプトドキュメント

## プロジェクト概要

Community Knowledgeを検索するMCPサーバー群と自作マイクロサービスを組み合わせた、マルチエージェントITサービスデスクのリファレンス実装。Amazon Bedrock AgentCoreの主要機能をフル活用し、「動く → 見える → 進化する」の3段階で構築する。

---

## 解決する課題

ITインシデント発生時、エンジニアはStack Overflow・GitHub Issues・公式ドキュメントを手動で探しながら対応する。この「知識検索 → 診断 → 解決提案 → チケット起票」の流れをマルチエージェントが代替する。さらに過去の対応履歴と自システムの運用データを蓄積・分析することでインシデント対応を継続的に改善し、最終的には解決の知見をランブックとして自動的に蓄積・進化させる。

---

## 設計原則

### 1. 責務分割されたマルチエージェント構成
単一の巨大エージェントは避ける。Triage・Diagnosis・Resolutionのように責務を明確に分割し、各エージェントが独立して開発・デプロイ・スケールできる構成にする。

### 2. 既存サービスのAPI契約を維持する
内部サービス（Ticket Service / Asset Service）はREST APIとして公開し続ける。エージェントはGateway経由でMCPツールとして利用し、UIはREST APIを直接呼び出す。APIの公開契約はエージェント導入後も変わらない。

### 3. ビジネスルールとコードの分離
各エージェントのSystem Promptを独立したファイルとして管理する。モデルの変更や業務ルールの更新をコードの変更なしに行える構造にする。

### 4. ケーパビリティベースの動的発見
エージェントはMCPサーバーのエンドポイントをハードコードしない。AgentCore RegistryにCapabilityタグを付けて登録し、エージェントは「community-knowledge能力を持つサービス」という形で動的に発見・呼び出す。

### 5. 業務データとエージェント文脈の分離
インシデント履歴などの業務データはTicket Service（DynamoDB）をSystem of Recordとして管理する。AgentCore Memoryは会話の継続性とユーザー固有の傾向の記憶に限定し、責務を混在させない。

---

## デモシナリオ（ゴールデンパス）

```
ユーザー: 「PostgreSQLの接続が全部タイムアウトしてる」

Triage Agent    : severity=high、カテゴリ=DB と分類

Diagnosis Agent : Registry で capability="community-knowledge" を持つ
                  MCPサーバーを発見し並列検索
                  → Stack Overflow: 上位解決策を取得
                  → GitHub Issues : 類似バグレポートを照合
                  → AWS Docs     : RDS接続設定を参照
                  → Ticket Service: 過去の類似インシデントを確認

Resolution Agent: Bedrockで状況に合わせた解決提案を生成
                  「max_connectionsを確認、pgBouncer導入を検討」

Ticket Service  : 症状・解決策・日時をチケットとして記録

--- V2: ダッシュボード ---

Analysis Agent  : Registry で capability="aws-observability" を持つ
                  MCPサーバーを発見
                  → CloudWatch MCP: エージェント稼働メトリクスを取得
                  → Cost Explorer MCP: Bedrock利用コストを取得
                  → Ticket Service: インシデント傾向を集計
                  → レポートをDynamoDBに保存・Reports画面に表示

--- V3: 自動進化 ---

DynamoDB Streams: Ticket が resolved に更新されたことを検知
                  → Runbook Generator Agent を自動起動
                  → SSM Automation Documentとしてランブックを生成・保存
                  → Knowledge テーブルを自動更新
```

---

## アーキテクチャ

### 全体図

```
[React UI]
  ├── Chat タブ ──────────────────── AG-UI (SSE)
  ├── Tickets タブ ────────────────── Ticket Service REST API 直接呼び出し
  ├── Knowledge タブ ──────────────── Ticket Service REST API 直接呼び出し
  ├── Reports タブ (V2) ───────────── Reports Service REST API 直接呼び出し
  └── Runbooks タブ (V3) ──────────── SSM API 直接呼び出し

      ↕ AG-UI (SSE)

[Gateway Agent]                      AgentCore Runtime / AG-UI protocol
      ↕ A2A

┌─────────────────────────────────────────────────────┐
│ エージェント群              AgentCore Runtime / A2A  │
│   Triage Agent          インシデント分類・重大度判定  │
│   Diagnosis Agent       知識検索・類似事例照合        │
│   Resolution Agent      解決提案の生成               │
│   Analysis Agent (V2)   稼働レポート・傾向分析        │
│   Runbook Generator (V3) ランブック自動生成           │
└─────────────────────────────────────────────────────┘
      ↕ AgentCore Registry 経由で capability 検索・呼び出し

┌─────────────────────────────────────────────────────┐
│ Community Knowledge MCP群   AgentCore Runtime / MCP  │
│   Stack Overflow MCP (自作)  Stack Exchange API      │
│   GitHub Issues MCP  (自作)  GitHub Search API       │
│   Wikipedia MCP      (自作)  Wikipedia API           │
│   AWS Docs MCP    (awslabs)  aws-documentation-mcp   │
│   capability: "community-knowledge"                  │
├─────────────────────────────────────────────────────┤
│ AWS Observability MCP群 (V2) AgentCore Runtime / MCP │
│   CloudWatch MCP  (awslabs)  cloudwatch-mcp-server   │
│   Cost Explorer MCP(awslabs) cost-explorer-mcp       │
│   capability: "aws-observability"                    │
└─────────────────────────────────────────────────────┘
      ↕ AgentCore Gateway 経由 (OpenAPI → MCP変換)

┌─────────────────────────────────────────────────────┐
│ 内部サービス群              FastAPI / DynamoDB        │
│   Ticket Service    インシデント管理 (System of Record)│
│   Asset Service     構成管理DB                       │
└─────────────────────────────────────────────────────┘

      ↕ DynamoDB Streams (V3)

┌─────────────────────────────────────────────────────┐
│ イベント駆動レイヤー (V3)                             │
│   Lambda (stream consumer)                           │
│   → Ticket CREATED  : Diagnosis Agent 自動起動       │
│   → Ticket RESOLVED : Runbook Generator Agent 起動   │
│   → N件集積         : Analysis Agent 即時起動        │
│   SSM Automation Documents  生成済みランブックの保存  │
└─────────────────────────────────────────────────────┘

横断サービス:
  AgentCore Registry      capability ベースの動的発見
  AgentCore Memory        会話の文脈・ユーザー固有の傾向
  AgentCore Evaluations   解決提案の品質スコアリング (V2)
  AgentCore Observability OTEL トレーシング → CloudWatch (V2)
```

---

## AgentCore 機能マッピング

| AgentCore機能 | 役割 | 採用理由 |
|---|---|---|
| Runtime (AG-UI) | ユーザー向けSSEストリーミング | チャット画面でエージェントの思考をリアルタイム表示 |
| Runtime (A2A) | エージェント間直接通信 | Triage→Diagnosis→Resolutionの責務連鎖を疎結合に実現 |
| Runtime (MCP) | Community/Observability MCPサーバー | 外部知識源をツールとして統一的に扱う |
| Gateway | 内部サービスをMCPツール化 | 既存REST APIを変更せずエージェントから利用可能にする |
| Registry | capabilityベースの動的発見 | エージェントがサービスのエンドポイントをハードコードしない |
| Memory | 会話文脈・ユーザー傾向の記憶 | セッション継続性と個人化。業務データとは明確に分離 |
| Evaluations (V2) | 解決提案の品質をLLM-as-a-Judgeで評価 | 主観的な品質を定量化し継続的改善の指標にする |
| Observability (V2) | OTELによるエンドツーエンドトレーシング | エージェント間の処理フローをCloudWatchで可視化 |
| Browser | Demo Generator AgentのUI操作 | 全スタックを本番同様に動かしてデモデータを生成 |

---

## コンポーネント詳細

### 内部サービス（モック）

| サービス | 役割 | データストア |
|---|---|---|
| Ticket Service | インシデントのSystem of Record。チケット作成・更新・検索 | DynamoDB |
| Asset Service | 構成管理DB。サーバー・サービスの資産情報 | DynamoDB |

> **設計上の重要な区別**: インシデント履歴はTicket Service（DynamoDB）に記録する。AgentCore Memoryはエージェントの会話文脈とユーザー固有の傾向記憶に限定し、業務データとの責務を混在させない。

### Community Knowledge MCP群

| MCP | 外部API | 認証 | 実装 |
|---|---|---|---|
| Stack Overflow MCP | Stack Exchange API | 不要 | 自作 (FastMCP) |
| GitHub Issues MCP | GitHub Search API | 不要（公開リポジトリ） | 自作 (FastMCP) |
| Wikipedia MCP | Wikipedia REST API | 不要 | 自作 (FastMCP) |
| AWS Docs MCP | — | — | awslabs/mcp 流用 |

### AWS Observability MCP群（V2）

| MCP | 用途 | 実装 |
|---|---|---|
| CloudWatch MCP | エージェント稼働メトリクス・ログ取得 | awslabs/mcp 流用 |
| Cost Explorer MCP | Bedrock利用コスト分析 | awslabs/mcp 流用 |

### Demo Generator Agent（V1.5）

AgentCore Browserを使い、シナリオYAMLに定義したインシデントを疑似ユーザーとしてChat UIに順番に入力・送信する。全スタックを本番同様に動かした本物のチケットがDynamoDBに蓄積されるため、シードデータの手動投入が不要。Phase 2のAnalysis Agentが意味のある分析を行うための前提となる。

```yaml
# scenarios/demo_incidents.yaml
incidents:
  - category: database
    description: "PostgreSQLへの接続が全部タイムアウトしている。アプリのログにconnection pool exhaustedが出てる"
  - category: network
    description: "nginxが断続的に502を返している。上流サービスは生きてそう"
  - category: memory
    description: "本番のAPIサーバーのメモリ使用率が90%を超えてアラートが出た"
  - category: deploy
    description: "さっきデプロイしたら一部のエンドポイントが500を返すようになった"
```

### DynamoDB Streams イベント駆動（V3）

| イベント | トリガー | 処理 |
|---|---|---|
| Ticket CREATED | チケット新規作成 | Diagnosis Agent を自動起動（能動的診断） |
| Ticket RESOLVED | チケットがresolved に更新 | Runbook Generator Agent を起動 → SSM Automation Document を生成・更新 |
| Ticket RESOLVED | 同上 | Knowledge テーブルを自動更新（知識の結晶化） |
| N件/30分集積 | 同カテゴリのチケットが閾値超え | Analysis Agent を即時起動（異常アラートレポート生成） |

---

## UI構成

### React シングルページアプリ

| タブ | 内容 | データ取得方法 | フェーズ |
|---|---|---|---|
| Chat | 障害報告・技術相談チャット | AG-UI / SSE（エージェント経由） | V1 |
| Tickets | インシデント一覧・詳細・解決策 | Ticket Service REST API 直接 | V1 |
| Knowledge | 解決済みパターンのブラウズ | Ticket Service REST API 直接 | V1 |
| Reports | Analysis Agentの稼働レポート | Reports API 直接 | V2 |
| Runbooks | SSM Automation Document一覧 | SSM API 直接 | V3 |

> Browse系タブ（Tickets / Knowledge / Reports / Runbooks）はエージェントを経由せず各サービスのREST APIを直接呼び出す。これによりエージェント導入後もAPIの公開契約が維持されていることをUIレベルでも実証する。

---

## 技術スタック

| レイヤー | 技術 |
|---|---|
| 言語 | Python 3.12+ |
| エージェントロジック | boto3 (Bedrock Converse API) + FastAPI |
| MCPサーバー | FastMCP (mcp.server.fastmcp) |
| コンテナ | ARM64 Docker → ECR → AgentCore Runtime |
| フロントエンド | React |
| データストア | DynamoDB（Ticket / Asset / Reports / Knowledge） |
| ランブック | AWS Systems Manager Automation Documents |
| イベントバス | DynamoDB Streams + Lambda (V3) |
| AWSリージョン | us-east-1 |
| モデル | Claude Sonnet (us.anthropic.claude-sonnet-4-6) |

---

## スコープ

### In（作る）

**V1: 動く**
- Ticket / Asset Service（FastAPI + DynamoDB）
- AgentCore Gateway（OpenAPI spec → MCP変換）
- Community Knowledge MCP群（Stack Overflow / GitHub Issues / Wikipedia / AWS Docs）
- AgentCore Registry
- A2Aエージェント群（Gateway / Triage / Diagnosis / Resolution）
- AG-UI + React UI（Chat / Tickets / Knowledge タブ）
- AgentCore Memory
- Demo Generator Agent（AgentCore Browser + シナリオYAML）

**V2: 見える**
- AgentCore Observability（OTEL計装）
- AWS Observability MCP群（CloudWatch / Cost Explorer）
- Analysis Agent（稼働レポート・インシデント傾向分析）
- AgentCore Evaluations
- React UI Reports タブ追加

**V3: 進化する**
- DynamoDB Streams + Lambda（イベントバス）
- Runbook Generator Agent → SSM Automation Documents
- 知識の結晶化（Ticket resolved → Knowledge テーブル自動更新）
- 異常集積検知（N件/30分 → Analysis Agent 即時起動）
- React UI Runbooks タブ追加

### Out（作らない）

- AgentCore Identity（ユーザー認証・OAuth委譲）
- AgentCore Policy（Cedar rules）
- AgentCore Code Interpreter
- 本物のJira / PagerDuty / Slack連携
- マルチテナント

---

## 実装ステップ

### V1: 動く

1. DynamoDBテーブル設計・作成（tickets / assets）
2. Ticket Service / Asset Service 実装（FastAPI）
3. AgentCore Gateway 登録（OpenAPI spec → MCP変換）
4. Community Knowledge MCP群 実装・デプロイ（ARM64コンテナ → ECR → Runtime）
5. AgentCore Registry 登録（capability タグ付き）
6. A2Aエージェント群 実装・デプロイ（Triage / Diagnosis / Resolution）
7. Gateway Agent 実装・デプロイ（AG-UI protocol）
8. AgentCore Memory 設定
9. React UI 実装（Chat / Tickets / Knowledge タブ）

### V1.5: デモデータ自動生成

10. シナリオYAML作成（incidents/demo_incidents.yaml）
11. Demo Generator Agent 実装・デプロイ（AgentCore Browser）
12. シナリオを一通り流してDynamoDBにチケットを蓄積

### V2: 見える

13. OTEL計装（AgentCore Observability）
14. AWS Observability MCP群 デプロイ・Registry登録
15. Analysis Agent 実装・デプロイ
16. AgentCore Evaluations 設定
17. React UI Reports タブ追加

### V3: 進化する

18. DynamoDB Streams 有効化
19. Lambda（stream consumer）実装
20. Runbook Generator Agent 実装・デプロイ
21. SSM Automation Document テンプレート設計
22. 知識の結晶化ロジック実装（Knowledge テーブル自動更新）
23. 異常集積検知ロジック実装
24. React UI Runbooks タブ追加

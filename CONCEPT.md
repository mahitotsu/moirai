# Agora — コンセプトドキュメント

## プロジェクト概要

デモ用の監視対象システムで発生したアラームを起点に、自動起票・診断・解決提案・知識蓄積を行うマルチエージェントITサービスデスクのリファレンス実装。Amazon Bedrock AgentCoreの主要機能をフル活用し、「障害が発生する → エージェントが動く → 知識が積み上がる」という自律運用フローをエンドツーエンドでデモする。

---

## 解決する課題

ITインシデント発生時、エンジニアはCloudWatchのアラームに気づき、手動でチケットを起票し、Stack Overflow・GitHub Issues・公式ドキュメントを手動で探しながら対応する。この「アラーム検知 → 起票 → 知識検索 → 診断 → 解決提案 → 知識蓄積」のサイクルをマルチエージェントが代替することで、インシデント対応の自動化と継続的な改善を実現する。

---

## 設計原則

### 1. アラーム駆動のエンドツーエンド自動化
人手の介入なしに「監視対象の異常検知 → 自動起票 → エージェント診断 → 解決提案 → 知識蓄積」のサイクルを完結させる。Chat UIは人間によるアドホック質問や経過観察のインターフェースとして位置づける。

### 2. 責務分割されたマルチエージェント構成
単一の巨大エージェントは避ける。Triage・Diagnosis・Resolutionのように責務を明確に分割し、各エージェントが独立して開発・デプロイ・スケールできる構成にする。

### 3. 既存サービスのAPI契約を維持する
内部サービス（Ticket Service / Asset Service）はREST APIとして公開し続ける。エージェントはGateway経由でMCPツールとして利用し、UIはREST APIを直接呼び出す。APIの公開契約はエージェント導入後も変わらない。

### 4. ビジネスルールとコードの分離
各エージェントのSystem Promptを独立したファイルとして管理する。モデルの変更や業務ルールの更新をコードの変更なしに行える構造にする。

### 5. ケーパビリティベースの動的発見
エージェントはMCPサーバーのエンドポイントをハードコードしない。AgentCore RegistryにCapabilityタグを付けて登録し、エージェントは「community-knowledge能力を持つサービス」という形で動的に発見・呼び出す。

### 6. 業務データとエージェント文脈の分離
インシデント履歴などの業務データはTicket Service（DynamoDB）をSystem of Recordとして管理する。AgentCore Memoryは会話の継続性とユーザー固有の傾向の記憶に限定し、責務を混在させない。

---

## デモシナリオ（ゴールデンパス）

### メインシナリオ：監視駆動の完全自動化

```
[監視対象システム]
  fake-api-server (Lambda) が EventBridge Scheduler から定期実行
  → 正常時: 200 OK を返し CloudWatch メトリクスを生成

[FIS 障害注入]
  FIS 実験テンプレートを起動
  → Lambda に FIS Extension Layer 経由でエラー率を注入
  → 呼び出しエラー率が急上昇
  → CloudWatch アラームが ALARM 状態に遷移
  → SNS トピックに通知

[イベント駆動レイヤー]
  Bridge Lambda がSNS通知を受信
  → Ticket Service にチケットを自動起票 (status: open)
  → Gateway Agent へ診断依頼を POST

[エージェントパイプライン]
  Gateway Agent (AG-UI protocol でSSEストリーミング)
    ↓ A2A
  Triage Agent    : severity=high、category=api-error と分類
    ↓ A2A
  Diagnosis Agent : Registry で capability="community-knowledge" を持つ
                    MCP群を発見し並列検索
                    → Stack Overflow : 上位解決策を取得
                    → GitHub Issues  : 類似バグレポートを照合
                    → AWS Docs       : Lambda/FIS ドキュメントを参照
                    → Ticket Service : 過去の類似インシデントを確認
    ↓ A2A
  Resolution Agent: 状況に合わせた解決提案を生成
                    → Ticket を更新 (status: diagnosed, resolution: "...")

[React UI]
  Tickets タブ: 自動起票されたチケットと診断結果をリアルタイム確認
  Chat タブ   : エージェントの思考プロセスをSSEで観察
```

### サブシナリオ：アドホック質問・問い合わせ

Chat タブはインシデントの自動処理フローを観察しながら、その場で質問・照会できるインターフェース。

**受け付ける質問の種類**

| 質問例 | 使うツール |
|---|---|
| 「このエラーの一般的な原因は？」（障害事例・対応策） | Community Knowledge MCP群 |
| 「過去の解決済み事例でDBカテゴリが多いのはなぜ？」（傾向分析） | Ticket Service MCP |
| 「今対応中の重大インシデントはある？」（進捗・重大度確認） | Ticket Service MCP |
| 「fake-api-server のエラー率は今どのくらい？」（稼働状況確認） | CloudWatch MCP |
| 「このアラーム、手動で診断してほしい」（手動診断トリガー） | Triage→Diagnosis→Resolution パイプライン |

**扱わない操作（System Promptで明示的に禁止）**

- 実システムへの変更実行（Lambda再起動・設定変更など）— 提案・分析にとどめる
- FIS実験の操作（障害注入の開始・停止）— デモ環境の意図しない操作を防ぐ

### V3: 見える

```
Analysis Agent が起動
→ CloudWatch MCP : エージェント稼働メトリクスを取得
→ Cost Explorer MCP: Bedrock 利用コストを取得
→ Ticket Service : インシデント傾向を集計
→ レポートを DynamoDB に保存 → Reports 画面に表示
```

### V4: 進化する

```
DynamoDB Streams: Ticket が resolved に更新されたことを検知
→ Runbook Generator Agent を自動起動
→ SSM Automation Document としてランブックを生成・保存
→ Knowledge テーブルを自動更新（次回の Diagnosis Agent が活用）

同カテゴリのチケットが N件/30分 集積
→ Analysis Agent を即時起動（異常アラートレポート生成）
```

---

## アーキテクチャ

### 全体図

```
┌─────────────────────────────────────────────────────┐
│ 監視対象システム                                      │
│   fake-api-server (Lambda + FIS Extension Layer)     │
│   EventBridge Scheduler → 定期実行 → メトリクス生成  │
│   FIS 実験テンプレート  → エラー率注入               │
└─────────────────────────────────────────────────────┘
      ↓ 異常検知

┌─────────────────────────────────────────────────────┐
│ アラーム + イベント駆動レイヤー                       │
│   CloudWatch アラーム → SNS トピック                 │
│   Bridge Lambda                                      │
│     → Ticket Service: チケット自動起票               │
│     → Gateway Agent : 診断依頼 POST                  │
└─────────────────────────────────────────────────────┘
      ↕ AG-UI (SSE)

[React UI]
  ├── Chat タブ ────────── AG-UI (SSE) でエージェント思考を観察・アドホック質問
  ├── Tickets タブ ──────── Ticket Service REST API 直接
  ├── Knowledge タブ ────── Ticket Service REST API 直接
  ├── Reports タブ (V3) ─── Reports Service REST API 直接
  └── Runbooks タブ (V4) ── SSM API 直接

      ↕ AG-UI (SSE)

[Gateway Agent]                      AgentCore Runtime / AG-UI protocol
      ↕ A2A

┌─────────────────────────────────────────────────────┐
│ エージェント群              AgentCore Runtime / A2A  │
│   Triage Agent          インシデント分類・重大度判定  │
│   Diagnosis Agent       知識検索・類似事例照合        │
│   Resolution Agent      解決提案の生成               │
│   Analysis Agent (V3)   稼働レポート・傾向分析        │
│   Runbook Generator (V4) ランブック自動生成           │
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
│ AWS Observability MCP群 (V3) AgentCore Runtime / MCP │
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
│ 知識進化レイヤー (V4)                                 │
│   Lambda (stream consumer)                           │
│   → Ticket RESOLVED : Runbook Generator Agent 起動   │
│   → N件/30分集積    : Analysis Agent 即時起動        │
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
| Runtime (AG-UI) | Bridge Lambda からのPOSTと、UI向けSSEストリーミング | アラーム起動とChat UIの両方でエージェント出力をリアルタイム表示 |
| Runtime (A2A) | エージェント間直接通信 | Triage→Diagnosis→Resolutionの責務連鎖を疎結合に実現 |
| Runtime (MCP) | Community/Observability MCPサーバー | 外部知識源をツールとして統一的に扱う |
| Gateway | 内部サービスをMCPツール化 | 既存REST APIを変更せずエージェントから利用可能にする |
| Registry | capabilityベースの動的発見 | エージェントがサービスのエンドポイントをハードコードしない |
| Memory | 会話文脈・ユーザー傾向の記憶 | セッション継続性と個人化。業務データとは明確に分離 |
| Policy (V3) | エージェント間のツールアクセスをCedarポリシーで制御 | 責務分割をコードではなくインフラレベルで強制。Triage/Diagnosis は読み取り専用、Resolution のみ書き込み許可 |
| Evaluations (V3) | 解決提案の品質をLLM-as-a-Judgeで評価 | 主観的な品質を定量化し継続的改善の指標にする |
| Observability (V3) | OTELによるエンドツーエンドトレーシング | Bridge Lambda → エージェント間の処理フローをCloudWatchで可視化 |

## Bedrock 機能マッピング

| Bedrock機能 | 役割 | 採用理由 |
|---|---|---|
| Guardrails | Gateway Agent の入出力をポリシーで制御 | FIS操作・実システム変更をプロンプト外から強制ブロック。Denied Topics で Chat UI からの迂回を防ぐ |
| Prompt Caching (`strategy="auto"`) | 全エージェントのシステムプロンプトを自動キャッシュ | システムプロンプトが 1,024 トークンを超えた時点でコスト・レイテンシを自動削減 |

---

## コンポーネント詳細

### 監視対象システム

| コンポーネント | 役割 | 実装 |
|---|---|---|
| fake-api-server | デモ用の被監視Lambdaサービス。FIS Extension Layer を組み込み | Lambda (Python) |
| EventBridge Scheduler | fake-api-server を定期呼び出しして CloudWatch メトリクスを生成。**デフォルト無効**。デモ・データ蓄積時のみ有効化する | EventBridge Scheduler |
| CloudWatch アラーム | エラー率が閾値を超えたときにSNSへ通知 | CloudWatch + SNS |
| FIS 実験テンプレート | Lambda Extension 経由でエラーを注入し、障害シナリオを再現 | AWS FIS |

**デモ制御コマンド**

```
make demo-start   # Scheduler 有効化（トラフィック開始・正常メトリクス生成）
make demo-inject  # FIS 実験開始（障害注入・アラーム発火）
make demo-stop    # Scheduler 無効化 + 実行中 FIS 実験を強制終了（クリーンアップ）
```

> デモの流れ: `demo-start` で正常ベースラインを確立してから `demo-inject` で障害を注入する。中断・終了時は必ず `demo-stop` を実行する。

### Bridge Lambda

監視アラームをエージェントパイプラインへ橋渡しする中核コンポーネント。

```
SNS 通知受信
  → Ticket Service: チケット自動起票
      { title: "CloudWatch ALARM: {alarm_name}", status: "open", source: "cloudwatch" }
  → Gateway Agent (AG-UI HTTP POST): 診断依頼を送信
      { message: "アラーム '{alarm_name}' が発火しました。診断を開始してください。" }
```

### 内部サービス

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

### AWS Observability MCP群

| MCP | 用途 | 実装 | フェーズ |
|---|---|---|---|
| CloudWatch MCP | Diagnosis Agent が障害メトリクス・ログを参照 | awslabs/mcp 流用 | V2 |
| Cost Explorer MCP | Bedrock利用コスト分析 | awslabs/mcp 流用 | V3 |

### DynamoDB Streams 知識進化レイヤー（V4）

| イベント | トリガー | 処理 |
|---|---|---|
| Ticket RESOLVED | チケットがresolved に更新 | Runbook Generator Agent を起動 → SSM Automation Document を生成・更新 |
| Ticket RESOLVED | 同上 | Knowledge テーブルを自動更新（知識の結晶化） |
| N件/30分集積 | 同カテゴリのチケットが閾値超え | Analysis Agent を即時起動（異常アラートレポート生成） |

---

## UI構成

### React シングルページアプリ

| タブ | 内容 | データ取得方法 | フェーズ |
|---|---|---|---|
| Chat | エージェントの思考プロセス観察・アドホック質問 | AG-UI / SSE（エージェント経由） | V1 |
| Tickets | 自動起票されたインシデント一覧・詳細・診断結果 | Ticket Service REST API 直接 | V1 |
| Knowledge | 解決済みパターンのブラウズ | Ticket Service REST API 直接 | V1 |
| Reports | Analysis Agentの稼働レポート | Reports API 直接 | V3 |
| Runbooks | SSM Automation Document一覧 | SSM API 直接 | V4 |

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
| 監視対象システム | Lambda + FIS Extension Layer + EventBridge Scheduler |
| アラーム連携 | CloudWatch アラーム + SNS + Bridge Lambda |
| 知識進化 | DynamoDB Streams + Lambda (V3) |
| AWSリージョン | us-east-1 |
| モデル | Claude Sonnet (us.anthropic.claude-sonnet-4-6) |

---

## スコープ

### In（作る）

**V1: 動く（完了）**
- Ticket / Asset Service（FastAPI + DynamoDB）
- AgentCore Gateway（OpenAPI spec → MCP変換）
- Community Knowledge MCP群（Stack Overflow / GitHub Issues / Wikipedia / AWS Docs）
- AgentCore Registry
- A2Aエージェント群（Gateway / Triage / Diagnosis / Resolution）
- AG-UI + React UI（Chat / Tickets / Knowledge タブ）
- AgentCore Memory

**V2: 自動化する**
- 監視対象システム（fake-api-server + FIS Extension Layer）
- EventBridge Scheduler（定期実行・メトリクス生成・デフォルト無効）
- CloudWatch アラーム + SNS トピック
- Bridge Lambda（アラーム → 自動起票 + エージェント起動）
- FIS 実験テンプレート（障害注入シナリオ）
- CloudWatch MCP（Diagnosis Agent が障害メトリクスを参照するため）
- Makefile デモ制御ターゲット（demo-start / demo-inject / demo-stop）
- Chat UI 改修・Gateway Agent システムプロンプト更新（アドホック質問・問い合わせ対応）
- Bedrock Guardrails（Gateway Agent の禁止操作を Denied Topics でブロック）
- Bedrock Prompt Caching（全エージェントに `CacheConfig(strategy="auto")` を設定）

**V3: 見える**
- AgentCore Observability（OTEL計装）
- Cost Explorer MCP（Bedrock利用コスト分析）
- Analysis Agent（稼働レポート・インシデント傾向分析）
- AgentCore Evaluations
- React UI Reports タブ追加

**V4: 進化する**
- DynamoDB Streams + Lambda（知識進化レイヤー）
- Runbook Generator Agent → SSM Automation Documents
- 知識の結晶化（Ticket resolved → Knowledge テーブル自動更新）
- 異常集積検知（N件/30分 → Analysis Agent 即時起動）
- React UI Runbooks タブ追加

### Out（作らない）

- AgentCore Identity（ユーザー認証・OAuth委譲）
- AgentCore Code Interpreter
- 本物のJira / PagerDuty / Slack連携
- マルチテナント

---

## 実装ステップ

### V1: 動く（完了）

1. DynamoDBテーブル設計・作成（tickets / assets）
2. Ticket Service 実装（FastAPI + DynamoDB）
3. Asset Service 実装（FastAPI + DynamoDB）
4. AgentCore Gateway 登録（OpenAPI spec → MCP変換）
5. Community Knowledge MCP群 実装・デプロイ
6. AgentCore Registry 登録（capability タグ付き）
7. A2Aエージェント群 実装・デプロイ（Triage / Diagnosis / Resolution）
8. Gateway Agent 実装・デプロイ（AG-UI protocol）
9. AgentCore Memory 設定
10. React UI 実装（Chat / Tickets / Knowledge タブ）

### V2: 自動化する

11. 監視対象 Lambda 実装（fake-api-server + FIS Extension Layer）
12. EventBridge Scheduler 設定（定期呼び出しで負荷生成）
13. CloudWatch アラーム + SNS トピック設定
14. Bridge Lambda 実装（アラーム → Ticket 自動起票 + Gateway Agent POST）
15. FIS 実験テンプレート作成（invocation-error シナリオ）
16. CloudWatch MCP デプロイ・Registry登録（Diagnosis Agent が障害メトリクスを参照するため）
17. Chat UI 改修・Gateway Agent システムプロンプト更新（インシデント起票 → アドホック質問・問い合わせ、禁止操作の明示）
18. AgentCore Policy 設定（Gateway に Policy Engine 付与、エージェント別ツールアクセス制御）
19. エンドツーエンドデモ検証（FIS起動 → アラーム → 診断 → チケット）

### V3: 見える

20. OTEL計装（AgentCore Observability）
21. Cost Explorer MCP デプロイ・Registry登録（Bedrock利用コスト分析）
22. Analysis Agent 実装・デプロイ
23. AgentCore Evaluations 設定
24. React UI Reports タブ追加

### V4: 進化する

24. DynamoDB Streams 有効化
25. Lambda（stream consumer）実装
26. Runbook Generator Agent 実装・デプロイ
27. SSM Automation Document テンプレート設計
28. 知識の結晶化ロジック実装（Knowledge テーブル自動更新）
29. 異常集積検知ロジック実装
30. React UI Runbooks タブ追加

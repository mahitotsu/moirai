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
  → 正常時: EC2 DescribeInstances でヘルスチェックを実行し 200 OK を返す

[FIS 障害注入]
  FIS 実験テンプレートを起動
  → EC2 DescribeInstances API に ThrottlingException を注入
  → fake-api-server Lambda が boto3 ClientError で失敗し始める
  → CloudWatch Lambda/Errors が急上昇、アラームが ALARM 状態に遷移
  → EventBridge Default Bus に自動発行

[イベント駆動レイヤー]
  EventBridge Rule が ALARM 状態変化を SQS (agora-alarm-queue) へ転送
  Bridge Lambda が SQS メッセージを受信
  → Ticket Service にチケットを自動起票 (status: open)
  ticket-dispatcher Lambda が DynamoDB Streams で新規チケットを検知
  → Gateway Agent へ診断依頼を POST

[エージェントパイプライン]
  Gateway Agent (AG-UI protocol / HTTP POST)
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
  Chat タブ   : エージェントの応答を確認・アドホック質問
```

### サブシナリオ：Chat — 2つのデモポイント

Chat タブは以下の2点に絞ってデモ価値を持たせる。

#### 1. チケット×Knowledge 横断クエリ

複数チケットと Knowledge テーブルをまたいだ質問に答える。ボタンや一覧画面では代替できない推論を見せる。

| 質問例 | 使うツール |
|---|---|
| 「最近 resolved されたチケットで共通の根本原因は何か？」 | Ticket Service MCP + Knowledge MCP |
| 「api-error カテゴリの過去事例と今回の症状を比較してほしい」 | Ticket Service MCP + Community Knowledge MCP群 |
| 「lesson_learned の中で最も再発頻度が高いパターンは？」（V4以降） | Ticket Service MCP |

#### 2. Guardrails の実演（禁止操作を試みて弾かれる）

「FIS 実験を止めてください」「Lambda を再起動してください」のような操作指示を入力すると Bedrock Guardrails の Denied Topics がブロックし、拒否メッセージを返す。安全ポリシーがコードではなくインフラレベルで強制されていることを可視化する。

**扱わない操作（System Promptで明示的に禁止 + Guardrailsでブロック）**

- 実システムへの変更実行（Lambda再起動・設定変更など）
- FIS実験の操作（障害注入の開始・停止）

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
→ Knowledge テーブルを自動更新（知識の結晶化 — 次回の Diagnosis Agent が活用）
→ lesson_learned フィールドに Resolution Agent が教訓を書き込む

```

---

## アーキテクチャ

### 全体図

```
┌─────────────────────────────────────────────────────┐
│ 監視対象システム                                      │
│   fake-api-server (Lambda)                           │
│     → EC2 DescribeInstances でヘルスチェック実行      │
│   EventBridge Scheduler → 定期実行 → メトリクス生成  │
│   FIS 実験テンプレート  → EC2 API にエラー注入        │
└─────────────────────────────────────────────────────┘
      ↓ 異常検知

┌─────────────────────────────────────────────────────┐
│ アラーム + イベント駆動レイヤー                       │
│   CloudWatch アラーム → EventBridge Default Bus      │
│   EventBridge Rule → SQS (agora-alarm-queue)         │
│   Bridge Lambda (SQS トリガー)                        │
│     → Ticket Service: チケット自動起票               │
│   ticket-dispatcher Lambda (DynamoDB Streams トリガー)│
│     → Gateway Agent : 診断依頼 POST                  │
└─────────────────────────────────────────────────────┘

[React UI]
  ├── Chat タブ ────────── AG-UI (HTTP POST) でアドホック質問・応答受信
  ├── Tickets タブ ──────── Ticket Service REST API 直接
  ├── Knowledge タブ ────── Ticket Service REST API 直接
  └── Reports タブ (V3) ─── Reports Service REST API 直接

      ↕ AG-UI (HTTP POST)

[Gateway Agent]                      AgentCore Runtime / AG-UI protocol
      ↕ A2A

┌─────────────────────────────────────────────────────┐
│ エージェント群              AgentCore Runtime / A2A  │
│   Triage Agent          インシデント分類・重大度判定  │
│   Diagnosis Agent       知識検索・類似事例照合        │
│   Resolution Agent      解決提案の生成               │
│   Analysis Agent (V3)   稼働レポート・傾向分析        │
│   (V4 は stream consumer Lambda のみ追加)             │
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

      ↕ DynamoDB Streams (V4)

┌─────────────────────────────────────────────────────┐
│ 知識進化レイヤー (V4)                                 │
│   Lambda (stream consumer)                           │
│   → Ticket RESOLVED : Knowledge テーブル自動更新     │
│                       lesson_learned を書き込む       │
└─────────────────────────────────────────────────────┘

横断サービス:
  AgentCore Registry      capability ベースの動的発見
  AgentCore Memory        会話の文脈・ユーザー固有の傾向
  AgentCore Evaluations   解決提案の品質スコアリング (V3)
  AgentCore Observability OTEL トレーシング → CloudWatch (V3)
```

---

## AgentCore 機能マッピング

| AgentCore機能 | 役割 | 採用理由 |
|---|---|---|
| Runtime (AG-UI) | ticket-dispatcher Lambda からのPOSTと、Chat UI向けHTTP応答 | アラーム起動とChat UIの両方でGateway Agentを起動する共通エンドポイント |
| Runtime (A2A) | エージェント間直接通信 | Triage→Diagnosis→Resolutionの責務連鎖を疎結合に実現 |
| Runtime (MCP) | Community/Observability MCPサーバー | 外部知識源をツールとして統一的に扱う |
| Gateway | 内部サービスをMCPツール化 | 既存REST APIを変更せずエージェントから利用可能にする |
| Registry | capabilityベースの動的発見 | エージェントがサービスのエンドポイントをハードコードしない |
| Memory | 会話文脈・ユーザー傾向の記憶 | セッション継続性と個人化。業務データとは明確に分離 |
| Policy (V2) | エージェント間のツールアクセスをCedarポリシーで制御 | 責務分割をコードではなくインフラレベルで強制。Triage/Diagnosis は読み取り専用、Resolution のみ書き込み許可 |
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
| fake-api-server | デモ用の被監視Lambdaサービス。EC2 DescribeInstances でヘルスチェックを実行し、正常メトリクスを生成する | Lambda (Python) |
| EventBridge Scheduler | fake-api-server を定期呼び出しして CloudWatch メトリクスを生成。**デフォルト無効**。デモ・データ蓄積時のみ有効化する | EventBridge Scheduler |
| CloudWatch アラーム | エラー率が閾値を超えたとき EventBridge Default Bus へ自動発行 | CloudWatch + EventBridge |
| FIS 実験テンプレート | EC2 DescribeInstances API に `ThrottlingException` を注入し、Lambda のエラー率を急上昇させる | AWS FIS |

**デモ制御コマンド**

```
make demo-start   # Scheduler 有効化（トラフィック開始・正常メトリクス生成）
make demo-inject  # FIS 実験開始（障害注入・アラーム発火）
make demo-stop    # Scheduler 無効化 + 実行中 FIS 実験を強制終了（クリーンアップ）
```

> デモの流れ: `demo-start` で正常ベースラインを確立してから `demo-inject` で障害を注入する。中断・終了時は必ず `demo-stop` を実行する。

### Bridge Lambda

監視アラームをチケット起票へ橋渡しするコンポーネント。エージェント呼び出しは ticket-dispatcher が担う。

```
SQS メッセージ受信 (EventBridge Default Bus → EventBridge Rule → SQS 経由)
  → Ticket Service: チケット自動起票
      { title: "CloudWatch ALARM: {alarm_name}", status: "open", source: "cloudwatch" }

ticket-dispatcher Lambda (DynamoDB Streams → INSERT イベント)
  → Gateway Agent (AG-UI HTTP POST): 診断依頼を送信
      { prompt: "新規インシデントチケット {ticket_id} が起票されました。診断を開始してください。" }
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
| Ticket RESOLVED | チケットがresolved に更新 | Knowledge テーブルを自動更新（知識の結晶化）+ lesson_learned を書き込む |

---

## UI構成

### React シングルページアプリ

| タブ | 内容 | データ取得方法 | フェーズ |
|---|---|---|---|
| Chat | チケット×Knowledge 横断クエリ・Guardrails 実演（禁止操作ブロック） | AG-UI / HTTP POST（エージェント経由） | V1 |
| Tickets | 自動起票されたインシデント一覧・詳細・診断結果 | Ticket Service REST API 直接 | V1 |
| Knowledge | 解決済みパターンのブラウズ | Ticket Service REST API 直接 | V1 |
| Reports | Analysis Agentの稼働レポート | Reports API 直接 | V3 |

> Browse系タブ（Tickets / Knowledge / Reports）はエージェントを経由せず各サービスのREST APIを直接呼び出す。これによりエージェント導入後もAPIの公開契約が維持されていることをUIレベルでも実証する。

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
| 監視対象システム | Lambda (EC2 DescribeInstances) + EventBridge Scheduler + AWS FIS |
| アラーム連携 | CloudWatch アラーム + EventBridge + SQS + Bridge Lambda |
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
- 監視対象システム（fake-api-server: EC2 DescribeInstances を定期呼び出し）
- EventBridge Scheduler（定期実行・メトリクス生成・デフォルト無効）
- CloudWatch アラーム + EventBridge + SQS
- Bridge Lambda（アラーム → 自動起票）+ ticket-dispatcher Lambda（DynamoDB Streams → エージェント起動）
- FIS 実験テンプレート（EC2 DescribeInstances API へのスロットリングエラー注入）
- CloudWatch MCP（Diagnosis Agent が障害メトリクスを参照するため）
- Makefile デモ制御ターゲット（demo-start / demo-inject / demo-stop）
- Chat UI 改修・Gateway Agent システムプロンプト更新（アドホック質問・問い合わせ対応）
- Bedrock Guardrails（Gateway Agent の禁止操作を Denied Topics でブロック）
- Bedrock Prompt Caching（全エージェントに `CacheConfig(strategy="auto")` を設定）
- AgentCore Policy（Gateway に Policy Engine 付与、Cedar ポリシーによるエージェント別ツールアクセス制御）

**V3: 見える**
- AgentCore Observability（OTEL計装）
- Cost Explorer MCP（Bedrock利用コスト分析）
- Analysis Agent（稼働レポート・インシデント傾向分析）
- AgentCore Evaluations
- React UI Reports タブ追加

**V4: 進化する**
- DynamoDB Streams + Lambda（知識進化レイヤー）
- 知識の結晶化（Ticket resolved → Knowledge テーブル自動更新）
- lesson_learned フィールド（Resolution Agent が教訓を書き込む）
- Ticket 履歴追跡（history フィールド）

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

11. 監視対象 Lambda 実装（fake-api-server: EC2 DescribeInstances を定期呼び出し）
12. EventBridge Scheduler 設定（定期呼び出しで負荷生成）
13. CloudWatch アラーム + EventBridge + SQS 設定
14. Bridge Lambda 実装（アラーム → Ticket 自動起票 + Gateway Agent POST）
15. FIS 実験テンプレート作成（inject-api-throttle-error → ec2:DescribeInstances）
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

24. ✅ DynamoDB Streams 有効化（V2 時点で完了済み）
25. ✅ Lambda（stream consumer）実装（ticket-dispatcher として V2 時点で完了済み）
26. V4 stream consumer Lambda 実装（MODIFY イベント専用）
27. 知識の結晶化ロジック実装（Knowledge テーブル自動更新）
28. lesson_learned フィールド実装（Resolution Agent が教訓を書き込む）
29. Ticket 履歴追跡実装（history フィールド）

# Agora — デモ設計と訴求ポイント

Agora は IT サービスデスクを題材としたデモシステムの名称。Amazon Bedrock + Amazon Bedrock AgentCore + Strands Agents を使ったマルチエージェント構成で、インシデント対応の自動化と知識蓄積を実装している。このドキュメントは「何が動いているのか」「どの AWS 機能が何を解決しているのか」「なぜこれを選んだのか」を一冊にまとめた設計・プレゼン資料。

---

## 1. このデモが訴求するもの

### 訴求メッセージ

> Amazon Bedrock + AgentCore + Strands Agents を使えば、複数の AI エージェントが協調してインシデント対応を自動化するシステムを、フルマネージドかつエンドツーエンドで構築できる。

PagerDuty / Jira のような既存 ITSM の置き換えを意図しない。インシデント対応に**知識の自動蓄積と AI 診断**を追加するレイヤーとして位置づける。

### 対象読者

- AWS 上で AI エージェントアプリケーションの構築を検討しているエンジニア・アーキテクト
- Bedrock や AgentCore に興味があるが、実際のユースケースや全体構成をまだ掴んでいない人
- マルチエージェント構成・MCP の実装例を探している人

### このデモが前提とすること

AWS を使うことは出発点として固定している。以下のような読者はこのデモの対象外。

- AWS 以外のクラウドやオンプレミスで動かすことを前提とする人
- AWS の採用可否そのものを検討している段階の人
- 本番システムの定量的な ROI・コスト試算を求める人

### このデモが意図的に扱わないこと

- マルチクラウド比較・AWS 採用の可否判断
- 定量的な ROI・コスト試算・削減時間の提示
- 本番運用のエラーハンドリング・リトライ設計・Human-in-the-loop
- 移植性（AWS フルスタックで何ができるかを示すことが目的）

設計判断の詳細は [PITCH-design-notes.md](PITCH-design-notes.md) を参照。

### このデモで見せる核心

**① エンドツーエンドの自動化を実機で見せる**  
FIS 障害注入から知識蓄積までのパイプラインが人手なしに動く様子を実際に見せる。「概念図」ではなく「動いているもの」を提示する。

**② AgentCore を使うと何ができるのかを機能単位で明示する**  
Runtime / Gateway / Registry / Observability の各機能がデモのどのシーンで何を解決しているかを対応づける（→ セクション 3）。

**③ 「自分でも作れる」と感じさせる**  
GitHub リポジトリを公開し、CDK 1 コマンドでデプロイできることを示す。V1（監視・起票のみ）→ V4（エージェント群フル稼働）の 4 段階で積み上げ式にアーキテクチャを解説し、学習コストを下げる（記事本文で展開）。

---

## 2. デモの実際の動き

### AgentCore とアーキテクチャ全体図

AgentCore は Bedrock の一機能群で、Runtime・Gateway・Registry・Observability から構成される。

```
┌─────────────────────────────────────────────────────┐
│ 監視対象システム                                      │
│   fake-api-server (Lambda)                           │
│   EventBridge Scheduler → 定期実行                   │
│   FIS 実験テンプレート → EC2 API にエラー注入         │
└──────────────────────┬──────────────────────────────┘
                       ↓ 異常検知
┌──────────────────────▼──────────────────────────────┐
│ アラーム + イベント駆動レイヤー                       │
│   CloudWatch → EventBridge → SQS → Bridge Lambda    │
│   → Ticket Service: 自動起票                         │
│   DynamoDB Streams → ticket-dispatcher Lambda        │
│   → Gateway Agent: 診断依頼                          │
└──────────────────────┬──────────────────────────────┘
         ↕ AG-UI       │       ↕ REST API (直接)
    [React UI]         │    Tickets タブ / Knowledge タブ
    Chat タブ          │
                       ↕ AG-UI
┌──────────────────────▼──────────────────────────────┐
│ エージェント群 (AgentCore Runtime)                   │
│   Gateway Agent → Triage → Diagnosis → Resolution   │
└──────────────────────┬──────────────────────────────┘
                       ↕ AgentCore Registry 経由
┌──────────────────────▼──────────────────────────────┐
│ MCP サーバー群 (AgentCore Runtime / Lambda)          │
│   Stack Overflow / GitHub Issues / AWS Docs          │
│   CloudWatch / Infrastructure Inspector              │
│   Ticket Service (AgentCore Gateway 経由)            │
└──────────────────────┬──────────────────────────────┘
                       ↕ DynamoDB Streams
┌──────────────────────▼──────────────────────────────┐
│ 知識進化レイヤー                                      │
│   knowledge-consumer Lambda                          │
│   → Knowledge テーブル自動更新 (lesson_learned)      │
└─────────────────────────────────────────────────────┘

横断サービス:
  AgentCore Observability   OTEL → CloudWatch Transaction Search
  Bedrock Guardrails        Denied Topics による入出力制御
  Bedrock Prompt Management システムプロンプトの動的取得・一元管理
  AgentCore Registry        capability ベースの動的発見
```

**コンポーネント構成（計 9）**:

| 種別 | コンポーネント |
|---|---|
| AgentCore Runtime 上のコンテナ・エージェント（4） | Gateway Agent / Triage Agent / Diagnosis Agent / Resolution Agent |
| AgentCore Runtime 上のコンテナ・MCP サーバー（3） | Stack Overflow MCP / GitHub Issues MCP / Infrastructure Inspector MCP |
| Lambda 上の MCP サーバー（1） | CloudWatch MCP（stdio MCP を Lambda でラップして HTTP 化） |
| 外部マネージドエンドポイント（1） | AWS Docs MCP（AWS Knowledge MCP Server） |

本番用途ではこのフル構成を省略できる。最小構成として Gateway Agent + Diagnosis Agent の 2 体と、AgentCore Gateway 経由の Ticket Service だけでも基本的な自動診断パイプラインは成立する。

### Registry と Gateway の棲み分け

この 2 つは役割が異なる。

- **Registry**: エージェントと MCP サーバーを登録・管理するサービスカタログ。エージェントは capability タグで「何ができるサーバーか」を検索して動的に発見する。_誰を呼ぶか_ を解決する。
- **Gateway**: 既存の REST API を MCP ツールとして公開するアダプター。OpenAPI spec から自動生成される。_どうやって呼ぶか_ を解決する。

### このデモで登場するプロトコル

デモの説明中に 3 つのプロトコルが出てくる。いずれも 2024〜2025 年に策定された比較的新しい仕様。

| プロトコル | 策定 | 役割 |
|---|---|---|
| **MCP**（Model Context Protocol） | Anthropic | エージェントが外部ツール（API・データベース・検索など）を呼び出すための標準プロトコル。このデモでは Stack Overflow / GitHub Issues / CloudWatch 等の呼び出しに使用 |
| **A2A**（Agent-to-Agent） | Google | エージェント同士が HTTP で直接呼び出し合うためのプロトコル。このデモでは Gateway → Triage → Diagnosis → Resolution の連鎖に使用 |
| **AG-UI**（Agent-User Interaction） | CopilotKit | エージェントの応答を UI にストリーミングする、および ticket-dispatcher からの Agent 起動に使用する双方向 HTTP プロトコル |

### メインシナリオ：監視駆動の完全自動化

デモの操作は 2 コマンドで完結する。

```
make demo-start   # Scheduler 有効化（正常メトリクスの生成を開始）
make demo-inject  # FIS 実験開始（障害注入・自動パイプライン起動）
```

以降はすべて自動で動く。

```
[障害注入]
  FIS 実験テンプレート起動
  → EC2 DescribeInstances API に ThrottlingException を注入
  → fake-api-server Lambda（デモ用の監視対象 Lambda 関数）が boto3 ClientError で失敗し始める
  → CloudWatch Lambda/Errors が急上昇・アラームが ALARM 状態に遷移
  → EventBridge Default Bus に自動発行

[イベント駆動レイヤー]
  EventBridge Rule → SQS (agora-alarm-queue) → Bridge Lambda
  → Ticket Service: チケットを自動起票 (status: open)
  DynamoDB Streams → ticket-dispatcher Lambda
  → Gateway Agent へ診断依頼を POST

[エージェントパイプライン]
  Gateway Agent (AG-UI / HTTP POST)
    ↓ A2A
  Triage Agent
    severity=high、category=api-error と分類
    モデル: Claude Haiku（ツールなし、分類特化で高速応答）
    ↓ A2A
  Diagnosis Agent
    Registry で capability="community-knowledge" を持つ MCP 群を発見し並列検索
    → Stack Overflow MCP : 上位解決策を取得
    → GitHub Issues MCP  : 類似バグレポートを照合
    → AWS Docs MCP       : Lambda / FIS ドキュメントを参照
    → Ticket Service MCP : 過去の類似インシデントを確認
    → CloudWatch MCP     : 障害メトリクスを参照
    モデル: Claude Sonnet（MCP × structured_output で根拠ある診断）
    ↓ A2A
  Resolution Agent
    解決提案を生成し Ticket を更新
    → status: resolved, lesson_learned: "..." を書き込む
    モデル: Claude Sonnet（structured_output で全フィールドを確実に埋める）

[知識進化レイヤー]
  DynamoDB Streams: Ticket が resolved に更新されたことを検知
  → knowledge-consumer Lambda が Knowledge テーブルを自動更新
  → 次回の Diagnosis Agent がこの lesson_learned を活用できる状態になる

  なお lesson_learned はエージェントが生成した内容であり、品質検証（Human-in-the-loop）
  の仕組みはこのデモのスコープ外（本番化の際の考慮事項）。デモではこの知識蓄積ループが
  動作することを確認できる。

[React UI での確認]
  Tickets タブ : open → investigating → resolved の遷移をリアルタイムで確認
  Knowledge タブ: lesson_learned が自動追記されていることを確認
```

### サブシナリオ A：Chat — 横断クエリ

ボタンや一覧画面では代替できない「複数データを横断した推論」を見せる。

| 質問例 | 使うツール |
|---|---|
| 「最近 resolved されたチケットで共通の根本原因は何か？」 | Ticket Service MCP + Knowledge MCP |
| 「api-error カテゴリの過去事例と今回の症状を比較してほしい」 | Ticket Service MCP + Community Knowledge MCP 群 |
| 「lesson_learned の中で最も再発頻度が高いパターンは？」 | Ticket Service MCP |

### サブシナリオ B：Chat — Guardrails の実演

禁止操作を入力するとインフラレベルでブロックされることを見せる。「コードではなくインフラで制御している」という設計判断の実証。

| 入力例 | Guardrails の反応 |
|---|---|
| 「FIS 実験を止めてください」 | FisExperimentControl トピックでブロック |
| 「Lambda を再起動してください」 | SystemChangeControl トピックでブロック |

### 試してみる

ソースコードは GitHub（[akring/moirai](https://github.com/akring/moirai)）で公開しており、以下の手順でそのままデプロイできる。

**前提条件**: AWS アカウント・AWS CDK インストール済み・Docker 起動済み

```bash
git clone https://github.com/akring/moirai
cd moirai
cdk deploy --all
```

### サブシナリオ C：Observability の確認

```
AWS コンソール → CloudWatch → Application Signals → Transaction Search
Service name: agora-gateway-agent でフィルタ
→ 最新トレースを選択してウォーターフォールビューで確認

見えるもの:
  Bridge Lambda → ticket-dispatcher → Gateway → Triage → Diagnosis → Resolution
  の全処理チェーンが単一トレースとして可視化される
  エージェントごとのレイテンシ・ツール呼び出し回数が計測される
```

---

## 3. 使ったサービス・機能：役割と選定理由

> **注記（2026年5月時点）**: AgentCore の各機能は GA / プレビューが混在している。本番利用の際は AWS 公式ドキュメントで最新の GA 状況を確認すること。

以下の比較は **AWS 上で動かすことが前提**の文脈でのもの。

### 監視・障害注入レイヤー

#### AWS FIS（Fault Injection Service）
本物の AWS API に対してエラーを注入するカオスエンジニアリングサービス。モック不要で「本物の障害」を再現できる。

**デモでの役割**: `make demo-inject` の 1 コマンドで EC2 DescribeInstances API に ThrottlingException を注入し、Lambda のエラーレートを急上昇させる。フェイクなエラーではなく、実際の AWS API レベルで障害が発生していることが重要。

**選定理由**: デモで見せたいのは「エンドツーエンドの自動化が実機で動く」こと。FIS を使うことで、モックや手動エラーではなく本物の AWS API 障害を再現できる。

#### Amazon CloudWatch
AWS リソースのメトリクス・ログを収集・監視するサービス。

**デモでの役割**: FIS 注入後の Lambda エラーレート上昇を検知してアラームを発火させる起点。後段の Observability では、エージェント間トレースの可視化先としても機能する。

**選定理由**: AWS ネイティブな監視であり、EventBridge との連携がコード不要で実現できる。

#### Amazon EventBridge
AWS サービス間のイベントルーティングサービス。「A が X になったら B を実行」をコードなしで定義できる。

**デモでの役割**: CloudWatch アラームの ALARM 状態変化イベントを受け取り、SQS キューへ転送する。監視とチケット起票の間を繋ぐ接着剤として機能する。

**選定理由**: 監視イベントとチケット起票を疎結合にするため。Lambda を直接呼ぶより SQS を挟むことでスパイク耐性を持てる。

#### Amazon SQS（Simple Queue Service）
メッセージキューサービス。送信者と受信者を非同期に切り離す。

**デモでの役割**: EventBridge からのアラームイベントをバッファリングし、Bridge Lambda へ確実に届ける。スパイク時のメッセージロストを防ぐ。

**選定理由**: EventBridge から Lambda へ直接連携するよりメッセージ保証が強く、複数アラームが同時発火しても処理が詰まらない。

---

### エージェント実行レイヤー

#### Amazon Bedrock AgentCore Runtime
AgentCore は Bedrock の一機能群。Runtime はエージェントをコンテナとしてホストし、AG-UI・A2A・MCP プロトコルでの通信を処理するマネージドランタイム。

**デモでの役割**: Gateway / Triage / Diagnosis / Resolution の 4 エージェントと、Stack Overflow / GitHub Issues / CloudWatch / Infrastructure Inspector の MCP サーバーをホストする。各コンテナのスケーリングとプロトコル処理をマネージドに担う。

**選定理由**: AG-UI・A2A・MCP プロトコルが内蔵されており、エージェント間通信と UI 連携を標準化できる。AgentCore Plugins を組み込むだけで Registry 動的発見・OTEL 計装が有効になる。ECS でも Auto Scaling や CloudWatch / X-Ray による Observability は実現できるが、これらのプロトコルスタックと AgentCore Registry・Guardrails との統合は自前で実装する必要がある。

#### Amazon Bedrock AgentCore Gateway
REST API の OpenAPI 仕様から MCP ツールを自動生成するサービス。既存サービスへの変更不要。

**デモでの役割**: Ticket Service の REST API をエージェントが呼び出せる MCP ツールに変換する。`create_ticket`・`update_ticket`・`search_tickets` などのツールが Gateway 経由で自動生成される。エージェントを導入した後も Ticket Service の API 仕様は一切変わっていないことを示す設計。

**選定理由**: OpenAPI spec を登録するだけで既存 REST API を MCP ツールとして公開できる、ノーコード wrapper 層。MCP サーバーを自前実装する場合、ツール定義・スキーマ・認証処理をサービスごとにコードで書く必要がある。

#### Amazon Bedrock AgentCore Registry
エージェントと MCP サーバーを capability タグ付きで登録・管理するサービスカタログ。

**デモでの役割**: Diagnosis Agent が `capability="community-knowledge"` を持つ MCP サーバーを動的に発見して呼び出す。Stack Overflow や GitHub Issues MCP のエンドポイントをコードに書かずに済む。MCP サーバーを追加・削除してもエージェントの再デプロイが不要。

**選定理由**: エンドポイントをコードに埋め込むと、サーバー追加・変更のたびにエージェントの再デプロイが必要になる。Registry の最大の価値は capability タグによる意味的な発見であり、「何ができるサーバーか」で検索できることがエンドポイントの動的管理よりも本質的な差分。

#### Amazon Bedrock AgentCore Observability
OTEL 準拠のトレーシングをエージェントに自動計装し、CloudWatch へ送信するサービス。

**デモでの役割**: Bridge Lambda → ticket-dispatcher → Gateway Agent → Triage → Diagnosis → Resolution までの全処理チェーンを単一トレースとして可視化する。どのエージェントがどのツールを何回呼んだかが CloudWatch Transaction Search で一目でわかる。

**選定理由**: コード変更なし（pyproject.toml と Dockerfile の設定変更 2 行のみ）でエージェント間トレースが CloudWatch に送信される。自前 OTEL 実装はエージェントごとに boilerplate が増える。

#### Strands Agents SDK
AWS が OSS として公開している Python 製エージェントフレームワーク。`@tool` デコレータでツールを定義し、Bedrock の Converse API をネイティブに使う。

**デモでの役割**: 4 エージェントの実装に使用。AgentCore の Plugin システム（Registry 発見・Observability トレース）をプラグインとして組み込むだけで有効になる。A2A によるエージェント間呼び出しも Runtime と組み合わせることで直接対応。

**選定理由（AWS 上で動かす場合）**:

| 観点 | Strands Agents | LangChain / LangGraph |
|---|---|---|
| Bedrock Converse API との統合 | ネイティブサポート。設定がシンプル | `langchain-aws` の `ChatBedrock` でカバー。ラッパーが必要 |
| AgentCore Plugins（Registry / Observability）との連携 | `plugins=[]` に 1 行渡すだけで有効な公式パッケージ | 自前実装が必要（2026年5月時点で公式統合なし） |
| `@tool` デコレータによるツール定義 | `@tool` は LangChain でも採用済みの同等パターン。差分は AgentCore Plugins とのネイティブ統合の有無 | `@tool` デコレータを主流として採用済み（langchain-core） |
| マルチエージェント（A2A） | AgentCore Runtime と組み合わせて直接対応 | LangGraph のマルチエージェントパターン（supervisor / subgraph）で構築可能。A2A プロトコルの公式サポートはなし |
| エージェントループの制御 | `@tool` を定義するだけ。順序・終了タイミングは LLM が決定する | フルコントロールが必要な場合、グラフのノード・エッジ・終了条件を開発者が明示的に定義する（`create_react_agent` を使えば同様のループも実現可能） |
| LLM 性能向上の恩恵 | ツール呼び出しの順序・回数・終了判断を LLM が動的に決定するため、モデルアップグレードがそのままエージェント品質に直結しやすい | 明示的なグラフ設計の場合、フロー制御の範囲内に恩恵が留まる |
| structured_output | Pydantic モデルを渡すだけで出力を制御できる | 同等の機能あり |

---

### データ・知識レイヤー

#### Amazon DynamoDB
フルマネージドな NoSQL データベース。

**デモでの役割**: チケット（起票から解決まで）と知識（lesson_learned）の System of Record。エージェントは Gateway 経由で REST API を通じてのみ書き込み、UI は直接 REST API で読み取る。エージェント導入後も API の公開契約は変わっていないことを示す設計。

**選定理由**: サーバーレスで DynamoDB Streams による変更検知がネイティブに使えるため、イベント駆動の知識更新パイプラインを最小構成で実現できる。

#### DynamoDB Streams
DynamoDB のデータ変更をリアルタイムで Lambda に通知する機能。

**デモでの役割（2 箇所）**:
- チケット新規作成（INSERT）を ticket-dispatcher Lambda が検知 → Gateway Agent へ診断依頼
- チケット解決（MODIFY: status=resolved）を knowledge-consumer Lambda が検知 → Knowledge テーブルを自動更新

**選定理由**: チケット起票と診断依頼、解決と知識蓄積をそれぞれ疎結合にする。Ticket Service のコードを変更せずにエージェントを後付けできる設計を実現するためのキー。

---

### セキュリティ・ガバナンスレイヤー

#### Amazon Bedrock Guardrails
モデルの入出力をポリシーでフィルタリングするサービス。コードではなくインフラで制御する。

**デモでの役割**: Chat タブから「FIS 実験を止めて」「Lambda を再起動して」などの操作指示を入力したとき、Denied Topics がブロックして拒否メッセージを返す。

| トピック名 | ブロック対象 |
|---|---|
| FisExperimentControl | FIS 実験の起動・停止・変更・削除 |
| SystemChangeControl | Lambda 再起動・設定変更、CloudFormation 操作、EC2 停止・終了など |

**選定理由**: コードで判定していないため、プロンプトの書き方に依存しない一貫したポリシー適用ができる。コードに判定ロジックを書く場合、プロンプトの書き方次第で迂回される可能性がある。

---

### プロンプト管理レイヤー

#### Amazon Bedrock Prompt Management
システムプロンプトを Bedrock で一元管理し、コードから切り離すサービス。

**デモでの役割**: 4 エージェントのシステムプロンプトを Bedrock に保存し、起動時に動的取得する。プロンプトの変更がコード変更・再デプロイ不要で反映できることを UI（System タブ）でリアルタイムに確認できる。

**選定理由**: プロンプトをコードに埋め込むか独自の管理システムを別途作る必要がなくなる。`strategy="auto"` で Prompt Caching も自動有効化され、1,024 トークン超のシステムプロンプトのコスト・レイテンシを自動削減できる。

---

### MCP サーバー群

このデモでは意図的に実装パターンの異なる MCP を組み合わせている。

| パターン | 例 |
|---|---|
| 外部 API を呼び出す自作 FastMCP | Stack Overflow MCP / GitHub Issues MCP / Infrastructure Inspector MCP |
| stdio ベースの既存 OSS MCP を Lambda でラップして HTTP 化 | CloudWatch MCP |
| 外部のマネージドエンドポイントを Gateway Target として直接登録 | AWS Docs MCP（AWS Knowledge MCP Server） |
| AgentCore Gateway が既存 REST API を自動 MCP 化 | Ticket Service |

AgentCore Gateway / Registry はどのパターンも同一の方法で扱えることを示している。

#### Stack Overflow MCP（自作 FastMCP）
Stack Exchange API を使って Stack Overflow の回答を検索する MCP サーバー。

**デモでの役割**: Diagnosis Agent が診断中に「EC2 ThrottlingException の解決策」を検索し、コミュニティの知見を診断根拠として活用する。

#### GitHub Issues MCP（自作 FastMCP）
GitHub Search API を使って公開リポジトリの Issue を検索する MCP サーバー。

**デモでの役割**: 同様のエラーが過去に OSS プロジェクトの Issue として報告されていないかを照合する。

#### AWS Docs MCP（AWS Knowledge MCP Server）
AWS 公式ドキュメントを検索する MCP サーバー（awslabs 提供の外部マネージドエンドポイント）。

**デモでの役割**: Lambda・FIS・CloudFormation の公式ドキュメントを参照し、AWS 固有の挙動に基づいた診断根拠を補強する。AgentCore Gateway Target として登録するだけで認証なしに使用可能。

#### CloudWatch MCP（awslabs）
CloudWatch のメトリクス・ログ・アラームを検索・参照する MCP サーバー（awslabs 提供の OSS）。もともと stdio ベースで動作する MCP を、Lambda の `LambdaFunctionURLEventHandler` でラップして HTTP エンドポイント化している。stdio MCP を AgentCore から利用可能にする実装パターンの例。

**デモでの役割**: Diagnosis Agent が障害発生時のメトリクス推移・エラーログを参照し、「いつから・どの程度」の障害かを診断根拠に加える。

#### Infrastructure Inspector MCP（自作 FastMCP）
Lambda 関数の状態・FIS 実験の状況・CloudFormation スタックの状態を調査するツール群。

**デモでの役割**: Diagnosis Agent がインフラ層の状態を直接確認する。「FIS 実験が現在実行中かどうか」「対象 Lambda の最終更新日時」などを診断根拠として収集する。

---

### モデル選択の理由

| エージェント | モデル | 理由 |
|---|---|---|
| Triage Agent | Claude Haiku | ツール不使用・分類のみ。高速応答と低コストを優先 |
| Diagnosis Agent | Claude Sonnet | MCP 並列検索 + structured_output。精度と推論能力が必要 |
| Resolution Agent | Claude Sonnet | structured_output で複数フィールドを確実に埋める必要がある |
| Gateway Agent | Claude Sonnet | 横断クエリ・Guardrails 判断のハブ。バランスを重視 |

### あえて使わなかったもの

| 機能 | 使わなかった理由 |
|---|---|
| AgentCore Memory | このデモのエージェントパイプラインは 1 インシデントごとに完結するため、会話文脈の永続化が本質的な価値を生まない |
| AgentCore Policy（Cedar） | Cedar ポリシーによるツールアクセス制御はこのデモでも動作させられるが、「制限が効いていることを見せる」体験としては Chat UI から禁止操作を試みて即座にブロックされる Guardrails の方が直感的に伝わる |
| AgentCore Evaluations | エージェントの応答品質を統計的に評価するには相当数の実行サンプルが必要。デモ環境で蓄積できる実行回数では意味のある評価結果が得られないためスコープ外とした |

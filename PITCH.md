# Agora — デモ設計と訴求ポイント

Amazon Bedrock + Amazon Bedrock AgentCore + Strands Agents を使ったマルチエージェント IT サービスデスクのデモ。このドキュメントは「なぜこのデモになったか」「何が動いているのか」「どの AWS 機能が何を解決しているのか」を一冊にまとめた設計・プレゼン資料。

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

---

## 2. デモ設計の判断プロセス

デモ内容を決める前に、このデモを見る可能性のある 6 種類の読者像（ペルソナ）を設定し、それぞれがどんな懸念・期待を持つかをシミュレーションした。

### ペルソナと懸念

#### P1: 「LangChain/CrewAI でいいじゃないか」派

OSS でエージェントを組んだ経験があり、AgentCore の追加価値に懐疑的。

> Strands SDK って何？LangChain と何が違うの？  
> Registry の動的発見は LangGraph subgraph でもできるよね？  
> AgentCore Runtime って結局コンテナ動かすだけでしょ。ECS でいいじゃん。

**懸念の核心**: AgentCore / Strands を選ぶ「差分」が見えない。

---

#### P2: 「Azure/GCP 版もあるよね」マルチクラウド派

他クラウドの AI エージェントサービスも検討済み。AWS 固有の価値を問う。

> Azure AI Foundry でも同じようなことできるよね。AWS を選ぶ理由は？  
> CloudWatch → EventBridge → SQS → Lambda の連鎖は AWS べったりで移植できない。  
> AgentCore ってまだプレビューじゃないの？

**懸念の核心**: 既存 AWS 環境との統合以外に、AWS を選ぶ積極的な理由が見えない。

---

#### P3: 「コスト・オペ負荷が怖い」慎重派

本番運用を想定してデモを見ている SRE / インフラエンジニア。

> コンテナが 9 個あるけど、全部の面倒を見ないといけないの？  
> 1 インシデントあたりのモデル呼び出しコストっていくら？  
> エージェントが失敗したときのリトライ設計はどうなってる？

**懸念の核心**: デモは動くが、本番運用のコストと複雑さが不透明。

---

#### P4: 「AgentCore 何もわからない」初見派

AWS エンジニアだが AgentCore は初めて。記事で初めてこのシステムに触れた読者。

> AgentCore って Bedrock の一部？ 別サービス？  
> Runtime / Gateway / Registry / Memory / Policy... 機能多すぎて全体像が掴めない。  
> アーキテクチャ図のコンポーネントが多くて追えない。  
> 自分でゼロから作れる気がしない。

**懸念の核心**: AgentCore の学習コストが高く、「自分でもできそう」という感覚が得られない。

---

#### P5: 「ビジネス価値は何？」ビジネス視点

技術に理解のあるエンジニアリングマネージャーや PM。

> FIS で障害注入して自動チケット... PagerDuty + Jira でよくない？  
> エンジニアの何時間が削減されるの？  
> lesson_learned の自動蓄積はいいけど、知識が正しいか誰が検証するの？

**懸念の核心**: 技術的な面白さはわかるが、具体的なビジネスインパクトが不明確。

---

#### P6: 「とにかく AWS が嫌」派

AWS への依存そのものへの反感を持つ。イデオロギー的で論理では動かしにくい。

> AWS のサービス名多すぎ。全部覚えないと使えないの？  
> AgentCore なんてまた新サービス出して、どうせ 3 年後に廃止されるんでしょ。  
> データ全部 AWS に預けたくない。  
> 結局 AWS にお金払い続けないと何もできない構成じゃん。

**懸念の核心**: AWS への依存そのもの（コスト・廃止リスク・データ主権）への反感。

---

### 訴求ポイントの仕分け

6 体の懸念を「デモ・記事で対処する」「あえて対処しない」で仕分けた。

#### 対処する

| 懸念 | 対処方針 |
|---|---|
| Strands SDK が何かわからない | LangChain との差分を記事で説明（→ セクション 4） |
| AgentCore Runtime / Registry / Gateway の付加価値が見えない | 機能選択の根拠を「なぜ使ったか」で説明（→ セクション 4） |
| AgentCore の GA / Preview 状況がわからない | 記事執筆時点の状況を注記として明示 |
| 全体像が掴めない・コンポーネントが多い | 機能マッピング表と段階的なアーキテクチャ図で整理（→ セクション 3・5） |
| 自分で作れる気がしない | GitHub リポジトリ公開 + `cdk deploy` 1 コマンドで動くことを示す |
| PagerDuty + Jira との差分 | 「既存 ITSM の置き換えではなく知識蓄積・自動診断の追加レイヤー」と明示 |

#### あえて対処しない

| 懸念 | 対処しない理由 |
|---|---|
| Azure / GCP でも同じことできる | 比較記事ではなく AWS リファレンス実装。対象読者を冒頭で明示して範囲を定める |
| 移植できない・AWS べったり | 「AWS フルスタックで何ができるかを示す」が目的であり、移植性は設計優先事項ではない |
| コンテナ 9 個の運用負荷 | フル構成を見せることがデモの目的。本番化では省略可能と一言添えるに留める |
| 誤診断時のリトライ・エラーハンドリング | リファレンス実装のスコープ外。本番化の考慮事項として末尾に一言 |
| 定量的な ROI・削減時間 | デモは「可能性を示す」フェーズ。定性的な価値提示に留める |
| lesson_learned の検証は誰が？ | Human-in-the-loop 設計は本番化の考慮事項。デモのスコープ外 |
| A2A / MCP は半年後 LangChain が対応しそう | 将来予測の話。標準プロトコル採用でロック軽減という論拠には短く触れる |
| **P6 全般** | **P6 はこのデモの対象読者ではない。AWS を使う前提がない人への説得は目的としない** |
| モデル呼び出しコストは？ | コスト試算は構成・実行頻度・モデルに依存し、汎用的な数字を示すことが難しい。Prompt Caching による削減効果は Section 4 で定性的に示すに留める |

---

### デモ設計の結論

仕分けの結果、このデモで見せる核心は以下の 3 点に絞られた。

**① エンドツーエンドの自動化を実機で見せる**  
FIS 障害注入から知識蓄積までのパイプラインが人手なしに動く様子を実際に見せる。「概念図」ではなく「動いているもの」を提示する。

**② AgentCore を使うと何ができるのかを機能単位で明示する**  
Runtime / Gateway / Registry / Observability の各機能がデモのどのシーンで何を解決しているかを対応づける（→ セクション 4・5）。

**③ 「自分でも作れる」と感じさせる**  
GitHub リポジトリを公開し、CDK 1 コマンドでデプロイできることを示す。V1 → V4 の積み上げ式でアーキテクチャを説明し、学習コストを下げる。

---

## 3. デモの実際の動き

### このデモで登場するプロトコル

デモの説明中に 3 つのプロトコルが出てくる。いずれも 2024〜2025 年に策定された比較的新しい仕様。

| プロトコル | 策定 | 役割 |
|---|---|---|
| **MCP**（Model Context Protocol） | Anthropic | エージェントが外部ツール（API・データベース・検索など）を呼び出すための標準プロトコル。このデモでは Stack Overflow / GitHub Issues / CloudWatch 等の呼び出しに使用 |
| **A2A**（Agent-to-Agent） | Google | エージェント同士が HTTP で直接呼び出し合うためのプロトコル。このデモでは Gateway → Triage → Diagnosis → Resolution の連鎖に使用 |
| **AG-UI**（Agent-User Interaction） | Agentlabs | エージェントの応答を UI にストリーミングするための HTTP プロトコル。このデモでは Chat タブへのリアルタイム表示と ticket-dispatcher からの Gateway Agent 起動に使用 |

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
  → fake-api-server Lambda が boto3 ClientError で失敗し始める
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

ソースコードは GitHub で公開しており、`cdk deploy` 1 コマンドでそのままデプロイできる。

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

## 4. なぜ AWS / AgentCore / Strands を使ったのか

### AgentCore を使う理由

> **注記（2026年5月時点）**: AgentCore の各機能は GA / プレビューが混在している。本番利用の際は AWS 公式ドキュメントで最新の GA 状況を確認すること。

| 機能 | なぜ使ったか | ECS / 自前実装との比較 |
|---|---|---|
| **Runtime** | AG-UI・A2A・MCP プロトコルが内蔵されており、エージェント間通信と UI 連携を標準化できる。AgentCore Plugins を組み込むだけで Registry 動的発見・OTEL 計装が有効になる | ECS でも Auto Scaling や CloudWatch / X-Ray による Observability は実現できる。ただし AG-UI / A2A / MCP のプロトコルスタックと AgentCore Registry・Guardrails との統合は自前で実装する必要がある |
| **Gateway** | OpenAPI spec を登録するだけで既存 REST API を MCP ツールとして公開できる。MCP サーバーの実装コードを一切書かずに既存 API をエージェントから利用可能にするノーコード wrapper 層 | MCP サーバーを自前実装する場合、ツール定義・スキーマ・認証処理をサービスごとにコードで書く必要がある |
| **Registry** | エージェントが MCP サーバーのエンドポイントをハードコードせず、capability タグで動的発見できる | エンドポイントをコードに埋め込むと、サーバー追加・変更のたびにエージェントの再デプロイが必要になる |
| **Observability** | ADOT 自動計装により、コード変更なしでエージェント間トレースが CloudWatch に送信される | 自前 OTEL 実装はエージェントごとに boilerplate が増え、トレースの継続性を保つのが難しい |

### Strands Agents を使う理由

AWS が OSS として公開している Python 製エージェントフレームワーク。以下の比較は **AWS 上で動かすことが前提**の文脈でのもの。

| 観点 | Strands Agents | LangChain / LangGraph |
|---|---|---|
| Bedrock Converse API との統合 | ネイティブサポート。設定がシンプル | ラッパーが必要 |
| AgentCore Plugins（Registry / Observability）との連携 | 公式プラグインとして提供。組み込み 1 行で有効 | 自前実装が必要 |
| `@tool` デコレータによるツール定義 | 関数 1 つで完結 | Tool クラスや Runnable など複数パターンがある |
| マルチエージェント（A2A） | AgentCore Runtime と組み合わせて直接対応 | LangGraph の subgraph 等で実装可能だが標準化されていない |
| structured_output | Pydantic モデルを渡すだけで出力を制御できる。A2A でエージェントを連鎖させる際の受け渡しスキーマとして直接利用できる | 同等の機能あり |
| 実装の立ち上がり | `@tool` と `@agent` の組み合わせで動くエージェントをすぐに作れる。このデモの全エージェントも数十行で骨格を実装できた | Chain / Graph / Node など多くの概念の理解が先に必要 |

### Bedrock の機能を使う理由

| 機能 | なぜ使ったか | Bedrock を使わない場合 |
|---|---|---|
| **Guardrails** | モデルの入出力そのものをフィルタリングするためインフラレベルで強制できる | コードに判定ロジックを書く必要があり、プロンプトの書き方次第で迂回される可能性がある |
| **Prompt Caching** | 1,024 トークン超のシステムプロンプトを `strategy="auto"` だけでキャッシュ。コスト・レイテンシを自動削減 | キャッシュなしで毎回フルコストの推論が走る。多エージェント構成では呼び出しごとに積み上がる |
| **Prompt Management** | システムプロンプトを Bedrock に保存し、コード変更なしで更新できる | プロンプトをコードに埋め込むか、独自の管理・配信システムを別途作る必要がある |

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

---

## 5. 使ったサービス・機能がデモで果たした役割

### 監視・障害注入レイヤー

#### AWS FIS（Fault Injection Service）
本物の AWS API に対してエラーを注入するカオスエンジニアリングサービス。モック不要で「本物の障害」を再現できる。

**デモでの役割**: `make demo-inject` の 1 コマンドで EC2 DescribeInstances API に ThrottlingException を注入し、Lambda のエラーレートを急上昇させる。フェイクなエラーではなく、実際の AWS API レベルで障害が発生していることが重要。

#### Amazon CloudWatch
AWS リソースのメトリクス・ログを収集・監視するサービス。

**デモでの役割**: FIS 注入後の Lambda エラーレート上昇を検知してアラームを発火させる起点。後段の Observability では、エージェント間トレースの可視化先としても機能する。

#### Amazon EventBridge
AWS サービス間のイベントルーティングサービス。「A が X になったら B を実行」をコードなしで定義できる。

**デモでの役割**: CloudWatch アラームの ALARM 状態変化イベントを受け取り、SQS キューへ転送する。監視とチケット起票の間を繋ぐ接着剤として機能する。

#### Amazon SQS（Simple Queue Service）
メッセージキューサービス。送信者と受信者を非同期に切り離す。

**デモでの役割**: EventBridge からのアラームイベントをバッファリングし、Bridge Lambda へ確実に届ける。スパイク時のメッセージロストを防ぐ。

---

### エージェント実行レイヤー

#### Amazon Bedrock AgentCore Runtime
エージェントをコンテナとしてホストし、AG-UI・A2A・MCP プロトコルでの通信を処理するマネージドランタイム。

**デモでの役割**: Gateway / Triage / Diagnosis / Resolution の 4 エージェントと、Stack Overflow / GitHub Issues / CloudWatch / Infrastructure Inspector の MCP サーバーをホストする。各コンテナのスケーリングとプロトコル処理をマネージドに担う。

#### Amazon Bedrock AgentCore Gateway
REST API の OpenAPI 仕様から MCP ツールを自動生成するサービス。既存サービスへの変更不要。

**デモでの役割**: Ticket Service の REST API をエージェントが呼び出せる MCP ツールに変換する。`create_ticket`・`update_ticket`・`search_tickets` などのツールが Gateway 経由で自動生成される。エージェントを導入した後も Ticket Service の API 仕様は一切変わっていない。

#### Amazon Bedrock AgentCore Registry
エージェントと MCP サーバーを capability タグ付きで登録・管理するサービスカタログ。

**デモでの役割**: Diagnosis Agent が `capability="community-knowledge"` を持つ MCP サーバーを動的に発見して呼び出す。Stack Overflow や GitHub Issues MCP のエンドポイントをコードに書かずに済む。MCP サーバーを追加・削除してもエージェントの再デプロイが不要。

#### Amazon Bedrock AgentCore Observability
OTEL 準拠のトレーシングをエージェントに自動計装し、CloudWatch へ送信するサービス。

**デモでの役割**: Bridge Lambda → ticket-dispatcher → Gateway Agent → Triage → Diagnosis → Resolution までの全処理チェーンを単一トレースとして可視化する。どのエージェントがどのツールを何回呼んだかが CloudWatch Transaction Search で一目でわかる。

#### Strands Agents SDK
AWS 製の Python エージェントフレームワーク。`@tool` デコレータでツールを定義し、Bedrock の Converse API をネイティブに使う。

**デモでの役割**: 4 エージェントの実装に使用。AgentCore の Plugin システム（Registry 発見・Observability トレース）をプラグインとして組み込むだけで有効になる。A2A によるエージェント間呼び出しも Runtime と組み合わせることで直接対応。

---

### データ・知識レイヤー

#### Amazon DynamoDB
フルマネージドな NoSQL データベース。

**デモでの役割**: チケット（起票から解決まで）と知識（lesson_learned）の System of Record。エージェントは Gateway 経由で REST API を通じてのみ書き込み、UI は直接 REST API で読み取る。エージェント導入後も API の公開契約は変わっていないことを示す設計。

#### DynamoDB Streams
DynamoDB のデータ変更をリアルタイムで Lambda に通知する機能。

**デモでの役割（2 箇所）**:
- チケット新規作成（INSERT）を ticket-dispatcher Lambda が検知 → Gateway Agent へ診断依頼
- チケット解決（MODIFY: status=resolved）を knowledge-consumer Lambda が検知 → Knowledge テーブルを自動更新

---

### セキュリティ・ガバナンスレイヤー

#### Amazon Bedrock Guardrails
モデルの入出力をポリシーでフィルタリングするサービス。コードではなくインフラで制御する。

**デモでの役割**: Chat タブから「FIS 実験を止めて」「Lambda を再起動して」などの操作指示を入力したとき、Denied Topics がブロックして拒否メッセージを返す。コードで判定していないため、プロンプトインジェクションで迂回できない。

| トピック名 | ブロック対象 |
|---|---|
| FisExperimentControl | FIS 実験の起動・停止・変更・削除 |
| SystemChangeControl | Lambda 再起動・設定変更、CloudFormation 操作、EC2 停止・終了など |

---

### プロンプト管理レイヤー

#### Amazon Bedrock Prompt Management
システムプロンプトを Bedrock で一元管理し、コードから切り離すサービス。

**デモでの役割**: 4 エージェントのシステムプロンプトを Bedrock に保存し、起動時に動的取得する。プロンプトの変更がコード変更・再デプロイ不要で反映できることを UI（System タブ）でリアルタイムに確認できる。

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

## アーキテクチャ全体図

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

### Registry と Gateway の棲み分け

この 2 つは役割が異なる。

- **Registry**: エージェントと MCP サーバーを登録・管理するサービスカタログ。エージェントは capability タグで「何ができるサーバーか」を検索して動的に発見する。_誰を呼ぶか_ を解決する。
- **Gateway**: 既存の REST API を MCP ツールとして公開するアダプター。OpenAPI spec から自動生成される。_どうやって呼ぶか_ を解決する。

> このデモはフル構成を見せることが目的。本番用途では MCP サーバーを統合したり不要なエージェントを省いたりして構成をシンプルにできる。


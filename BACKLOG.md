# Agora — バックログ

> 実装の詳細・設計意図は [CONCEPT.md](CONCEPT.md) を参照。

## 現在のフォーカス

**フェーズ**: V4 完了・AgentCore 統合整備中  
**次のタスク**: `make cdk-deploy` → Registry/Gateway 整合確認 → E2Eデモ再確認

---

## V1: 動く（完了）

- [x] 1. DynamoDBテーブル設計・作成 (tickets / assets)
- [x] 2. Ticket Service 実装 (FastAPI + DynamoDB)
- [x] 3. Asset Service 実装 (FastAPI + DynamoDB)
- [x] 4. AgentCore Gateway 登録 (OpenAPI spec → MCP変換)
- [x] 5. Community Knowledge MCP群 実装・デプロイ
  - [x] 5a. Stack Overflow MCP (FastMCP + Stack Exchange API)
  - [x] 5b. GitHub Issues MCP (FastMCP + GitHub Search API)
  - [x] 5c. Wikipedia MCP (FastMCP + Wikipedia API)
  - [x] 5d. AWS Docs MCP (awslabs/mcp 流用)
- [x] 6. AgentCore Registry 登録 (capability タグ付き)
- [x] 7. A2Aエージェント群 実装・デプロイ
  - [x] 7a. Triage Agent
  - [x] 7b. Diagnosis Agent
  - [x] 7c. Resolution Agent
- [x] 8. Gateway Agent 実装・デプロイ (AG-UI protocol)
- [x] 9. AgentCore Memory 設定 ※後にスコープ外へ除外 (コスト対効果低・デモ価値薄) → CDK/agent.py から削除済み
- [x] 10. React UI 実装
  - [x] 10a. Chat タブ (AG-UI / SSE)
  - [x] 10b. Tickets タブ (REST API直接)
  - [x] 10c. Knowledge タブ (REST API直接)

## V2: 自動化する

- [x] 11. 監視対象 Lambda 実装 (fake-api-server: EC2 DescribeInstances を定期呼び出し)
- [x] 12. EventBridge Scheduler 設定 (定期呼び出しで負荷生成・デフォルト無効)
  - [x] 12a. Makefile デモ制御ターゲット実装 (demo-start / demo-inject / demo-stop)
- [x] 13. CloudWatch アラーム + EventBridge Rule + SQS(+DLQ) 設定
- [x] 14. Bridge Lambda 実装 (アラーム → Ticket 自動起票)
  - [x] 14a. ticket-dispatcher Lambda 実装 (DynamoDB Streams → Gateway Agent 呼び出し・V4先取り)
- [x] 15. FIS 実験テンプレート作成 (inject-api-throttle-error → ec2:DescribeInstances)
- [x] 16. CloudWatch MCP デプロイ・Registry登録 (Diagnosis Agent が障害メトリクスを参照するため)
  - [x] Registry登録をCDK Custom Resource (Lambda-backed) に移行・手動スクリプト廃止
  - [x] Diagnosis Agent に check_cloudwatch_alarms ツール追加
- [x] 17. Chat UI 改修・Gateway Agent システムプロンプト更新
  - [x] インシデント起票 UI → アドホック質問・問い合わせ UI に変更
  - [x] 受け付ける質問カテゴリ・禁止操作を Gateway Agent System Prompt に反映
  - [x] Bedrock Guardrails 設定 (FIS操作・実システム変更を Denied Topics でブロック)
  - [x] 全エージェントに Prompt Caching (`CacheConfig(strategy="auto")`) を設定
- [x] 18. AgentCore Policy 設定 (エージェント間ツールアクセス制御)
  - AgentCore Gateway に Policy Engine を付与
  - Triage Agent: `search_*` のみ許可、チケット作成・更新は禁止
  - Diagnosis Agent: `search_*` のみ許可、書き込み系ツールは全禁止
  - Resolution Agent: `create_ticket` / `update_ticket_resolution` のみ許可
- [x] 19. エンドツーエンドデモ検証 (FIS起動 → アラーム → 診断 → チケット)
  - Gateway execution role に `GetWorkloadAccessToken` + `GetResourceApiKey` を追加して Gateway → Lambda転送を修正
  - Resolution Agent system_prompt を修正: 既存チケットを `status:resolved` で更新するよう指示
  - E2E確認済み: Gateway MCP tool call → Lambda → DynamoDB ticket status=resolved
  - 再検証 (426406d): Makefile スタック名修正 / Category enum 追加 + TicketUpdate に category 追加 / タイムアウト 300s→900s

## V3: 見える

- [x] 20. OTEL計装 (AgentCore Observability)
  - 全エージェント (gateway/triage/diagnosis/resolution) に `aws-opentelemetry-distro` を追加
  - Dockerfile CMD を `opentelemetry-instrument python agent.py` に変更 (ADOT自動計装)
  - 全エージェントロール・MCPロールに X-Ray 送信権限を追加 (CDK)
  - `make obs-setup` ターゲット追加 (CloudWatch Transaction Search 一回限りのアカウント設定)
- [x] 21. Cost Explorer MCP デプロイ・Registry登録 ※後にスコープ外へ除外 → ea1220f で削除
- [x] 22. Analysis Agent 実装・デプロイ ※後にスコープ外へ除外 → ea1220f で削除
  - Analysis Agent・Reports Service・agora-reports テーブル・CloudFront `/api/reports*`・UI Reports タブを全削除
  - デモのメインストーリーと切れており、コンテンツも CloudWatch 等で代替可能なため除外
- [x] 23. AgentCore Evaluations 設定 ※スコープ外へ除外 → CDK/Makefile/scripts/eval_setup.py から削除済み
  - ADOT→X-Ray転送のサイレント失敗により OnlineEvaluationConfig が作成不可のため除外
- [x] 24. React UI Reports タブ追加 ※後にスコープ外へ除外 → ea1220f で削除

## V4: 進化する

- [x] 25. DynamoDB Streams 有効化 (`StreamViewType.NEW_AND_OLD_IMAGES` — V2 時点で完了済み)
- [x] 26. Lambda (stream consumer) 実装 (ticket-dispatcher が INSERT イベントを処理 — V2 時点で完了済み)
- [x] 27. V4 stream consumer Lambda 実装 (MODIFY イベント専用: ticket resolved → 知識結晶化)
- [x] 28. 知識の結晶化ロジック実装 (Ticket resolved → Knowledge テーブル自動更新)
- [x] 29. Ticket 履歴追跡実装 (`history: List[HistoryEntry]` を DynamoDB リスト属性として追加。エージェントが open/investigating/resolved 各遷移時に `{timestamp, status, note, actor}` を書き込む)
- [x] 30. `lesson_learned` フィールド実装 (Resolution Agent が close 時に1文の教訓を書き込む。Knowledge タブはこのフィールドを `resolution` の代わりに主表示に使用)
- [x] 31. Gateway Agent system_prompt 改訂 (Chat の役割を「チケット×Knowledge 横断クエリ」と「Guardrails 実演」に絞る。横断クエリを得意とする旨を明示し、Analysis Agent 起動などボタン代替可能な指示は受け付けない旨を追記)

---

## 保守・品質改善

- [x] ハードコード除去リファクタリング (0c532ef) — AWS リージョン・テーブル名・モデルID・Secret パスを環境変数/CDKトークンに移行
- [x] CDK deprecated 警告解消 (61655e9) — grant_* メソッドを add_to_policy に置換・DynamoEventSource/SqsQueue target をL1に置換
- [x] E2Eデモ検証 (531bb35) — Dockerfile commonモジュールパス修正・Guardrail出力ブロック解除・V4全機能パイプライン70秒で完走確認
- [x] E2Eデモ残存バグ修正 (2026-05-24) — 3件の問題を解消:
  - `lesson_learned` 未設定: Resolution Agent system_prompt を改訂し update_ticket 時の全必須フィールド (status/resolution/category/lesson_learned) を明示
  - 重複 history エントリ: `ticket-service/app/repository.py` に `data.status != existing.status` ガードを追加・DynamoDB Streams リトライで重複しないことをテストで確認
  - Chat タブ JSON parse エラー: CloudFront OAC → Lambda に `lambda:InvokeFunctionUrl` 権限を明示付与 (CDK) + `api.ts` に Content-Type チェックを追加
- [x] デモスコープ絞り込み (e5f7433 2026-05-24):
  - Wikipedia MCP・Asset Service を完全削除（デモストーリーと無関係）
  - Cedar Policy Engine を CDK から除去（LOG_ONLY モードで可視効果なし）
  - infrastructure-inspector FastMCP 追加（Lambda/FIS/CloudFormation 調査ツール・デモ診断フロー強化）
- [x] AgentCore 統合整備 (5b35733 2026-05-25):
  - MCP全5サーバーをport=8000/EXPOSE 8000に統一（AgentCore Runtime要件）
  - CfnGatewayTarget化（Lambda Custom Resource廃止・GATEWAY_IAM_ROLE + SigV4認証）
  - A2Aエージェント全4体をBedrockAgentCoreApp(@app.entrypoint)化
  - Gateway/Diagnosis/ResolutionをRegistry経由のMCP・サブエージェント動的発見に移行
  - agents/common/registry.py を共通モジュールとして作成
  - aws-docs/cloudwatchはportミスマッチ問題調査中のためGateway登録を一時スキップ
- [x] CloudWatch MCP を Lambda wrap に切り替え (2026-05-25):
  - `run-mcp-servers-with-aws-lambda` (BedrockAgentCoreApp) を採用
  - AgentCore Runtime (コンテナ) → Lambda + Function URL (AWS_IAM) に変更
  - `LambdaFunctionURLEventHandler` で stdio↔HTTP ブリッジ
  - `mcp_server` Gateway Target として登録 (service="lambda" SigV4)
- [x] Registry/Gateway 不整合修正 (f1a1520 2026-05-26):
  - agora-cloudwatch: runtime_name=None に修正 (Lambda wrap)・description 87文字に短縮 (schema ValidationException 修正)
  - agora-ticket-service: Registry MCP エントリ新規追加
  - agora-aws-knowledge: Registry MCP エントリ新規追加
  - _register_mcp: 空文字フィールドを条件付き追加に変更・_CATALOG_VERSION "14" に更新
- [x] aws-docs MCP → AWS Knowledge MCP Server 置き換え (2026-05-25):
  - aws-docs コンテナ (AgentCore Runtime) を廃止・mcp-servers/aws-docs/ を削除
  - AWS Knowledge MCP Server (https://knowledge-mcp.global.api.aws) を CfnGatewayTarget として直接登録
  - 認証不要エンドポイントは credential_provider_configurations を省略することで Gateway Target に登録可能と判明
  - agora-aws-knowledge が READY ステータスに遷移し、外部マネージドエンドポイントのプロキシが可能であることを確認
- [x] デモ品質整備 (d7f88c1 2026-05-24):
  - gateway/agent.py の run_analysis 未定義インポート削除（致命的バグ修正）
  - CONCEPT.md 整合性修正（削除済みコンポーネントへの全言及を除去・現状に合わせて刷新）
  - UI System タブ追加（エージェント・MCP一覧・System Prompt 表示・コピーボタン付き）

## 完了済み

- [x] リポジトリ構成・開発アーキテクチャ設計
- [x] uv workspace 設定 (pyproject.toml)
- [x] CDK DataStack 雛形 (DynamoDBテーブル定義)
- [x] Claude Code カスタマイズ (CLAUDE.md / settings.json / commands)
- [x] 初回コミット (6f6aff6) — プロジェクト全体の scaffold を Git 管理下に置いた

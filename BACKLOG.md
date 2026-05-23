# Agora — バックログ

> 実装の詳細・設計意図は [CONCEPT.md](CONCEPT.md) を参照。

## 現在のフォーカス

**フェーズ**: V4 完了  
**次のタスク**: 次のマイルストーンを検討中

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
- [x] 21. Cost Explorer MCP デプロイ・Registry登録 (Bedrock利用コスト分析)
  - `awslabs.billing-cost-management-mcp-server` を採用（旧 `awslabs-cost-explorer-mcp-server` は yanked）
  - `mcp-servers/cost-explorer/` 作成・ECR プッシュ・`AgoraCostExplorerRuntime` & Endpoint 作成
  - `mcp_runtime_role` に CE / Budgets / FreeTier / CostOptimizationHub 権限を追加
  - Registry CatalogVersion を 4 にバンプして再登録
- [x] 22. Analysis Agent 実装・デプロイ
  - `agents/analysis/` 作成: Strands A2A + boto3 tools (get_ticket_stats, get_lambda_error_metrics, get_bedrock_costs, save_report)
  - `services/reports-service/` 作成: FastAPI (GET/POST /reports)、`agora-reports` DynamoDB テーブル追加
  - Gateway Agent に `run_analysis` ツール追加・system_prompt 更新
  - CDK: agora-reports テーブル / ReportsServiceFn / AgoraAnalysisRuntime / CloudFront `/api/reports*` / CatalogVersion→5
- [x] 23. AgentCore Evaluations 設定 ※スコープ外へ除外 → CDK/Makefile/scripts/eval_setup.py から削除済み
  - ADOT→X-Ray転送のサイレント失敗により OnlineEvaluationConfig が作成不可のまま解決の目処が立たないためデモスコープから除外
- [x] 24. React UI Reports タブ追加

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

## 完了済み

- [x] リポジトリ構成・開発アーキテクチャ設計
- [x] uv workspace 設定 (pyproject.toml)
- [x] CDK DataStack 雛形 (DynamoDBテーブル定義)
- [x] Claude Code カスタマイズ (CLAUDE.md / settings.json / commands)
- [x] 初回コミット (6f6aff6) — プロジェクト全体の scaffold を Git 管理下に置いた

# Agora — バックログ

> 実装の詳細・設計意図は [CONCEPT.md](CONCEPT.md) を参照。

## 現在のフォーカス

**フェーズ**: V2 — 自動化する  
**次のタスク**: #19 エンドツーエンドデモ検証

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
- [x] 9. AgentCore Memory 設定
- [x] 10. React UI 実装
  - [x] 10a. Chat タブ (AG-UI / SSE)
  - [x] 10b. Tickets タブ (REST API直接)
  - [x] 10c. Knowledge タブ (REST API直接)

## V2: 自動化する

- [x] 11. 監視対象 Lambda 実装 (fake-api-server: DynamoDB GetItem を定期呼び出し)
- [x] 12. EventBridge Scheduler 設定 (定期呼び出しで負荷生成・デフォルト無効)
  - [x] 12a. Makefile デモ制御ターゲット実装 (demo-start / demo-inject / demo-stop)
- [x] 13. CloudWatch アラーム + EventBridge Rule + SQS(+DLQ) 設定
- [x] 14. Bridge Lambda 実装 (アラーム → Ticket 自動起票)
  - [x] 14a. ticket-dispatcher Lambda 実装 (DynamoDB Streams → Gateway Agent 呼び出し・V4先取り)
- [x] 15. FIS 実験テンプレート作成 (inject-api-throttle-error → dynamodb:GetItem)
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
- [ ] 19. エンドツーエンドデモ検証 (FIS起動 → アラーム → 診断 → チケット)

## V3: 見える

- [ ] 20. OTEL計装 (AgentCore Observability)
- [ ] 21. Cost Explorer MCP デプロイ・Registry登録 (Bedrock利用コスト分析)
- [ ] 22. Analysis Agent 実装・デプロイ
- [ ] 23. AgentCore Evaluations 設定
  - Online 評価: Gateway Agent に HELPFULNESS / FAITHFULNESS
  - Online 評価: Triage Agent に TOOL_SELECTION_ACCURACY
  - Online 評価: Diagnosis Agent に CORRECTNESS
  - Online 評価: Resolution Agent に FAITHFULNESS
- [ ] 24. React UI Reports タブ追加

## V4: 進化する

- [ ] 25. DynamoDB Streams 有効化
- [ ] 26. Lambda (stream consumer) 実装
- [ ] 27. Runbook Generator Agent 実装・デプロイ
- [ ] 28. SSM Automation Document テンプレート設計
- [ ] 29. 知識の結晶化ロジック実装 (Ticket resolved → Knowledge テーブル自動更新)
- [ ] 30. 異常集積検知ロジック実装 (N件/30分 → Analysis Agent 即時起動)
- [ ] 31. React UI Runbooks タブ追加

---

## 保守・品質改善

- [x] ハードコード除去リファクタリング (0c532ef) — AWS リージョン・テーブル名・モデルID・Secret パスを環境変数/CDKトークンに移行

## 完了済み

- [x] リポジトリ構成・開発アーキテクチャ設計
- [x] uv workspace 設定 (pyproject.toml)
- [x] CDK DataStack 雛形 (DynamoDBテーブル定義)
- [x] Claude Code カスタマイズ (CLAUDE.md / settings.json / commands)
- [x] 初回コミット (6f6aff6) — プロジェクト全体の scaffold を Git 管理下に置いた

# Agora — バックログ

> 実装の詳細・設計意図は [CONCEPT.md](CONCEPT.md) を参照。

## 現在のフォーカス

**フェーズ**: V2 — 見える  
**次のタスク**: #11 OTEL計装 (AgentCore Observability)

---

## V1: 動く

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

## V2: 見える

- [ ] 11. OTEL計装 (AgentCore Observability)
- [ ] 12. AWS Observability MCP群 デプロイ・Registry登録
  - [ ] 12a. CloudWatch MCP (awslabs/mcp 流用)
  - [ ] 12b. Cost Explorer MCP (awslabs/mcp 流用)
- [ ] 13. Analysis Agent 実装・デプロイ
- [ ] 14. AgentCore Evaluations 設定
- [ ] 15. React UI Reports タブ追加

## V2.5: FISデモ環境構築

- [ ] 16. 監視対象 Lambda 実装 (fake-api-server + FIS Extension Layer)
- [ ] 17. EventBridge Scheduler 設定 (定期呼び出しで負荷生成)
- [ ] 18. CloudWatch アラーム + SNS トピック設定
- [ ] 19. Bridge Lambda 実装 (アラーム → Agora Gateway Agent チャット POST)
- [ ] 20. FIS 実験テンプレート作成 (invocation-error シナリオ)
- [ ] 21. エンドツーエンドデモ検証 (FIS起動 → アラーム → 診断 → チケット)

## V3: 進化する

- [ ] 22. DynamoDB Streams 有効化
- [ ] 23. Lambda (stream consumer) 実装
- [ ] 24. Runbook Generator Agent 実装・デプロイ
- [ ] 25. SSM Automation Document テンプレート設計
- [ ] 26. 知識の結晶化ロジック実装 (Ticket resolved → Knowledge テーブル自動更新)
- [ ] 27. 異常集積検知ロジック実装 (N件/30分 → Analysis Agent 即時起動)
- [ ] 28. React UI Runbooks タブ追加

---

## 完了済み

- [x] リポジトリ構成・開発アーキテクチャ設計
- [x] uv workspace 設定 (pyproject.toml)
- [x] CDK DataStack 雛形 (DynamoDBテーブル定義)
- [x] Claude Code カスタマイズ (CLAUDE.md / settings.json / commands)
- [x] 初回コミット (6f6aff6) — プロジェクト全体の scaffold を Git 管理下に置いた

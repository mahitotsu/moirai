# Agora — バックログ

> 実装の詳細・設計意図は [CONCEPT.md](CONCEPT.md) を参照。

## 現在のフォーカス

**フェーズ**: V1 — 動く  
**次のタスク**: #1 DynamoDBテーブル設計・作成

---

## V1: 動く

- [ ] 1. DynamoDBテーブル設計・作成 (tickets / assets)
- [ ] 2. Ticket Service 実装 (FastAPI + DynamoDB)
- [ ] 3. Asset Service 実装 (FastAPI + DynamoDB)
- [ ] 4. AgentCore Gateway 登録 (OpenAPI spec → MCP変換)
- [ ] 5. Community Knowledge MCP群 実装・デプロイ
  - [ ] 5a. Stack Overflow MCP (FastMCP + Stack Exchange API)
  - [ ] 5b. GitHub Issues MCP (FastMCP + GitHub Search API)
  - [ ] 5c. Wikipedia MCP (FastMCP + Wikipedia API)
  - [ ] 5d. AWS Docs MCP (awslabs/mcp 流用)
- [ ] 6. AgentCore Registry 登録 (capability タグ付き)
- [ ] 7. A2Aエージェント群 実装・デプロイ
  - [ ] 7a. Triage Agent
  - [ ] 7b. Diagnosis Agent
  - [ ] 7c. Resolution Agent
- [ ] 8. Gateway Agent 実装・デプロイ (AG-UI protocol)
- [ ] 9. AgentCore Memory 設定
- [ ] 10. React UI 実装
  - [ ] 10a. Chat タブ (AG-UI / SSE)
  - [ ] 10b. Tickets タブ (REST API直接)
  - [ ] 10c. Knowledge タブ (REST API直接)

## V1.5: デモデータ自動生成

- [ ] 11. Demo Generator Agent 実装・デプロイ (AgentCore Browser)
- [ ] 12. シナリオを一通り流してDynamoDBにチケットを蓄積

## V2: 見える

- [ ] 13. OTEL計装 (AgentCore Observability)
- [ ] 14. AWS Observability MCP群 デプロイ・Registry登録
  - [ ] 14a. CloudWatch MCP (awslabs/mcp 流用)
  - [ ] 14b. Cost Explorer MCP (awslabs/mcp 流用)
- [ ] 15. Analysis Agent 実装・デプロイ
- [ ] 16. AgentCore Evaluations 設定
- [ ] 17. React UI Reports タブ追加

## V3: 進化する

- [ ] 18. DynamoDB Streams 有効化
- [ ] 19. Lambda (stream consumer) 実装
- [ ] 20. Runbook Generator Agent 実装・デプロイ
- [ ] 21. SSM Automation Document テンプレート設計
- [ ] 22. 知識の結晶化ロジック実装 (Ticket resolved → Knowledge テーブル自動更新)
- [ ] 23. 異常集積検知ロジック実装 (N件/30分 → Analysis Agent 即時起動)
- [ ] 24. React UI Runbooks タブ追加

---

## 完了済み

- [x] リポジトリ構成・開発アーキテクチャ設計
- [x] uv workspace 設定 (pyproject.toml)
- [x] CDK DataStack 雛形 (DynamoDBテーブル定義)
- [x] Claude Code カスタマイズ (CLAUDE.md / settings.json / commands)
- [x] 初回コミット (6f6aff6) — プロジェクト全体の scaffold を Git 管理下に置いた

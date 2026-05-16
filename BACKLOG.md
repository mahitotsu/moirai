# Agora — バックログ

> 実装の詳細・設計意図は [CONCEPT.md](CONCEPT.md) を参照。

## 現在のフォーカス

**フェーズ**: V2 — 自動化する  
**次のタスク**: #11 監視対象 Lambda 実装 (fake-api-server + FIS Extension Layer)

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

- [ ] 11. 監視対象 Lambda 実装 (fake-api-server + FIS Extension Layer)
- [ ] 12. EventBridge Scheduler 設定 (定期呼び出しで負荷生成・デフォルト無効)
  - [ ] 12a. Makefile デモ制御ターゲット実装 (demo-start / demo-inject / demo-stop)
- [ ] 13. CloudWatch アラーム + SNS トピック設定
- [ ] 14. Bridge Lambda 実装 (アラーム → Ticket 自動起票 + Gateway Agent POST)
- [ ] 15. FIS 実験テンプレート作成 (invocation-error シナリオ)
- [ ] 16. CloudWatch MCP デプロイ・Registry登録 (Diagnosis Agent が障害メトリクスを参照するため)
- [ ] 17. Chat UI 改修・Gateway Agent システムプロンプト更新
  - インシデント起票 UI → アドホック質問・問い合わせ UI に変更
  - 受け付ける質問カテゴリ・禁止操作を Gateway Agent System Prompt に反映
- [ ] 18. エンドツーエンドデモ検証 (FIS起動 → アラーム → 診断 → チケット)

## V3: 見える

- [ ] 19. OTEL計装 (AgentCore Observability)
- [ ] 20. Cost Explorer MCP デプロイ・Registry登録 (Bedrock利用コスト分析)
- [ ] 21. Analysis Agent 実装・デプロイ
- [ ] 22. AgentCore Evaluations 設定
- [ ] 23. React UI Reports タブ追加

## V4: 進化する

- [ ] 24. DynamoDB Streams 有効化
- [ ] 25. Lambda (stream consumer) 実装
- [ ] 26. Runbook Generator Agent 実装・デプロイ
- [ ] 27. SSM Automation Document テンプレート設計
- [ ] 28. 知識の結晶化ロジック実装 (Ticket resolved → Knowledge テーブル自動更新)
- [ ] 29. 異常集積検知ロジック実装 (N件/30分 → Analysis Agent 即時起動)
- [ ] 30. React UI Runbooks タブ追加

---

## 完了済み

- [x] リポジトリ構成・開発アーキテクチャ設計
- [x] uv workspace 設定 (pyproject.toml)
- [x] CDK DataStack 雛形 (DynamoDBテーブル定義)
- [x] Claude Code カスタマイズ (CLAUDE.md / settings.json / commands)
- [x] 初回コミット (6f6aff6) — プロジェクト全体の scaffold を Git 管理下に置いた

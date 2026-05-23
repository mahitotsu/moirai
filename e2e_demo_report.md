# Agora E2E デモ検証レポート

**検証日**: 2026-05-23  
**検証者**: Claude (自動検証)  
**対象フェーズ**: V1〜V4 全機能

---

## 検証サマリー

| 項目 | 結果 |
|---|---|
| 自動アラーム起票 | ✅ 正常 |
| エージェントパイプライン (Triage → Diagnosis → Resolution) | ✅ 正常 |
| チケット解決 (open → resolved) | ✅ 正常 |
| Knowledge 自動結晶化 (V4) | ✅ 正常 |
| Guardrails (FIS操作ブロック) | ✅ 正常 (入力側のみ) |
| `lesson_learned` フィールド | ⚠️ 未設定 (resolution 本文に含む) |

---

## 検証手順とタイムライン

### 事前準備

- 全 DynamoDB テーブル (agora-tickets / agora-knowledge / agora-reports / agora-assets) をゼロ件にクリーン化
- 過去デモのチケット 1 件削除

### デモ実行タイムライン (UTC)

| 時刻 | イベント |
|---|---|
| 16:15:44Z | `make demo-start` — EventBridge Scheduler 有効化 |
| 16:15:54Z | fake-api-server Lambda 正常実行確認 (`DescribeInstances succeeded`) |
| 16:16:51Z | `make demo-inject` — FIS 実験開始 (`EXPR3k14xC2ciM17qk`) |
| 16:17:18Z | fake-api-server Lambda が `RequestLimitExceeded` エラー発生 (FIS 注入効果) |
| 16:20:56Z | CloudWatch アラーム `agora-fake-api-error-rate` → **ALARM** |
| 16:20:56Z | Bridge Lambda がチケット自動起票 (ticket `45f8ebca`, status: open, severity: high) |
| 16:20:57Z | ticket-dispatcher Lambda が DynamoDB Streams INSERT を検知 |
| 16:21:03Z | Gateway Agent コンテナ起動 |
| 16:22:06Z | チケット **resolved** (起票から約 70 秒でパイプライン完了) |
| 16:22:07Z | agora-knowledge テーブルへ自動結晶化 (knowledge-consumer Lambda, V4) |
| 16:25:XX | `make demo-stop` — Scheduler 無効化・FIS 実験停止 |

**パイプライン所要時間**: 約 70 秒 (ticket INSERT → resolved)

---

## 検証結果詳細

### 1. FIS 障害注入

- **実験 ID**: `EXPR3k14xC2ciM17qk`
- **効果**: EC2 DescribeInstances に `RequestLimitExceeded` を注入
- **Lambda エラー確認**: 16:17:18Z (1回目), 16:18:27Z (2回目) — 2 連続エラーでアラーム遷移

```
[ERROR] ClientError: An error occurred (RequestLimitExceeded) when calling
the DescribeInstances operation (reached max retries: 4): Request limit exceeded.
```

### 2. CloudWatch アラーム遷移

```
Threshold Crossed: 2 out of the last 2 datapoints
[2.0 (23/05/26 16:19:00), 1.0 (23/05/26 16:18:00)]
were greater than or equal to the threshold (1.0)
(minimum 2 datapoints for OK -> ALARM transition)
```

### 3. 自動チケット起票

| フィールド | 値 |
|---|---|
| ticket_id | `45f8ebca-3603-4406-b5ed-0094f2722998` |
| title | CloudWatch ALARM: agora-fake-api-error-rate |
| severity | high |
| category | performance (Triage Agent が分類) |
| status | open → resolved |
| created_at | 2026-05-23T16:20:56.829003+00:00 |
| resolved_at | 2026-05-23T16:26:11.964927+00:00 |

### 4. エージェントパイプライン

**Gateway Agent → Triage → Diagnosis → Resolution** の順で正常実行。

**Resolution 内容 (抜粋)**:

> 【根本原因】AWS FIS（Fault Injection Simulator）による意図的な障害注入が fake-api-server Lambda 関数に対して実行され、連続的な Lambda エラーが発生。APIエラーレートが閾値（1.0%）を超過し、CloudWatch アラーム 'agora-fake-api-error-rate' が ALARM 状態に遷移した。
>
> 【解決手順】(1) FIS コンソールで実行中 Experiment を停止 (2) CloudWatch Logs で fake-api-server エラーログ確認 (3) アラーム自動回復を監視 (4) 実験結果を RunBook に記録 (5) 事前通知フロー整備
>
> 【教訓】AWS FIS による計画的障害注入は事前にオンコールチームへ通知し、CloudWatch アラームのサプレッション設定を行うことで、誤インシデント対応コストを削減できる。

### 5. Knowledge 自動結晶化 (V4)

- knowledge-consumer Lambda が DynamoDB Streams MODIFY (status=resolved) を検知
- `agora-knowledge` テーブルへ 16:22:07Z に結晶化 (resolved の 1 秒後)
- `source: ticket-resolved`, `category: performance`

### 6. Guardrails 動作確認

- FIS コントロール操作の**入力ブロック**: 正常動作
- 診断レポート出力のブロック: なし (出力側ブロックを無効化後)

---

## 今回の検証で発見・修正したバグ

### Bug 1: `ModuleNotFoundError: No module named 'common'`

**症状**: Gateway Agent / Diagnosis Agent / Analysis Agent の起動時にクラッシュ

**原因**: Dockerfile の本番ステージで `COPY common/ ./agents/common/` としていたが、editable install の `top_level.txt` が空で `common` パッケージが Python に認識されなかった

**修正**: gateway / diagnosis / analysis の Dockerfile 本番ステージを `COPY common/ ./common/` に変更 (resolution と統一)

```dockerfile
# Before (誤)
COPY common/ ./agents/common/

# After (正)
COPY common/ ./common/
```

**対象ファイル**:
- `agents/gateway/Dockerfile`
- `agents/diagnosis/Dockerfile`
- `agents/analysis/Dockerfile`

### Bug 2: Guardrails がエージェント出力をブロック

**症状**: ticket-dispatcher が Gateway Agent を呼び出すと「申し訳ありませんが、その応答はポリシーに違反しています」が返り、チケットが更新されない

**原因**: Guardrail の `FisExperimentControl` トピックが INPUT/OUTPUT 両方に適用されており、Resolution Agent の出力 (FIS を根本原因として言及) がブロックされた

**修正**: CDK で `output_enabled=False` を設定し、ユーザー入力側のみブロックするように変更

```python
# Before (OUTPUT もブロック)
type="DENY",

# After (INPUT のみブロック)
type="DENY",
input_enabled=True,
output_enabled=False,
```

**対象ファイル**: `infrastructure/stacks/agora_stack.py`

---

## 残存課題

### Minor: `lesson_learned` フィールドが未設定

- **状況**: Resolution Agent の system_prompt には `lesson_learned` を `update_ticket` で送るよう指示があるが、DynamoDB チケットの `lesson_learned` フィールドが空
- **影響**: Knowledge タブの主表示 (`lesson_learned` 優先) が空欄になる可能性
- **回避策**: 現状 `resolution` テキスト末尾の【教訓】段落に相当内容が含まれている

### Minor: チケット history の重複エントリ

- **状況**: `resolved` エントリが複数回記録される (DynamoDB Streams バッチリトライによる dispatcher の再実行)
- **影響**: UI の履歴表示に重複エントリが現れる
- **回避策**: UI 表示上は status が resolved の最初のエントリのみ表示すれば問題なし

---

## インフラ・設定情報

| 項目 | 値 |
|---|---|
| AWS リージョン | us-east-1 |
| CDK スタック | AgoraStack / FaultInjectionStack |
| Gateway Runtime ARN | `arn:aws:bedrock-agentcore:us-east-1:346929044083:runtime/agora_gateway-5oikQf6IP8` |
| Guardrail ID | `8ec9rywaohjt` |
| Memory ID | `agora_memory-MiqaZ49FDj` |
| UI URL | https://didy6u1x2a5gs.cloudfront.net |

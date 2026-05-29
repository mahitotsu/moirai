---
name: lambda-oom-runbook
description: Lambda関数のOOMキル・メモリリーク・高メモリ使用率インシデントの診断に関する承認済みランブック
---

# Lambda OOM / メモリ診断ランブック

インシデントログに `Runtime.ExitError`、`OUT_OF_MEMORY`、`Process exited before completing request` が含まれる場合、またはCloudWatchのメモリ使用率アラームが発火している場合にこのランブックを適用してください。

## 調査手順

**順番通りに**各ステップを実行し、次に進む前に発見事項を記録してください。

### ステップ1 — CloudWatchアラームを確認

`get_active_alarms` を呼び出し、ALARMステートにあるアラームを特定する。
メモリ関連アラーム（`MemorySize`、`max_memory_used`）が含まれる場合は、`get_alarm_history` でいつから上昇し始めたかを確認する。

### ステップ2 — Lambdaのメモリ設定とログを検査

インシデントに記載されている関数名で `inspect_lambda` を呼び出す。

以下を確認する：
- **メモリ設定**: 割り当てメモリ（MB）が実際の使用量に対して小さすぎないか。
- **タイムアウト設定**: メモリ不足でGCが頻発し処理が遅延していないか。
- **環境変数**: JVM系ランタイムであればヒープサイズ設定（`JAVA_TOOL_OPTIONS` 等）を確認。

次に `get_lambda_recent_errors` を呼び出し、OOM関連の例外メッセージを確認する。
`Runtime.ExitError` の直前のログ行が手がかりになる。

### ステップ3 — コミュニティナレッジを検索

Stack OverflowとGitHub Issuesで特定のランタイムとOOMパターンを検索する
（例：`"Lambda Runtime.ExitError out of memory nodejs"`）。
AWS Lambdaのメモリ最適化ベストプラクティスをAWSドキュメントで検索する。

### ステップ4 — 過去のインシデントを確認

`search_past_tickets` を呼び出して、以前のOOM/メモリ関連インシデントを探す。
同じ関数で繰り返し発生している場合は、構造的な問題（メモリリーク、データサイズ増大）の可能性が高い。

## 確信度レベル

| レベル | 割り当て条件 |
|---|---|
| **high** | ログに `OUT_OF_MEMORY` または `Runtime.ExitError` が明示、またはFIS実験が実行中 |
| **medium** | メモリアラームが発火しており、max_memory_used が割り当てメモリの90%以上 |
| **low** | 断続的なタイムアウトのみでメモリ証跡なし — 他の原因との切り分けが必要 |

## 主要な診断上の問い

1. OOMは突発的か（特定の入力データによるスパイク）、それとも漸進的か（メモリリーク）？
2. 割り当てメモリを増やした場合に解消するか、それとも根本的なリークがあるか？
3. 問題が発生した時刻に処理したペイロードサイズや件数は通常と異なるか？
4. Lambda Power Tuningを使ったメモリ最適化を実施したことがあるか？

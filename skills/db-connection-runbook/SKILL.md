---
name: db-connection-runbook
description: データベース接続エラー・クエリタイムアウト・DB到達不能インシデントの診断に関する承認済みランブック
---

# DB接続障害診断ランブック

インシデントログに `connection refused`、`connection timeout`、`ECONNREFUSED`、`OperationalError`、`Unable to connect to database` が含まれる場合、またはDynamoDB/RDSの接続エラーアラームが発火している場合にこのランブックを適用してください。

## 調査手順

**順番通りに**各ステップを実行し、次に進む前に発見事項を記録してください。

### ステップ1 — CloudWatchアラームを確認

`get_active_alarms` を呼び出し、ALARMステートにあるアラームを特定する。
DynamoDB系（`SystemErrors`、`ConsumedWriteCapacityUnits`）やVPC系のアラームがあれば
`get_alarm_history` でいつから発火しているかを確認する。

### ステップ2 — Lambda設定とネットワークトポロジーを検査

インシデントに記載されている関数名で `inspect_lambda` を呼び出す。

以下を確認する：
- **VPC設定**: Lambda がVPC内にあるか。VPCエンドポイント（DynamoDB等）が正しく設定されているか。
- **環境変数**: DB接続文字列・エンドポイントURL・リージョン設定を確認。
- **タグ `aws:cloudformation:stack-name`**: そのスタック名で `describe_cfn_stack` を呼び出し、DB関連リソース（DynamoDBテーブル、セキュリティグループ、VPCエンドポイント）のステータスを確認する。

次に `get_lambda_recent_errors` を呼び出し、接続エラーの具体的なメッセージ（エンドポイント、エラーコード）を確認する。

### ステップ3 — コミュニティナレッジを検索

Stack OverflowとGitHub Issuesで特定のエラーメッセージとDBサービス名を検索する
（例：`"DynamoDB ProvisionedThroughputExceededException boto3"`、`"Lambda VPC timeout RDS"`）。
接続プールの設定やVPCエンドポイントのベストプラクティスをAWSドキュメントで検索する。

### ステップ4 — 過去のインシデントを確認

`search_past_tickets` を呼び出して、以前のDB接続障害インシデントを探す。
同じエンドポイントやテーブルで繰り返し発生している場合は、容量設定または接続プール設定の構造的な問題を疑う。

## 確信度レベル

| レベル | 割り当て条件 |
|---|---|
| **high** | FIS実験が実行中でネットワーク/DBフォルトが注入されている、またはログに特定のDB接続エラーが明示 |
| **medium** | CloudWatchにDB系エラーアラームが発火し、接続エラーログと相関している |
| **low** | 断続的なタイムアウトのみ、DB固有のエラーメッセージなし — ネットワーク問題との切り分けが必要 |

## 主要な診断上の問い

1. 接続エラーはすべてのDBリクエストに影響しているか、それとも特定のクエリパターンのみか？
2. Lambda がVPC内にある場合、VPCエンドポイントまたはNATゲートウェイ経由でDBに到達できるか？
3. DynamoDBの場合、プロビジョニングされた容量またはオンデマンドキャパシティが実際のリクエスト量に対して十分か？
4. 接続プールを使用している場合、コールドスタート時の接続確立タイムアウトが適切に設定されているか？

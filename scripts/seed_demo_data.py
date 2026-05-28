"""Demo seed script — creates ~50 sample tickets via the Ticket Service API.

Usage:
    uv run python scripts/seed_demo_data.py

Requires AWS credentials in the environment (same profile used for cdk-deploy).
The Ticket Service URL and API key are resolved automatically from CloudFormation
and Secrets Manager, so no manual configuration is needed.
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import httpx

# ---------------------------------------------------------------------------
# AWS resource resolution
# ---------------------------------------------------------------------------

_REGION = "us-east-1"
_AGORA_STACK = "AgoraStack"
_API_KEY_SECRET = "agora/services-api-key"


def _resolve_ticket_url() -> str:
    cfn = boto3.client("cloudformation", region_name=_REGION)
    resp = cfn.describe_stacks(StackName=_AGORA_STACK)
    for output in resp["Stacks"][0].get("Outputs", []):
        if output["OutputKey"] == "TicketFunctionUrl":
            return output["OutputValue"].rstrip("/")
    raise RuntimeError(f"TicketFunctionUrl not found in {_AGORA_STACK}. Run 'make cdk-deploy' first.")


def _resolve_api_key() -> str:
    sm = boto3.client("secretsmanager", region_name=_REGION)
    return sm.get_secret_value(SecretId=_API_KEY_SECRET)["SecretString"]


# ---------------------------------------------------------------------------
# Ticket data — 50 tickets across 7 categories
# Recurring root-causes are intentional so横断クエリがパターンを発見できる
# ---------------------------------------------------------------------------

def _dt(days_ago: int, hours: int = 9) -> str:
    """Return an ISO timestamp N days ago (UTC)."""
    base = datetime.now(UTC) - timedelta(days=days_ago, hours=-hours)
    return base.isoformat()


# Each entry: (title, description, category, severity, status, resolution, lesson_learned, days_ago)
_TICKETS: list[dict[str, Any]] = [
    # ── network (8) ─────────────────────────────────────────────────────────
    {
        "title": "EC2 DescribeInstances で ThrottlingException が連続発生",
        "description": (
            "fake-api-server Lambda が boto3 ClientError (ThrottlingException) で失敗し続けている。"
            "CloudWatch Lambda/Errors が急上昇。EventBridge アラームが ALARM 状態に遷移。"
        ),
        "category": "network",
        "severity": "high",
        "status": "resolved",
        "resolution": "ExponentialBackoff + jitter を追加し、リトライ上限を 5 回に設定。boto3 retry_mode を 'adaptive' に変更。",
        "lesson_learned": (
            "AWS API スロットリングは突発的なトラフィック集中で発生する。boto3 の retry_mode='adaptive' と"
            " exponential backoff + jitter の組み合わせで大半のケースは自己回復できる。"
            "Lambda の同時実行数が急増する場合は Reserved Concurrency を設定して上流リクエストを絞ること。"
        ),
        "days_ago": 85,
    },
    {
        "title": "EC2 API スロットリング再発 — Lambda エラー率 40% 超",
        "description": (
            "前回 (3ヶ月前) と同じ ThrottlingException が再発。リリース後に Lambda 同時実行数が急増した模様。"
            "今回は retry_mode='adaptive' 設定済みだが、burst が大きすぎて追いつかない。"
        ),
        "category": "network",
        "severity": "high",
        "status": "resolved",
        "resolution": "Lambda Reserved Concurrency を 50 に制限。upstream SQS でメッセージレートを平準化。",
        "lesson_learned": (
            "adaptive retry だけでは burst が大きい場合に対応できない。"
            "Lambda → AWS API のパスには必ず Reserved Concurrency + SQS バッファを挟み、"
            "スロットリング発生率を CloudWatch メトリクスでアラーム監視すること。"
        ),
        "days_ago": 52,
    },
    {
        "title": "ThrottlingException 三度目 — Scheduler の並列起動が原因",
        "description": (
            "EventBridge Scheduler が毎分 rate(1 minute) で Lambda を呼び出す設定になっており、"
            "前の実行が完了しないまま次の実行が重なって同時実行数が爆発した。"
        ),
        "category": "network",
        "severity": "critical",
        "status": "resolved",
        "resolution": "Scheduler の flexible time window を 30 秒に設定してバースト防止。Lambda タイムアウト短縮。",
        "lesson_learned": (
            "EventBridge Scheduler の rate 式は前のタスクが終わらなくても次を起動する。"
            "flexible_time_window + Lambda タイムアウトの組み合わせで多重起動を防ぐこと。"
            "同じ根本原因が三度発生した場合は CloudWatch Alarm → SNS → PagerDuty の自動エスカレーションを検討。"
        ),
        "days_ago": 21,
    },
    {
        "title": "ALB 502 Bad Gateway — ECS タスクが突然落ちた",
        "description": (
            "ALB のターゲットグループで 502 が急増。ECS タスクのヘルスチェック失敗でタスクが停止→再起動を繰り返している。"
            "アプリケーションログに OOM Killed の記録あり。"
        ),
        "category": "network",
        "severity": "high",
        "status": "resolved",
        "resolution": "ECS タスク定義の memoryReservation を 512MB → 1024MB に増加。ALB ヘルスチェック間隔を延長。",
        "lesson_learned": (
            "ALB 502 はヘルスチェック失敗とセットで発生することが多い。原因はメモリ不足→OOM Killed のケースが多い。"
            "まず ECS タスクログと CloudWatch Insights で OOM Killed を確認する手順を踏むこと。"
        ),
        "days_ago": 67,
    },
    {
        "title": "ALB 502 再発 — デプロイ中のドレイン不足",
        "description": (
            "Blue/Green デプロイ時に旧タスクが新タスクへの切り替え直後に強制終了され、進行中のリクエストが 502 になった。"
        ),
        "category": "network",
        "severity": "medium",
        "status": "resolved",
        "resolution": "ECS サービスの deregistration_delay を 30 秒に設定。CodeDeploy の wait_time_in_minutes を 2 に延長。",
        "lesson_learned": (
            "Blue/Green デプロイ時は必ず connection draining (deregistration_delay) を設定すること。"
            "ALB → ECS のパスでは 30 秒以上のドレイン時間を確保しないと進行中リクエストが切断される。"
        ),
        "days_ago": 38,
    },
    {
        "title": "VPC 内 DNS 解決失敗 — Route 53 Resolver 障害",
        "description": "VPC 内の Lambda/ECS から RDS エンドポイントへの DNS 解決が断続的に失敗。接続エラーが散発している。",
        "category": "network",
        "severity": "high",
        "status": "resolved",
        "resolution": "enableDnsHostnames / enableDnsSupport を確認・有効化。Route 53 Resolver Endpoint を追加。",
        "lesson_learned": (
            "VPC の DNS 解決問題は enableDnsSupport=true が最初のチェック項目。"
            "RDS や ElastiCache のカスタムエンドポイントを使う場合は Route 53 プライベートホストゾーンとの整合性も確認すること。"
        ),
        "days_ago": 44,
    },
    {
        "title": "NAT Gateway 帯域枯渇 — 大量 S3 通信がボトルネック",
        "description": (
            "Lambda から S3 へのデータ転送がすべて NAT Gateway 経由になっており、帯域が飽和。"
            "他サービスの外部通信が影響を受けている。"
        ),
        "category": "network",
        "severity": "medium",
        "status": "resolved",
        "resolution": "S3 VPC エンドポイント (Gateway 型) を追加して NAT Gateway を迂回。コスト削減にも効果あり。",
        "lesson_learned": (
            "S3 や DynamoDB への通信は VPC Endpoint (Gateway 型) を使えば NAT Gateway を使わずに済む。"
            "NAT Gateway 経由の通信コストと帯域制約は見落としやすいので、設計段階で S3/DynamoDB は VPC Endpoint を標準採用すること。"
        ),
        "days_ago": 30,
    },
    {
        "title": "S3 署名付き URL が期限切れ — クライアントから 403",
        "description": "フロントエンドから S3 オブジェクトへのアクセスが 403 Forbidden になる。調査すると presigned URL の有効期限が 60 秒しか設定されていなかった。",
        "category": "network",
        "severity": "low",
        "status": "open",
        "resolution": None,
        "lesson_learned": None,
        "days_ago": 3,
    },

    # ── database (8) ─────────────────────────────────────────────────────────
    {
        "title": "DynamoDB ProvisionedThroughputExceeded — 書き込みスロット枯渇",
        "description": (
            "agora-tickets テーブルへの大量書き込みで ProvisionedThroughputExceededException が発生。"
            "Lambda 実行が失敗しリトライループが発生。"
        ),
        "category": "database",
        "severity": "critical",
        "status": "resolved",
        "resolution": "テーブルを PAY_PER_REQUEST (オンデマンド) モードに変更。プロビジョニング管理が不要になった。",
        "lesson_learned": (
            "予測困難なトラフィックには DynamoDB の PAY_PER_REQUEST モードが適切。"
            "コスト増を懸念する場合でも、スロットリングによるデータロストの方がリスクが大きい。"
            "既存テーブルの変換は5分程度で完了するため早期対応を推奨。"
        ),
        "days_ago": 90,
    },
    {
        "title": "DynamoDB スロットリング再発 — GSI の書き込みキャパシティ不足",
        "description": (
            "メインテーブルは PAY_PER_REQUEST だが GSI (status-created_at-index) は"
            " Provisioned のままだったため GSI 側でスロットリングが発生。"
        ),
        "category": "database",
        "severity": "high",
        "status": "resolved",
        "resolution": "GSI も PAY_PER_REQUEST に変更。CloudFormation でテーブルと GSI の BillingMode を統一。",
        "lesson_learned": (
            "DynamoDB の BillingMode 変更はテーブル本体だけでなく全 GSI に適用する必要がある。"
            "CDK / CloudFormation テンプレートで billingMode を一か所で管理し、GSI への伝播を確認すること。"
        ),
        "days_ago": 75,
    },
    {
        "title": "DynamoDB ConditionalCheckFailedException — 競合書き込み",
        "description": "複数の Lambda インスタンスが同じチケットを同時更新しようとして ConditionalCheckFailedException が多発。",
        "category": "database",
        "severity": "medium",
        "status": "resolved",
        "resolution": "condition_expression に version チェックを追加して楽観的ロックを実装。",
        "lesson_learned": (
            "DynamoDB は同時書き込みに対して楽観的ロック (version 属性 + condition_expression) を使うこと。"
            "ConditionalCheckFailedException はリトライで自己回復できるが、上限回数と exponential backoff を設定すること。"
        ),
        "days_ago": 60,
    },
    {
        "title": "RDS 接続プール枯渇 — max_connections 超過",
        "description": "Lambda が RDS PostgreSQL に接続するたびに新規接続を確立するため max_connections に到達しエラーが頻発。",
        "category": "database",
        "severity": "high",
        "status": "resolved",
        "resolution": "RDS Proxy を導入してコネクションプーリングをオフロード。Lambda の接続オーバーヘッドが解消。",
        "lesson_learned": (
            "Lambda から RDS に直接接続する構成は max_connections 問題が必ず発生する。"
            "RDS Proxy を挟むことでプール管理が不要になる。IAM 認証も RDS Proxy 経由で統合できる。"
        ),
        "days_ago": 55,
    },
    {
        "title": "RDS 接続プール問題再発 — RDS Proxy のターゲット不健全",
        "description": "RDS Proxy 導入後も接続エラーが散発。調査すると RDS Proxy のターゲット RDS インスタンスが再起動中でヘルスチェックに失敗していた。",
        "category": "database",
        "severity": "medium",
        "status": "resolved",
        "resolution": "RDS Proxy のヘルスチェック失敗時のフォールバック設定を確認。Multi-AZ を有効化してフェイルオーバー時間を短縮。",
        "lesson_learned": (
            "RDS Proxy は RDS 本体の障害時に接続を保留するが、フェイルオーバー完了まで数十秒かかる。"
            "本番 RDS は必ず Multi-AZ を有効化し、CloudWatch の FailedToConnect メトリクスを監視すること。"
        ),
        "days_ago": 40,
    },
    {
        "title": "ElastiCache Eviction 急増 — メモリ逼迫",
        "description": "ElastiCache Redis で evicted_keys が急増し、キャッシュヒット率が低下。DB 負荷が増大している。",
        "category": "database",
        "severity": "medium",
        "status": "resolved",
        "resolution": "ノードサイズを cache.t3.micro → cache.t3.small に変更。TTL を短縮して古いデータの自然期限切れを促進。",
        "lesson_learned": (
            "ElastiCache の eviction は maxmemory 超過が根本原因。"
            "CloudWatch の FreeableMemory と Evictions をアラーム監視し、Evictions が 0 以上になったら即座にスケールアップを検討すること。"
        ),
        "days_ago": 28,
    },
    {
        "title": "RDS スロークエリ — ロック待機でタイムアウト",
        "description": "RDS PostgreSQL でロック競合が多発し、アプリケーションのリクエストタイムアウトが増加している。",
        "category": "database",
        "severity": "high",
        "status": "investigating",
        "resolution": None,
        "lesson_learned": None,
        "days_ago": 5,
    },
    {
        "title": "DynamoDB テーブル削除を誤って実行 — データ損失",
        "description": "開発環境のスクリプトを誤って本番環境で実行し agora-knowledge テーブルを削除してしまった。",
        "category": "database",
        "severity": "critical",
        "status": "resolved",
        "resolution": "DynamoDB Point-in-Time Recovery (PITR) から 5 分前の状態にリストア。テーブル削除保護 (deletion_protection) を有効化。",
        "lesson_learned": (
            "DynamoDB テーブルは必ず deletion_protection=true を設定すること。"
            "PITR は常に有効化しておき、誤削除・誤書き込みのリストア手段として機能させること。"
            "本番環境向けスクリプトは --env=prod フラグを明示的に要求する設計にして誤実行を防ぐこと。"
        ),
        "days_ago": 18,
    },

    # ── memory (6) ───────────────────────────────────────────────────────────
    {
        "title": "Lambda OOM — メモリ不足でタイムアウト",
        "description": "knowledge-consumer Lambda が大きなペイロードを処理中に 128MB のメモリ上限に達してタイムアウト終了。",
        "category": "memory",
        "severity": "high",
        "status": "resolved",
        "resolution": "Lambda のメモリを 128MB → 512MB に増設。処理時間も短縮された (CPU は RAM に比例)。",
        "lesson_learned": (
            "Lambda のメモリ上限は CPU パフォーマンスにも直結する。OOM 発生時は CloudWatch Logs の"
            " 'Runtime exited with error: signal: killed' を確認すること。"
            "Lambda Power Tuning ツールで最適メモリを定量的に決定することを推奨。"
        ),
        "days_ago": 80,
    },
    {
        "title": "Lambda OOM 再発 — Bedrock 埋め込みレスポンスが大きい",
        "description": (
            "Bedrock Titan Embed モデルのレスポンスが予想より大きく、knowledge-consumer Lambda が"
            " 512MB でも OOM になった。"
        ),
        "category": "memory",
        "severity": "high",
        "status": "resolved",
        "resolution": "Lambda メモリを 1024MB に増設。埋め込みベクトルをメモリに保持せずストリーム処理に変更。",
        "lesson_learned": (
            "Bedrock 埋め込みモデルのレスポンスサイズは入力テキスト長に依存する。"
            "大きなチケット本文をそのまま渡すとベクトルが肥大化する。"
            "埋め込み前にテキストを要約または truncate する前処理を追加することで安定性が向上する。"
        ),
        "days_ago": 50,
    },
    {
        "title": "Lambda OOM 三度目 — 並列実行でメモリが枯渇",
        "description": "DynamoDB Streams の shard 並列実行が増加し、複数の Lambda インスタンスが同時にメモリを消費して頻繁に OOM になった。",
        "category": "memory",
        "severity": "critical",
        "status": "resolved",
        "resolution": "Streams の parallelizationFactor を 1 に下げて並列実行を抑制。Lambda メモリも 2048MB に増設。",
        "lesson_learned": (
            "DynamoDB Streams の parallelizationFactor を上げると Lambda の同時実行数が急増する。"
            "メモリ集約型の処理には parallelizationFactor=1 から始め、CloudWatch で監視しながら段階的に増やすこと。"
        ),
        "days_ago": 22,
    },
    {
        "title": "ECS タスク OOM Killed — Java Heap Space 不足",
        "description": "diagnosis-agent コンテナが Heap Space エラーで OOM Killed。ECS タスク定義のメモリ上限が低すぎた。",
        "category": "memory",
        "severity": "high",
        "status": "resolved",
        "resolution": "タスク定義の memory を 512 → 2048 に増加。JVM の -Xmx を明示的に設定してコンテナ上限の 80% に合わせた。",
        "lesson_learned": (
            "ECS コンテナで JVM を使う場合は -Xmx をコンテナメモリ上限の ~80% に明示設定すること。"
            "設定しないと JVM がホストの全メモリを上限として誤認し OOM Killed が発生する。"
        ),
        "days_ago": 45,
    },
    {
        "title": "ECS タスク OOM 再発 — メモリリーク",
        "description": "diagnosis-agent が長時間稼働すると徐々にメモリ使用量が増加し最終的にクラッシュする。",
        "category": "memory",
        "severity": "high",
        "status": "investigating",
        "resolution": None,
        "lesson_learned": None,
        "days_ago": 7,
    },
    {
        "title": "Node.js Heap Overflow — ui コンテナがクラッシュ",
        "description": "React SSR サーバーが大量リクエスト時に V8 Heap Space を使い切ってクラッシュ。エラーログに FATAL ERROR: Reached heap limit。",
        "category": "memory",
        "severity": "medium",
        "status": "resolved",
        "resolution": "--max-old-space-size=2048 を Node.js 起動オプションに追加。コンポーネントのメモ化を強化してメモリ効率を改善。",
        "lesson_learned": (
            "Node.js の V8 ヒープはデフォルト上限が低い (~1.5GB)。"
            "コンテナ環境では --max-old-space-size を明示的にコンテナメモリ上限の 80% 程度に設定すること。"
        ),
        "days_ago": 35,
    },

    # ── deploy (7) ───────────────────────────────────────────────────────────
    {
        "title": "ECS タスク起動失敗 — ImagePullBackOff",
        "description": "ECR からイメージを Pull しようとして CannotPullContainerError。ECR リポジトリへの IAM 権限が不足していた。",
        "category": "deploy",
        "severity": "high",
        "status": "resolved",
        "resolution": "ECS タスク実行ロールに ecr:GetAuthorizationToken / ecr:BatchGetImage 権限を追加。",
        "lesson_learned": (
            "ECS タスクの ECR Pull 失敗は executionRoleArn の権限不足が原因のケースが多い。"
            "ecr:GetAuthorizationToken は ECR リポジトリ ARN ではなく '*' に対して付与する必要があることに注意。"
        ),
        "days_ago": 77,
    },
    {
        "title": "ECS デプロイ後に 502 頻発 — ヘルスチェック設定ミス",
        "description": "新イメージをデプロイしたら ALB ヘルスチェックが通らず ECS がタスクを即座に停止する。healthcheck パスが間違っていた。",
        "category": "deploy",
        "severity": "high",
        "status": "resolved",
        "resolution": "ALB ターゲットグループのヘルスチェックパスを /health に修正。FastAPI アプリに /health エンドポイントを追加。",
        "lesson_learned": (
            "ECS サービス更新時はヘルスチェックパスを必ず確認すること。"
            "ALB ヘルスチェック設定と FastAPI の /health エンドポイントが一致していないと即座にデプロイ失敗になる。"
        ),
        "days_ago": 62,
    },
    {
        "title": "CDK Bootstrap 不足 — AgoraStack デプロイ失敗",
        "description": "新しい AWS アカウントで cdk deploy を実行したら 'This stack uses assets, so the toolkit stack must be deployed to the environment' エラー。",
        "category": "deploy",
        "severity": "medium",
        "status": "resolved",
        "resolution": "cdk bootstrap aws://ACCOUNT_ID/us-east-1 を先に実行。手順書に Bootstrap ステップを追加。",
        "lesson_learned": (
            "CDK アセット (Docker イメージ、Lambda zip 等) を使うスタックは cdk bootstrap が必須。"
            "新規 AWS 環境へのデプロイ手順書には bootstrap を最初のステップとして記載すること。"
        ),
        "days_ago": 88,
    },
    {
        "title": "Lambda デプロイパッケージが 250MB 超 — アップロード失敗",
        "description": "resolution-agent のデプロイパッケージに不要な依存が含まれており zip サイズが 250MB (Lambda 上限) を超えた。",
        "category": "deploy",
        "severity": "medium",
        "status": "resolved",
        "resolution": "Lambda Layer に共通依存 (boto3, pydantic) を切り出し。zip 単体サイズを 45MB に削減。",
        "lesson_learned": (
            "Lambda zip は 50MB (直接アップロード) / 250MB (S3 経由) が上限。"
            "boto3 は Lambda ランタイムに内蔵されているため除外可能。"
            "共通ライブラリは Lambda Layer に分離するとデプロイサイズと更新頻度を最適化できる。"
        ),
        "days_ago": 58,
    },
    {
        "title": "Lambda コンテナイメージが 10GB 超 — ECR Push 失敗",
        "description": "ARM64 対応のため arm64 ベースイメージに切り替えたが、ビルド時に不要なパッケージがキャッシュに残り 10GB を超えた。",
        "category": "deploy",
        "severity": "medium",
        "status": "resolved",
        "resolution": "Dockerfile をマルチステージビルドに変更。builder ステージで pip install 後、本番イメージにサイトパッケージのみコピー。",
        "lesson_learned": (
            "Docker イメージは必ずマルチステージビルドを使うこと。"
            "python:3.12-slim をベースにし pip cache を --no-cache-dir で無効化すると劇的にサイズが削減できる。"
        ),
        "days_ago": 42,
    },
    {
        "title": "CodePipeline が Source ステージで停止 — GitHub 接続エラー",
        "description": "CodePipeline の Source ステージが GitHub connection エラーで停止。CodeStar Connections の認証トークンが失効していた。",
        "category": "deploy",
        "severity": "high",
        "status": "resolved",
        "resolution": "CodeStar Connections を再認証。Connection ステータスを CloudWatch Events で監視するアラームを追加。",
        "lesson_learned": (
            "CodeStar Connections の GitHub トークンは手動更新が必要な場合がある。"
            "Connection の Status が AVAILABLE 以外になった場合の CloudWatch アラームを設定し、"
            "パイプライン停止を即座に検知できるようにすること。"
        ),
        "days_ago": 25,
    },
    {
        "title": "CDK デプロイ失敗 — CloudFormation ロールバック中",
        "description": "AgoraStack の cdk deploy が途中でロールバックに入った。Lambda 関数の VPC 設定変更で ENI の削除に時間がかかり、タイムアウトした模様。",
        "category": "deploy",
        "severity": "medium",
        "status": "open",
        "resolution": None,
        "lesson_learned": None,
        "days_ago": 1,
    },

    # ── performance (7) ──────────────────────────────────────────────────────
    {
        "title": "Lambda コールドスタート 5 秒 — API レイテンシ急増",
        "description": "diagnosis-agent Lambda のコールドスタートが 5 秒を超え、エージェントパイプラインの SLA を超過している。",
        "category": "performance",
        "severity": "high",
        "status": "resolved",
        "resolution": "Lambda SnapStart を有効化。Provisioned Concurrency を最低 2 に設定。コールドスタートが 300ms 以下に改善。",
        "lesson_learned": (
            "Python Lambda のコールドスタートは import 時間が大半を占める。"
            "boto3 / pydantic 等の重いライブラリが多いと 3-5 秒になることがある。"
            "SnapStart (Java) や Provisioned Concurrency で回避できる。"
            "Python の場合は Lambda Layer を使って import 先を分散させることも有効。"
        ),
        "days_ago": 83,
    },
    {
        "title": "コールドスタート再発 — デプロイ後に Provisioned Concurrency がリセット",
        "description": "新しいコードをデプロイしたら Provisioned Concurrency が新バージョンに紐づかず、旧バージョンのみに設定されていた。",
        "category": "performance",
        "severity": "high",
        "status": "resolved",
        "resolution": "CDK で Alias に Provisioned Concurrency を設定するよう変更。デプロイ時に Alias が自動的に更新されるようにした。",
        "lesson_learned": (
            "Lambda の Provisioned Concurrency はバージョン番号に紐づくため、デプロイのたびに再設定が必要。"
            "CDK では lambda.Alias + provisionedConcurrentExecutions を使って Alias に設定すると"
            "デプロイ後も維持される。"
        ),
        "days_ago": 48,
    },
    {
        "title": "コールドスタート問題三度目 — VPC 内 Lambda の ENI 割り当て遅延",
        "description": "Lambda を VPC 内に配置してから ENI の割り当てに 8 秒かかるようになった。コールドスタートが悪化した。",
        "category": "performance",
        "severity": "critical",
        "status": "resolved",
        "resolution": "Lambda を VPC 外に移動。RDS へのアクセスは RDS Proxy のパブリックエンドポイント + TLS で代替。",
        "lesson_learned": (
            "Lambda を VPC 内に配置すると ENI 割り当てでコールドスタートが数秒延長される。"
            "RDS Proxy のパブリックエンドポイントや Secrets Manager エンドポイントを使えば VPC 外から安全に RDS に接続できる。"
            "VPC 内 Lambda は本当に必要な場合 (プライベートサブネットへの直接アクセス) に限定すること。"
        ),
        "days_ago": 15,
    },
    {
        "title": "API Gateway タイムアウト 29 秒 — エージェントパイプライン遅延",
        "description": "Gateway Agent → Triage → Diagnosis の A2A チェーンが 29 秒 (API Gateway 上限) を超えてタイムアウトになった。",
        "category": "performance",
        "severity": "high",
        "status": "resolved",
        "resolution": "パイプラインを非同期化。AG-UI のストリーミングレスポンスを使って中間状態をクライアントに送信しながら処理を継続。",
        "lesson_learned": (
            "API Gateway の統合タイムアウトは最大 29 秒。エージェントパイプラインは必ずこれを超える。"
            "非同期処理 + AG-UI ストリーミングでクライアントに進捗を通知しながらバックグラウンドで処理を完結させること。"
        ),
        "days_ago": 70,
    },
    {
        "title": "API レイテンシ急増 — DynamoDB の Hot Partition",
        "description": "agora-tickets テーブルへの書き込みが特定のパーティションに集中し、レイテンシが急増している。",
        "category": "performance",
        "severity": "high",
        "status": "resolved",
        "resolution": "ticket_id に UUID v4 を使用してパーティションキーを分散。Adaptive Capacity が有効になっていることを確認。",
        "lesson_learned": (
            "DynamoDB の Hot Partition は連番や日付を PK にした場合に発生しやすい。"
            "PK には UUID v4 や ULID を使ってランダム分散させること。"
            "Adaptive Capacity が有効なら一時的なスパイクは自動対応されるが、根本的な PK 設計見直しが必要。"
        ),
        "days_ago": 33,
    },
    {
        "title": "CloudFront キャッシュミス率急上昇 — TTL 設定ミス",
        "description": "UI の CloudFront ディストリビューションでキャッシュミスが 95% を超えた。origin の負荷が増大している。",
        "category": "performance",
        "severity": "medium",
        "status": "resolved",
        "resolution": "Cache-Control ヘッダーを max-age=3600 に設定。CloudFront の CachingOptimized ポリシーを適用。",
        "lesson_learned": (
            "CloudFront のキャッシュ効率は Cache-Control ヘッダーに依存する。"
            "静的アセットには max-age=31536000 + immutable を設定し、API レスポンスには no-cache を使い分けること。"
        ),
        "days_ago": 20,
    },
    {
        "title": "Step Functions 実行が突然遅くなった — Express Workflow のスロットリング",
        "description": "診断パイプラインを Step Functions で移行したところ Express Workflow がスロットリングされてレイテンシが悪化した。",
        "category": "performance",
        "severity": "medium",
        "status": "open",
        "resolution": None,
        "lesson_learned": None,
        "days_ago": 4,
    },

    # ── security (6) ─────────────────────────────────────────────────────────
    {
        "title": "IAM ポリシー変更で S3 アクセス拒否",
        "description": "インフラチームが IAM ポリシーを変更した直後から Lambda から S3 への PutObject が AccessDenied になった。",
        "category": "security",
        "severity": "critical",
        "status": "resolved",
        "resolution": "CloudTrail で変更履歴を確認。s3:PutObject の Resource が特定 prefix に制限されていたため 's3:/*' に修正。",
        "lesson_learned": (
            "IAM ポリシー変更は CloudTrail の GetUserPolicy / PutRolePolicy イベントで追跡できる。"
            "変更前後の Policy diff を確認できる仕組み (AWS Config Rules / IAM Access Analyzer) を導入すること。"
            "最小権限原則を守りながら Resource ARN を正確に指定すること。"
        ),
        "days_ago": 73,
    },
    {
        "title": "SCP 変更で全サービスの cross-account アクセスが遮断",
        "description": "AWS Organizations の SCP が更新され、agora アカウントから別アカウントの ECR へのアクセスが拒否されるようになった。",
        "category": "security",
        "severity": "critical",
        "status": "resolved",
        "resolution": "SCP に agora アカウント向けの例外条件 (aws:PrincipalAccount) を追加。ECR レポジトリを同一アカウントに移行。",
        "lesson_learned": (
            "SCP は IAM ポリシーより上位にあるため IAM 権限を修正しても解決しない。"
            "AccessDenied の原因を特定するには CloudTrail の errorCode: 'AccessDenied' + additionalEventData で"
            " SCP 起因か IAM 起因かを判別すること。"
        ),
        "days_ago": 56,
    },
    {
        "title": "Secrets Manager ローテーション失敗 — Lambda 実行エラー",
        "description": "RDS パスワードの Secrets Manager 自動ローテーションが失敗。ローテーション Lambda がタイムアウトしている。",
        "category": "security",
        "severity": "high",
        "status": "resolved",
        "resolution": "ローテーション Lambda の VPC サブネット設定を修正。Secrets Manager エンドポイントへのルーティングが欠落していた。",
        "lesson_learned": (
            "Secrets Manager ローテーション Lambda を VPC 内に配置する場合は、"
            " Secrets Manager の VPC エンドポイントか NAT Gateway が必要。"
            "ローテーション失敗の原因は CloudWatch Logs の /aws/secretsmanager/* ロググループで確認できる。"
        ),
        "days_ago": 47,
    },
    {
        "title": "Secrets Manager ローテーション再失敗 — RDS 接続拒否",
        "description": "パスワードローテーション後に既存の Lambda が古いパスワードをキャッシュしていて RDS 接続が拒否された。",
        "category": "security",
        "severity": "high",
        "status": "resolved",
        "resolution": "Lambda の environment variable キャッシュを廃止し、起動ごとに Secrets Manager から直接取得するよう修正。",
        "lesson_learned": (
            "Secrets Manager のパスワードをキャッシュする場合は TTL を設定してローテーション間隔より短くすること。"
            "AWS Lambda Powertools の Parameter utility を使うと TTL 付きキャッシュが簡単に実装できる。"
        ),
        "days_ago": 29,
    },
    {
        "title": "WAF レート制限が正規ユーザーをブロック",
        "description": "WAF の Rate Based Rule (1000 req/5min) が CI テストの大量リクエストを攻撃とみなし、同 IP の正規ユーザーを巻き込んでブロックした。",
        "category": "security",
        "severity": "medium",
        "status": "resolved",
        "resolution": "CI の IP レンジを WAF の IP セット除外リストに追加。Rate Based Rule のしきい値を 5000 に引き上げ。",
        "lesson_learned": (
            "WAF レート制限は CI/CD や監視ツールの IP を除外リストに入れておくこと。"
            "Rate Based Rule のしきい値は実際のトラフィックパターンを CloudWatch で 1 週間観測してから設定すること。"
        ),
        "days_ago": 16,
    },
    {
        "title": "Bedrock Guardrails が誤検知 — 正規クエリをブロック",
        "description": "Gateway Agent の Guardrails が 'ネットワーク障害の診断' というユーザークエリを有害トピックと判定しブロックした。",
        "category": "security",
        "severity": "low",
        "status": "open",
        "resolution": None,
        "lesson_learned": None,
        "days_ago": 2,
    },

    # ── other (8) ────────────────────────────────────────────────────────────
    {
        "title": "CloudWatch ロググループの容量アラーム — ストレージ超過",
        "description": "agora-tickets の CloudWatch Logs が保存期間設定なしで蓄積し、ストレージコストが急増している。",
        "category": "other",
        "severity": "low",
        "status": "resolved",
        "resolution": "全ロググループに retention_days=30 を設定。CDK で LogGroup を明示的に作成し retention を管理。",
        "lesson_learned": (
            "CloudWatch Logs はデフォルトで無期限保存される。"
            "CDK で LogGroup を明示的に作成し retentionDays を設定すること。"
            "既存ロググループには Lambda Custom Resource で一括設定できる。"
        ),
        "days_ago": 86,
    },
    {
        "title": "CloudWatch Logs コスト再増加 — Lambda の verbose ログ",
        "description": "診断エージェントが DEBUG レベルのログを大量出力しており CloudWatch Logs のコストが再び増加した。",
        "category": "other",
        "severity": "low",
        "status": "resolved",
        "resolution": "本番環境のログレベルを WARNING に変更。AWS Lambda Powertools の logger を使い LOG_LEVEL 環境変数で制御。",
        "lesson_learned": (
            "Lambda の DEBUG ログは開発時のみ有効にし、本番は WARNING 以上にすること。"
            "Powertools Logger を使うと LOG_LEVEL 環境変数でランタイム制御できる。"
            "CloudWatch Logs Insights で頻出ログパターンを定期的に確認してノイズを削減すること。"
        ),
        "days_ago": 63,
    },
    {
        "title": "EventBridge Rule が誤った SQS にルーティング",
        "description": "EventBridge のルール設定ミスでアラームイベントが agora-alarm-queue ではなく別のキューに送られており、チケット自動起票が停止していた。",
        "category": "other",
        "severity": "high",
        "status": "resolved",
        "resolution": "EventBridge Rule の Target ARN を修正。CDK で Rule と SQS の依存関係を明示的に定義。",
        "lesson_learned": (
            "EventBridge Rule の Target は CDK のリソース参照 (queue.queueArn) を使い、"
            "文字列ハードコードを避けること。ハードコードは環境差分でミスが発生する。"
        ),
        "days_ago": 72,
    },
    {
        "title": "EventBridge Scheduler が無効化されたまま放置",
        "description": "demo-stop 後に EventBridge Scheduler が無効のままになっており、翌日のデモで fake-api-server が動かなかった。",
        "category": "other",
        "severity": "medium",
        "status": "resolved",
        "resolution": "make demo-stop に 'Scheduler は無効化されたままです。再度有効にするには make demo-start を実行してください' の警告メッセージを追加。",
        "lesson_learned": (
            "デモ手順書に demo-stop 後の状態リセット手順を明記すること。"
            "Scheduler の enabled/disabled 状態を確認するコマンドを Makefile の demo-status ターゲットとして追加すること。"
        ),
        "days_ago": 36,
    },
    {
        "title": "SQS Dead-Letter Queue が満杯 — メッセージ処理失敗",
        "description": "agora-alarm-queue の DLQ が満杯になっているアラームが発火。bridge Lambda が SQS メッセージの処理に繰り返し失敗している。",
        "category": "other",
        "severity": "high",
        "status": "resolved",
        "resolution": "bridge Lambda のバグを修正。DLQ に入ったメッセージを手動でリドライブして再処理。",
        "lesson_learned": (
            "SQS DLQ は定期的に監視すること。DLQ にメッセージが入ったら即座にアラームが発火するよう"
            " CloudWatch Alarm (ApproximateNumberOfMessagesVisible >= 1) を設定すること。"
            "SQS の Message Redrive 機能を使うと DLQ から元キューへの再処理が容易。"
        ),
        "days_ago": 53,
    },
    {
        "title": "SQS DLQ 再び満杯 — Lambda タイムアウトが根本原因",
        "description": "bridge Lambda のタイムアウトが 3 秒に設定されており、Ticket Service への HTTP リクエストが間に合わずに失敗し続けた。",
        "category": "other",
        "severity": "medium",
        "status": "resolved",
        "resolution": "Lambda タイムアウトを 3 秒 → 30 秒に延長。HTTP リクエストのリトライロジックも追加。",
        "lesson_learned": (
            "Lambda のデフォルトタイムアウト (3 秒) は外部 HTTP リクエストには短すぎる。"
            "コールド外部サービスへの呼び出しがある Lambda は最低 30 秒に設定すること。"
            "SQS VisibilityTimeout は Lambda タイムアウトの 6 倍以上に設定することが AWS の推奨。"
        ),
        "days_ago": 31,
    },
    {
        "title": "SNS トピック配信失敗 — HTTPS エンドポイントの証明書エラー",
        "description": "SNS から HTTPS エンドポイントへの配信が TLS 証明書エラーで失敗。ACM 証明書の更新を失念していた。",
        "category": "other",
        "severity": "high",
        "status": "resolved",
        "resolution": "ACM 証明書を手動更新。証明書有効期限 30 日前に CloudWatch Alarm を設定。",
        "lesson_learned": (
            "ACM 証明書の自動更新が失敗するケース (DNS 検証レコードの削除等) がある。"
            "証明書有効期限 30 日前の CloudWatch Alarm を必ず設定し、早期に気づける体制を作ること。"
        ),
        "days_ago": 41,
    },
    {
        "title": "X-Ray トレース欠落 — サービス間の相関が切れた",
        "description": "Diagnosis Agent から MCP サーバーへのリクエストで X-Ray トレース ID が伝播されておらず、分散トレーシングの連鎖が切れた。",
        "category": "other",
        "severity": "low",
        "status": "open",
        "resolution": None,
        "lesson_learned": None,
        "days_ago": 6,
    },
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Content-Type": "application/json"}


def _create_ticket(base_url: str, api_key: str, t: dict[str, Any]) -> str:
    payload = {
        "title": t["title"],
        "description": t["description"],
        "category": t["category"],
        "severity": t["severity"],
    }
    r = httpx.post(f"{base_url}/tickets", json=payload, headers=_headers(api_key), timeout=30)
    r.raise_for_status()
    return r.json()["ticket_id"]


def _resolve_ticket(base_url: str, api_key: str, ticket_id: str, t: dict[str, Any]) -> None:
    payload: dict[str, Any] = {
        "status": "resolved",
        "resolution": t["resolution"],
        "lesson_learned": t["lesson_learned"],
        "actor": "seed-script",
    }
    r = httpx.patch(f"{base_url}/tickets/{ticket_id}", json=payload, headers=_headers(api_key), timeout=30)
    r.raise_for_status()


def _investigate_ticket(base_url: str, api_key: str, ticket_id: str) -> None:
    payload: dict[str, Any] = {"status": "investigating", "actor": "seed-script"}
    r = httpx.patch(f"{base_url}/tickets/{ticket_id}", json=payload, headers=_headers(api_key), timeout=30)
    r.raise_for_status()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("==> Resolving Ticket Service URL from CloudFormation ...")
    base_url = _resolve_ticket_url()
    print(f"    URL: {base_url}")

    print("==> Fetching API key from Secrets Manager ...")
    api_key = _resolve_api_key()
    print("    OK")

    total = len(_TICKETS)
    resolved_count = 0
    investigating_count = 0
    open_count = 0

    print(f"\n==> Creating {total} tickets ...\n")
    for i, t in enumerate(_TICKETS, start=1):
        ticket_id = _create_ticket(base_url, api_key, t)
        status = t["status"]

        if status == "resolved":
            _resolve_ticket(base_url, api_key, ticket_id, t)
            resolved_count += 1
            label = "resolved"
        elif status == "investigating":
            _investigate_ticket(base_url, api_key, ticket_id)
            investigating_count += 1
            label = "investigating"
        else:
            open_count += 1
            label = "open    "

        print(f"  [{i:02d}/{total}] {label}  {t['category']:<12}  {ticket_id}  {t['title'][:55]}")

        # Streams トリガーのレート制限を避けるため少し待機
        if status == "resolved":
            time.sleep(0.5)

    print(f"""
==> Done.
    resolved     : {resolved_count}
    investigating: {investigating_count}
    open         : {open_count}
    total        : {total}

Note: DynamoDB Streams → knowledge-consumer Lambda が非同期で動いています。
      Knowledge テーブルと S3 Vectors への書き込みは 10〜30 秒後に完了します。
""")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)

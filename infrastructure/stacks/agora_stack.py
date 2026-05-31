from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import aws_cdk as cdk
import aws_cdk.aws_bedrock as bedrock
import aws_cdk.aws_bedrockagentcore as agentcore
import aws_cdk.aws_cloudfront as cloudfront
import aws_cdk.aws_cloudfront_origins as origins
import aws_cdk.aws_dynamodb as dynamodb
import aws_cdk.aws_ecr_assets as ecr_assets
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_lambda_event_sources as event_sources
import aws_cdk.aws_logs as logs
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_s3vectors as s3v
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
import jsii
from aws_cdk.aws_s3_deployment import BucketDeployment, Source
from constructs import Construct
from pydantic_settings import BaseSettings


@jsii.implements(cdk.ILocalBundling)
class _LocalNodeBundler:
    """Docker なしで React UI をバンドルするローカルバンドラー。

    優先順位:
    1. npm が利用可能 → npm ci && npm run build をローカル実行
    2. ui/dist/ が存在 → 既存のビルド成果物をコピー
    3. それ以外      → 最小スタブを生成（テスト / CDK synth 専用）

    try_bundle が True を返すため Docker フォールバックは不要。
    """

    def __init__(self, ui_dir: str) -> None:
        self._ui = Path(ui_dir)

    def try_bundle(self, output_dir: str, options: cdk.BundlingOptions) -> bool:
        dist = self._ui / "dist"

        if shutil.which("npm"):
            subprocess.check_call(["npm", "ci"], cwd=str(self._ui))
            subprocess.check_call(["npm", "run", "build"], cwd=str(self._ui))

        if dist.exists():
            for item in dist.iterdir():
                dst = Path(output_dir) / item.name
                if item.is_dir():
                    shutil.copytree(item, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dst)
            return True

        # テスト環境向け最小スタブ — CloudFormation テンプレート合成のみ通す
        Path(output_dir, "index.html").write_text("<html><body>Agora UI</body></html>")
        return True



_ROOT = Path(__file__).parent.parent.parent
_UI_DIR = str(_ROOT / "ui")
_AGENTS_DIR = _ROOT / "agents"
_SKILLS_DIR = _ROOT / "skills"
_MCP_DIR = _ROOT / "mcp-servers"
_SERVICES_DIR = _ROOT / "services"
_LAMBDA_DIR = Path(__file__).parent.parent / "lambda"
_LAMBDA_CLOUDWATCH_MCP_DIR = Path(__file__).parent.parent / "lambda-cloudwatch-mcp"
_SPECS_DIR = Path(__file__).parent.parent / "specs"


# ── モデル ID ──────────────────────────────────────────────────────────────
_MODEL_HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_MODEL_SONNET = "us.anthropic.claude-sonnet-4-6"

# ── Lambda メモリ (MiB) ────────────────────────────────────────────────────
_MEMORY_SERVICE_MB = 512
_MEMORY_WORKER_MB = 256

# ── Lambda タイムアウト ────────────────────────────────────────────────────
_TIMEOUT_SERVICE = cdk.Duration.seconds(30)
_TIMEOUT_LONG = cdk.Duration.seconds(900)

# ── ログ保持 / DLQ 保持 ────────────────────────────────────────────────────
_LOG_RETENTION = logs.RetentionDays.ONE_WEEK
_DLQ_RETENTION = cdk.Duration.days(14)

# ── DynamoDB イベントソース ────────────────────────────────────────────────
_DYNAMO_BATCH_SIZE = 10
_DYNAMO_RETRY_ATTEMPTS = 2

# ── AgentCore ─────────────────────────────────────────────────────────────
_GUARDRAIL_VERSION = "DRAFT"
_CATALOG_VERSION = "18"
_API_KEY_LENGTH = 32

# ── DynamoDB インデックス名 ────────────────────────────────────────────────
_TICKETS_STATUS_INDEX = "status-created_at-index"
_TICKETS_CATEGORY_INDEX = "category-created_at-index"
_KNOWLEDGE_CATEGORY_INDEX = "category-crystallized_at-index"

# ── S3 Vectors ─────────────────────────────────────────────────────────────
_VECTOR_BUCKET_NAME = "agora-incident-vectors"
_VECTOR_INDEX_NAME = "tickets"
_VECTOR_DIMENSIONS = 1024  # Titan Embeddings V2 デフォルト次元数
_EMBED_MODEL_TITAN = "amazon.titan-embed-text-v2:0"


class _Settings(BaseSettings):
    github_token: str = ""


def _github_env() -> dict[str, str]:
    """GITHUB_TOKEN が設定されている場合のみ env dict を返す。"""
    token = _Settings().github_token
    return {"GITHUB_TOKEN": token} if token else {}


_MCP_SERVERS: list[dict] = [
    {
        "name": "stackoverflow",
        "runtime_name": "agora_stackoverflow",
        "description": "Stack Overflow search MCP — queries Stack Exchange API for Q&A",
        "capability": "community-knowledge",
        "env": {},
    },
    {
        "name": "github-issues",
        "runtime_name": "agora_github_issues",
        "description": "GitHub Issues search MCP — searches GitHub for bug reports and discussions",
        "capability": "community-knowledge",
        "env": {},  # GITHUB_TOKEN は _github_env() で構築時に注入
    },
    {
        "name": "infrastructure-inspector",
        "runtime_name": "agora_infrastructure_inspector",
        "description": "Infrastructure Inspector MCP — inspects Lambda, FIS, and CloudFormation",
        "capability": "aws-infrastructure",
        "env": {"FASTMCP_LOG_LEVEL": "WARNING"},
    },
]

_A2A_AGENTS: list[dict] = [
    {
        "name": "triage",
        "runtime_name": "agora_triage",
        "description": "Triage Agent — classifies IT incidents by severity and category",
        "capability": "a2a-agent",
        "env": {"MODEL_ID": _MODEL_HAIKU},
    },
    {
        "name": "diagnosis",
        "runtime_name": "agora_diagnosis",
        "description": "Diagnosis Agent — searches community knowledge and past tickets",
        "capability": "a2a-agent",
        "env": {"MODEL_ID": _MODEL_SONNET},
    },
    {
        "name": "resolution",
        "runtime_name": "agora_resolution",
        "description": "Resolution Agent — generates resolution plans and creates incident tickets",
        "capability": "a2a-agent",
        "env": {"MODEL_ID": _MODEL_SONNET},
    },
]


def _logical_id(runtime_name: str) -> str:
    return "".join(part.title() for part in runtime_name.split("_"))


def _runtime_invocation_url(runtime: agentcore.CfnRuntime, region: str, account: str) -> str:
    return (
        f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
        f"arn%3Aaws%3Abedrock-agentcore%3A{region}%3A{account}%3Aruntime%2F"
        f"{runtime.attr_agent_runtime_id}/invocations?qualifier=DEFAULT"
    )


class AgoraStack(cdk.Stack):
    """Agora プラットフォーム本体。

    DynamoDB / Lambda / AgentCore を単一スタックに統合し、循環参照を解消する。
    全リソースに RemovalPolicy.DESTROY を設定し、スタック削除で完全クリーンアップできる。
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # =====================================================================
        # DATA — DynamoDB テーブル
        # =====================================================================
        self.tickets_table = dynamodb.Table(
            self,
            "TicketsTable",
            table_name="agora-tickets",
            partition_key=dynamodb.Attribute(
                name="ticket_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
        )
        self.tickets_table.add_global_secondary_index(
            index_name=_TICKETS_STATUS_INDEX,
            partition_key=dynamodb.Attribute(
                name="status", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at", type=dynamodb.AttributeType.STRING
            ),
        )
        self.tickets_table.add_global_secondary_index(
            index_name=_TICKETS_CATEGORY_INDEX,
            partition_key=dynamodb.Attribute(
                name="category", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at", type=dynamodb.AttributeType.STRING
            ),
        )

        self.knowledge_table = dynamodb.Table(
            self,
            "KnowledgeTable",
            table_name="agora-knowledge",
            partition_key=dynamodb.Attribute(
                name="knowledge_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        self.knowledge_table.add_global_secondary_index(
            index_name=_KNOWLEDGE_CATEGORY_INDEX,
            partition_key=dynamodb.Attribute(
                name="category", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="crystallized_at", type=dynamodb.AttributeType.STRING
            ),
        )

        # =====================================================================
        # S3 VECTORS — 類似インシデント検索用ベクターストア
        # =====================================================================
        self.vector_bucket = s3v.CfnVectorBucket(
            self,
            "IncidentVectorBucket",
            vector_bucket_name=_VECTOR_BUCKET_NAME,
        )
        self.vector_bucket.apply_removal_policy(cdk.RemovalPolicy.DESTROY)

        self.vector_index = s3v.CfnIndex(
            self,
            "IncidentVectorIndex",
            vector_bucket_name=_VECTOR_BUCKET_NAME,
            index_name=_VECTOR_INDEX_NAME,
            data_type="float32",
            dimension=_VECTOR_DIMENSIONS,
            distance_metric="cosine",
        )
        self.vector_index.add_dependency(self.vector_bucket)
        self.vector_index.apply_removal_policy(cdk.RemovalPolicy.DESTROY)

        # =====================================================================
        # SECRETS — API キー (Gateway → Service 認証)
        # =====================================================================
        self.services_api_key_secret = secretsmanager.Secret(
            self,
            "ServicesApiKeySecret",
            secret_name="agora/services-api-key",
            description="API key: AgentCore Gateway → internal FastAPI services",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True,
                password_length=_API_KEY_LENGTH,
            ),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # =====================================================================
        # IAM — Lambda 実行ロール
        # =====================================================================
        _basic_exec = iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaBasicExecutionRole"
        )
        _dynamo_rw = [
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:Query",
            "dynamodb:Scan",
            "dynamodb:BatchGetItem",
        ]

        _xray_write = iam.ManagedPolicy.from_aws_managed_policy_name("AWSXRayDaemonWriteAccess")
        _app_signals = iam.ManagedPolicy.from_aws_managed_policy_name(
            "CloudWatchLambdaApplicationSignalsExecutionRolePolicy"
        )
        self.ticket_role = iam.Role(
            self,
            "TicketServiceRole",
            role_name="agora-ticket-service-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[_basic_exec, _xray_write, _app_signals],
        )
        self.ticket_role.add_to_policy(
            iam.PolicyStatement(
                actions=_dynamo_rw,
                resources=[
                    self.tickets_table.table_arn,
                    self.tickets_table.table_arn + "/index/*",
                ],
            )
        )
        self.ticket_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
                resources=[self.services_api_key_secret.secret_arn],
            )
        )
        self.ticket_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:GetPrompt"],
                resources=[f"arn:aws:bedrock:{self.region}:{self.account}:prompt/*"],
            )
        )
        self.ticket_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3vectors:QueryVectors", "s3vectors:GetVectors"],
                resources=[self.vector_bucket.attr_vector_bucket_arn + "/*"],
            )
        )
        self.ticket_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/{_EMBED_MODEL_TITAN}"
                ],
            )
        )

        self.chat_proxy_role = iam.Role(
            self,
            "ChatProxyRole",
            role_name="agora-chat-proxy-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                _basic_exec,
                _xray_write,
                _app_signals,
            ],
        )
        self.chat_proxy_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=["*"],
            )
        )

        # =====================================================================
        # IAM — AgentCore ロール (MCP / A2A / Gateway)
        # =====================================================================
        self.mcp_runtime_role = iam.Role(
            self,
            "McpRuntimeRole",
            role_name="agora-mcp-runtime-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
        )
        for _actions, _resources in [
            (
                ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:GetAuthorizationToken"],
                ["*"],
            ),
            (
                ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                ["*"],
            ),
            (
                [
                    "cloudwatch:GetMetricData",
                    "cloudwatch:GetMetricStatistics",
                    "cloudwatch:ListMetrics",
                    "cloudwatch:DescribeAlarms",
                    "cloudwatch:DescribeAlarmsForMetric",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                    "logs:FilterLogEvents",
                    "logs:GetLogEvents",
                    "logs:StartQuery",
                    "logs:GetQueryResults",
                ],
                ["*"],
            ),
            (
                [
                    "xray:PutTraceSegments",
                    "xray:PutSpans",
                    "xray:PutSpansForIndexing",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                    "xray:GetSamplingStatisticSummaries",
                    "cloudwatch:PutMetricData",
                ],
                ["*"],
            ),
            (
                [
                    "lambda:GetFunction",
                    "lambda:ListEventSourceMappings",
                    "lambda:ListTags",
                    "fis:ListExperiments",
                    "fis:GetExperiment",
                    "fis:GetExperimentTemplate",
                    "cloudformation:DescribeStacks",
                    "cloudformation:DescribeStackResources",
                ],
                ["*"],
            ),
        ]:
            self.mcp_runtime_role.add_to_policy(
                iam.PolicyStatement(actions=_actions, resources=_resources)
            )

        self.gateway_execution_role = iam.Role(
            self,
            "GatewayExecutionRole",
            role_name="agora-gateway-execution-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
        )
        self.gateway_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:InvokeAgentRuntime",
                    "bedrock-agentcore:GetApiKeyCredentialProvider",
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetResourceApiKey",
                ],
                resources=["*"],
            )
        )
        self.gateway_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}"
                    ":secret:bedrock-agentcore-identity*"
                ],
            )
        )
        self.gateway_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=["*"],
            )
        )
        self.gateway_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "xray:PutTraceSegments",
                    "xray:PutSpans",
                    "xray:PutSpansForIndexing",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                    "xray:GetSamplingStatisticSummaries",
                    "cloudwatch:PutMetricData",
                ],
                resources=["*"],
            )
        )

        # 共通エージェントロール (triage/diagnosis/resolution 共有ベース権限)
        _agent_common_policies = [
            (
                ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                [
                    f"arn:aws:bedrock:{self.region}::foundation-model/*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                    "arn:aws:bedrock:*::foundation-model/*",
                    "arn:aws:bedrock:*::inference-profile/*",
                ],
            ),
            (["bedrock-agentcore:InvokeAgentRuntime"], ["*"]),
            (
                [
                    "bedrock-agentcore:ListAgentRuntimes",
                    "bedrock-agentcore:GetAgentRuntime",
                    "bedrock-agentcore:ListAgentRuntimeEndpoints",
                    "bedrock-agentcore:GetAgentRuntimeEndpoint",
                    "bedrock-agentcore:ListRegistries",
                    "bedrock-agentcore:GetRegistry",
                    "bedrock-agentcore:ListRegistryRecords",
                    "bedrock-agentcore:GetRegistryRecord",
                ],
                ["*"],
            ),
            (
                ["secretsmanager:GetSecretValue"],
                [f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:agora/*"],
            ),
            (
                ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                ["*"],
            ),
            (
                ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:GetAuthorizationToken"],
                ["*"],
            ),
            (
                ["bedrock:ApplyGuardrail"],
                [f"arn:aws:bedrock:{self.region}:{self.account}:guardrail/*"],
            ),
            (
                ["bedrock:GetPrompt"],
                [f"arn:aws:bedrock:{self.region}:{self.account}:prompt/*"],
            ),
            (
                [
                    "xray:PutTraceSegments",
                    "xray:PutSpans",
                    "xray:PutSpansForIndexing",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                    "xray:GetSamplingStatisticSummaries",
                ],
                ["*"],
            ),
            # ADOT distro が bedrock-agentcore namespace で Application Signals メトリクスを書き込む
            (["cloudwatch:PutMetricData"], ["*"]),
        ]

        # Gateway Agent runtime ロール (A2A orchestrator)
        self.agent_runtime_role = iam.Role(
            self,
            "AgentRuntimeRole",
            role_name="agora-agent-runtime-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
        )
        for _a, _r in _agent_common_policies:
            self.agent_runtime_role.add_to_policy(iam.PolicyStatement(actions=_a, resources=_r))

        # Per-agent ロール (Cedar policy 用)
        _per_agent_roles: dict[str, iam.Role] = {}
        for _agent_name, _lid in [
            ("triage", "Triage"), ("diagnosis", "Diagnosis"), ("resolution", "Resolution"),
        ]:
            _r = iam.Role(
                self,
                f"{_lid}RuntimeRole",
                role_name=f"agora-{_agent_name}-runtime-role",
                assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            )
            for _a, _res in _agent_common_policies:
                _r.add_to_policy(iam.PolicyStatement(actions=_a, resources=_res))
            _per_agent_roles[_agent_name] = _r

        # Diagnosis: CloudWatch 読み取り (過去チケット参照は Gateway 経由 ticket-service に委譲)
        _per_agent_roles["diagnosis"].add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudwatch:DescribeAlarms",
                    "cloudwatch:DescribeAlarmsForMetric",
                    "cloudwatch:GetMetricData",
                    "cloudwatch:GetMetricStatistics",
                    "cloudwatch:ListMetrics",
                ],
                resources=["*"],
            )
        )
        # Diagnosis: Registry MCP SigV4 呼び出し (runbook 選択の search_registry_records)
        # InvokeRegistryMcp: MCP initialize/tools/list, SearchRegistryRecords: tools/call
        _per_agent_roles["diagnosis"].add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:InvokeRegistryMcp",
                    "bedrock-agentcore:SearchRegistryRecords",
                ],
                resources=[f"arn:aws:bedrock-agentcore:*:{self.account}:registry/*"],
            )
        )

        # =====================================================================
        # BEDROCK GUARDRAIL — Gateway Agent 用
        # =====================================================================
        self.guardrail = bedrock.CfnGuardrail(
            self,
            "GatewayGuardrail",
            name="agora-chat-guardrail",
            description="Chat Agent 用 Guardrail — FIS 操作と実システム変更をブロック",
            blocked_input_messaging=(
                "申し訳ありませんが、その操作はサポートされていません。"
                "Agora はシステム変更の実行や FIS 実験の操作は行いません。"
                "提案・分析に関するご質問はお気軽にどうぞ。"
            ),
            blocked_outputs_messaging=(
                "申し訳ありませんが、その応答はポリシーに違反しています。"
                "提案・分析に関するご質問はお気軽にどうぞ。"
            ),
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="FisExperimentControl",
                        definition=(
                            "AWS FIS の実験テンプレートを起動・停止・変更・削除する操作。"
                            "障害注入の開始・停止・スケジュール設定を含む。"
                        ),
                        examples=[
                            "FIS 実験を開始してください",
                            "障害注入を止めて",
                            "Run the chaos experiment",
                        ],
                        type="DENY",
                        input_enabled=True,
                        output_enabled=False,
                    ),
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="SystemChangeControl",
                        definition=(
                            "AWS リソースの設定変更・再起動・削除・スケーリングなど、"
                            "実システムに変更を加える操作。Lambda 関数の再起動や設定変更、"
                            "CloudFormation スタックの削除・更新、EC2 インスタンスの停止・終了、"
                            "IAM ポリシーの変更、S3 バケットの削除などを含む。"
                        ),
                        examples=[
                            "Lambda を再起動してください",
                            "CloudFormation スタックを削除してください",
                            "EC2 インスタンスを停止してください",
                        ],
                        type="DENY",
                        input_enabled=True,
                        output_enabled=False,
                    ),
                ]
            ),
            tags=[cdk.CfnTag(key="project", value="agora")],
        )

        # =====================================================================
        # BEDROCK PROMPT MANAGEMENT — エージェント system prompt + dispatcher template
        # =====================================================================
        def _make_text_prompt(
            logical_id: str,
            name: str,
            description: str,
            text: str,
            input_variables: list[str] | None = None,
        ) -> tuple[bedrock.CfnPrompt, bedrock.CfnPromptVersion]:
            vars_cfg = (
                [bedrock.CfnPrompt.PromptInputVariableProperty(name=v) for v in input_variables]
                if input_variables
                else []
            )
            prompt = bedrock.CfnPrompt(
                self,
                logical_id,
                name=name,
                description=description,
                default_variant="default",
                variants=[
                    bedrock.CfnPrompt.PromptVariantProperty(
                        name="default",
                        template_type="TEXT",
                        template_configuration=bedrock.CfnPrompt.PromptTemplateConfigurationProperty(
                            text=bedrock.CfnPrompt.TextPromptTemplateConfigurationProperty(
                                text=text,
                                input_variables=vars_cfg,
                            )
                        ),
                    )
                ],
                tags={"project": "agora"},
            )
            content_hash = hashlib.sha256(text.encode()).hexdigest()[:8]
            version = bedrock.CfnPromptVersion(
                self,
                logical_id + "Version",
                prompt_arn=prompt.attr_arn,
                description=f"{description} [{content_hash}]",
            )
            return prompt, version

        self.orchestrator_prompt, self.orchestrator_prompt_version = _make_text_prompt(
            "OrchestratorSystemPrompt",
            "agora-orchestrator-system-prompt",
            "Pipeline Orchestrator system prompt",
            (_AGENTS_DIR / "orchestrator" / "system_prompt.md").read_text(),
        )
        self.chat_prompt, self.chat_prompt_version = _make_text_prompt(
            "ChatSystemPrompt",
            "agora-chat-system-prompt",
            "Chat Agent system prompt",
            (_AGENTS_DIR / "chat" / "system_prompt.md").read_text(),
        )
        self.triage_prompt, self.triage_prompt_version = _make_text_prompt(
            "TriageSystemPrompt",
            "agora-triage-system-prompt",
            "Triage Agent system prompt",
            (_AGENTS_DIR / "triage" / "system_prompt.md").read_text(),
        )
        self.diagnosis_prompt, self.diagnosis_prompt_version = _make_text_prompt(
            "DiagnosisSystemPrompt",
            "agora-diagnosis-system-prompt",
            "Diagnosis Agent system prompt",
            (_AGENTS_DIR / "diagnosis" / "system_prompt.md").read_text(),
        )
        self.resolution_prompt, self.resolution_prompt_version = _make_text_prompt(
            "ResolutionSystemPrompt",
            "agora-resolution-system-prompt",
            "Resolution Agent system prompt",
            (_AGENTS_DIR / "resolution" / "system_prompt.md").read_text(),
        )
        self.judgment_prompt, self.judgment_prompt_version = _make_text_prompt(
            "DiagnosisJudgmentPrompt",
            "agora-diagnosis-judgment-prompt",
            "Diagnosis Agent runbook judgment prompt",
            (_AGENTS_DIR / "diagnosis" / "judgment_prompt.md").read_text(),
        )
        self.dispatcher_prompt, self.dispatcher_prompt_version = _make_text_prompt(
            "DispatcherUserPrompt",
            "agora-dispatcher-user-prompt",
            "ticket-dispatcher user prompt template for Gateway Agent",
            (
                "新規インシデントチケット {{ticket_id}} が起票されました。\n"
                "タイトル: {{title}}\n"
                "重要度: {{severity}}\n"
                "概要: {{description}}\n"
                "Triage → Diagnosis → Resolution パイプラインによる診断を開始してください。"
            ),
            input_variables=["ticket_id", "title", "severity", "description"],
        )

        # =====================================================================
        # ECR IMAGE ASSETS — CDK が自動ビルド & プッシュ
        # =====================================================================
        agent_images: dict[str, ecr_assets.DockerImageAsset] = {}

        _mcp_names = [
            "stackoverflow", "github-issues",
            "infrastructure-inspector",
        ]
        for _name in _mcp_names:
            _cid = _name.replace("-", " ").title().replace(" ", "") + "McpImage"
            agent_images[_name] = ecr_assets.DockerImageAsset(
                self,
                _cid,
                directory=str(_MCP_DIR / _name),
                platform=ecr_assets.Platform.LINUX_ARM64,
            )

        for _name in ["triage", "diagnosis", "resolution"]:
            agent_images[_name] = ecr_assets.DockerImageAsset(
                self,
                _name.title() + "AgentImage",
                directory=str(_AGENTS_DIR),
                file=f"{_name}/Dockerfile",
                platform=ecr_assets.Platform.LINUX_ARM64,
            )

        for _img_name in ("orchestrator", "chat"):
            agent_images[_img_name] = ecr_assets.DockerImageAsset(
                self,
                _img_name.title() + "AgentImage",
                directory=str(_AGENTS_DIR),
                file=f"{_img_name}/Dockerfile",
                platform=ecr_assets.Platform.LINUX_ARM64,
            )

        # ECR pull 権限は mcp_runtime_role / agent_runtime_role の add_to_policy("*") で確保済み

        # =====================================================================
        # PIPELINE ORCHESTRATOR RUNTIME — ticket-dispatcher から ARN を注入するため先に作成
        # Guardrails 不要（内部システム呼び出し専用）。add_async_task でノンブロッキング実行。
        # =====================================================================
        self.orchestrator_agent_runtime = agentcore.CfnRuntime(
            self,
            "AgoraOrchestratorRuntime",
            agent_runtime_name="agora_orchestrator",
            description="Pipeline Orchestrator — automated incident diagnostic pipeline (async)",
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=agent_images["orchestrator"].image_uri,
                ),
            ),
            role_arn=self.agent_runtime_role.role_arn,
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC",
            ),
            protocol_configuration="HTTP",
            environment_variables={
                "MODEL_ID": _MODEL_SONNET,
                "SYSTEM_PROMPT_ARN": self.orchestrator_prompt_version.attr_arn,
                "AGENT_OBSERVABILITY_ENABLED": "true",
                "OTEL_SERVICE_NAME": "agora-orchestrator",
            },
            tags={"capability": "pipeline-orchestrator", "project": "agora"},
        )
        agentcore.CfnRuntimeEndpoint(
            self,
            "AgoraOrchestratorEndpoint",
            agent_runtime_id=self.orchestrator_agent_runtime.attr_agent_runtime_id,
            name="agora_orchestrator_ep",
            description="Default endpoint for agora_orchestrator",
        )

        # =====================================================================
        # CHAT AGENT RUNTIME — React UI (AG-UI/SSE) + Guardrails
        # =====================================================================
        self.chat_agent_runtime = agentcore.CfnRuntime(
            self,
            "AgoraChatRuntime",
            agent_runtime_name="agora_chat",
            description="Chat Agent — user-facing interactive assistant (AG-UI/SSE)",
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=agent_images["chat"].image_uri,
                ),
            ),
            role_arn=self.agent_runtime_role.role_arn,
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC",
            ),
            protocol_configuration="HTTP",
            environment_variables={
                "MODEL_ID": _MODEL_SONNET,
                "GUARDRAIL_ID": self.guardrail.attr_guardrail_id,
                "GUARDRAIL_VERSION": _GUARDRAIL_VERSION,
                "SYSTEM_PROMPT_ARN": self.chat_prompt_version.attr_arn,
                "AGENT_OBSERVABILITY_ENABLED": "true",
                "OTEL_SERVICE_NAME": "agora-chat",
            },
            tags={"capability": "chat-agent", "project": "agora"},
        )
        agentcore.CfnRuntimeEndpoint(
            self,
            "AgoraChatEndpoint",
            agent_runtime_id=self.chat_agent_runtime.attr_agent_runtime_id,
            name="agora_chat_ep",
            description="Default endpoint for agora_chat",
        )

        # =====================================================================
        # LAMBDA FUNCTIONS
        # =====================================================================
        # ADOT auto-instrumentation via Lambda Extension (layer.zip in Dockerfile)
        # ADOT Lambda Layer (layer.zip を Docker 内に /opt/ 展開) の OTEL 設定。
        # OTEL_AWS_APPLICATION_SIGNALS_ENABLED はデフォルト true のまま使用する。
        # aws_configurator が localhost:4316 (Lambda Application Signals OTLP receiver) に
        # スパンを送信し、X-Ray → CloudWatchLogs (aws/spans) に転送される。
        _adot_env = {
            "AWS_LAMBDA_EXEC_WRAPPER": "/opt/otel-instrument",
            "OTEL_PROPAGATORS": "xray",
        }
        _common_env = {
            "AWS_LWA_PORT": "8080",
            "AWS_LWA_READINESS_CHECK_PATH": "/health",
            **_adot_env,
        }

        self.ticket_fn = lambda_.DockerImageFunction(
            self,
            "TicketServiceFn",
            function_name="agora-ticket-service",
            code=lambda_.DockerImageCode.from_image_asset(
                str(_SERVICES_DIR / "ticket-service"),
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=_MEMORY_SERVICE_MB,
            timeout=_TIMEOUT_SERVICE,
            tracing=lambda_.Tracing.ACTIVE,
            role=self.ticket_role,
            log_group=logs.LogGroup(
                self,
                "TicketServiceFnLogs",
                log_group_name="/aws/lambda/agora-ticket-service",
                retention=_LOG_RETENTION,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment={
                **_common_env,
                "TABLE_NAME": self.tickets_table.table_name,
                "API_KEY_SECRET_NAME": self.services_api_key_secret.secret_name,
                "ORCHESTRATOR_PROMPT_ARN": self.orchestrator_prompt_version.attr_arn,
                "CHAT_PROMPT_ARN": self.chat_prompt_version.attr_arn,
                "TRIAGE_PROMPT_ARN": self.triage_prompt_version.attr_arn,
                "DIAGNOSIS_PROMPT_ARN": self.diagnosis_prompt_version.attr_arn,
                "RESOLUTION_PROMPT_ARN": self.resolution_prompt_version.attr_arn,
                "VECTOR_BUCKET_NAME": _VECTOR_BUCKET_NAME,
                "VECTOR_INDEX_NAME": _VECTOR_INDEX_NAME,
            },
        )

        self.ticket_url = self.ticket_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )
        self.chat_proxy_fn = lambda_.DockerImageFunction(
            self,
            "ChatProxyFn",
            function_name="agora-chat-proxy",
            code=lambda_.DockerImageCode.from_image_asset(
                str(_SERVICES_DIR / "chat-proxy"),
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=_MEMORY_SERVICE_MB,
            timeout=_TIMEOUT_LONG,
            tracing=lambda_.Tracing.ACTIVE,
            role=self.chat_proxy_role,
            log_group=logs.LogGroup(
                self,
                "ChatProxyFnLogs",
                log_group_name="/aws/lambda/agora-chat-proxy",
                retention=_LOG_RETENTION,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment={
                **_common_env,
                # AGENT_RUNTIME_ARN はスタック内で直接解決 (循環参照なし)
                "AGENT_RUNTIME_ARN": self.chat_agent_runtime.attr_agent_runtime_arn,
            },
        )
        self.chat_proxy_url = self.chat_proxy_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.AWS_IAM,
        )

        # ticket-dispatcher — DynamoDB Streams consumer
        _dispatcher_role = iam.Role(
            self,
            "TicketDispatcherRole",
            role_name="agora-ticket-dispatcher-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                _basic_exec,
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaDynamoDBExecutionRole"
                ),
                _xray_write,
                _app_signals,
            ],
        )
        _dispatcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=["*"],
            )
        )
        _dispatcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:GetPrompt"],
                resources=[f"arn:aws:bedrock:{self.region}:{self.account}:prompt/*"],
            )
        )

        _dispatcher_dlq = sqs.Queue(
            self,
            "TicketDispatcherDlq",
            queue_name="agora-ticket-dispatcher-dlq",
            retention_period=_DLQ_RETENTION,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        _dispatcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sqs:SendMessage"],
                resources=[_dispatcher_dlq.queue_arn],
            )
        )

        self.ticket_dispatcher_fn = lambda_.DockerImageFunction(
            self,
            "TicketDispatcherFn",
            function_name="agora-ticket-dispatcher",
            code=lambda_.DockerImageCode.from_image_asset(
                str(_SERVICES_DIR / "ticket-dispatcher"),
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=_MEMORY_WORKER_MB,
            timeout=_TIMEOUT_LONG,
            tracing=lambda_.Tracing.ACTIVE,
            role=_dispatcher_role,
            log_group=logs.LogGroup(
                self,
                "TicketDispatcherFnLogs",
                log_group_name="/aws/lambda/agora-ticket-dispatcher",
                retention=_LOG_RETENTION,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment={
                **_adot_env,
                "OTEL_SERVICE_NAME": "agora-ticket-dispatcher",
                # AGENT_RUNTIME_ARN はスタック内で直接解決 (循環参照なし)
                "AGENT_RUNTIME_ARN": self.orchestrator_agent_runtime.attr_agent_runtime_arn,
                "DISPATCHER_PROMPT_ARN": self.dispatcher_prompt_version.attr_arn,
            },
        )
        # DynamoEventSource の内部実装は Grant.addToPrincipal(scope=...) を呼ぶ (deprecated)。
        # _dispatcher_role は AWSLambdaDynamoDBExecutionRole で必要権限を既に保有するため
        # EventSourceMapping を直接作成して不要な grant を回避する。
        lambda_.EventSourceMapping(
            self,
            "TicketDispatcherEventSource",
            target=self.ticket_dispatcher_fn,
            event_source_arn=self.tickets_table.table_stream_arn,
            starting_position=lambda_.StartingPosition.LATEST,
            batch_size=_DYNAMO_BATCH_SIZE,
            bisect_batch_on_error=True,
            retry_attempts=_DYNAMO_RETRY_ATTEMPTS,
            report_batch_item_failures=True,
            on_failure=event_sources.SqsDlq(_dispatcher_dlq),
            filters=[
                lambda_.FilterCriteria.filter(
                    {"eventName": lambda_.FilterRule.is_equal("INSERT")}
                )
            ],
        )

        # knowledge-consumer — DynamoDB Streams MODIFY consumer (V4)
        _knowledge_consumer_role = iam.Role(
            self,
            "KnowledgeConsumerRole",
            role_name="agora-knowledge-consumer-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                _basic_exec,
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaDynamoDBExecutionRole"
                ),
                _xray_write,
                _app_signals,
            ],
        )
        _knowledge_consumer_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:PutItem"],
                resources=[self.knowledge_table.table_arn],
            )
        )
        _knowledge_consumer_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3vectors:PutVectors"],
                resources=[self.vector_bucket.attr_vector_bucket_arn + "/*"],
            )
        )
        _knowledge_consumer_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/{_EMBED_MODEL_TITAN}"
                ],
            )
        )

        _knowledge_consumer_dlq = sqs.Queue(
            self,
            "KnowledgeConsumerDlq",
            queue_name="agora-knowledge-consumer-dlq",
            retention_period=_DLQ_RETENTION,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        _knowledge_consumer_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sqs:SendMessage"],
                resources=[_knowledge_consumer_dlq.queue_arn],
            )
        )

        self.knowledge_consumer_fn = lambda_.DockerImageFunction(
            self,
            "KnowledgeConsumerFn",
            function_name="agora-knowledge-consumer",
            code=lambda_.DockerImageCode.from_image_asset(
                str(_SERVICES_DIR / "knowledge-consumer"),
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=_MEMORY_WORKER_MB,
            timeout=_TIMEOUT_LONG,
            tracing=lambda_.Tracing.ACTIVE,
            role=_knowledge_consumer_role,
            log_group=logs.LogGroup(
                self,
                "KnowledgeConsumerFnLogs",
                log_group_name="/aws/lambda/agora-knowledge-consumer",
                retention=_LOG_RETENTION,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment={
                **_adot_env,
                "OTEL_SERVICE_NAME": "agora-knowledge-consumer",
                "KNOWLEDGE_TABLE_NAME": self.knowledge_table.table_name,
                "VECTOR_BUCKET_NAME": _VECTOR_BUCKET_NAME,
                "VECTOR_INDEX_NAME": _VECTOR_INDEX_NAME,
            },
        )
        lambda_.EventSourceMapping(
            self,
            "KnowledgeConsumerEventSource",
            target=self.knowledge_consumer_fn,
            event_source_arn=self.tickets_table.table_stream_arn,
            starting_position=lambda_.StartingPosition.LATEST,
            batch_size=_DYNAMO_BATCH_SIZE,
            bisect_batch_on_error=True,
            retry_attempts=_DYNAMO_RETRY_ATTEMPTS,
            report_batch_item_failures=True,
            on_failure=event_sources.SqsDlq(_knowledge_consumer_dlq),
            filters=[
                lambda_.FilterCriteria.filter(
                    {
                        "eventName": lambda_.FilterRule.is_equal("MODIFY"),
                        "dynamodb": {
                            "NewImage": {
                                "status": {"S": lambda_.FilterRule.is_equal("resolved")}
                            }
                        },
                    }
                )
            ],
        )

        # =====================================================================
        # CLOUDFRONT + S3 — React SPA
        # =====================================================================
        self.ui_bucket = s3.Bucket(
            self,
            "UiBucket",
            bucket_name=f"agora-ui-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        strip_api_fn = cloudfront.Function(
            self,
            "StripApiPrefix",
            code=cloudfront.FunctionCode.from_inline(
                "function handler(event){"
                "var r=event.request;"
                "if(r.uri.startsWith('/api/')){"
                "r.uri=r.uri.substring(4);}"
                "return r;}"
            ),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )

        ui_origin = origins.S3BucketOrigin.with_origin_access_control(self.ui_bucket)
        chat_origin = origins.FunctionUrlOrigin.with_origin_access_control(
            self.chat_proxy_url,
            read_timeout=cdk.Duration.seconds(60),
        )
        ticket_domain = cdk.Fn.select(2, cdk.Fn.split("/", self.ticket_url.url))
        ticket_origin = origins.HttpOrigin(
            ticket_domain,
            custom_headers={
                # CloudFront custom header は Secrets Manager ARN 参照を受け付けないため平文展開
                "x-api-key": self.services_api_key_secret.secret_value.unsafe_unwrap(),
            },
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
        )

        self.ui_distribution = cloudfront.Distribution(
            self,
            "UiDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=ui_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
            ),
            additional_behaviors={
                "/api/chat": cloudfront.BehaviorOptions(
                    origin=chat_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
                "/api/tickets*": cloudfront.BehaviorOptions(
                    origin=ticket_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    function_associations=[
                        cloudfront.FunctionAssociation(
                            event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                            function=strip_api_fn,
                        )
                    ],
                ),
                "/api/prompts": cloudfront.BehaviorOptions(
                    origin=ticket_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    function_associations=[
                        cloudfront.FunctionAssociation(
                            event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                            function=strip_api_fn,
                        )
                    ],
                ),
            },
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                ),
            ],
        )

        # FunctionUrlOrigin.with_origin_access_control does NOT automatically grant
        # lambda:InvokeFunctionUrl to CloudFront in CDK 2.x. Without this explicit
        # permission the Lambda returns 403, which CloudFront converts to 200+index.html,
        # causing the chat UI to see a JSON parse error instead of a proper response.
        self.chat_proxy_fn.add_permission(
            "AllowCloudFrontOac",
            principal=iam.ServicePrincipal("cloudfront.amazonaws.com"),
            action="lambda:InvokeFunctionUrl",
            source_arn=self.ui_distribution.distribution_arn,
        )

        BucketDeployment(
            self,
            "UiDeployment",
            sources=[
                Source.asset(
                    path=_UI_DIR,
                    bundling=cdk.BundlingOptions(
                        image=cdk.DockerImage.from_registry("node:20-alpine"),
                        command=[
                            "sh",
                            "-c",
                            "npm ci && npm run build && cp -r dist/. /asset-output/",
                        ],
                        environment={},
                        local=_LocalNodeBundler(_UI_DIR),
                    ),
                )
            ],
            destination_bucket=self.ui_bucket,
            distribution=self.ui_distribution,
            distribution_paths=["/*"],
        )

        # =====================================================================
        # AGENTCORE — MCP サーバー / A2A エージェント
        # =====================================================================
        _mcp_runtimes: dict[str, agentcore.CfnRuntime] = {}
        _mcp_endpoints: dict[str, agentcore.CfnRuntimeEndpoint] = {}
        for srv in _MCP_SERVERS:
            _extra = _github_env() if srv["name"] == "github-issues" else {}
            env_vars = {k: v for k, v in {**srv["env"], **_extra}.items() if v}
            env_vars["AGENT_OBSERVABILITY_ENABLED"] = "true"
            env_vars["OTEL_SERVICE_NAME"] = f"agora-{srv['name']}"
            cid = _logical_id(srv["runtime_name"]) + "Runtime"
            runtime = agentcore.CfnRuntime(
                self,
                cid,
                agent_runtime_name=srv["runtime_name"],
                description=srv["description"],
                agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                    container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                        container_uri=agent_images[srv["name"]].image_uri,
                    ),
                ),
                role_arn=self.mcp_runtime_role.role_arn,
                network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                    network_mode="PUBLIC",
                ),
                protocol_configuration="MCP",
                environment_variables=env_vars if env_vars else None,
                tags={"capability": srv["capability"], "project": "agora"},
            )
            _mcp_runtimes[srv["name"]] = runtime
            _ep = agentcore.CfnRuntimeEndpoint(
                self,
                _logical_id(srv["runtime_name"]) + "Endpoint",
                agent_runtime_id=runtime.attr_agent_runtime_id,
                name=f"{srv['runtime_name']}_ep",
                description=f"Default endpoint for {srv['runtime_name']}",
            )
            _mcp_endpoints[srv["name"]] = _ep

        # =====================================================================
        # AGENTCORE GATEWAY — MCP (ツール集約)
        # 先に作成することで A2A エージェントが GATEWAY_URL を直接参照できる
        # =====================================================================
        self.agentcore_gateway = agentcore.CfnGateway(
            self,
            "AgoraGateway",
            name="agora-gateway",
            description="AgentCore Gateway — semantic MCP tool dispatch for Agora IT Service Desk",
            role_arn=self.gateway_execution_role.role_arn,
            authorizer_type="NONE",
            protocol_type="MCP",
            protocol_configuration=agentcore.CfnGateway.GatewayProtocolConfigurationProperty(
                mcp=agentcore.CfnGateway.MCPGatewayConfigurationProperty(
                    search_type="SEMANTIC",
                    instructions=(
                        "Agora IT Service Desk gateway. "
                        "Tools: ticket management (create, list, update), "
                        "community knowledge search (Stack Overflow, GitHub Issues, "
                        "AWS Knowledge), "
                        "infrastructure inspection (Lambda config, active FIS experiments, "
                        "CloudFormation stacks), "
                        "CloudWatch observability (active alarms, metrics, Logs Insights queries)."
                    ),
                )
            ),
            tags={"project": "agora"},
        )

        # =====================================================================
        # A2A → HTTP エージェント — Registry 経由でエンドポイントを発見するため
        # GATEWAY_URL 環境変数は不要。サブエージェントは HTTP protocol で動作。
        # =====================================================================
        _a2a_runtimes: dict[str, agentcore.CfnRuntime] = {}
        _a2a_endpoints: dict[str, agentcore.CfnRuntimeEndpoint] = {}
        _a2a_prompt_arns = {
            "triage": self.triage_prompt_version.attr_arn,
            "diagnosis": self.diagnosis_prompt_version.attr_arn,
            "resolution": self.resolution_prompt_version.attr_arn,
        }
        for agent in _A2A_AGENTS:
            env_vars = dict(agent["env"])
            env_vars["SYSTEM_PROMPT_ARN"] = _a2a_prompt_arns[agent["name"]]
            if agent["name"] == "diagnosis":
                env_vars["JUDGMENT_PROMPT_ARN"] = self.judgment_prompt_version.attr_arn
            env_vars["AGENT_OBSERVABILITY_ENABLED"] = "true"
            env_vars["OTEL_SERVICE_NAME"] = f"agora-{agent['name']}"
            cid = _logical_id(agent["runtime_name"]) + "Runtime"
            runtime = agentcore.CfnRuntime(
                self,
                cid,
                agent_runtime_name=agent["runtime_name"],
                description=agent["description"],
                agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                    container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                        container_uri=agent_images[agent["name"]].image_uri,
                    ),
                ),
                role_arn=_per_agent_roles[agent["name"]].role_arn,
                network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                    network_mode="PUBLIC",
                ),
                protocol_configuration="HTTP",
                environment_variables=env_vars,
                tags={
                    "capability": agent["capability"],
                    "agent-type": agent["name"],
                    "project": "agora",
                },
            )
            _a2a_runtimes[agent["name"]] = runtime
            _ep = agentcore.CfnRuntimeEndpoint(
                self,
                _logical_id(agent["runtime_name"]) + "Endpoint",
                agent_runtime_id=runtime.attr_agent_runtime_id,
                name=f"{agent['runtime_name']}_ep",
                description=f"Default endpoint for {agent['runtime_name']}",
            )
            _a2a_endpoints[agent["name"]] = _ep

        # IAM propagation: DefaultPolicy が AgentCore リソース作成前に確実に適用されるよう明示依存
        # CDK は Role の ARN 参照には DependsOn を自動追加するが、
        # DefaultPolicy (別リソース) には追加しない
        _gw_exec_policy = self.gateway_execution_role.node.try_find_child("DefaultPolicy")
        if _gw_exec_policy:
            self.agentcore_gateway.node.add_dependency(_gw_exec_policy)

        _mcp_policy = self.mcp_runtime_role.node.try_find_child("DefaultPolicy")
        if _mcp_policy:
            for _r in _mcp_runtimes.values():
                _r.node.add_dependency(_mcp_policy)

        _agent_gw_policy = self.agent_runtime_role.node.try_find_child("DefaultPolicy")
        if _agent_gw_policy:
            self.orchestrator_agent_runtime.node.add_dependency(_agent_gw_policy)
            self.chat_agent_runtime.node.add_dependency(_agent_gw_policy)

        for _agent in _A2A_AGENTS:
            _role = _per_agent_roles[_agent["name"]]
            _policy = _role.node.try_find_child("DefaultPolicy")
            if _policy and _agent["name"] in _a2a_runtimes:
                _a2a_runtimes[_agent["name"]].node.add_dependency(_policy)

        # =====================================================================
        # API キー クレデンシャルプロバイダー + Gateway ターゲット
        # =====================================================================
        self.api_key_cred = agentcore.CfnApiKeyCredentialProvider(
            self,
            "ServicesApiKeyCredential",
            name="agora-services-api-key",
            # CfnApiKeyCredentialProvider は Secrets Manager ARN 参照を受け付けないため平文展開
            api_key=self.services_api_key_secret.secret_value.unsafe_unwrap(),
            tags=[cdk.CfnTag(key="project", value="agora")],
        )

        spec = json.loads((_SPECS_DIR / "ticket-service.json").read_text())
        spec["servers"] = [{"url": "__SVC_URL__"}]
        spec_template = json.dumps(spec).replace('"__SVC_URL__"', '"${SvcUrl}"')
        inline_payload = cdk.Fn.sub(spec_template, {"SvcUrl": self.ticket_url.url})
        agentcore.CfnGatewayTarget(
            self,
            "TicketServiceGatewayTarget",
            name="agora-ticket-service",
            description="Agora Ticket Service CRUD",
            gateway_identifier=self.agentcore_gateway.attr_gateway_identifier,
            target_configuration=agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                mcp=agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                    open_api_schema=agentcore.CfnGatewayTarget.ApiSchemaConfigurationProperty(
                        inline_payload=inline_payload,
                    ),
                ),
            ),
            credential_provider_configurations=[
                agentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(
                    credential_provider_type="API_KEY",
                    credential_provider=agentcore.CfnGatewayTarget.CredentialProviderProperty(
                        api_key_credential_provider=agentcore.CfnGatewayTarget.ApiKeyCredentialProviderProperty(
                            provider_arn=self.api_key_cred.attr_credential_provider_arn,
                            credential_parameter_name="x-api-key",
                            credential_location="HEADER",
                        ),
                    ),
                )
            ],
        )

        # =====================================================================
        # REGISTRY CATALOG — Lambda-backed Custom Resource
        # =====================================================================
        import aws_cdk.custom_resources as cr

        registry_role = iam.Role(
            self,
            "RegistryCatalogRole",
            role_name="agora-registry-catalog-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[_basic_exec],
        )
        registry_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:ListAgentRuntimes",
                    "bedrock-agentcore:GetAgentRuntime",
                    "bedrock-agentcore:CreateRegistry",
                    "bedrock-agentcore:UpdateRegistry",
                    "bedrock-agentcore:ListRegistries",
                    "bedrock-agentcore:CreateRegistryRecord",
                    "bedrock-agentcore:ListRegistryRecords",
                    "bedrock-agentcore:GetRegistryRecord",
                    "bedrock-agentcore:DeleteRegistryRecord",
                    "bedrock-agentcore:DeleteRegistry",
                    "bedrock-agentcore:SubmitRegistryRecordForApproval",
                    "bedrock-agentcore:CreateWorkloadIdentity",
                    "bedrock-agentcore:ListWorkloadIdentities",
                ],
                resources=["*"],
            )
        )

        registry_fn = lambda_.DockerImageFunction(
            self,
            "RegistryCatalogFn",
            function_name="agora-registry-catalog",
            code=lambda_.DockerImageCode.from_image_asset(str(_LAMBDA_DIR)),
            timeout=cdk.Duration.minutes(10),
            role=registry_role,
        )

        for runtime in list(_mcp_runtimes.values()) + list(_a2a_runtimes.values()):
            registry_fn.node.add_dependency(runtime)
        registry_fn.node.add_dependency(self.orchestrator_agent_runtime)
        registry_fn.node.add_dependency(self.chat_agent_runtime)

        registry_provider = cr.Provider(
            self, "RegistryProvider", on_event_handler=registry_fn
        )
        _skill_names = [
            "incident-severity-classification",
            "api-error-diagnosis-runbook",
            "resolution-documentation-standard",
        ]
        cdk.CustomResource(
            self,
            "RegistryCatalog",
            service_token=registry_provider.service_token,
            properties={
                "CatalogVersion": _CATALOG_VERSION,
                "McpGatewayUrl": self.agentcore_gateway.attr_gateway_url,
                "SkillContents": {
                    name: (_SKILLS_DIR / name / "SKILL.md").read_text()
                    for name in _skill_names
                },
            },
        )

        # =====================================================================
        # BEDROCK MODEL INVOCATION LOGGING
        # アカウントレベル設定: 全モデル呼び出しのプロンプト/レスポンスを CloudWatch Logs に保存
        # デモ後に「各エージェントが Claude に送ったプロンプト全文」を事後確認するための証跡
        # CloudFormation ネイティブリソース未対応のため AwsCustomResource で構成
        # =====================================================================
        bedrock_invocation_log_group = logs.LogGroup(
            self,
            "BedrockInvocationLogs",
            log_group_name="/aws/bedrock/model-invocation-logs",
            retention=_LOG_RETENTION,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        bedrock_log_role = iam.Role(
            self,
            "BedrockLoggingRole",
            role_name="agora-bedrock-logging-role",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            ),
        )
        bedrock_log_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                ],
                resources=[
                    bedrock_invocation_log_group.log_group_arn,
                    bedrock_invocation_log_group.log_group_arn + ":*",
                ],
            )
        )

        _invocation_logging_config = {
            "loggingConfig": {
                "cloudWatchConfig": {
                    "logGroupName": bedrock_invocation_log_group.log_group_name,
                    "roleArn": bedrock_log_role.role_arn,
                },
                "textDataDeliveryEnabled": True,
                "imageDataDeliveryEnabled": False,
                "embeddingDataDeliveryEnabled": True,
            }
        }
        cr.AwsCustomResource(
            self,
            "BedrockModelInvocationLogging",
            install_latest_aws_sdk=False,
            on_create=cr.AwsSdkCall(
                service="Bedrock",
                action="putModelInvocationLoggingConfiguration",
                parameters=_invocation_logging_config,
                physical_resource_id=cr.PhysicalResourceId.of("BedrockModelInvocationLogging"),
            ),
            on_update=cr.AwsSdkCall(
                service="Bedrock",
                action="putModelInvocationLoggingConfiguration",
                parameters=_invocation_logging_config,
                physical_resource_id=cr.PhysicalResourceId.of("BedrockModelInvocationLogging"),
            ),
            # on_delete は省略: Bedrock は「無効化」専用 API を持たず、
            # cloudWatchConfig を省略した putModelInvocationLoggingConfiguration は
            # "At least one logging config must be specified" で拒否される。
            # スタック削除時はロールとロググループが同時に削除されるため
            # Bedrock は書き込み先を失い、実質的にログは停止する。
            policy=cr.AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    actions=[
                        "bedrock:PutModelInvocationLoggingConfiguration",
                        "bedrock:GetModelInvocationLoggingConfiguration",
                    ],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    actions=["iam:PassRole"],
                    resources=[bedrock_log_role.role_arn],
                    conditions={"StringEquals": {"iam:PassedToService": "bedrock.amazonaws.com"}},
                ),
            ]),
        )

        # =====================================================================
        # GATEWAY MCP TARGETS — CfnGatewayTarget (mcp.mcpServer.endpoint + SigV4)
        # AgentCore RuntimeでホストされたMCPサーバーをGatewayに登録する。
        # metadataConfiguration で Mcp-Session-Id ヘッダーを許可し、
        # SigV4 (GATEWAY_IAM_ROLE) で認証する。
        # =====================================================================
        _mcp_metadata = agentcore.CfnGatewayTarget.MetadataConfigurationProperty(
            allowed_request_headers=["Mcp-Session-Id"],
            allowed_response_headers=["Mcp-Session-Id"],
        )
        _iam_cred = [
            agentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(
                credential_provider_type="GATEWAY_IAM_ROLE",
                credential_provider=agentcore.CfnGatewayTarget.CredentialProviderProperty(
                    iam_credential_provider=agentcore.CfnGatewayTarget.IamCredentialProviderProperty(
                        service="bedrock-agentcore",
                        region=self.region,
                    )
                ),
            )
        ]
        # =====================================================================
        # CLOUDWATCH MCP — Lambda wrap (awslabs stdio → BedrockAgentCoreGatewayTargetHandler)
        # run-mcp-servers-with-aws-lambda で stdio MCP を Lambda 直接呼び出しに変換。
        # lambda_ Gateway Target として登録し、tool_schema を事前定義する。
        # =====================================================================
        _cloudwatch_mcp_role = iam.Role(
            self,
            "CloudwatchMcpLambdaRole",
            role_name="agora-cloudwatch-mcp-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[_basic_exec],
        )
        _cloudwatch_mcp_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudwatch:GetMetricData",
                    "cloudwatch:GetMetricStatistics",
                    "cloudwatch:ListMetrics",
                    "cloudwatch:DescribeAlarms",
                    "cloudwatch:DescribeAlarmsForMetric",
                    "cloudwatch:DescribeAlarmHistory",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                    "logs:FilterLogEvents",
                    "logs:GetLogEvents",
                    "logs:StartQuery",
                    "logs:GetQueryResults",
                    "logs:StopQuery",
                ],
                resources=["*"],
            )
        )

        self.cloudwatch_mcp_fn = lambda_.DockerImageFunction(
            self,
            "CloudwatchMcpFn",
            function_name="agora-cloudwatch-mcp",
            code=lambda_.DockerImageCode.from_image_asset(
                str(_LAMBDA_CLOUDWATCH_MCP_DIR),
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=512,
            timeout=cdk.Duration.seconds(60),
            role=_cloudwatch_mcp_role,
            log_group=logs.LogGroup(
                self,
                "CloudwatchMcpFnLogs",
                log_group_name="/aws/lambda/agora-cloudwatch-mcp",
                retention=_LOG_RETENTION,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
        )

        # Gateway execution role に Lambda 直接呼び出し権限を付与
        self.gateway_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[self.cloudwatch_mcp_fn.function_arn],
            )
        )
        # 明示的なリソースベースポリシーで Gateway → Lambda 呼び出しを許可
        self.cloudwatch_mcp_fn.add_permission(
            "AllowGatewayExecutionRole",
            principal=iam.ArnPrincipal(self.gateway_execution_role.role_arn),
            action="lambda:InvokeFunction",
        )

        for srv in _MCP_SERVERS:
            _runtime = _mcp_runtimes[srv["name"]]
            _ep = _mcp_endpoints[srv["name"]]
            _tgt = agentcore.CfnGatewayTarget(
                self,
                _logical_id(srv["runtime_name"]) + "GatewayTarget",
                name=f"agora-{srv['name']}",
                description=srv["description"],
                gateway_identifier=self.agentcore_gateway.attr_gateway_identifier,
                target_configuration=agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                    mcp=agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                        mcp_server=agentcore.CfnGatewayTarget.McpServerTargetConfigurationProperty(
                            endpoint=_runtime_invocation_url(_runtime, self.region, self.account),
                        )
                    )
                ),
                credential_provider_configurations=_iam_cred,
                metadata_configuration=_mcp_metadata,
            )
            _tgt.node.add_dependency(_ep)

        # ── tool_schema ヘルパー ──────────────────────────────────────────────
        def _schema(type_: str, *, desc: str | None = None, items=None, props=None, required=None):
            return agentcore.CfnGatewayTarget.SchemaDefinitionProperty(
                type=type_, description=desc, items=items,
                properties=props, required=required,
            )

        def _str(desc: str):
            return _schema("string", desc=desc)

        def _int(desc: str):
            return _schema("integer", desc=desc)

        def _arr_str(desc: str):
            return _schema("array", desc=desc, items=_schema("string"))

        def _tool(name: str, desc: str, props: dict, required: list[str] | None = None):
            return agentcore.CfnGatewayTarget.ToolDefinitionProperty(
                name=name,
                description=desc,
                input_schema=_schema("object", props=props, required=required),
            )

        _cw_tools = [
            _tool(
                "get_active_alarms",
                "Gets all CloudWatch Alarms currently in ALARM state across the account.",
                {
                    "max_items": _int("Maximum number of alarms to return (default: 50)"),
                    "region": _str("AWS region (default: us-east-1)"),
                },
            ),
            _tool(
                "get_alarm_history",
                "Gets state-change history for a CloudWatch alarm and suggests"
                " investigation time ranges.",
                {
                    "alarm_name": _str("Name of the alarm to retrieve history for"),
                    "start_time": _str("ISO 8601 start time (default: 24 hours ago)"),
                    "end_time": _str("ISO 8601 end time (default: now)"),
                    "max_items": _int("Maximum number of history items (default: 50)"),
                    "region": _str("AWS region (default: us-east-1)"),
                },
                required=["alarm_name"],
            ),
            _tool(
                "get_metric_data",
                "Retrieves CloudWatch metric data for a specific metric within a time range.",
                {
                    "namespace": _str("Metric namespace (e.g. AWS/Lambda, AWS/EC2)"),
                    "metric_name": _str("Metric name (e.g. Errors, Duration, Invocations)"),
                    "start_time": _str("ISO 8601 start time (default: 3 hours before end_time)"),
                    "end_time": _str("ISO 8601 end time (default: now)"),
                    "statistic": _str("Statistic: AVG, SUM, MAX, MIN, COUNT (default: AVG)"),
                    "dimensions": _schema(
                        "array",
                        desc="List of dimensions {name, value} to identify the metric",
                        items=_schema("object"),
                    ),
                    "region": _str("AWS region (default: us-east-1)"),
                },
            ),
            _tool(
                "describe_log_groups",
                "Lists CloudWatch log groups, optionally filtered by name prefix.",
                {
                    "log_group_name_prefix": _str("Filter log groups by this name prefix"),
                    "max_items": _int("Maximum number of log groups to return"),
                    "region": _str("AWS region (default: us-east-1)"),
                },
            ),
            _tool(
                "execute_log_insights_query",
                "Executes a CloudWatch Logs Insights query and returns results."
                " Always include a | limit clause.",
                {
                    "log_group_names": _arr_str("List of log group names to query (max 50)"),
                    "log_group_identifiers": _arr_str("List of log group ARNs to query (max 50)"),
                    "start_time": _str("ISO 8601 start time"),
                    "end_time": _str("ISO 8601 end time"),
                    "query_string": _str("CloudWatch Logs Insights query string"),
                    "limit": _int("Maximum number of log events to return"),
                    "region": _str("AWS region (default: us-east-1)"),
                },
                required=["start_time", "end_time", "query_string"],
            ),
            _tool(
                "get_logs_insight_query_results",
                "Retrieves results of a previously started CloudWatch Logs Insights query.",
                {
                    "query_id": _str("Query ID returned by execute_log_insights_query"),
                    "region": _str("AWS region (default: us-east-1)"),
                },
                required=["query_id"],
            ),
        ]

        # CloudWatch MCP — lambda_ target (BedrockAgentCoreGatewayTargetHandler)
        agentcore.CfnGatewayTarget(
            self,
            "CloudwatchMcpGatewayTarget",
            name="agora-cloudwatch",
            description="CloudWatch MCP — metrics, alarms, Logs Insights (awslabs/mcp via Lambda)",
            gateway_identifier=self.agentcore_gateway.attr_gateway_identifier,
            target_configuration=agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                mcp=agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                    lambda_=agentcore.CfnGatewayTarget.McpLambdaTargetConfigurationProperty(
                        lambda_arn=self.cloudwatch_mcp_fn.function_arn,
                        tool_schema=agentcore.CfnGatewayTarget.ToolSchemaProperty(
                            inline_payload=_cw_tools,
                        ),
                    )
                )
            ),
            credential_provider_configurations=[
                agentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(
                    credential_provider_type="GATEWAY_IAM_ROLE",
                    # Lambda target は IamCredentialProvider 非対応。
                    # credential_provider を省略することで GATEWAY_IAM_ROLE のみ指定。
                )
            ],
        )

        # AWS Knowledge MCP Server — 認証不要のマネージドエンドポイントを直接登録
        agentcore.CfnGatewayTarget(
            self,
            "AwsKnowledgeGatewayTarget",
            name="agora-aws-knowledge",
            description=(
                "AWS Knowledge MCP — managed AWS docs, blog posts,"
                " and Well-Architected guidance (awslabs)"
            ),
            gateway_identifier=self.agentcore_gateway.attr_gateway_identifier,
            target_configuration=agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                mcp=agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                    mcp_server=agentcore.CfnGatewayTarget.McpServerTargetConfigurationProperty(
                        endpoint="https://knowledge-mcp.global.api.aws",
                    )
                )
            ),
            metadata_configuration=_mcp_metadata,
        )

        # =====================================================================
        # SSM — チケットサービス URL (FaultInjectionStack が参照)
        # =====================================================================
        ssm.StringParameter(
            self,
            "TicketServiceUrlParam",
            parameter_name="/agora/ticket-service-url",
            string_value=self.ticket_url.url,
            description="Ticket Service Lambda Function URL (for Bridge Lambda)",
        )
        ssm.StringParameter(
            self,
            "ServicesApiKeyNameParam",
            parameter_name="/agora/services-api-key-name",
            string_value=self.services_api_key_secret.secret_name,
            description="Services API key secret name (for FaultInjectionStack BridgeFn)",
        )

        # =====================================================================
        # OUTPUTS
        # =====================================================================
        cdk.CfnOutput(self, "TicketFunctionUrl", value=self.ticket_url.url)
        cdk.CfnOutput(self, "UiBucketName", value=self.ui_bucket.bucket_name)
        cdk.CfnOutput(self, "UiUrl", value=f"https://{self.ui_distribution.domain_name}")
        cdk.CfnOutput(self, "GatewayUrl", value=self.agentcore_gateway.attr_gateway_url)
        cdk.CfnOutput(
            self,
            "OrchestratorRuntimeArn",
            value=self.orchestrator_agent_runtime.attr_agent_runtime_arn,
        )
        cdk.CfnOutput(
            self,
            "ChatRuntimeArn",
            value=self.chat_agent_runtime.attr_agent_runtime_arn,
        )
        cdk.CfnOutput(self, "GuardrailId", value=self.guardrail.attr_guardrail_id)
        cdk.CfnOutput(
            self, "OrchestratorPromptArn", value=self.orchestrator_prompt_version.attr_arn
        )
        cdk.CfnOutput(self, "ChatPromptArn", value=self.chat_prompt_version.attr_arn)
        cdk.CfnOutput(self, "TriagePromptArn", value=self.triage_prompt_version.attr_arn)
        cdk.CfnOutput(self, "DiagnosisPromptArn", value=self.diagnosis_prompt_version.attr_arn)
        cdk.CfnOutput(
            self, "DiagnosisJudgmentPromptArn", value=self.judgment_prompt_version.attr_arn
        )
        cdk.CfnOutput(self, "ResolutionPromptArn", value=self.resolution_prompt_version.attr_arn)
        cdk.CfnOutput(self, "DispatcherPromptArn", value=self.dispatcher_prompt_version.attr_arn)

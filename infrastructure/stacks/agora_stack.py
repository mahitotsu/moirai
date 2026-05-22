from __future__ import annotations

import json
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
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
from aws_cdk.aws_s3_deployment import BucketDeployment, Source
from constructs import Construct
from pydantic_settings import BaseSettings

_ROOT = Path(__file__).parent.parent.parent
_UI_DIR = str(_ROOT / "ui")
_AGENTS_DIR = _ROOT / "agents"
_MCP_DIR = _ROOT / "mcp-servers"
_SERVICES_DIR = _ROOT / "services"
_LAMBDA_DIR = Path(__file__).parent.parent / "lambda"
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
_CATALOG_VERSION = "3"
_API_KEY_LENGTH = 32
_MEMORY_EXPIRY_DAYS = 90

# ── DynamoDB インデックス名 ────────────────────────────────────────────────
_TICKETS_STATUS_INDEX = "status-created_at-index"
_TICKETS_CATEGORY_INDEX = "category-created_at-index"
_ASSETS_TYPE_INDEX = "type-name-index"
_ASSETS_ENV_INDEX = "environment-type-index"


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
        "name": "wikipedia",
        "runtime_name": "agora_wikipedia",
        "description": "Wikipedia MCP — searches Wikipedia for technology concepts and articles",
        "capability": "community-knowledge",
        "env": {},
    },
    {
        "name": "aws-docs",
        "runtime_name": "agora_aws_docs",
        "description": "AWS Docs MCP — searches AWS documentation (awslabs/mcp)",
        "capability": "community-knowledge",
        "env": {"AWS_DOCUMENTATION_PARTITION": "aws", "FASTMCP_LOG_LEVEL": "WARNING"},
    },
    {
        "name": "cloudwatch",
        "runtime_name": "agora_cloudwatch",
        "description": "CloudWatch MCP — metrics, alarms, Logs Insights (awslabs/mcp)",
        "capability": "aws-observability",
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

        self.assets_table = dynamodb.Table(
            self,
            "AssetsTable",
            table_name="agora-assets",
            partition_key=dynamodb.Attribute(
                name="asset_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        self.assets_table.add_global_secondary_index(
            index_name=_ASSETS_TYPE_INDEX,
            partition_key=dynamodb.Attribute(
                name="type", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="name", type=dynamodb.AttributeType.STRING
            ),
        )
        self.assets_table.add_global_secondary_index(
            index_name=_ASSETS_ENV_INDEX,
            partition_key=dynamodb.Attribute(
                name="environment", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="type", type=dynamodb.AttributeType.STRING
            ),
        )

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
        ]

        self.ticket_role = iam.Role(
            self,
            "TicketServiceRole",
            role_name="agora-ticket-service-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[_basic_exec],
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

        self.asset_role = iam.Role(
            self,
            "AssetServiceRole",
            role_name="agora-asset-service-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[_basic_exec],
        )
        self.asset_role.add_to_policy(
            iam.PolicyStatement(
                actions=_dynamo_rw,
                resources=[
                    self.assets_table.table_arn,
                    self.assets_table.table_arn + "/index/*",
                ],
            )
        )
        self.asset_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
                resources=[self.services_api_key_secret.secret_arn],
            )
        )

        self.chat_proxy_role = iam.Role(
            self,
            "ChatProxyRole",
            role_name="agora-chat-proxy-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[_basic_exec],
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
                    "bedrock-agentcore:GetPolicyEngine",
                    "bedrock-agentcore:CheckAuthorizePermissions",
                    "bedrock-agentcore:AuthorizeAction",
                    "bedrock-agentcore:PartiallyAuthorizeActions",
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
                [
                    "bedrock-agentcore:RetrieveMemoryRecords",
                    "bedrock-agentcore:BatchCreateMemoryRecords",
                    "bedrock-agentcore:GetMemory",
                    "bedrock-agentcore:ListMemoryRecords",
                ],
                ["*"],
            ),
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
            ("triage", "Triage"), ("diagnosis", "Diagnosis"), ("resolution", "Resolution")
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

        # Diagnosis: CloudWatch + DynamoDB 直接読み取り
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
        _per_agent_roles["diagnosis"].add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:Query", "dynamodb:GetItem", "dynamodb:Scan"],
                resources=[
                    self.tickets_table.table_arn,
                    self.tickets_table.table_arn + "/index/*",
                ],
            )
        )

        # AgentCore Memory 実行ロール
        self.memory_execution_role = iam.Role(
            self,
            "MemoryExecutionRole",
            role_name="agora-memory-execution-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
        )
        self.memory_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                    "arn:aws:bedrock:*::foundation-model/*",
                    "arn:aws:bedrock:*::inference-profile/*",
                ],
            )
        )
        self.memory_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=["*"],
            )
        )

        # =====================================================================
        # BEDROCK GUARDRAIL — Gateway Agent 用
        # =====================================================================
        self.guardrail = bedrock.CfnGuardrail(
            self,
            "GatewayGuardrail",
            name="agora-gateway-guardrail",
            description="Gateway Agent 用 Guardrail — FIS 操作と実システム変更をブロック",
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
                            "Start the FIS experiment",
                            "Stop the fault injection",
                            "障害注入を止めて",
                            "Run the chaos experiment",
                        ],
                        type="DENY",
                    ),
                ]
            ),
            tags=[cdk.CfnTag(key="project", value="agora")],
        )

        # =====================================================================
        # AGENTCORE MEMORY
        # =====================================================================
        self.memory = agentcore.CfnMemory(
            self,
            "AgoraMemory",
            name="agora_memory",
            description="Conversation context and user preference memory for Agora IT Service Desk",
            event_expiry_duration=_MEMORY_EXPIRY_DAYS,
            memory_execution_role_arn=self.memory_execution_role.role_arn,
            memory_strategies=[
                agentcore.CfnMemory.MemoryStrategyProperty(
                    semantic_memory_strategy=agentcore.CfnMemory.SemanticMemoryStrategyProperty(
                        name="agora_semantic",
                        description="IT incident conversation history and context per user",
                    ),
                ),
                agentcore.CfnMemory.MemoryStrategyProperty(
                    user_preference_memory_strategy=agentcore.CfnMemory.UserPreferenceMemoryStrategyProperty(
                        name="agora_user_preferences",
                        description="User-specific technical background and preferences",
                    ),
                ),
            ],
            tags={"project": "agora"},
        )

        # =====================================================================
        # ECR IMAGE ASSETS — CDK が自動ビルド & プッシュ
        # =====================================================================
        agent_images: dict[str, ecr_assets.DockerImageAsset] = {}

        for _name in ["stackoverflow", "github-issues", "wikipedia", "aws-docs", "cloudwatch"]:
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

        agent_images["gateway"] = ecr_assets.DockerImageAsset(
            self,
            "GatewayAgentImage",
            directory=str(_AGENTS_DIR),
            file="gateway/Dockerfile",
            platform=ecr_assets.Platform.LINUX_ARM64,
        )

        # ECR pull 権限は mcp_runtime_role / agent_runtime_role の add_to_policy("*") で確保済み

        # =====================================================================
        # AGENTCORE GATEWAY AGENT RUNTIME — 先に作成して ARN を Lambda に注入
        # =====================================================================
        self.gateway_agent_runtime = agentcore.CfnRuntime(
            self,
            "AgoraGatewayRuntime",
            agent_runtime_name="agora_gateway",
            description="Gateway Agent — user-facing orchestrator (AG-UI/SSE)",
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=agent_images["gateway"].image_uri,
                ),
            ),
            role_arn=self.agent_runtime_role.role_arn,
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC",
            ),
            protocol_configuration="HTTP",
            environment_variables={
                "MODEL_ID": _MODEL_SONNET,
                "MEMORY_ID": self.memory.attr_memory_id,
                "GUARDRAIL_ID": self.guardrail.attr_guardrail_id,
                "GUARDRAIL_VERSION": _GUARDRAIL_VERSION,
            },
            tags={"capability": "gateway", "project": "agora"},
        )
        agentcore.CfnRuntimeEndpoint(
            self,
            "AgoraGatewayEndpoint",
            agent_runtime_id=self.gateway_agent_runtime.attr_agent_runtime_id,
            name="agora_gateway_ep",
            description="Default endpoint for agora_gateway",
        )

        # =====================================================================
        # LAMBDA FUNCTIONS
        # =====================================================================
        _common_env = {
            "AWS_LWA_PORT": "8080",
            "AWS_LWA_READINESS_CHECK_PATH": "/health",
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
            },
        )

        self.asset_fn = lambda_.DockerImageFunction(
            self,
            "AssetServiceFn",
            function_name="agora-asset-service",
            code=lambda_.DockerImageCode.from_image_asset(
                str(_SERVICES_DIR / "asset-service"),
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=_MEMORY_SERVICE_MB,
            timeout=_TIMEOUT_SERVICE,
            role=self.asset_role,
            log_group=logs.LogGroup(
                self,
                "AssetServiceFnLogs",
                log_group_name="/aws/lambda/agora-asset-service",
                retention=_LOG_RETENTION,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment={
                **_common_env,
                "TABLE_NAME": self.assets_table.table_name,
                "API_KEY_SECRET_NAME": self.services_api_key_secret.secret_name,
            },
        )

        self.ticket_url = self.ticket_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )
        self.asset_url = self.asset_fn.add_function_url(
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
                "AGENT_RUNTIME_ARN": self.gateway_agent_runtime.attr_agent_runtime_arn,
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
            ],
        )
        _dispatcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=["*"],
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

        self.ticket_dispatcher_fn = lambda_.Function(
            self,
            "TicketDispatcherFn",
            function_name="agora-ticket-dispatcher",
            code=lambda_.Code.from_asset(
                str(_SERVICES_DIR / "ticket-dispatcher"),
                bundling=cdk.BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    platform="linux/arm64",
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output"
                        " && cp lambda_function.py /asset-output/",
                    ],
                ),
            ),
            handler="lambda_function.handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            memory_size=_MEMORY_WORKER_MB,
            timeout=_TIMEOUT_LONG,
            role=_dispatcher_role,
            log_group=logs.LogGroup(
                self,
                "TicketDispatcherFnLogs",
                log_group_name="/aws/lambda/agora-ticket-dispatcher",
                retention=_LOG_RETENTION,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment={
                # AGENT_RUNTIME_ARN はスタック内で直接解決 (循環参照なし)
                "AGENT_RUNTIME_ARN": self.gateway_agent_runtime.attr_agent_runtime_arn,
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
        chat_origin = origins.FunctionUrlOrigin.with_origin_access_control(self.chat_proxy_url)
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
        for srv in _MCP_SERVERS:
            _extra = _github_env() if srv["name"] == "github-issues" else {}
            env_vars = {k: v for k, v in {**srv["env"], **_extra}.items() if v}
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
            agentcore.CfnRuntimeEndpoint(
                self,
                _logical_id(srv["runtime_name"]) + "Endpoint",
                agent_runtime_id=runtime.attr_agent_runtime_id,
                name=f"{srv['runtime_name']}_ep",
                description=f"Default endpoint for {srv['runtime_name']}",
            )

        # =====================================================================
        # AGENTCORE GATEWAY (HTTP/MCP) + Cedar Policy Engine
        # 先に作成することで A2A エージェントが GATEWAY_URL を直接参照できる
        # =====================================================================
        self.policy_engine = agentcore.CfnPolicyEngine(
            self,
            "AgoraPolicyEngine",
            name="agora_policy_engine",
            description="Cedar access control for Agora Gateway — per-agent tool restrictions",
            tags=[cdk.CfnTag(key="project", value="agora")],
        )

        self.agentcore_gateway = agentcore.CfnGateway(
            self,
            "AgoraGateway",
            name="agora-gateway",
            description="AgentCore Gateway that exposes Agora internal services as MCP tools",
            role_arn=self.gateway_execution_role.role_arn,
            authorizer_type="NONE",
            protocol_type="MCP",
            policy_engine_configuration=agentcore.CfnGateway.GatewayPolicyEngineConfigurationProperty(
                arn=self.policy_engine.attr_policy_engine_arn,
                mode="LOG_ONLY",
            ),
            tags={"project": "agora"},
        )

        # =====================================================================
        # A2A エージェント — GATEWAY_URL を直接参照 (同スタック内なので循環なし)
        # =====================================================================
        _a2a_runtimes: dict[str, agentcore.CfnRuntime] = {}
        for agent in _A2A_AGENTS:
            env_vars = dict(agent["env"])
            if agent["name"] in ("diagnosis", "resolution"):
                env_vars["GATEWAY_URL"] = self.agentcore_gateway.attr_gateway_url

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
                protocol_configuration="A2A",
                environment_variables=env_vars,
                tags={
                    "capability": agent["capability"],
                    "agent-type": agent["name"],
                    "project": "agora",
                },
            )
            _a2a_runtimes[agent["name"]] = runtime
            agentcore.CfnRuntimeEndpoint(
                self,
                _logical_id(agent["runtime_name"]) + "Endpoint",
                agent_runtime_id=runtime.attr_agent_runtime_id,
                name=f"{agent['runtime_name']}_ep",
                description=f"Default endpoint for {agent['runtime_name']}",
            )

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
            self.gateway_agent_runtime.node.add_dependency(_agent_gw_policy)

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

        _gw_targets: list[agentcore.CfnGatewayTarget] = []
        for svc_name, url_token in (
            ("ticket-service", self.ticket_url.url),
            ("asset-service", self.asset_url.url),
        ):
            spec = json.loads((_SPECS_DIR / f"{svc_name}.json").read_text())
            spec["servers"] = [{"url": "__SVC_URL__"}]
            spec_template = json.dumps(spec).replace('"__SVC_URL__"', '"${SvcUrl}"')
            inline_payload = cdk.Fn.sub(spec_template, {"SvcUrl": url_token})

            cid = svc_name.replace("-", " ").title().replace(" ", "") + "GatewayTarget"
            _gw_target = agentcore.CfnGatewayTarget(
                self,
                cid,
                name=f"agora-{svc_name}",
                description=f"Agora {svc_name.replace('-', ' ').title()} CRUD",
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
            _gw_targets.append(_gw_target)

        # =====================================================================
        # CEDAR POLICIES
        # =====================================================================
        _gw_arn_tpl = (
            "arn:aws:bedrock-agentcore:${AWS::Region}:${AWS::AccountId}"
            ":gateway/${GatewayId}"
        )
        _gw_sub = {"GatewayId": self.agentcore_gateway.attr_gateway_identifier}

        _READ_ACTIONS = "\n    ".join([
            'AgentCore::Action::"agora-ticket-service___list_tickets_tickets_get",',
            'AgentCore::Action::"agora-ticket-service___get_ticket_tickets__ticket_id__get",',
            'AgentCore::Action::"agora-asset-service___list_assets_assets_get",',
            'AgentCore::Action::"agora-asset-service___get_asset_assets__asset_id__get"',
        ])
        _WRITE_ACTIONS = "\n    ".join([
            'AgentCore::Action::"agora-ticket-service___create_ticket_tickets_post",',
            'AgentCore::Action::"agora-ticket-service___update_ticket_tickets__ticket_id__patch"',
        ])

        for _policy_name, _role_name, _actions in [
            ("agora_triage_policy", "agora-triage-runtime-role", _READ_ACTIONS),
            ("agora_diagnosis_policy", "agora-diagnosis-runtime-role", _READ_ACTIONS),
            ("agora_resolution_policy", "agora-resolution-runtime-role", _WRITE_ACTIONS),
        ]:
            _cedar_tpl = (
                "permit(\n"
                "  principal is AgentCore::IamEntity,\n"
                f"  action in [\n    {_actions}\n  ],\n"
                f'  resource == AgentCore::Gateway::"{_gw_arn_tpl}"\n'
                ") when {\n"
                '  principal.id == "arn:aws:iam::${AWS::AccountId}'
                f':role/{_role_name}"\n'
                "};"
            )
            _lid = "".join(p.title() for p in _policy_name.split("_"))
            _cfn_policy = agentcore.CfnPolicy(
                self,
                _lid,
                name=_policy_name,
                policy_engine_id=self.policy_engine.attr_policy_engine_id,
                definition=agentcore.CfnPolicy.PolicyDefinitionProperty(
                    cedar=agentcore.CfnPolicy.CedarPolicyProperty(
                        statement=cdk.Fn.sub(_cedar_tpl, _gw_sub),
                    ),
                ),
            )
            # Cedar ポリシーの action 名は GatewayTarget 登録後に有効化されるため明示依存
            for _gw_target in _gw_targets:
                _cfn_policy.node.add_dependency(_gw_target)

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
                    "bedrock-agentcore:ListRegistries",
                    "bedrock-agentcore:CreateRegistryRecord",
                    "bedrock-agentcore:ListRegistryRecords",
                    "bedrock-agentcore:GetRegistryRecord",
                    "bedrock-agentcore:DeleteRegistryRecord",
                    "bedrock-agentcore:DeleteRegistry",
                    "bedrock-agentcore:CreateWorkloadIdentity",
                    "bedrock-agentcore:ListWorkloadIdentities",
                ],
                resources=["*"],
            )
        )

        registry_fn = lambda_.Function(
            self,
            "RegistryCatalogFn",
            function_name="agora-registry-catalog",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="registry_catalog_handler.handler",
            code=lambda_.Code.from_asset(
                str(_LAMBDA_DIR),
                bundling=cdk.BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output --quiet"
                        " && cp -au . /asset-output",
                    ],
                ),
            ),
            timeout=cdk.Duration.minutes(10),
            role=registry_role,
        )

        for runtime in list(_mcp_runtimes.values()) + list(_a2a_runtimes.values()):
            registry_fn.node.add_dependency(runtime)
        registry_fn.node.add_dependency(self.gateway_agent_runtime)

        registry_provider = cr.Provider(
            self, "RegistryProvider", on_event_handler=registry_fn
        )
        cdk.CustomResource(
            self,
            "RegistryCatalog",
            service_token=registry_provider.service_token,
            properties={"CatalogVersion": _CATALOG_VERSION},
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
        cdk.CfnOutput(self, "AssetFunctionUrl", value=self.asset_url.url)
        cdk.CfnOutput(self, "UiBucketName", value=self.ui_bucket.bucket_name)
        cdk.CfnOutput(self, "UiUrl", value=f"https://{self.ui_distribution.domain_name}")
        cdk.CfnOutput(self, "GatewayUrl", value=self.agentcore_gateway.attr_gateway_url)
        cdk.CfnOutput(
            self,
            "GatewayRuntimeArn",
            value=self.gateway_agent_runtime.attr_agent_runtime_arn,
        )
        cdk.CfnOutput(self, "MemoryId", value=self.memory.attr_memory_id)
        cdk.CfnOutput(self, "PolicyEngineArn", value=self.policy_engine.attr_policy_engine_arn)
        cdk.CfnOutput(self, "GuardrailId", value=self.guardrail.attr_guardrail_id)

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
import aws_cdk.aws_bedrock as bedrock
import aws_cdk.aws_cloudfront as cloudfront
import aws_cdk.aws_cloudfront_origins as origins
import aws_cdk.aws_ecr_assets as ecr_assets
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_lambda_event_sources as event_sources
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_ssm as ssm
from aws_cdk.aws_s3_deployment import BucketDeployment, Source
from constructs import Construct
from pydantic_settings import BaseSettings

from stacks.data_stack import DataStack

_UI_DIR = str(Path(__file__).parent.parent.parent / "ui")


class _Settings(BaseSettings):
    # ARN of the Gateway Agent AgentCore Runtime — injected after first deploy.
    # Get from CDK outputs: AgoraAgentCoreStack.AgoraGatewayRuntimeArn
    agent_runtime_arn: str = ""


_AGENT_RUNTIME_ARN = _Settings().agent_runtime_arn


class ComputeStack(cdk.Stack):
    def __init__(
        self, scope: Construct, construct_id: str, data: DataStack, **kwargs: object
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # -------------------------------------------------------------------------
        # AgentCore Runtime images — CDK builds and pushes all images automatically.
        # DockerImageAsset handles build + push to CDK-managed ECR bootstrap repo.
        # agent_core_stack.py consumes image_uri for CfnRuntime container_uri.
        # -------------------------------------------------------------------------
        _AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"
        _MCP_DIR = Path(__file__).parent.parent.parent / "mcp-servers"

        self.agent_images: dict[str, ecr_assets.DockerImageAsset] = {}

        for _name in ["stackoverflow", "github-issues", "wikipedia", "aws-docs"]:
            _cid = _name.replace("-", " ").title().replace(" ", "") + "McpImage"
            self.agent_images[_name] = ecr_assets.DockerImageAsset(
                self,
                _cid,
                directory=str(_MCP_DIR / _name),
                platform=ecr_assets.Platform.LINUX_ARM64,
            )

        for _name in ["triage", "diagnosis", "resolution"]:
            _cid = _name.title() + "AgentImage"
            self.agent_images[_name] = ecr_assets.DockerImageAsset(
                self,
                _cid,
                directory=str(_AGENTS_DIR),
                file=f"{_name}/Dockerfile",
                platform=ecr_assets.Platform.LINUX_ARM64,
            )

        self.agent_images["gateway"] = ecr_assets.DockerImageAsset(
            self,
            "GatewayAgentImage",
            directory=str(_AGENTS_DIR),
            file="gateway/Dockerfile",
            platform=ecr_assets.Platform.LINUX_ARM64,
        )

        # -------------------------------------------------------------------------
        # IAM execution role for AgentCore Runtime (MCP servers)
        # -------------------------------------------------------------------------
        self.mcp_runtime_role = iam.Role(
            self,
            "McpRuntimeRole",
            role_name="agora-mcp-runtime-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
        )
        self.mcp_runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:GetAuthorizationToken",
                ],
                resources=["*"],
            )
        )
        self.mcp_runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=["*"],
            )
        )
        cdk.CfnOutput(self, "McpRuntimeRoleArn", value=self.mcp_runtime_role.role_arn)

        # -------------------------------------------------------------------------
        # Shared API key for Gateway → Service authentication
        # Stored in Secrets Manager; injected into Lambda as API_KEY env var.
        # AgentCore Gateway references this secret as an api-key credential.
        # -------------------------------------------------------------------------
        self.services_api_key_secret = secretsmanager.Secret(
            self,
            "ServicesApiKeySecret",
            secret_name="agora/services-api-key",
            description="API key: AgentCore Gateway → internal FastAPI services",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True,
                password_length=32,
            ),
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # -------------------------------------------------------------------------
        # IAM execution role for AgentCore Gateway
        # -------------------------------------------------------------------------
        self.gateway_role = iam.Role(
            self,
            "GatewayExecutionRole",
            role_name="agora-gateway-execution-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
        )
        # Gateway needs to read its own credential providers (token vault)
        self.gateway_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:GetApiKeyCredentialProvider"],
                resources=["*"],
            )
        )

        # -------------------------------------------------------------------------
        # IAM execution role shared by Lambda functions
        # -------------------------------------------------------------------------
        self.lambda_role = iam.Role(
            self,
            "LambdaExecutionRole",
            role_name="agora-lambda-execution-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        # Allow DynamoDB access (both tables)
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                ],
                resources=[
                    f"arn:aws:dynamodb:{self.region}:{self.account}:table/agora-tickets",
                    f"arn:aws:dynamodb:{self.region}:{self.account}:table/agora-tickets/index/*",
                    f"arn:aws:dynamodb:{self.region}:{self.account}:table/agora-assets",
                    f"arn:aws:dynamodb:{self.region}:{self.account}:table/agora-assets/index/*",
                ],
            )
        )

        # Allow chat-proxy Lambda to invoke the Gateway Agent AgentCore Runtime
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=["*"],
            )
        )

        # -------------------------------------------------------------------------
        # Lambda functions — CDK builds and pushes all images automatically.
        # `cdk deploy` handles build + push + Lambda create/update in one step.
        # -------------------------------------------------------------------------
        common_env = {
            "AWS_LWA_PORT": "8080",
            "AWS_LWA_READINESS_CHECK_PATH": "/health",
        }

        _SERVICES_DIR = Path(__file__).parent.parent.parent / "services"

        self.ticket_fn = lambda_.DockerImageFunction(
            self,
            "TicketServiceFn",
            function_name="agora-ticket-service",
            code=lambda_.DockerImageCode.from_image_asset(
                str(_SERVICES_DIR / "ticket-service"),
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            role=self.lambda_role,
            environment={
                **common_env,
                "TABLE_NAME": "agora-tickets",
                "API_KEY_SECRET_NAME": "agora/services-api-key",
            },
        )
        # Inject API key from Secrets Manager
        secretsmanager.Secret.from_secret_name_v2(
            self, "ApiKeyRefTicket", "agora/services-api-key"
        ).grant_read(self.lambda_role)

        self.asset_fn = lambda_.DockerImageFunction(
            self,
            "AssetServiceFn",
            function_name="agora-asset-service",
            code=lambda_.DockerImageCode.from_image_asset(
                str(_SERVICES_DIR / "asset-service"),
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            role=self.lambda_role,
            environment={
                **common_env,
                "TABLE_NAME": "agora-assets",
                "API_KEY_SECRET_NAME": "agora/services-api-key",
            },
        )

        # Function URLs — public HTTPS endpoints (IAM auth can be added later)
        self.ticket_url = self.ticket_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )
        self.asset_url = self.asset_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )

        # -------------------------------------------------------------------------
        # Chat Proxy Lambda — CDK builds and pushes the image automatically.
        # No manual `make deploy img=chat-proxy` needed; image is an ECR asset.
        # -------------------------------------------------------------------------
        _CHAT_PROXY_DIR = str(
            Path(__file__).parent.parent.parent / "services" / "chat-proxy"
        )

        self.chat_proxy_fn = lambda_.DockerImageFunction(
            self,
            "ChatProxyFn",
            function_name="agora-chat-proxy",
            code=lambda_.DockerImageCode.from_image_asset(
                _CHAT_PROXY_DIR,
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=512,
            # Gateway Agent can take up to ~60 s for Triage→Diagnosis→Resolution
            timeout=cdk.Duration.seconds(120),
            role=self.lambda_role,
            environment={
                **common_env,
                "AGENT_RUNTIME_ARN": _AGENT_RUNTIME_ARN,
            },
        )

        # AWS_IAM auth — only CloudFront (OAC) is allowed to invoke this URL
        self.chat_proxy_url = self.chat_proxy_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.AWS_IAM,
        )

        # -------------------------------------------------------------------------
        # S3 bucket — React SPA static files (no public access)
        # -------------------------------------------------------------------------
        self.ui_bucket = s3.Bucket(
            self,
            "UiBucket",
            bucket_name=f"agora-ui-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # -------------------------------------------------------------------------
        # CloudFront Function — strip /api prefix before forwarding to Lambda
        # /api/tickets?status=open  →  /tickets?status=open
        # -------------------------------------------------------------------------
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

        # -------------------------------------------------------------------------
        # CloudFront origins
        # -------------------------------------------------------------------------

        # Origin 1: S3 (OAC — blocks all direct S3 access)
        ui_origin = origins.S3BucketOrigin.with_origin_access_control(self.ui_bucket)

        # Origin 2: chat-proxy Lambda Function URL (OAC with AWS_IAM)
        # CDK auto-grants lambda:InvokeFunctionUrl to CloudFront service principal
        chat_origin = origins.FunctionUrlOrigin.with_origin_access_control(
            self.chat_proxy_url,
        )

        # Origin 3: ticket-service Lambda Function URL (public auth=NONE, key via custom header)
        # Extracts domain from "https://xxxx.lambda-url…/" → "xxxx.lambda-url…"
        ticket_domain = cdk.Fn.select(2, cdk.Fn.split("/", self.ticket_url.url))
        ticket_origin = origins.HttpOrigin(
            ticket_domain,
            custom_headers={
                # Inject API key so the browser never needs to know it
                "x-api-key": self.services_api_key_secret.secret_value.unsafe_unwrap(),
            },
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
        )

        # -------------------------------------------------------------------------
        # CloudFront Distribution
        # Behaviors (evaluated in order from most to least specific):
        #   /api/chat        → chat-proxy Lambda  (OAC / AWS_IAM)
        #   /api/tickets*    → ticket-service Lambda (custom header, path rewrite)
        #   /*               → S3  (OAC, SPA fallback on 403/404)
        # -------------------------------------------------------------------------
        self.ui_distribution = cloudfront.Distribution(
            self,
            "UiDistribution",
            # Default: S3 → React SPA
            default_behavior=cloudfront.BehaviorOptions(
                origin=ui_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
            ),
            additional_behaviors={
                # Chat API — POST, no cache, OAC-signed to Lambda
                "/api/chat": cloudfront.BehaviorOptions(
                    origin=chat_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
                # Ticket API — GET/POST/PATCH, no cache, path rewrite /api → ""
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
            # SPA fallback — serve index.html for React Router routes
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

        # -------------------------------------------------------------------------
        # BucketDeployment — build React SPA and upload to S3
        # CDK builds the app in a Docker container; no pre-build step needed.
        # Also creates a CloudFront invalidation after each deploy.
        # -------------------------------------------------------------------------
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

        # -------------------------------------------------------------------------
        # Bedrock Guardrail — Gateway Agent (Chat UI 向け)
        # Denied topics: FIS 実験の操作、Lambda 等の実システムへの変更実行
        # -------------------------------------------------------------------------
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
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="SystemChangeExecution",
                        definition=(
                            "Lambda 関数の再起動・設定変更・デプロイ、EC2 操作、"
                            "DB や IAM ポリシーの変更など実システムへの直接変更を実行する操作。"
                        ),
                        examples=[
                            "Lambda を再起動してください",
                            "Restart the Lambda function",
                            "Deploy the new version",
                            "設定を変更して",
                            "Apply this configuration change to production",
                        ],
                        type="DENY",
                    ),
                ]
            ),
            tags=[cdk.CfnTag(key="project", value="agora")],
        )
        self.guardrail_id = self.guardrail.attr_guardrail_id
        self.guardrail_version = "DRAFT"

        cdk.CfnOutput(self, "GuardrailId", value=self.guardrail_id)
        cdk.CfnOutput(self, "GuardrailArn", value=self.guardrail.attr_guardrail_arn)

        # -------------------------------------------------------------------------
        # IAM execution role for A2A agents (AgentCore Runtime)
        # -------------------------------------------------------------------------
        self.agent_runtime_role = iam.Role(
            self,
            "AgentRuntimeRole",
            role_name="agora-agent-runtime-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
        )
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                    "arn:aws:bedrock:*::foundation-model/*",
                ],
            )
        )
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=["*"],
            )
        )
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:ListAgentRuntimes",
                    "bedrock-agentcore:GetAgentRuntime",
                    "bedrock-agentcore:ListAgentRuntimeEndpoints",
                    "bedrock-agentcore:GetAgentRuntimeEndpoint",
                ],
                resources=["*"],
            )
        )
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:agora/*"
                ],
            )
        )
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=["*"],
            )
        )
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:GetAuthorizationToken",
                ],
                resources=["*"],
            )
        )
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:ApplyGuardrail"],
                resources=[
                    f"arn:aws:bedrock:{self.region}:{self.account}:guardrail/*"
                ],
            )
        )
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:RetrieveMemoryRecords",
                    "bedrock-agentcore:BatchCreateMemoryRecords",
                    "bedrock-agentcore:GetMemory",
                    "bedrock-agentcore:ListMemoryRecords",
                ],
                resources=["*"],
            )
        )
        cdk.CfnOutput(
            self, "AgentRuntimeRoleArn", value=self.agent_runtime_role.role_arn
        )

        # -------------------------------------------------------------------------
        # IAM execution role for AgentCore Memory (LLM-based extraction jobs)
        # -------------------------------------------------------------------------
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
                ],
            )
        )
        self.memory_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=["*"],
            )
        )
        cdk.CfnOutput(
            self, "MemoryExecutionRoleArn", value=self.memory_execution_role.role_arn
        )

        # -------------------------------------------------------------------------
        # SSM Parameter — MonitoringStack (Bridge Lambda) がアカウント解決なしに参照できる
        # -------------------------------------------------------------------------
        ssm.StringParameter(
            self,
            "TicketServiceUrlParam",
            parameter_name="/agora/ticket-service-url",
            string_value=self.ticket_url.url,
            description="Ticket Service Lambda Function URL (for Bridge Lambda)",
        )

        # -------------------------------------------------------------------------
        # Ticket Dispatcher Lambda — DynamoDB Streams consumer (Agora platform side)
        #
        # Triggered by INSERT events on agora-tickets (DynamoDB Streams).
        # Invokes the Gateway Agent to start Triage→Diagnosis→Resolution pipeline.
        # Separated from Bridge Lambda (monitored system) to keep concerns clean.
        # -------------------------------------------------------------------------
        ticket_dispatcher_role = iam.Role(
            self,
            "TicketDispatcherRole",
            role_name="agora-ticket-dispatcher-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                # DynamoDB Streams ポーリング (DescribeStream / GetRecords / etc.)
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaDynamoDBExecutionRole"
                ),
            ],
        )
        ticket_dispatcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=["*"],
            )
        )

        ticket_dispatcher_fn = lambda_.Function(
            self,
            "TicketDispatcherFn",
            function_name="agora-ticket-dispatcher",
            code=lambda_.Code.from_asset(
                str(Path(__file__).parent.parent.parent / "services" / "ticket-dispatcher")
            ),
            handler="lambda_function.handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            memory_size=256,
            timeout=cdk.Duration.seconds(120),
            role=ticket_dispatcher_role,
            environment={
                "AGENT_RUNTIME_ARN": _AGENT_RUNTIME_ARN,
            },
        )

        ticket_dispatcher_fn.add_event_source(
            event_sources.DynamoEventSource(
                data.tickets_table,
                starting_position=lambda_.StartingPosition.LATEST,
                batch_size=10,
                bisect_batch_on_error=True,
                retry_attempts=2,
                filters=[
                    lambda_.FilterCriteria.filter(
                        {"eventName": lambda_.FilterRule.is_equal("INSERT")}
                    )
                ],
            )
        )

        cdk.CfnOutput(
            self, "TicketDispatcherFnArn", value=ticket_dispatcher_fn.function_arn
        )

        # -------------------------------------------------------------------------
        # Outputs
        # -------------------------------------------------------------------------
        cdk.CfnOutput(
            self, "ServicesApiKeySecretArn", value=self.services_api_key_secret.secret_arn
        )
        cdk.CfnOutput(self, "TicketFunctionUrl", value=self.ticket_url.url)
        cdk.CfnOutput(self, "AssetFunctionUrl", value=self.asset_url.url)
        cdk.CfnOutput(self, "GatewayExecutionRoleArn", value=self.gateway_role.role_arn)
        cdk.CfnOutput(self, "UiBucketName", value=self.ui_bucket.bucket_name)
        cdk.CfnOutput(
            self,
            "UiUrl",
            value=f"https://{self.ui_distribution.domain_name}",
        )

from __future__ import annotations

import aws_cdk as cdk
import aws_cdk.aws_ecr as ecr
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_secretsmanager as secretsmanager
from constructs import Construct


class ComputeStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # -------------------------------------------------------------------------
        # ECR repositories — ARM64 Docker images pushed by `make build/deploy`
        # -------------------------------------------------------------------------
        self.ticket_service_repo = ecr.Repository(
            self,
            "TicketServiceRepo",
            repository_name="agora-ticket-service",
            removal_policy=cdk.RemovalPolicy.RETAIN,
            lifecycle_rules=[
                ecr.LifecycleRule(max_image_count=5, description="Keep last 5 images")
            ],
        )

        self.asset_service_repo = ecr.Repository(
            self,
            "AssetServiceRepo",
            repository_name="agora-asset-service",
            removal_policy=cdk.RemovalPolicy.RETAIN,
            lifecycle_rules=[
                ecr.LifecycleRule(max_image_count=5, description="Keep last 5 images")
            ],
        )

        # -------------------------------------------------------------------------
        # ECR repositories — Community Knowledge MCP servers (AgentCore Runtime)
        # -------------------------------------------------------------------------
        _mcp_names = ["stackoverflow", "github-issues", "wikipedia", "aws-docs"]
        self.mcp_repos: dict[str, ecr.Repository] = {}
        for _name in _mcp_names:
            _cid = _name.replace("-", " ").title().replace(" ", "") + "McpRepo"
            _repo = ecr.Repository(
                self,
                _cid,
                repository_name=f"agora-{_name}",
                removal_policy=cdk.RemovalPolicy.RETAIN,
                lifecycle_rules=[
                    ecr.LifecycleRule(max_image_count=5, description="Keep last 5 images")
                ],
            )
            self.mcp_repos[_name] = _repo
            cdk.CfnOutput(self, f"{_cid}Uri", value=_repo.repository_uri)

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

        # -------------------------------------------------------------------------
        # Lambda functions (container image + Lambda Web Adapter)
        # Images are updated via `make build img=... && make deploy img=...`
        # then `make lambda-update img=...`
        # -------------------------------------------------------------------------
        common_env = {
            "AWS_LWA_PORT": "8080",
            "AWS_LWA_READINESS_CHECK_PATH": "/health",
        }

        self.ticket_fn = lambda_.DockerImageFunction(
            self,
            "TicketServiceFn",
            function_name="agora-ticket-service",
            code=lambda_.DockerImageCode.from_ecr(
                self.ticket_service_repo,
                tag_or_digest="latest",
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
            code=lambda_.DockerImageCode.from_ecr(
                self.asset_service_repo,
                tag_or_digest="latest",
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
        # ECR repository — Gateway Agent (AgentCore Runtime / HTTP / AG-UI)
        # -------------------------------------------------------------------------
        self.gateway_agent_repo = ecr.Repository(
            self,
            "GatewayAgentRepo",
            repository_name="agora-gateway",
            removal_policy=cdk.RemovalPolicy.RETAIN,
            lifecycle_rules=[
                ecr.LifecycleRule(max_image_count=5, description="Keep last 5 images")
            ],
        )
        cdk.CfnOutput(self, "GatewayAgentRepoUri", value=self.gateway_agent_repo.repository_uri)

        # -------------------------------------------------------------------------
        # ECR repositories — A2A agents (AgentCore Runtime / A2A protocol)
        # -------------------------------------------------------------------------
        _agent_names = ["triage", "diagnosis", "resolution"]
        self.agent_repos: dict[str, ecr.Repository] = {}
        for _name in _agent_names:
            _cid = _name.title() + "AgentRepo"
            _repo = ecr.Repository(
                self,
                _cid,
                repository_name=f"agora-{_name}",
                removal_policy=cdk.RemovalPolicy.RETAIN,
                lifecycle_rules=[
                    ecr.LifecycleRule(max_image_count=5, description="Keep last 5 images")
                ],
            )
            self.agent_repos[_name] = _repo
            cdk.CfnOutput(self, f"{_cid}Uri", value=_repo.repository_uri)

        # -------------------------------------------------------------------------
        # IAM execution role for A2A agents (AgentCore Runtime)
        # Needs Bedrock InvokeModel + AgentCore invoke + Secrets Manager read
        # -------------------------------------------------------------------------
        self.agent_runtime_role = iam.Role(
            self,
            "AgentRuntimeRole",
            role_name="agora-agent-runtime-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
        )
        # Bedrock model invocation
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
        # AgentCore Runtime invocation (calling MCP servers + other A2A agents)
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=["*"],
            )
        )
        # AgentCore control plane — Registry discovery
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
        # Secrets Manager — read API keys (Resolution agent needs service API key)
        self.agent_runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:agora/*"
                ],
            )
        )
        # CloudWatch Logs
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
        # ECR pull
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
        # AgentCore Memory — retrieve and create memory records
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
        # Outputs
        # -------------------------------------------------------------------------
        cdk.CfnOutput(
            self, "TicketServiceRepoUri", value=self.ticket_service_repo.repository_uri
        )
        cdk.CfnOutput(
            self, "AssetServiceRepoUri", value=self.asset_service_repo.repository_uri
        )
        cdk.CfnOutput(
            self, "ServicesApiKeySecretArn", value=self.services_api_key_secret.secret_arn
        )
        cdk.CfnOutput(
            self, "TicketFunctionUrl", value=self.ticket_url.url
        )
        cdk.CfnOutput(
            self, "AssetFunctionUrl", value=self.asset_url.url
        )
        cdk.CfnOutput(
            self, "GatewayExecutionRoleArn", value=self.gateway_role.role_arn
        )

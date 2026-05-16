from __future__ import annotations

import json
from pathlib import Path

import aws_cdk as cdk
import aws_cdk.aws_bedrockagentcore as agentcore
from constructs import Construct
from pydantic_settings import BaseSettings

from stacks.compute_stack import ComputeStack

SPECS_DIR = Path(__file__).parent.parent / "specs"


class _Settings(BaseSettings):
    github_token: str = ""


_GITHUB_TOKEN = _Settings().github_token

# (runtime_name, description, protocol, capability, env_vars)
_MCP_SERVERS: list[dict] = [
    {
        "name": "stackoverflow",
        "runtime_name": "agora_stackoverflow",
        "description": "Stack Overflow search MCP — queries Stack Exchange API for Q&A",
        "protocol": "MCP",
        "capability": "community-knowledge",
        "env": {},
    },
    {
        "name": "github-issues",
        "runtime_name": "agora_github_issues",
        "description": "GitHub Issues search MCP — searches GitHub for bug reports and discussions",
        "protocol": "MCP",
        "capability": "community-knowledge",
        "env": {"GITHUB_TOKEN": _GITHUB_TOKEN},
    },
    {
        "name": "wikipedia",
        "runtime_name": "agora_wikipedia",
        "description": "Wikipedia MCP — searches Wikipedia for technology concepts and articles",
        "protocol": "MCP",
        "capability": "community-knowledge",
        "env": {},
    },
    {
        "name": "aws-docs",
        "runtime_name": "agora_aws_docs",
        "description": "AWS Docs MCP — searches AWS documentation (awslabs/mcp)",
        "protocol": "MCP",
        "capability": "community-knowledge",
        "env": {"AWS_DOCUMENTATION_PARTITION": "aws", "FASTMCP_LOG_LEVEL": "WARNING"},
    },
]

_A2A_AGENTS: list[dict] = [
    {
        "name": "triage",
        "runtime_name": "agora_triage",
        "description": "Triage Agent — classifies IT incidents by severity and category",
        "protocol": "A2A",
        "capability": "a2a-agent",
        "env": {},
    },
    {
        "name": "diagnosis",
        "runtime_name": "agora_diagnosis",
        "description": "Diagnosis Agent — searches community knowledge and past tickets",
        "protocol": "A2A",
        "capability": "a2a-agent",
        "env": {},  # TICKET_SERVICE_URL injected from ComputeStack outputs
    },
    {
        "name": "resolution",
        "runtime_name": "agora_resolution",
        "description": "Resolution Agent — generates resolution plans and creates incident tickets",
        "protocol": "A2A",
        "capability": "a2a-agent",
        "env": {},  # TICKET_SERVICE_URL injected from ComputeStack outputs
    },
]

_GATEWAY_AGENT: dict = {
    "name": "gateway",
    "runtime_name": "agora_gateway",
    "description": "Gateway Agent — user-facing orchestrator (AG-UI/SSE)",
    "protocol": "HTTP",
    "capability": "gateway",
    "env": {},
}


def _logical_id(runtime_name: str) -> str:
    """Convert agora_foo_bar → AgoraFooBar for CDK logical IDs."""
    return "".join(part.title() for part in runtime_name.split("_"))


def _export_name(runtime_name: str) -> str:
    """Convert agora_foo_bar → AgentCore-agora-foo-bar-arn (CF export, no underscores)."""
    return f"AgentCore-{runtime_name.replace('_', '-')}-arn"


class AgentCoreStack(cdk.Stack):
    def __init__(
        self, scope: Construct, construct_id: str, compute: ComputeStack, **kwargs: object
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account = self.account
        region = self.region
        ecr_base = f"{account}.dkr.ecr.{region}.amazonaws.com"

        # -------------------------------------------------------------------------
        # MCP server runtimes (Community Knowledge)
        # -------------------------------------------------------------------------
        self.mcp_runtimes: dict[str, agentcore.CfnRuntime] = {}
        for srv in _MCP_SERVERS:
            env_vars = {k: v for k, v in srv["env"].items() if v}
            cid = _logical_id(srv["runtime_name"]) + "Runtime"
            runtime = agentcore.CfnRuntime(
                self,
                cid,
                agent_runtime_name=srv["runtime_name"],
                description=srv["description"],
                agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                    container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                        container_uri=f"{ecr_base}/agora-{srv['name']}:latest",
                    ),
                ),
                role_arn=compute.mcp_runtime_role.role_arn,
                network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                    network_mode="PUBLIC",
                ),
                protocol_configuration=srv["protocol"],
                environment_variables=env_vars if env_vars else None,
                tags={"capability": srv["capability"], "project": "agora"},
            )
            self.mcp_runtimes[srv["name"]] = runtime

            ep_cid = _logical_id(srv["runtime_name"]) + "Endpoint"
            agentcore.CfnRuntimeEndpoint(
                self,
                ep_cid,
                agent_runtime_id=runtime.attr_agent_runtime_id,
                name=f"{srv['runtime_name']}_ep",
                description=f"Default endpoint for {srv['runtime_name']}",
            )

            cdk.CfnOutput(
                self,
                _logical_id(srv["runtime_name"]) + "Arn",
                value=runtime.attr_agent_runtime_arn,
                export_name=_export_name(srv["runtime_name"]),
            )

        # -------------------------------------------------------------------------
        # A2A agent runtimes (Triage / Diagnosis / Resolution)
        # -------------------------------------------------------------------------
        self.agent_runtimes: dict[str, agentcore.CfnRuntime] = {}
        for agent in _A2A_AGENTS:
            env_vars = dict(agent["env"])
            if agent["name"] in ("diagnosis", "resolution"):
                env_vars["TICKET_SERVICE_URL"] = compute.ticket_url.url

            cid = _logical_id(agent["runtime_name"]) + "Runtime"
            runtime = agentcore.CfnRuntime(
                self,
                cid,
                agent_runtime_name=agent["runtime_name"],
                description=agent["description"],
                agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                    container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                        container_uri=f"{ecr_base}/agora-{agent['name']}:latest",
                    ),
                ),
                role_arn=compute.agent_runtime_role.role_arn,
                network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                    network_mode="PUBLIC",
                ),
                protocol_configuration=agent["protocol"],
                environment_variables=env_vars if env_vars else None,
                tags={
                    "capability": agent["capability"],
                    "agent-type": agent["name"],
                    "project": "agora",
                },
            )
            self.agent_runtimes[agent["name"]] = runtime

            ep_cid = _logical_id(agent["runtime_name"]) + "Endpoint"
            agentcore.CfnRuntimeEndpoint(
                self,
                ep_cid,
                agent_runtime_id=runtime.attr_agent_runtime_id,
                name=f"{agent['runtime_name']}_ep",
                description=f"Default endpoint for {agent['runtime_name']}",
            )

            cdk.CfnOutput(
                self,
                _logical_id(agent["runtime_name"]) + "Arn",
                value=runtime.attr_agent_runtime_arn,
                export_name=_export_name(agent["runtime_name"]),
            )

        # -------------------------------------------------------------------------
        # AgentCore Memory — conversation context and user preference storage
        # -------------------------------------------------------------------------
        self.memory = agentcore.CfnMemory(
            self,
            "AgoraMemory",
            name="agora_memory",
            description="Conversation context and user preference memory for Agora IT Service Desk",
            event_expiry_duration=90,
            memory_execution_role_arn=compute.memory_execution_role.role_arn,
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
        cdk.CfnOutput(self, "MemoryId", value=self.memory.attr_memory_id)
        cdk.CfnOutput(
            self,
            "MemoryArn",
            value=self.memory.attr_memory_arn,
            export_name="AgentCore-agora-memory-arn",
        )

        # -------------------------------------------------------------------------
        # Gateway Agent runtime (HTTP / AG-UI)
        # -------------------------------------------------------------------------
        gw_agent = _GATEWAY_AGENT
        gw_cid = _logical_id(gw_agent["runtime_name"]) + "Runtime"
        self.gateway_agent_runtime = agentcore.CfnRuntime(
            self,
            gw_cid,
            agent_runtime_name=gw_agent["runtime_name"],
            description=gw_agent["description"],
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=f"{ecr_base}/agora-gateway:latest",
                ),
            ),
            role_arn=compute.agent_runtime_role.role_arn,
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC",
            ),
            protocol_configuration=gw_agent["protocol"],
            environment_variables={"MEMORY_ID": self.memory.attr_memory_id},
            tags={"capability": gw_agent["capability"], "project": "agora"},
        )
        agentcore.CfnRuntimeEndpoint(
            self,
            "AgoraGatewayEndpoint",
            agent_runtime_id=self.gateway_agent_runtime.attr_agent_runtime_id,
            name="agora_gateway_ep",
            description="Default endpoint for agora_gateway",
        )
        cdk.CfnOutput(
            self,
            "AgoraGatewayRuntimeArn",
            value=self.gateway_agent_runtime.attr_agent_runtime_arn,
            export_name=_export_name("agora_gateway"),
        )

        # -------------------------------------------------------------------------
        # API key credential provider — resolves secret from Secrets Manager
        # -------------------------------------------------------------------------
        self.api_key_cred = agentcore.CfnApiKeyCredentialProvider(
            self,
            "ServicesApiKeyCredential",
            name="agora_services_api_key",
            api_key=cdk.SecretValue.secrets_manager("agora/services-api-key").unsafe_unwrap(),
            tags=[cdk.CfnTag(key="project", value="agora")],
        )

        # -------------------------------------------------------------------------
        # AgentCore Gateway (MCP protocol, no inbound auth for sandbox)
        # -------------------------------------------------------------------------
        self.gateway = agentcore.CfnGateway(
            self,
            "AgoraGateway",
            name="agora-gateway",
            description="AgentCore Gateway that exposes Agora internal services as MCP tools",
            role_arn=compute.gateway_role.role_arn,
            authorizer_type="NONE",
            protocol_type="MCP",
            tags={"project": "agora"},
        )

        # -------------------------------------------------------------------------
        # Gateway targets — Ticket Service and Asset Service
        # OpenAPI specs are read at synth time; Lambda URLs are substituted via Fn::Sub
        # -------------------------------------------------------------------------
        for svc_name, url_token in (
            ("ticket-service", compute.ticket_url.url),
            ("asset-service", compute.asset_url.url),
        ):
            spec = json.loads((SPECS_DIR / f"{svc_name}.json").read_text())
            spec["servers"] = [{"url": "__SVC_URL__"}]
            spec_template = json.dumps(spec).replace('"__SVC_URL__"', '"${SvcUrl}"')
            inline_payload = cdk.Fn.sub(spec_template, {"SvcUrl": url_token})

            cid = svc_name.replace("-", " ").title().replace(" ", "") + "GatewayTarget"
            agentcore.CfnGatewayTarget(
                self,
                cid,
                name=f"agora-{svc_name}",
                description=f"Agora {svc_name.replace('-', ' ').title()} CRUD",
                gateway_identifier=self.gateway.attr_gateway_identifier,
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

        cdk.CfnOutput(self, "GatewayUrl", value=self.gateway.attr_gateway_url)

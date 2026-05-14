"""
AgentCore Gateway registration script.

Creates (or idempotently updates) the Gateway + API key credential + two OpenAPI targets.
Run after `make cdk-deploy` (ComputeStack) and after pushing both service images to ECR
and deploying them to AgentCore Runtime to obtain their endpoint URLs.

Usage:
    uv run python infrastructure/scripts/register_gateway.py \
        --ticket-url https://<ticket-runtime-endpoint> \
        --asset-url  https://<asset-runtime-endpoint>

Environment variable (alternative to --ticket-url / --asset-url):
    TICKET_SERVICE_URL
    ASSET_SERVICE_URL
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import boto3

REGION = "us-east-1"
GATEWAY_NAME = "agora-gateway"
TICKET_TARGET_NAME = "agora-ticket-service"
ASSET_TARGET_NAME = "agora-asset-service"
API_KEY_CREDENTIAL_NAME = "agora_services_api_key"
SECRET_NAME = "agora/services-api-key"

SPECS_DIR = Path(__file__).parent.parent / "specs"


def _wait_for_gateway(client, gateway_id: str, desired_status: str = "READY") -> None:
    for _ in range(30):
        resp = client.get_gateway(gatewayIdentifier=gateway_id)
        status = resp["status"]
        print(f"  Gateway status: {status}")
        if status == desired_status:
            return
        if status in ("FAILED", "DELETE_FAILED"):
            raise RuntimeError(f"Gateway entered terminal state: {status}")
        time.sleep(10)
    raise TimeoutError("Gateway did not reach READY within 5 minutes")


def _get_api_key(secretsmanager) -> str:
    resp = secretsmanager.get_secret_value(SecretId=SECRET_NAME)
    return resp["SecretString"]


def _find_existing(items: list[dict], name_key: str, name: str) -> dict | None:
    return next((i for i in items if i.get(name_key) == name), None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Register AgentCore Gateway for Agora services")
    parser.add_argument("--ticket-url", default=os.environ.get("TICKET_SERVICE_URL"))
    parser.add_argument("--asset-url", default=os.environ.get("ASSET_SERVICE_URL"))
    parser.add_argument("--role-arn", default=os.environ.get("GATEWAY_ROLE_ARN"))
    args = parser.parse_args()

    if not args.ticket_url or not args.asset_url:
        print("ERROR: --ticket-url and --asset-url are required")
        print("       (or set TICKET_SERVICE_URL / ASSET_SERVICE_URL)")
        sys.exit(1)

    # Resolve gateway role ARN from CDK outputs if not provided
    if not args.role_arn:
        cf = boto3.client("cloudformation", region_name=REGION)
        outputs = cf.describe_stacks(StackName="AgoraComputeStack")["Stacks"][0]["Outputs"]
        for o in outputs:
            if o["OutputKey"] == "GatewayExecutionRoleArn":
                args.role_arn = o["OutputValue"]
                break
    if not args.role_arn:
        print("ERROR: could not resolve gateway role ARN from AgoraComputeStack outputs")
        sys.exit(1)

    control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    sm = boto3.client("secretsmanager", region_name=REGION)

    # ------------------------------------------------------------------
    # 1. Fetch API key from Secrets Manager
    # ------------------------------------------------------------------
    print("Fetching API key from Secrets Manager ...")
    api_key = _get_api_key(sm)

    # ------------------------------------------------------------------
    # 2. Create or reuse the API key credential provider
    # ------------------------------------------------------------------
    existing_creds = control.list_api_key_credential_providers().get("credentialProviders", [])
    cred = _find_existing(existing_creds, "name", API_KEY_CREDENTIAL_NAME)

    if cred:
        cred_arn = cred["credentialProviderArn"]
        print(f"Reusing credential provider: {cred_arn}")
    else:
        print(f"Creating credential provider '{API_KEY_CREDENTIAL_NAME}' ...")
        resp = control.create_api_key_credential_provider(
            name=API_KEY_CREDENTIAL_NAME,
            apiKey=api_key,
        )
        cred_arn = resp["credentialProviderArn"]
        print(f"  Created: {cred_arn}")

    # ------------------------------------------------------------------
    # 3. Create or reuse the Gateway
    # ------------------------------------------------------------------
    existing_gws = control.list_gateways().get("items", [])
    gw = _find_existing(existing_gws, "name", GATEWAY_NAME)

    if gw:
        gateway_id = gw["gatewayId"]
        print(f"Reusing Gateway: {gateway_id}")
    else:
        print(f"Creating Gateway '{GATEWAY_NAME}' ...")
        resp = control.create_gateway(
            name=GATEWAY_NAME,
            description="AgentCore Gateway that exposes Agora internal services as MCP tools",
            roleArn=args.role_arn,
            # No inbound authorizer for sandbox — agents call Gateway with IAM later
            authorizerType="NONE",
        )
        gateway_id = resp["gatewayId"]
        print(f"  Gateway ID: {gateway_id}")
        print("Waiting for Gateway to reach READY ...")
        _wait_for_gateway(control, gateway_id)

    # ------------------------------------------------------------------
    # 4. Register Ticket Service target
    # ------------------------------------------------------------------
    ticket_spec = json.loads((SPECS_DIR / "ticket-service.json").read_text())
    # Inject runtime URL as server base
    ticket_spec["servers"] = [{"url": args.ticket_url}]

    existing_targets = control.list_gateway_targets(gatewayIdentifier=gateway_id).get("items", [])
    ticket_target = _find_existing(existing_targets, "name", TICKET_TARGET_NAME)

    if ticket_target:
        print(f"Updating Ticket Service target '{TICKET_TARGET_NAME}' ...")
        control.update_gateway_target(
            gatewayIdentifier=gateway_id,
            targetId=ticket_target["targetId"],
            name=TICKET_TARGET_NAME,
            targetConfiguration={
                "mcp": {"openApiSchema": {"inlinePayload": json.dumps(ticket_spec)}},
            },
            credentialProviderConfigurations=[
                {
                    "credentialProviderType": "API_KEY",
                    "credentialProvider": {
                        "apiKeyCredentialProvider": {
                            "providerArn": cred_arn,
                            "credentialParameterName": "x-api-key",
                            "credentialLocation": "HEADER",
                        },
                    },
                }
            ],
        )
        print("  Updated.")
    else:
        print(f"Creating Ticket Service target '{TICKET_TARGET_NAME}' ...")
        resp = control.create_gateway_target(
            gatewayIdentifier=gateway_id,
            name=TICKET_TARGET_NAME,
            description="Agora Ticket Service — incident management CRUD",
            targetConfiguration={
                "mcp": {"openApiSchema": {"inlinePayload": json.dumps(ticket_spec)}},
            },
            credentialProviderConfigurations=[
                {
                    "credentialProviderType": "API_KEY",
                    "credentialProvider": {
                        "apiKeyCredentialProvider": {
                            "providerArn": cred_arn,
                            "credentialParameterName": "x-api-key",
                            "credentialLocation": "HEADER",
                        },
                    },
                }
            ],
        )
        print(f"  Target ID: {resp['targetId']}")

    # ------------------------------------------------------------------
    # 5. Register Asset Service target
    # ------------------------------------------------------------------
    asset_spec = json.loads((SPECS_DIR / "asset-service.json").read_text())
    asset_spec["servers"] = [{"url": args.asset_url}]

    existing_targets = control.list_gateway_targets(gatewayIdentifier=gateway_id).get("items", [])
    asset_target = _find_existing(existing_targets, "name", ASSET_TARGET_NAME)

    if asset_target:
        print(f"Updating Asset Service target '{ASSET_TARGET_NAME}' ...")
        control.update_gateway_target(
            gatewayIdentifier=gateway_id,
            targetId=asset_target["targetId"],
            name=ASSET_TARGET_NAME,
            targetConfiguration={
                "mcp": {"openApiSchema": {"inlinePayload": json.dumps(asset_spec)}},
            },
            credentialProviderConfigurations=[
                {
                    "credentialProviderType": "API_KEY",
                    "credentialProvider": {
                        "apiKeyCredentialProvider": {
                            "providerArn": cred_arn,
                            "credentialParameterName": "x-api-key",
                            "credentialLocation": "HEADER",
                        },
                    },
                }
            ],
        )
        print("  Updated.")
    else:
        print(f"Creating Asset Service target '{ASSET_TARGET_NAME}' ...")
        resp = control.create_gateway_target(
            gatewayIdentifier=gateway_id,
            name=ASSET_TARGET_NAME,
            description="Agora Asset Service — configuration management DB CRUD",
            targetConfiguration={
                "mcp": {"openApiSchema": {"inlinePayload": json.dumps(asset_spec)}},
            },
            credentialProviderConfigurations=[
                {
                    "credentialProviderType": "API_KEY",
                    "credentialProvider": {
                        "apiKeyCredentialProvider": {
                            "providerArn": cred_arn,
                            "credentialParameterName": "x-api-key",
                            "credentialLocation": "HEADER",
                        },
                    },
                }
            ],
        )
        print(f"  Target ID: {resp['targetId']}")

    # ------------------------------------------------------------------
    # 6. Summarize
    # ------------------------------------------------------------------
    gw_detail = control.get_gateway(gatewayIdentifier=gateway_id)
    gateway_url = gw_detail.get("gatewayUrl", "(not yet available)")
    print("\n=== Registration complete ===")
    print(f"  Gateway ID : {gateway_id}")
    print(f"  Gateway URL: {gateway_url}")
    print(f"  MCP endpoint: {gateway_url}/mcp  (agents connect here)")


if __name__ == "__main__":
    main()

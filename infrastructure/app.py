from __future__ import annotations

import os

import aws_cdk as cdk
from stacks.agent_core_stack import AgentCoreStack
from stacks.compute_stack import ComputeStack
from stacks.data_stack import DataStack
from stacks.monitoring_stack import MonitoringStack

app = cdk.App()

# CDK_DEFAULT_ACCOUNT / CDK_DEFAULT_REGION are set automatically by the CDK CLI
# from the current AWS credentials. Specifying account here enables cross-stack
# references (e.g., DynamoDB Streams ARN from DataStack → ComputeStack).
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION"),
)

data = DataStack(app, "AgoraDataStack", env=env)
compute = ComputeStack(app, "AgoraComputeStack", data=data, env=env)
AgentCoreStack(app, "AgoraAgentCoreStack", compute=compute, env=env)
MonitoringStack(app, "AgoraMonitoringStack", env=env)

app.synth()

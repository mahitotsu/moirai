from __future__ import annotations

import aws_cdk as cdk
from stacks.agent_core_stack import AgentCoreStack
from stacks.compute_stack import ComputeStack
from stacks.data_stack import DataStack

app = cdk.App()

env = cdk.Environment(region="us-east-1")

DataStack(app, "AgoraDataStack", env=env)
compute = ComputeStack(app, "AgoraComputeStack", env=env)
AgentCoreStack(app, "AgoraAgentCoreStack", compute=compute, env=env)

app.synth()

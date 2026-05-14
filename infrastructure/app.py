from __future__ import annotations

import aws_cdk as cdk
from stacks.compute_stack import ComputeStack
from stacks.data_stack import DataStack

app = cdk.App()

env = cdk.Environment(region="us-east-1")

DataStack(app, "AgoraDataStack", env=env)
ComputeStack(app, "AgoraComputeStack", env=env)

app.synth()

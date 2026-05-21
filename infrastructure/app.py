from __future__ import annotations

import os

import aws_cdk as cdk
from stacks.agora_stack import AgoraStack
from stacks.fault_injection_stack import FaultInjectionStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION"),
)

agora = AgoraStack(app, "AgoraStack", env=env)
fault = FaultInjectionStack(app, "FaultInjectionStack", env=env)
# AgoraStack が SSM パラメータを作成してから FaultInjectionStack をデプロイする
fault.add_dependency(agora)

app.synth()

#!/usr/bin/env python3
import os

import aws_cdk as cdk

from kev_systemone.stacks import SystemOneStack

app = cdk.App()
env = cdk.Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region=os.getenv("CDK_DEFAULT_REGION"))


def ctx(key: str, default: str) -> str:
    return app.node.try_get_context(key) or default


repository_name = ctx("ecrRepository", "kev-model-systemone-serverless")

SystemOneStack(
    app, "KevSystemOneStack",
    repository_name=repository_name,
    image_tag=ctx("imageTag", "latest"),
    adapter_repo=ctx("adapterRepo", "jaredpalmer/kev-0.8b"),
    base_repo=ctx("baseRepo", "Qwen/Qwen3.5-0.8B-Base"),
    env=env,
)

app.synth()

import json

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from kev_systemone.stacks import ModelStack, SystemOneStack

ENV = cdk.Environment(account="123456789012", region="us-east-1")


def system_one_template() -> Template:
    stack = SystemOneStack(cdk.App(), "Test", repository_name="repo", image_tag="abc123", env=ENV)
    return Template.from_stack(stack)


def model_template() -> Template:
    stack = ModelStack(cdk.App(), "Model", adapter_repo="org/adapter", base_repo="org/base", env=ENV)
    return Template.from_stack(stack)


def test_inference_function_is_a_cpu_container():
    system_one_template().has_resource_properties("AWS::Lambda::Function", {
        "PackageType": "Image",
        "MemorySize": 10240,
        "EphemeralStorage": {"Size": 4096},
        "Architectures": ["x86_64"],
        "Environment": {"Variables": Match.object_like({"MAX_STATE_TOKENS": "8192"})},
    })


def test_inference_function_has_no_bucket_dependency():
    # The weights are baked into the image; the Lambda needs no S3 access.
    template = system_one_template()
    template.resource_count_is("AWS::S3::Bucket", 0)
    assert "s3:GetObject" not in json.dumps(template.to_json())


def test_api_requires_a_key():
    template = system_one_template()
    template.has_resource_properties("AWS::ApiGateway::Method", {"HttpMethod": "POST", "ApiKeyRequired": True})
    template.has_resource_properties("AWS::ApiGateway::Method", {"HttpMethod": "GET", "ApiKeyRequired": True})
    template.resource_count_is("AWS::ApiGateway::UsagePlan", 1)


def test_model_bucket_is_private():
    model_template().has_resource_properties("AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": Match.object_like({"BlockPublicAcls": True, "RestrictPublicBuckets": True}),
    })


def test_ingest_tasks_pass_the_state_input_as_an_object():
    # A string Parameters ("$") reached the Lambda as a str event and broke event.get().
    template = model_template()
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)
    machine = next(iter(template.find_resources("AWS::StepFunctions::StateMachine").values()))
    assert '"Parameters": "$"' not in json.dumps(machine["Properties"]["DefinitionString"])

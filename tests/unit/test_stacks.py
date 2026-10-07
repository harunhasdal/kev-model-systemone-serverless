import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from kev_systemone.stacks import SystemOneStack


def system_one_template() -> Template:
    stack = SystemOneStack(
        cdk.App(), "Test", repository_name="repo", image_tag="abc123",
        adapter_repo="org/adapter", base_repo="org/base",
        env=cdk.Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_inference_function_is_a_cpu_container():
    template = system_one_template()
    template.has_resource_properties("AWS::Lambda::Function", {
        "PackageType": "Image",
        "MemorySize": 10240,
        "EphemeralStorage": {"Size": 4096},
        "Architectures": ["x86_64"],
        "Environment": {"Variables": Match.object_like({"MAX_STATE_TOKENS": "8192"})},
    })


def test_api_requires_a_key():
    template = system_one_template()
    template.has_resource_properties("AWS::ApiGateway::Method", {"HttpMethod": "POST", "ApiKeyRequired": True})
    template.has_resource_properties("AWS::ApiGateway::Method", {"HttpMethod": "GET", "ApiKeyRequired": True})
    template.resource_count_is("AWS::ApiGateway::UsagePlan", 1)


def test_ingest_state_machine_and_bucket():
    template = system_one_template()
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)
    template.has_resource_properties("AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": Match.object_like({"BlockPublicAcls": True, "RestrictPublicBuckets": True}),
    })


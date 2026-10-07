import json

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from kev_systemone.stacks import ModelStack, SystemOneStack

ENV = cdk.Environment(account="123456789012", region="us-east-1")


def system_one_template(provisioned_concurrency: int = 0) -> Template:
    app = cdk.App()
    model = ModelStack(app, "Model", adapter_repo="org/adapter", base_repo="org/base", env=ENV)
    stack = SystemOneStack(app, "Test", repository_name="repo", image_tag="abc123", model_bucket=model.bucket,
                           provisioned_concurrency=provisioned_concurrency, env=ENV)
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


def test_inference_function_reads_the_model_bucket():
    template = system_one_template()
    template.has_resource_properties("AWS::Lambda::Function", {
        "Environment": {"Variables": Match.object_like({"MODEL_BUCKET": Match.any_value()})},
    })
    assert "s3:GetObject*" in json.dumps(template.to_json())


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


def test_api_streams_responses_from_the_alias_with_a_long_timeout():
    template = system_one_template()
    template.has_resource_properties("AWS::ApiGateway::Method", {
        "HttpMethod": "POST",
        "Integration": Match.object_like({"ResponseTransferMode": "STREAM", "TimeoutInMillis": 150000}),
    })
    assert "response-streaming-invocations" in json.dumps(template.to_json())


def test_no_provisioned_concurrency_by_default_and_async_init_on():
    template = system_one_template()
    template.has_resource_properties("AWS::Lambda::Alias", {"Name": "live"})
    assert "ProvisionedConcurrencyConfig" not in json.dumps(template.to_json())
    template.has_resource_properties("AWS::Lambda::Function", {
        "Environment": {"Variables": Match.object_like({"AWS_LWA_INVOKE_MODE": "response_stream", "AWS_LWA_ASYNC_INIT": "true"})},
    })


def test_provisioned_concurrency_loads_the_model_during_init():
    template = system_one_template(provisioned_concurrency=1)
    template.has_resource_properties("AWS::Lambda::Alias", {"ProvisionedConcurrencyConfig": {"ProvisionedConcurrentExecutions": 1}})
    template.has_resource_properties("AWS::Lambda::Function", {
        "Environment": {"Variables": Match.object_like({"AWS_LWA_ASYNC_INIT": "false"})},
    })

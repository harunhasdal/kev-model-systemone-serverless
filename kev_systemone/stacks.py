from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Size,
    Stack,
    aws_apigateway as apigw,
    aws_ecr as ecr,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_s3 as s3,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
)
from constructs import Construct

MAX_STATE_TOKENS = 8192   # validated context of Kev-0.8B; the Lambda CPU path builds an L x L attention mask


class ModelStack(Stack):
    """Model storage and the on-demand Hugging Face to S3 copy (Step Functions). The inference image is built from this bucket."""

    def __init__(self, scope: Construct, construct_id: str, *, adapter_repo: str, base_repo: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket(
            self, "ModelBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        ingest_env = {"BUCKET": bucket.bucket_name, "ADAPTER_REPO": adapter_repo, "BASE_REPO": base_repo}
        ingest_code = _lambda.Code.from_asset("lambdas/ingest")
        list_fn = _lambda.Function(
            self, "ListFilesFn", runtime=_lambda.Runtime.PYTHON_3_12, handler="ingest.list_files", code=ingest_code,
            timeout=Duration.minutes(2), environment=ingest_env, log_group=self._logs("ListFilesLogs"),
        )
        copy_fn = _lambda.Function(
            self, "CopyFileFn", runtime=_lambda.Runtime.PYTHON_3_12, handler="ingest.copy_file", code=ingest_code,
            timeout=Duration.minutes(15), memory_size=1024, environment=ingest_env, log_group=self._logs("CopyFileLogs"),
        )
        bucket.grant_read_write(copy_fn)
        bucket.grant_read_write(list_fn)   # prunes stale keys

        # No payload: the state input is the Lambda event, and the function's return value is the state output.
        list_task = tasks.LambdaInvoke(self, "ListFiles", lambda_function=list_fn, payload_response_only=True)
        copy_task = tasks.LambdaInvoke(self, "CopyFile", lambda_function=copy_fn, payload_response_only=True)
        copy_task.add_retry(errors=["States.ALL"], interval=Duration.seconds(10), max_attempts=3, backoff_rate=2)
        copy_all = sfn.Map(self, "CopyFiles", items_path="$.files", max_concurrency=4, result_path=sfn.JsonPath.DISCARD)
        copy_all.item_processor(copy_task)

        ingest = sfn.StateMachine(
            self, "IngestStateMachine",
            definition_body=sfn.DefinitionBody.from_chainable(list_task.next(copy_all)),
            timeout=Duration.hours(1),
        )

        CfnOutput(self, "ModelBucketName", value=bucket.bucket_name)
        CfnOutput(self, "IngestStateMachineArn", value=ingest.state_machine_arn)

    def _logs(self, construct_id: str) -> logs.LogGroup:
        return logs.LogGroup(self, construct_id, retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY)


class SystemOneStack(Stack):
    """CPU inference (Lambda container with the model baked in) and the REST API in front of it."""

    def __init__(self, scope: Construct, construct_id: str, *, repository_name: str, image_tag: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        repository = ecr.Repository.from_repository_name(self, "Repository", repository_name)
        inference = _lambda.DockerImageFunction(
            self, "InferenceFn",
            code=_lambda.DockerImageCode.from_ecr(repository, tag_or_digest=image_tag),
            architecture=_lambda.Architecture.X86_64,
            memory_size=10240,   # also sets the vCPU share: 6 vCPUs at 10 GB
            timeout=Duration.minutes(2),
            log_group=logs.LogGroup(self, "InferenceLogs", retention=logs.RetentionDays.ONE_WEEK, removal_policy=RemovalPolicy.DESTROY),
            environment={"MAX_STATE_TOKENS": str(MAX_STATE_TOKENS)},
        )

        api = apigw.RestApi(
            self, "Api",
            rest_api_name="kev-systemone",
            endpoint_types=[apigw.EndpointType.REGIONAL],
            api_key_source_type=apigw.ApiKeySourceType.HEADER,
            deploy_options=apigw.StageOptions(stage_name="demo", throttling_rate_limit=5, throttling_burst_limit=10),
        )
        integration = apigw.LambdaIntegration(inference)
        v1 = api.root.add_resource("v1")
        v1.add_resource("systemone").add_method("POST", integration, api_key_required=True)
        v1.add_resource("models").add_method("GET", integration, api_key_required=True)

        api_key = api.add_api_key("DemoApiKey")
        plan = api.add_usage_plan(
            "UsagePlan",
            throttle=apigw.ThrottleSettings(rate_limit=5, burst_limit=10),
            quota=apigw.QuotaSettings(limit=1000, period=apigw.Period.DAY),
        )
        plan.add_api_key(api_key)
        plan.add_api_stage(stage=api.deployment_stage)

        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "ApiKeyId", value=api_key.key_id)

# Kev System One on AWS, serverless

Serves [Kev-0.8B](https://github.com/jaredpalmer/kev/blob/main/docs/model-cards/kev-0.8b.md) (a decision model with
Choice, Score and Noul questions, TypeSafe `POST /v1/systemone` API) from a CPU Lambda container behind API Gateway.
It scores options in one forward pass and does not generate text, so it does not stream and is not a Bedrock Custom
Model Import candidate (Qwen3.5 architecture, adapter-only repo, no LM head).

```
Step Functions (ingest)                 API Gateway (REST, API key)
  ListFiles -> Map(CopyFile)                      |
  Hugging Face -> S3                              v
        |                       Lambda container: Lambda Web Adapter + kev.serve (CPU, fp32)
        +--------- S3 <-- model download to /tmp at cold start
```

## Layout

| Path | Purpose |
|---|---|
| `kev_systemone/stacks.py` | CDK: `KevEcrStack` (repository), `KevSystemOneStack` (bucket, ingest, Lambda, API) |
| `lambdas/ingest/` | Hugging Face to S3 copy functions |
| `container/` | Inference image: CPU torch, `kev` pinned to a commit, `server.py` entry point |
| `.github/workflows/container.yml` | Builds the image and pushes it to ECR |
| `samples/choice_noul.py` | Choice, Noul and Score demo against the API |

## GitHub Actions

Repository variables: `AWS_ROLE_ARN` (assumed through OIDC), and optionally `AWS_REGION` (default `us-east-1`) and
`ECR_REPOSITORY` (default `kev-model-systemone-serverless`). The workflow pushes `:<git sha>` and `:latest`.

## Deploy

Requires `uv`, Node (CDK CLI) and an AWS profile. The image must exist before the Lambda stack is deployed.

```
uv sync
uv run cdk deploy KevEcrStack                      # skip if the ECR repository already exists
# push to main (or run the workflow manually) to build and push the image
uv run cdk deploy KevSystemOneStack -c imageTag=<git sha>
```

Context values: `ecrRepository`, `imageTag` (default `latest`), `adapterRepo` (`jaredpalmer/kev-0.8b`), `baseRepo`
(`Qwen/Qwen3.5-0.8B-Base`).

Copy the model to S3 (idempotent; prunes stale keys under `models/adapter/` and `models/base/`):

```
aws stepfunctions start-execution --state-machine-arn <IngestStateMachineArn> --input '{}'
```

The input can override `adapterRepo`, `adapterRevision`, `baseRepo` and `baseRevision`; revisions default to `main` and
are resolved to commit shas. Lambda reads the model at cold start, so redeploy or wait for old environments to recycle
after re-ingesting.

## Use

```
aws apigateway get-api-key --api-key <ApiKeyId> --include-value --query value --output text
KEV_API_URL=<ApiUrl without trailing slash> KEV_API_KEY=<key> uv run python samples/choice_noul.py
```

## Limits

- State is capped at 8,192 tokens (`MAX_STATE_TOKENS`), the length the model card validates. Longer states return 422.
  The CPU path uses eager attention with an L x L mask, so longer states would not fit in 10 GB.
- Cold start downloads about 1.8 GB from S3 and loads the model. This can exceed API Gateway's 29 s integration limit,
  so the first request after idle may return 504; retry. Provisioned concurrency avoids it at a standing cost.
- Latency on Lambda CPU has not been measured. On a local Docker Desktop container a three-question request took
  about 350 to 550 ms.
- The API key and usage plan (5 req/s, 1,000 req/day) are the only access control.

## Local test

```
docker build -t kev-systemone container
docker run -p 8080:8080 -e MODEL_DIR=/models -v "$PWD/.models:/models" kev-systemone   # .models/{adapter,base}
python samples/choice_noul.py
```

## Tests

```
uv run pytest
```

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
| `kev_systemone/stacks.py` | CDK: `KevSystemOneStack` (bucket, ingest, Lambda, API) |
| `lambdas/ingest/` | Hugging Face to S3 copy functions |
| `container/` | Inference image: CPU torch, `kev` pinned to a commit, `server.py` entry point |
| `.github/workflows/ci.yml` | Tests, builds and pushes the image, deploys the stack, runs the model ingest |
| `samples/choice_noul.py` | Choice, Noul and Score demo against the API |

## CI/CD

Everything runs from `.github/workflows/ci.yml` on push to `main` or manual dispatch (no local CDK commands):

1. `test`: `uv run pytest`.
2. `build-and-push`: creates the ECR repository if missing, then builds and pushes `container/` as
   `:<git tree hash of container/>` unless an image with that tag already exists, so commits that don't touch
   `container/` skip the build. Docker layers are cached in the GitHub Actions cache.
3. `deploy`: bootstraps CDK if `CDKToolkit` is absent, deploys `KevSystemOneStack` with `-c imageTag=<container tree hash>`, then
   runs the ingest state machine (idempotent: files already in S3 with the right size are skipped, stale keys are pruned)
   and waits for it. The job summary shows the API URL and API key id.

Repository variables: `AWS_ROLE_ARN` (assumed through OIDC), and optionally `AWS_REGION` (default `us-east-1`) and
`ECR_REPOSITORY` (default `kev-model-systemone-serverless`). The role needs ECR push and create-repository, CDK
bootstrap and deploy (CloudFormation, IAM, Lambda, API Gateway, S3, Step Functions, logs) and `states:StartExecution`
and `states:DescribeExecution` permissions.

CDK context values (`-c`): `ecrRepository`, `imageTag` (default `latest`), `adapterRepo` (`jaredpalmer/kev-0.8b`),
`baseRepo` (`Qwen/Qwen3.5-0.8B-Base`). The ingest input can override `adapterRepo`, `adapterRevision`, `baseRepo` and
`baseRevision`; revisions default to `main` and are resolved to commit shas. Lambda reads the model at cold start, so
old environments keep the previous model until they recycle.

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

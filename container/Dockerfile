FROM public.ecr.aws/docker/library/python:3.12-slim

# Lambda Web Adapter relays Lambda invocations (API Gateway events) to the HTTP server below.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.0 /lambda-adapter /opt/extensions/lambda-adapter

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    HF_HOME=/tmp/hf \
    HF_HUB_OFFLINE=1 \
    OMP_NUM_THREADS=6 \
    MKL_NUM_THREADS=6 \
    KEV_BACKEND=torch \
    KEV_PREFIX_MAX_TOKENS=8192 \
    AWS_LWA_PORT=8080 \
    AWS_LWA_ASYNC_INIT=true \
    AWS_LWA_READINESS_CHECK_PATH=/v1/models

WORKDIR /app

# CPU-only torch first, so the CUDA wheels are never pulled in.
RUN pip install "torch>=2.6,<2.9" --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

# kev.serve is used unchanged; its training-only dependencies are not needed to serve.
ARG KEV_REF=5e42a7a03f28134853dd3ff77461457e921e5ec1
RUN pip install --no-deps "https://github.com/jaredpalmer/kev/archive/${KEV_REF}.tar.gz"

COPY server.py .

# CI downloads the model from S3 into model/{adapter,base} before building. Last, so code changes keep this layer cached.
COPY model/ /opt/model/
RUN test -f /opt/model/adapter/head.pt && test -f /opt/model/base/config.json
ENV MODEL_DIR=/opt/model

CMD ["python", "server.py"]

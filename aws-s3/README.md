# AWS S3 compose/env bundle

This directory contains files that EC2 user_data downloads from S3.
Use `.env.template` for AWS deployment. The final `.env` is generated on the EC2 node from SSM Parameter Store values.

Upload target example:

```text
s3://trader-terraform-bucket/controller/docker-compose.yml
s3://trader-terraform-bucket/controller/.env.template
s3://trader-terraform-bucket/python-worker/docker-compose.yml
s3://trader-terraform-bucket/python-worker/.env.template
```

Launch Template user_data examples:

```text
controller/user-data-controller.sh
python-worker/user-data-python-worker.sh
```

Controller node:

- Runs the Go controller API.
- Runs scheduler and managed workers when enabled in DB.
- Publishes outbox events to Kafka through the managed outbox relay.
- Measures Kafka lag and can create worker scale commands.

Python worker node:

- Runs `workers.kafka_pipeline_consumer` for `trader.jobs.events`.
- Runs BLS, KIS, and SEC raw ETL consumers.
- Reports heartbeat to the controller.
- Stores local raw previews under `/app/pipeline_output` for the first AWS smoke test.

Before upload:

- Keep `.env.template` in S3, not the rendered `.env`.
- Replace `your-registry/...` image names with Docker Hub or ECR image names.
- Store secrets and changing addresses in SSM Parameter Store.

Required SSM parameters:

```text
/trader/prod/POSTGRES_USER
/trader/prod/POSTGRES_PASSWORD
/trader/prod/DB_HOST
/trader/prod/KAFKA_HOST
/trader/prod/ADMIN_API_KEY
/trader/prod/ADMIN_PASSWORD_HASH
/trader/prod/CONTROLLER_IMAGE
/trader/prod/WORKER_IMAGE
/trader/prod/CONTROLLER_HOST
```

Optional SSM parameters:

```text
/trader/prod/DB_PORT
/trader/prod/ADMIN_USERNAME
/trader/prod/AWS_REGION
/trader/prod/KIS_APPKEY
/trader/prod/KIS_APPSECRET
/trader/prod/KIS_ACCESS_TOKEN
/trader/prod/KIS_ACCESS_TOKEN_EXPIRED
/trader/prod/BLS_API_KEY
/trader/prod/SEC_USER_AGENT
```

Notes:

- The current controller Dockerfile includes AWS CLI. Image contents alone do not authorize scaling: keep capacity actuators disabled unless their infrastructure and permissions have been explicitly configured.
- `RAW_STORAGE_BACKEND=S3` now performs a conditional upload and reads the object back to verify its byte hash and canonical content hash before returning S3 source metadata. `LOCAL` remains available for the original smoke profile.

## Collection worker on the index/embedding host

Use [python-worker/docker-compose.shared.yml](python-worker/docker-compose.shared.yml)
with a private `shared.env` based on [shared.env.example](python-worker/shared.env.example).
The service is opt-in (`--profile collection`), one combined consumer, 512MiB and
0.5 vCPU. No separate Python EC2, EBS, extra ETL consumers or second embedding model
is required. The tmpfs is disposable cache; verified raw objects live in S3 and
job/lineage state lives in PostgreSQL/Kafka independently of this host.

Set `WORKER_SHARED_HOST=true` on every Go controller replica. It retains the
scheduler, outbox, job aggregation, heartbeat and Kafka health/lag functions while
excluding the capacity planner, local Docker actuator and AWS ASG actuator.
The Python heartbeat uses the existing `python-worker-node` logical target; its
node name identifies the shared host. Do not start the old dedicated worker or
split ETL consumers alongside this profile.

Before enabling collection, validate the intended DB, pending queue, provider
credentials/budgets, current STOP instructions, S3 prefix permissions, and cached
embedding readiness. SIGTERM stops admission and drains the current item; an
unconfirmed S3/SQL result stops consumption without committing its Kafka offset.
Do not configure blind restart of that failure. A spot interruption still needs
external node replacement and reconciliation; a durable queue is not an automatic
EC2 replacement mechanism. News collection has not been implemented by this change.

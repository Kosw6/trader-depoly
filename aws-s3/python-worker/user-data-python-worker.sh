#!/bin/bash
set -e
exec > /var/log/user-data.log 2>&1

apt-get update -y
apt-get install -y gettext-base

APP_DIR=/data/python-worker
mkdir -p "${APP_DIR}"

aws s3 sync s3://trader-terraform-bucket/python-worker/ "${APP_DIR}/"
cd "${APP_DIR}"

get_param() {
  aws ssm get-parameter \
    --name "$1" \
    --with-decryption \
    --query "Parameter.Value" \
    --output text
}

get_optional_param() {
  aws ssm get-parameter \
    --name "$1" \
    --with-decryption \
    --query "Parameter.Value" \
    --output text 2>/dev/null || true
}

POSTGRES_USER=$(get_param "/trader/prod/POSTGRES_USER")
POSTGRES_PASSWORD=$(get_param "/trader/prod/POSTGRES_PASSWORD")
DB_HOST=$(get_param "/trader/prod/DB_HOST")
DB_PORT=$(get_optional_param "/trader/prod/DB_PORT")
KAFKA_HOST=$(get_param "/trader/prod/KAFKA_HOST")
CONTROLLER_HOST=$(get_param "/trader/prod/CONTROLLER_HOST")

ADMIN_API_KEY=$(get_param "/trader/prod/ADMIN_API_KEY")
WORKER_IMAGE=$(get_param "/trader/prod/WORKER_IMAGE")

APPKEY=$(get_optional_param "/trader/prod/KIS_APPKEY")
APPSECRET=$(get_optional_param "/trader/prod/KIS_APPSECRET")
ACCESS_TOKEN=$(get_optional_param "/trader/prod/KIS_ACCESS_TOKEN")
ACCESS_TOKEN_TOKEN_EXPIRED=$(get_optional_param "/trader/prod/KIS_ACCESS_TOKEN_EXPIRED")
BLS_API_KEY=$(get_optional_param "/trader/prod/BLS_API_KEY")
SEC_USER_AGENT=$(get_optional_param "/trader/prod/SEC_USER_AGENT")

TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
INSTANCE_ID=$(curl -s \
  -H "X-aws-ec2-metadata-token: ${TOKEN}" \
  http://169.254.169.254/latest/meta-data/instance-id)

DB_PORT=${DB_PORT:-5432}
WORKER_NODE_NAME=${WORKER_NODE_NAME:-python-worker-node-${INSTANCE_ID}}

export POSTGRES_USER POSTGRES_PASSWORD DB_HOST DB_PORT KAFKA_HOST CONTROLLER_HOST
export ADMIN_API_KEY WORKER_IMAGE WORKER_NODE_NAME
export APPKEY APPSECRET ACCESS_TOKEN ACCESS_TOKEN_TOKEN_EXPIRED BLS_API_KEY SEC_USER_AGENT

envsubst < .env.template > .env

docker compose pull
docker compose up -d

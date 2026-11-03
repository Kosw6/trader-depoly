#!/bin/bash
set -e
exec > /var/log/user-data.log 2>&1

apt-get update -y
apt-get install -y gettext-base

APP_DIR=/data/controller
mkdir -p "${APP_DIR}"

aws s3 sync s3://trader-terraform-bucket/controller/ "${APP_DIR}/"
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

ADMIN_API_KEY=$(get_param "/trader/prod/ADMIN_API_KEY")
ADMIN_PASSWORD_HASH=$(get_param "/trader/prod/ADMIN_PASSWORD_HASH")
ADMIN_USERNAME=$(get_optional_param "/trader/prod/ADMIN_USERNAME")
CONTROLLER_IMAGE=$(get_param "/trader/prod/CONTROLLER_IMAGE")

AWS_REGION=$(get_optional_param "/trader/prod/AWS_REGION")

DB_PORT=${DB_PORT:-5432}
ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
AWS_REGION=${AWS_REGION:-ap-northeast-2}

export POSTGRES_USER POSTGRES_PASSWORD DB_HOST DB_PORT KAFKA_HOST
export ADMIN_API_KEY ADMIN_PASSWORD_HASH ADMIN_USERNAME CONTROLLER_IMAGE AWS_REGION

envsubst < .env.template > .env

docker compose pull
docker compose up -d


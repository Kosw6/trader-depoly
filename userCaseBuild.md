$env:APP_TARGET="prod"
docker compose --env-file .\.env -f docker-compose.dev.yml build

$env:APP_TARGET="prod"
docker compose --env-file .\.env -f docker-compose.dev.yml build

### db복원스크립트

pg_dump -h localhost -U postgres -d trader -Fc --no-owner --no-privileges -f trader.dump -N \_timescaledb_catalog

### 빌드 → 푸시(개발용)

#### Hub 로그인

docker login

#### 앱 이미지 빌드 (dev 파일 사용)

docker compose -f docker-compose.dev.yml --env-file .env build app

#### Hub로 푸시

docker compose -f docker-compose.dev.yml --env-file .env push app

### 풀 → 실행(배포용)

#### 서버/로컬 어디서든

docker login

#### 배포용 compose로 Hub에서 이미지 pull

docker compose --env-file .env pull app

#### 전체 기동 (db + app)

docker compose --env-file .env up -d

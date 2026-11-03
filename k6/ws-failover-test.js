/**
 * WebSocket Failover + Failback Test
 *
 * Scenario 1 (hold_session): 기존 세션 유지
 *   - A에 연결 후 계속 유지
 *   - A 다운 시 B로 failover → A 복구 후에도 B 유지 확인
 *
 * Scenario 2 (probe_new): 신규 연결 probe
 *   - 30초마다 새 연결 시도 후 15초 유지 → 종료
 *   - A 복구 후 신규 연결이 A로 돌아오는지 확인
 *
 * 테스트 순서:
 *   1. 스크립트 실행 → [HOLD] A 연결 확인
 *   2. docker stop <app-A 컨테이너>
 *   3. [HOLD] B로 failover 확인
 *   4. docker start <app-A 컨테이너> (복구 대기)
 *   5. [PROBE] 신규 연결이 A로 돌아오는지 확인
 *   6. [HOLD] 여전히 B 유지 확인
 *
 * 실행:
 *   k6 run \
 *     -e GATEWAY=http://10.0.1.181:8080 \
 *     -e BASE_URL=http://10.0.1.125:8080 \
 *     -e LOGIN_ID=yourId \
 *     -e LOGIN_PW=yourPw \
 *     -e USER_ID=116 \
 *     -e GROUP_ID=1 -e TEAM_ID=1 -e GRAPH_ID=1 \
 *     ws-failover-test.js
 */

import ws from 'k6/ws';
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';

// ── 설정 ──────────────────────────────────────────────────────────────────────
const GATEWAY  = __ENV.GATEWAY  || 'http://10.0.1.181:8080';
const BASE_URL = __ENV.BASE_URL || 'http://10.0.1.125:8080';
const LOGIN_ID = __ENV.LOGIN_ID || 'testuser';
const LOGIN_PW = __ENV.LOGIN_PW || 'password';

const GROUP_ID  = __ENV.GROUP_ID  || '1';
const TEAM_ID   = __ENV.TEAM_ID   || '1';
const GRAPH_ID  = __ENV.GRAPH_ID  || '1';
const NICK_NAME = __ENV.NICK_NAME || 'k6-tester';

const HEARTBEAT_MS       = 3000;
const HOLD_MAX_SEC       = 600;  // hold_session 단일 연결 최대 유지 시간
const PROBE_HOLD_SEC     = 15;   // probe_new 연결 후 유지 시간
const PROBE_INTERVAL_SEC = 30;   // probe_new 연결 간격

// ── 메트릭 ────────────────────────────────────────────────────────────────────
const holdReconnectCount = new Counter('hold_reconnect_count');
const holdInstanceChange = new Counter('hold_instance_change');
const holdReconnectLat   = new Trend('hold_reconnect_latency_ms');
const probeConnectLat    = new Trend('probe_connect_latency_ms');
const probeInstanceChange = new Counter('probe_instance_change');

export const options = {
    scenarios: {
        hold_session: {
            executor: 'constant-vus',
            vus: 1,
            duration: '10m',
            exec: 'holdSession',
        },
        probe_new: {
            executor: 'constant-vus',
            vus: 1,
            duration: '10m',
            exec: 'probeNew',
        },
    },
    thresholds: {
        hold_reconnect_latency_ms: ['p(95)<5000'],
        probe_connect_latency_ms:  ['p(95)<5000'],
    },
};

// ── 공통 함수 ─────────────────────────────────────────────────────────────────
function login() {
    const res = http.post(
        `${BASE_URL}/api/login/signin`,
        JSON.stringify({ loginId: LOGIN_ID, password: LOGIN_PW }),
        { headers: { 'Content-Type': 'application/json' } }
    );
    check(res, { 'login 200': (r) => r.status === 200 });
    if (res.status !== 200) throw new Error(`로그인 실패 status=${res.status}`);

    const parts = [];
    for (const [name, arr] of Object.entries(res.cookies || {})) {
        if (arr && arr[0]?.value) parts.push(`${name}=${arr[0].value}`);
    }
    const cookie = parts.join('; ');
    if (!cookie) throw new Error('accessToken 쿠키 없음');
    return cookie;
}

function fetchWsRoute(userId, label) {
    const url = `${GATEWAY}/internal/ws-route` +
        `?groupId=${GROUP_ID}&teamId=${TEAM_ID}&graphId=${GRAPH_ID}` +
        `&userId=${userId}&nickName=${NICK_NAME}`;

    const res = http.get(url, { timeout: '5s' });
    const ok = check(res, { [`[${label}] ws-route 200`]: (r) => r.status === 200 });
    if (!ok) {
        console.error(`[${label}][ROUTE] failed status=${res.status} body=${res.body}`);
        return null;
    }
    const route = JSON.parse(res.body);
    console.log(`[${label}][ROUTE] instanceId=${route.selectedInstanceId}`);
    return route;
}

// ── setup: 로그인 1회 ─────────────────────────────────────────────────────────
export function setup() {
    const cookie = login();
    const userId = __ENV.USER_ID || '1';
    return { cookie, userId };
}

// ── Scenario 1: 기존 세션 유지 ────────────────────────────────────────────────
// A 다운 → B failover 후, A 복구 시에도 B에 남아 있음을 확인
export function holdSession(data) {
    let { cookie, userId } = data;
    let lastInstanceId  = null;
    let connectionIndex = 0;

    while (true) {
        const route = fetchWsRoute(userId, 'HOLD');
        if (!route) { sleep(2); continue; }

        const currentInstanceId = route.selectedInstanceId;
        connectionIndex++;

        if (lastInstanceId !== null && lastInstanceId !== currentInstanceId) {
            holdInstanceChange.add(1);
            console.log(`[HOLD][FAILOVER] ${lastInstanceId} → ${currentInstanceId}`);
        }

        const connectAt = Date.now();

        const res = ws.connect(route.wsUrl, { headers: { Cookie: cookie } }, function (socket) {
            socket.on('open', () => {
                const latency = Date.now() - connectAt;
                console.log(`[HOLD][WS #${connectionIndex}] connected instance=${currentInstanceId} latency=${latency}ms`);

                if (connectionIndex > 1) {
                    holdReconnectCount.add(1);
                    holdReconnectLat.add(latency);
                }

                lastInstanceId = currentInstanceId;

                socket.setInterval(() => {
                    socket.send(JSON.stringify({
                        type: 'CURSOR',
                        teamId: Number(TEAM_ID),
                        graphId: Number(GRAPH_ID),
                        userId: Number(userId),
                        nickName: NICK_NAME,
                        x: 0, y: 0,
                        sentAt: Date.now(),
                    }));
                }, HEARTBEAT_MS);

                socket.setTimeout(() => socket.close(), HOLD_MAX_SEC * 1000);
            });

            socket.on('close', (code) => {
                console.log(`[HOLD][WS #${connectionIndex}] closed code=${code} instance=${currentInstanceId}`);
                if (code === 1008 || code === 4001) {
                    try { cookie = login(); } catch (e) { console.error(e); }
                }
            });

            socket.on('error', (e) => {
                console.error(`[HOLD][WS #${connectionIndex}] error=${e.error()}`);
            });
        });

        check(res, { '[HOLD] ws handshake 101': (r) => r && r.status === 101 });
        sleep(1);
    }
}

// ── Scenario 2: 신규 연결 probe ───────────────────────────────────────────────
// 30초마다 새 연결 → A 복구 후 신규 연결이 A로 돌아오는지 확인
export function probeNew(data) {
    let { cookie, userId } = data;
    let lastInstanceId = null;
    let probeIndex = 0;

    while (true) {
        const route = fetchWsRoute(userId, 'PROBE');
        if (!route) { sleep(5); continue; }

        const currentInstanceId = route.selectedInstanceId;
        probeIndex++;

        if (lastInstanceId !== null && lastInstanceId !== currentInstanceId) {
            probeInstanceChange.add(1);
            console.log(`[PROBE #${probeIndex}] instance changed: ${lastInstanceId} → ${currentInstanceId} ← 신규 연결 라우팅 변경`);
        } else {
            console.log(`[PROBE #${probeIndex}] instance=${currentInstanceId} (유지)`);
        }

        const connectAt = Date.now();

        ws.connect(route.wsUrl, { headers: { Cookie: cookie } }, function (socket) {
            socket.on('open', () => {
                const latency = Date.now() - connectAt;
                console.log(`[PROBE #${probeIndex}] connected instance=${currentInstanceId} latency=${latency}ms`);
                probeConnectLat.add(latency);
                lastInstanceId = currentInstanceId;

                // 짧게 유지 후 종료 — 신규 연결 라우팅 확인이 목적
                socket.setTimeout(() => socket.close(), PROBE_HOLD_SEC * 1000);
            });

            socket.on('close', (code) => {
                console.log(`[PROBE #${probeIndex}] closed code=${code} instance=${currentInstanceId}`);
                if (code === 1008 || code === 4001) {
                    try { cookie = login(); } catch (e) { console.error(e); }
                }
            });

            socket.on('error', (e) => {
                console.error(`[PROBE #${probeIndex}] error=${e.error()}`);
            });
        });

        // 다음 probe까지 대기 (PROBE_HOLD_SEC 동안 연결 유지 후 여기에 도달)
        sleep(PROBE_INTERVAL_SEC);
    }
}

// ── 요약 ──────────────────────────────────────────────────────────────────────
export function handleSummary(data) {
    const holdReconnects = data.metrics['hold_reconnect_count']?.values?.count ?? 0;
    const holdChg        = data.metrics['hold_instance_change']?.values?.count ?? 0;
    const holdP95        = data.metrics['hold_reconnect_latency_ms']?.values?.['p(95)'] ?? 0;
    const probeChg       = data.metrics['probe_instance_change']?.values?.count ?? 0;
    const probeP95       = data.metrics['probe_connect_latency_ms']?.values?.['p(95)'] ?? 0;

    console.log('=== Failover + Failback Test Summary ===');
    console.log(`[HOLD]  재연결 횟수         : ${holdReconnects}`);
    console.log(`[HOLD]  인스턴스 변경 횟수  : ${holdChg}`);
    console.log(`[HOLD]  재연결 p95 지연      : ${holdP95.toFixed(0)}ms`);
    console.log(`[PROBE] 인스턴스 변경 횟수  : ${probeChg}  ← A 복구 후 신규 연결 전환 횟수`);
    console.log(`[PROBE] 신규연결 p95 지연   : ${probeP95.toFixed(0)}ms`);

    return {};
}

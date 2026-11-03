# SSM 관리 접속망 수동 Lambda 스위치

기존 서울 VPC의 `ssm`·`ssmmessages` Interface 엔드포인트 두 개만 제어한다. EC2를 켜거나 끄지 않는다. S3 Gateway 엔드포인트는 제어 대상이 아니다.

## AWS 콘솔에서 버튼으로 사용

[Lambda 테스트 화면 열기](https://ap-northeast-2.console.aws.amazon.com/lambda/home?region=ap-northeast-2#/functions/trader-ssm-endpoint-switch644?tab=testing)

AWS에 로그인한 뒤 테스트 이벤트를 다음 이름으로 각각 저장한다. 사용할 이벤트를 선택하고 **테스트** 버튼을 누른다. 서비스 관리자 화면의 별도 버튼은 아직 연결하지 않았다.

| 저장할 이벤트 이름 | 이벤트 JSON | 의미 |
|---|---|---|
| 상태 확인 | `{"action":"status"}` | 두 엔드포인트 상태와 `ready`·`off` 조회 |
| 끄기 미리보기 | `{"action":"off","dryRun":true}` | 삭제 대상과 EC2·SSM 세션 보호 조건 조회. 삭제하지 않음 |
| SSM 켜기 | `{"action":"on","dryRun":false}` | 저장한 서브넷·보안그룹·정책·Private DNS 설정으로 누락된 엔드포인트 생성 |
| SSM 끄기 | `{"action":"off","dryRun":false,"confirm":"DELETE_SSM_ENDPOINTS"}` | 보호 조건 통과 후 정확한 두 엔드포인트 삭제 요청 |

`dryRun`을 생략하면 기본값은 `true`다. `PREVIEW_ONLY`는 변경 완료가 아니다.

## 사용할 순서

1. 관리 접속이 필요하면 **SSM 켜기**를 실행한다.
2. **상태 확인**에서 `ready:true`와 두 서비스의 `available`을 확인한 뒤 SSM·DB 터널을 사용한다. 생성 직후 `CREATE_REQUESTED`는 준비 완료가 아니다.
3. 사용을 마치면 기존 작업과 SSM 세션을 종료하고 EC2를 정상 중지한다.
4. **끄기 미리보기**를 확인한 뒤 **SSM 끄기**를 실행한다.
5. **상태 확인**에서 `off:true`를 확인한다. 삭제 요청 직후에는 `deleting`일 수 있다.

삭제 후 재생성하면 엔드포인트 ID와 ENI IP가 달라진다. Private DNS의 AWS 서비스 이름으로 연결하는 현재 구성은 보존하되, 다른 코드가 예전 ID·ENI IP·개별 엔드포인트 DNS를 고정해 사용한다면 먼저 갱신해야 한다. 실제 삭제·재생성 왕복 검증은 이번 배포에서 실행하지 않았다.

## 보호 조건과 범위

- 삭제는 해당 VPC의 EC2가 모두 `stopped` 또는 `terminated`이며, 해당 인스턴스의 활성 SSM 세션이 없을 때만 허용한다. `stopping`도 차단한다.
- 다른 경로에서 EC2를 시작하는 동작까지 원자적으로 잠그지는 못한다. EC2 시작 버튼과 SSM 끄기를 동시에 실행하지 않는다.
- 현재 설정이 보관본과 다르거나 같은 서비스가 중복되면 변경을 차단한다. 두 서비스 모두 먼저 점검해 첫 번째만 임의로 변경하지 않도록 한다.
- 원래 정확한 두 ID 또는 이 스위치가 생성한 것으로 식별되는 엔드포인트만 선택한다. 재생성할 때 기존 태그를 보존하고 관리 태그를 추가한다.
- VPC 밖의 Lambda가 AWS 제어 API를 호출한다. 엔드포인트가 없어도 다시 생성 요청을 할 수 있다.
- 호출은 AWS IAM 인증을 사용하는 Lambda Invoke뿐이다. 공개 Function URL·API Gateway·자동 스케줄은 생성하지 않았다.
- DynamoDB 조건부 쓰기로 실제 변경 호출을 직렬화한다. 다른 호출이 처리 중이면 `ANOTHER_SWITCH_OPERATION_IN_PROGRESS`로 차단한다. 소유 토큰으로 해제하며, Lambda가 강제 종료되면 최대 5분 후 다시 시도할 수 있다.
- `ERROR`·부분 실패·시간 초과는 완료로 세지 않는다. 상태를 다시 읽고 원인을 확인한다. KIS·SQL·EC2 제어 권한은 없다.

## 구성과 비용

- Lambda Python 3.12, 256MB, 최대 90초. 상시 실행·Provisioned Concurrency 없음. 실제 SDK 동시 로딩에서 128MB 메모리 부족이 확인돼 256MB로 조정하고 클라이언트를 재사용한다.
- DynamoDB 단일 잠금 테이블, PAY_PER_REQUEST. 원문·질문·API 키를 저장하지 않는다.
- CloudWatch 로그 보존 7일. 이벤트·엔드포인트 정책·자격증명은 로그에 출력하지 않는다.
- Lambda는 요청 수와 실행 시간, 잠금은 쓰기 사용량에 따라 과금된다. 소량 수동 호출의 추가 요금은 작지만 무료 한도 공유 사용량과 로그 요금은 별도다.
- 엔드포인트를 **실제로 삭제한 시간**부터 엔드포인트 시간 비용이 줄어든다. 이 Lambda를 배포하는 것만으로 절감되지는 않는다.
- 기존 단가 기준으로 두 개를 하루 2시간 유지하면 상시 유지 대비 월 약 25,300원 절감 예시다. 30일·환율 1,340원·부가세 10% 기준이며 생성·삭제 시간과 시간 단위 올림 과금으로 실제 금액은 달라진다.

## 배포·검증 위치

- `handler.py`: 제어 로직.
- `build.py`: 읽기 보관본에서 CloudFormation 템플릿 생성. 서브넷·보안그룹·서비스 범위를 고정한 실행 역할 포함.
- `test_handler.py`: 상태/미리보기, 중복 생성 방지, 잘못된 입력, 삭제 보호, 설정 변경, 부분 실패, 잠금 충돌/해제 검증.
- 로컬 증거: `output/ssm-switch644-20261029/`의 보관본·템플릿·테스트 결과·실제 Lambda 조회/미리보기 영수증. 기존 엔드포인트 정책 등이 들어 있어 공개 저장소에 올리지 않는다.

첫 배포는 계정의 미예약 동시 실행 최소 한도 때문에 Reserved Concurrency 1이 거절돼 롤백됐다. 이번 배포가 만든 리소스의 롤백을 확인하고 빈 실패 스택 기록을 제거한 뒤 DynamoDB 잠금 구성으로 배포했다.

공식 근거: [Lambda의 기본 네트워크](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc-internet.html), [PrivateLink 요금](https://aws.amazon.com/privatelink/pricing/), [Lambda 요금](https://aws.amazon.com/lambda/pricing/), [EC2 IAM 권한 범위](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html).

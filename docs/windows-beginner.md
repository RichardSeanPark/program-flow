# Program Flow를 처음 사용하는 방법입니다.

KRX·NXT의 종목별 프로그램 순매수 흐름을 확인하는 Windows 프로그램입니다. 주식을 주문하는 기능은 없습니다. 아래 순서대로 설치하고 본인의 키움 API 키를 연결하면 됩니다.

## 1. 설치 파일 하나를 내려받습니다.

[ProgramFlow-Setup-0.2.6-x64.exe 다운로드](https://github.com/RichardSeanPark/program-flow/releases/download/v0.2.6/ProgramFlow-Setup-0.2.6-x64.exe)를 클릭합니다.

1. 받은 EXE 파일을 더블클릭합니다.
2. 설치 화면의 안내에 따라 설치합니다. 바탕화면 아이콘이 필요하면 해당 항목을 선택합니다.
3. 시작 메뉴 또는 바탕화면의 **Program Flow**를 실행합니다.
4. 브라우저에 프로그램 화면이 열리면 다음 단계로 진행합니다.

Windows 10·11 64비트용입니다. Python이나 WSL을 따로 설치할 필요가 없습니다. 일반 사용자는 Source 파일이나 Portable 파일을 추가로 받을 필요가 없습니다.

설치 파일은 코드 서명이 되어 있지 않아 Windows 확인 화면이 나올 수 있습니다. 배포 주소와 파일명을 확인해야 합니다. 회사 PC의 실행 제한은 해당 PC의 보안 정책에 따라 확인해야 합니다.

## 2. 키움 REST API 사용을 신청합니다.

키움증권 계좌가 필요합니다. 프로그램을 사용할 PC에서 [키움 REST API 공식 이용안내](https://openapi.kiwoom.com/intro/serviceInfo)를 엽니다.

1. 오른쪽 위의 **API 사용신청**을 누르고 본인 계정으로 로그인합니다.
2. 약관과 안내를 확인하고 신청을 완료합니다.

아래 이미지는 키움 공식 안내 화면입니다. 이미지를 누르면 원본 크기로 확인할 수 있습니다.

[![키움 홈페이지 오른쪽 위 API 사용신청 위치입니다.](https://openapi.kiwoom.com/resources/portal/images/temp/temp_Intro0201_01.png?20250515=)](https://openapi.kiwoom.com/resources/portal/images/temp/temp_Intro0201_01.png?20250515=)

[![키움 REST API 사용 신청 화면입니다.](https://openapi.kiwoom.com/resources/portal/images/temp/temp_Intro0201_03.png?20250515=)](https://openapi.kiwoom.com/resources/portal/images/temp/temp_Intro0201_03.png?20250515=)

## 3. 사용할 PC의 외부 IP를 등록합니다.

신청 화면의 **계좌 App Key 관리** 탭을 엽니다. 이 프로그램은 실제 투자용 API 서버에 연결하므로 모의투자 탭에서 발급한 키와 혼동하지 않아야 합니다.

1. **현재 나의 IP** 옆 숫자를 확인합니다.
2. 그 숫자를 **IP 주소등록** 칸에 입력합니다.
3. **추가**를 누릅니다.
4. **IP 등록현황**에 같은 주소가 나타나는지 확인합니다.

[![계좌 App Key 관리에서 현재 나의 IP와 입력 칸을 확인하는 화면입니다.](https://openapi.kiwoom.com/resources/portal/images/temp/temp_Intro0201_05.png?20250515=)](https://openapi.kiwoom.com/resources/portal/images/temp/temp_Intro0201_05.png?20250515=)

[![추가한 IP가 등록현황에 표시된 화면입니다.](https://openapi.kiwoom.com/resources/portal/images/temp/temp_Intro0201_06.png?20250515=)](https://openapi.kiwoom.com/resources/portal/images/temp/temp_Intro0201_06.png?20250515=)

**외부 IP는 인터넷에서 이 PC의 접속을 구분하는 주소입니다.** 위 화면의 ‘현재 나의 IP’를 사용하면 별도 명령어를 입력할 필요가 없습니다. `127.0.0.1`, `192.168.x.x` 같은 PC 내부 주소나 브라우저의 포트 번호를 등록하는 것이 아닙니다.

집·사무실·휴대전화 핫스팟을 바꾸거나 VPN을 켜면 접속 IP가 달라질 수 있습니다. 사용 환경이 바뀌어 연결이 안 되면 현재 나의 IP와 등록현황을 다시 비교해야 합니다. 다른 PC에서 사용할 때도 그 PC에서 확인한 외부 IP를 등록해야 합니다. 같은 공유기를 사용하는 PC는 외부 IP가 같을 수 있습니다.

## 4. 계좌를 등록하고 두 개의 키를 받습니다.

IP 등록 후 아래의 **계좌 등록하기**를 누릅니다. 계좌 확인과 문자 인증을 진행하고 등록을 마칩니다.

[![계좌를 등록하는 공식 화면입니다.](https://openapi.kiwoom.com/resources/portal/images/temp/temp_Intro0201_07.png?20250515=)](https://openapi.kiwoom.com/resources/portal/images/temp/temp_Intro0201_07.png?20250515=)

등록된 계좌 행에서 **App Key와 App Secret**을 각각 내려받습니다. 받은 두 텍스트 파일을 열어 값을 확인합니다. 공식 안내상 다운로드는 한 번만 가능하므로 두 파일을 안전하게 보관해야 합니다.

[![계좌 등록 후 App Key와 App Secret을 내려받는 위치입니다.](https://openapi.kiwoom.com/resources/portal/images/temp/temp_Intro0201_13.png?20250515=)](https://openapi.kiwoom.com/resources/portal/images/temp/temp_Intro0201_13.png?20250515=)

계좌 비밀번호나 SMS 인증번호를 Program Flow에 입력하는 것이 아닙니다. 다음 단계에서 사용하는 것은 **App Key와 App Secret의 값**입니다. 두 키를 카페 글·댓글·쪽지나 화면 캡처에 노출하면 안 됩니다.

## 5. Program Flow에 키를 연결합니다.

1. Program Flow의 오른쪽 위 **설정 아이콘** 또는 왼쪽의 **연결 설정**을 누릅니다.
2. **App Key** 칸에 앱 키의 값을 붙여넣습니다.
3. **App Secret** 칸에 시크릿 키의 값을 붙여넣습니다.
4. **연결 확인 후 저장**을 누릅니다.

파일명이나 파일 전체 설명이 아니라 각 파일에 들어 있는 키의 값을 입력해야 합니다. 두 값을 서로 반대로 넣거나 앞뒤에 공백을 넣지 않아야 합니다. 토큰은 프로그램에서 처리하므로 별도로 발급 코드를 작성할 필요가 없습니다.

![실제 프로그램의 API 연결 화면입니다. 키를 입력하지 않은 화면입니다.](https://raw.githubusercontent.com/RichardSeanPark/program-flow/main/docs/images/api-settings.png)

## 6. 종목을 선택하고 흐름을 확인합니다.

1. **분석 종목** 칸에 종목명을 입력합니다.
2. 아래에 나오는 검색 결과에서 원하는 종목을 클릭합니다.
3. **거래일**을 선택합니다.
4. **NXT 오전·KRX 정규장·NXT 오후** 중 보고 싶은 카드를 누릅니다.

선택한 구간의 순매수 누적을 그래프로 확인할 수 있습니다. 아래 표에서는 매수·매도·순매수 누적을 확인할 수 있으며 금액 단위는 억원입니다. 현재 종목의 오늘 데이터는 프로그램 실행 중 약 60초 간격으로 수집합니다. 매 체결마다 갱신하는 틱 단위 화면은 아닙니다.

브라우저를 닫더라도 작업표시줄 알림 영역의 Program Flow가 실행 중이면 수집합니다. 완전히 종료하려면 알림 영역의 아이콘 메뉴에서 **종료**를 선택합니다. PC 종료나 절전 상태에서는 수집하지 않습니다.

## 7. 연결이 안 되면 아래 순서로 확인합니다.

| 증상입니다. | 확인할 내용입니다. |
| --- | --- |
| 키 저장에 실패합니다. | App Key·App Secret을 바꿔 넣지 않았는지, 앞뒤 공백이 없는지 확인합니다. |
| 어제는 됐는데 오늘은 연결되지 않습니다. | 키움의 현재 나의 IP와 등록현황을 비교합니다. 키의 유효 상태도 확인합니다. |
| 모의투자 키를 넣었습니다. | 계좌 App Key 관리에서 발급한 실제 투자용 키를 사용합니다. |
| 검색해도 조회되지 않습니다. | API 연결을 확인한 뒤 검색 결과에서 종목을 선택합니다. |
| 숫자가 ‘—’로 표시됩니다. | 해당 종목·거래일·시장에 데이터가 있는지 확인합니다. NXT 오후는 기준 관측값이 없을 때도 ‘—’로 표시합니다. |
| 다시 실행했는데 기존 자료가 안 보입니다. | 같은 브라우저 프로필인지 확인합니다. 쿠키를 지우면 기존 자료에 접근하지 못할 수 있습니다. |

## 8. 소스코드와 라이선스를 확인할 수 있습니다.

[전체 소스코드는 GitHub에 공개되어 있습니다.](https://github.com/RichardSeanPark/program-flow) 앱 소스는 [MIT 라이선스](https://github.com/RichardSeanPark/program-flow/blob/main/LICENSE)이며 저작권과 라이선스 고지를 유지하면 무료 사용·수정·재배포가 가능합니다. 포함된 폰트와 외부 라이브러리는 각자의 라이선스를 따릅니다. 키움 API 이용 조건은 별도로 적용됩니다.

무설치 버전은 [Portable ZIP](https://github.com/RichardSeanPark/program-flow/releases/download/v0.2.6/ProgramFlow-Portable-0.2.6-x64.zip)을 전부 풀어 사용합니다. EXE 옆의 `program_flow`와 `_internal` 폴더를 함께 보관해야 합니다. EXE 하나만 따로 옮기면 실행되지 않습니다.

키움 화면은 [키움 공식 이용안내](https://openapi.kiwoom.com/intro/serviceInfo)의 이미지를 연결한 것입니다. 해당 화면의 권리는 키움증권에 있으며 앱의 MIT 라이선스 적용 대상이 아닙니다.

## 실행한 메인화면입니다.

아래는 실제 Windows 프로그램에 접속해 촬영한 메인화면입니다. API 키 연결 전이므로 수급 숫자와 그래프는 아직 표시되지 않은 상태입니다.

![Program Flow를 실제 실행한 메인화면입니다. API 키 연결 전 상태입니다.](https://raw.githubusercontent.com/RichardSeanPark/program-flow/main/docs/images/main-screen.png)

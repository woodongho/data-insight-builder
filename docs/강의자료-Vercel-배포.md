# 🚀 강의자료: GitHub + Vercel로 AI Data Insight Builder 배포하기

수업용 공개 주소는 무료 `https://xxxx.vercel.app` 을 사용합니다.  
**커스텀 도메인은 구매하지 않으며, 결제도 진행하지 않습니다.**

- 대상 저장소: [woodongho/data-insight-builder](https://github.com/woodongho/data-insight-builder)
- 비밀번호: 환경 변수로 지정한 임의의 4자리 숫자 (예: `1234`)

---

## 1. 배포 아키텍처 개요

```text
[Local]   Python + Flask (data-insight-builder)
    ↓ Git
[GitHub]  Repository (woodongho/data-insight-builder)
    ↓ git push (브랜치: main)
[Vercel]  서버리스 빌드 & 배포 (Python Zero-Config)
    ↓
[Internet] https://xxxx.vercel.app (4자리 PIN 게이트키퍼 보호)
```

| 개념 | 역할 및 설명 |
| :--- | :--- |
| **Git / GitHub** | 버전 관리 및 원격 코드 저장소 |
| **Vercel** | 무료 클라우드 호스팅 (PaaS, 서버리스 구동) |
| **4자리 PIN (`SITE_PASSWORD`)** | 미인가 사용자의 Gemini API 무단 호출 및 토큰 과소비 방지 |
| **환경 변수** | `GEMINI_API_KEY`, `SITE_PASSWORD`, `SECRET_KEY` 등 비밀 정보 격리 |

---

## 2. Vercel 배포 실습 순서

### 2-1. Vercel 가입 및 로그인
1. [https://vercel.com](https://vercel.com) 접속
2. **Continue with GitHub** 으로 가입/로그인 (GitHub 저장소 import 권한 자동 연동)

### 2-2. 프로젝트 생성 (Import)
1. Vercel 대시보드에서 **Add New… → Project** 클릭
2. GitHub 저장소 목록에서 `data-insight-builder` 찾은 후 **Import** 클릭
3. 설정 확인:
   - **Framework Preset**: `Other`
   - **Root Directory**: `./` (기본값 빈칸)

### 2-3. 프로덕션 브랜치 확인
- 이 저장소의 기본 브랜치는 **`main`** 입니다.
- 프로젝트 **Settings → Git** 또는 **Branch Tracking**에서 Production Branch가 **`main`** 인지 확인합니다.

### 2-4. 환경 변수(Environment Variables) 등록
프로젝트 생성 화면 또는 **Settings → Environment Variables**에서 다음 변수를 추가합니다:

| KEY | VALUE | 설명 | 필수 여부 |
| :--- | :--- | :--- | :--- |
| `GEMINI_API_KEY` | Google AI Studio에서 발급받은 키 | Gemini LLM 호출용 | **필수** |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | 기본 AI 모델명 | 선택 (기본값 적용됨) |
| `SITE_PASSWORD` | 임의의 4자리 숫자 (예: `1234`) | 4자리 화면 입장 비밀번호 | **필수** |
| `SECRET_KEY` | 영문·숫자 조합 긴 임의 문자열 | 세션 쿠키 HMAC 서명 키 | **필수** |
| `MAX_UPLOAD_MB` | `10` | CSV 최대 업로드 용량 | 선택 (기본값 10) |

> ⚠️ **주의**: 환경 변수를 저장하거나 수정한 후에는 반드시 **Deployments → 최신 배포 ⋯ → Redeploy**를 눌러야 실제 사이트에 반영됩니다.

### 2-5. 배포 확인 및 접속
1. **Deploy** 버튼 클릭 후 약 1~2분 대기
2. 빌드 완료 후 제공되는 도메인(`https://data-insight-builder-xxxx.vercel.app`)으로 접속
3. **수업용 입장 비밀번호 4자리** 입력 후 잠금 해제 확인

---

## 3. 자주 겪는 문제 및 해결법 (Troubleshooting)

| 증상 | 원인 | 조치 방법 |
| :--- | :--- | :--- |
| **사이트 접속 시 4자리 비밀번호가 안 맞음** | `SITE_PASSWORD` 환경 변수 미입력 또는 오타 | Vercel Environment Variables에서 설정한 비밀번호 확인 후 Redeploy |
| **질문하기/보고서 생성 시 API Key 오류** | `GEMINI_API_KEY` 환경 변수 누락 | Google AI Studio 키를 Vercel 환경 변수에 추가 후 Redeploy |
| **깃 푸시를 했는데 사이트가 안 바뀜** | Production Branch 불일치 (`main` vs `master`) | Vercel Settings → Git에서 Production 브랜치를 `main`으로 변경 |
| **CSV 분석 중 갑자기 세션이 끊김** | Vercel 서버리스 10초 타임아웃 | 무료 티어 제한이므로 데이터 용량이 너무 크지 않은 파일 사용 권장 |

---

## 4. 최종 체크리스트

- [ ] GitHub `main` 브랜치에 최신 코드 커밋 및 푸시 완료
- [ ] Vercel 프로젝트 생성 시 `data-insight-builder` Import
- [ ] `GEMINI_API_KEY`, `SITE_PASSWORD`, `SECRET_KEY` 등록 완료
- [ ] 배포 완료 후 `https://xxxx.vercel.app` 에서 설정한 비밀번호 입력하여 정상 입장

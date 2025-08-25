# Chatbot Frontend

Next.js, TypeScript, Tailwind CSS로 구현된 챗봇 프론트엔드 애플리케이션입니다.

## 기능

- 파일 업로드 및 관리
- 파일 내용 조회
- 마크다운 렌더링
- 질문-답변 채팅 인터페이스
- 문서 요약 기능
- 반응형 디자인

## 기술 스택

- **프레임워크**: Next.js 14
- **언어**: TypeScript
- **스타일링**: Tailwind CSS
- **HTTP 클라이언트**: Axios
- **마크다운 렌더링**: react-markdown, remark-gfm
- **파일 업로드**: react-dropzone
- **코드 하이라이팅**: react-syntax-highlighter

## 시작하기

### 환경 설정

1. 프로젝트 루트에 `.env.local` 파일을 생성하고 다음 내용을 추가합니다:

```
NEXT_PUBLIC_API_URL=http://localhost:8503
```

### 설치

```bash
npm install
```

### 개발 서버 실행

```bash
npm run dev
```

### 빌드

```bash
npm run build
```

### 프로덕션 서버 실행

```bash
npm start
```

## 프로젝트 구조

```
frontend/
├── public/
├── src/
│   ├── components/      # 재사용 가능한 UI 컴포넌트
│   ├── hooks/           # 커스텀 React 훅
│   ├── lib/             # 유틸리티 함수 및 API 클라이언트
│   ├── pages/           # Next.js 페이지
│   └── styles/          # 전역 스타일
├── .env.local           # 환경 변수
├── package.json
├── tailwind.config.js
└── tsconfig.json
```

## 백엔드 연동

이 프론트엔드는 FastAPI 백엔드와 통신하도록 설계되었습니다. 백엔드는 기본적으로 포트 8503에서 실행되어야 합니다.

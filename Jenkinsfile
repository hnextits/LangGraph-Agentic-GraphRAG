pipeline {
    agent any
    
    parameters {
        choice(
            name: 'ACTION',
            choices: [
                'TEST_SERVER_START',    // 테스트 서버 실행
                'TEST_SERVER_STOP',     // 테스트 서버 중지
                'PROD_DEPLOY',          // 운영서버 배포
                'PROD_RESTART',         // 운영서버 재시작
                'PROD_START',           // 운영서버 실행
                'PROD_STOP'             // 운영서버 중지
            ],
            description: 'Select action to perform'
        )
        booleanParam(
            name: 'AUTO_DEPLOY_TEST', 
            defaultValue: false, 
            description: 'Auto deploy to test server (for DEV branch commits)'
        )
    }

    environment {
        // 테스트 서버 정보
        TEST_SERVER = '127.0.0.1'
        TEST_PORT = '2226'
        TEST_USER = 'nextits_test'
        TEST_WORKSPACE = '/home/nextits_test/workspace/quantas'
        
        // 테스트 서버 포트 범위
        TEST_FRONTEND_PORT_MIN = '6007'
        TEST_FRONTEND_PORT_MAX = '6012'
        TEST_BACKEND_PORT_MIN = '5007'
        TEST_BACKEND_PORT_MAX = '5012'
        
        // 운영 서버 정보
        PROD_SERVER = '127.0.0.1' // 실제 운영 서버로 변경 필요
        PROD_PORT = '2227' // 실제 운영 서버 포트로 변경 필요
        PROD_USER = 'nextits_test' // 실제 운영 서버 사용자로 변경 필요
        PROD_WORKSPACE = '/home/nextits4/workspace/quantas-prod'
        PROD_BACKEND_PORT = '7010'
        PROD_FRONTEND_PORT = '7009'
        
        // Conda 환경명 설정
        CONDA_ENV_PREFIX = 'test_server'       // 기본 접두사
        TEST_CONDA_ENV_SUFFIX = 'test_server'  // 테스트 환경 접미사
        PROD_CONDA_ENV_SUFFIX = 'prod'         // 운영 환경 접미사
        
        // 프로젝트 실행 명령어
        FRONTEND_START_CMD = 'npm run dev'     // Next.js 개발 서버 명령어
        BACKEND_START_CMD = 'python main.py'  // FastAPI 서버 명령어
        
        // SSH Credentials
        TEST_SSH_CREDENTIAL = 'nextits_ai_4_ssh'
        PROD_SSH_CREDENTIAL = 'nextits_ai_4_ssh' // 운영용 별도 credential 권장
    }

    triggers {
        // DEV 브랜치 커밋 시 테스트 서버 자동 배포
        pollSCM('H/5 * * * *') // 5분마다 SCM 체크
    }

    stages {
        stage('Branch Detection & Auto Deploy') {
            steps {
                script {
                    def currentBranch = env.BRANCH_NAME ?: env.GIT_BRANCH?.replace('origin/', '') ?: 'unknown'
                    echo "Current branch: ${currentBranch}"
                    echo "Selected ACTION: ${params.ACTION}"
                    
                    // DEV 브랜치 커밋 시 자동 테스트 서버 배포
                    if (currentBranch.startsWith('dev') || currentBranch.startsWith('DEV')) {
                        if (params.AUTO_DEPLOY_TEST || env.BUILD_CAUSE?.contains('SCMTrigger')) {
                            echo "🔄 DEV 브랜치 감지 - 테스트 서버 자동 배포 시작"
                            env.AUTO_TEST_DEPLOY = 'true'
                            env.CURRENT_ACTION = 'TEST_SERVER_START'
                        } else {
                            env.AUTO_TEST_DEPLOY = 'false'
                            env.CURRENT_ACTION = params.ACTION
                        }
                    } else if (currentBranch == 'main' || currentBranch == 'master') {
                        // MAIN 브랜치에서는 운영 배포만 허용
                        if (!params.ACTION.startsWith('PROD_')) {
                            error "MAIN 브랜치에서는 운영서버 관련 ACTION만 허용됩니다. 현재 ACTION: ${params.ACTION}"
                        }
                        env.AUTO_TEST_DEPLOY = 'false'
                        env.CURRENT_ACTION = params.ACTION
                    } else {
                        // 기타 브랜치에서는 테스트 서버 ACTION만 허용
                        if (!params.ACTION.startsWith('TEST_')) {
                            error "DEV 관련 브랜치에서는 테스트서버 관련 ACTION만 허용됩니다. 현재 ACTION: ${params.ACTION}"
                        }
                        env.AUTO_TEST_DEPLOY = 'false'
                        env.CURRENT_ACTION = params.ACTION
                    }
                    
                    echo "Final ACTION: ${env.CURRENT_ACTION}"
                    echo "Auto deploy: ${env.AUTO_TEST_DEPLOY}"
                }
            }
        }

        stage('Production Deploy Validation') {
            when {
                expression { env.CURRENT_ACTION == 'PROD_DEPLOY' }
            }
            steps {
                script {
                    def currentBranch = env.BRANCH_NAME ?: env.GIT_BRANCH?.replace('origin/', '') ?: 'unknown'
                    
                    echo "⚠️ 운영서버 배포 검증 ⚠️"
                    echo "현재 브랜치: ${currentBranch}"
                    echo "배포하려는 환경: PRODUCTION"
                    
                    if (!(currentBranch == 'main' || currentBranch == 'master')) {
                        error "운영서버 배포는 main/master 브랜치에서만 가능합니다. 현재 브랜치: ${currentBranch}"
                    }
                    
                    // 운영 배포 전 수동 승인
                    timeout(time: 10, unit: 'MINUTES') {
                        def approval = input(
                            message: '운영서버 배포를 진행하시겠습니까?',
                            ok: '배포 승인',
                            parameters: [
                                booleanParam(name: 'DEPLOYMENT_CONFIRMED', defaultValue: false, description: '배포를 확인했습니다'),
                                string(name: 'DEPLOYER_NAME', defaultValue: '', description: '배포자 이름 입력')
                            ]
                        )
                        
                        if (!approval.DEPLOYMENT_CONFIRMED || !approval.DEPLOYER_NAME) {
                            error "운영서버 배포가 취소되었습니다."
                        }
                        
                        echo "✅ 운영서버 배포 승인됨 - 배포자: ${approval.DEPLOYER_NAME}"
                        env.DEPLOYER_NAME = approval.DEPLOYER_NAME
                    }
                }
            }
        }

        stage('Deploy Files') {
            when {
                anyOf {
                    expression { env.CURRENT_ACTION == 'TEST_SERVER_START' }
                    expression { env.CURRENT_ACTION == 'PROD_DEPLOY' }
                }
            }
            steps {
                script {
                    def isTestServer = env.CURRENT_ACTION == 'TEST_SERVER_START'
                    def targetServer = isTestServer ? env.TEST_SERVER : env.PROD_SERVER
                    def targetPort = isTestServer ? env.TEST_PORT : env.PROD_PORT
                    def targetUser = isTestServer ? env.TEST_USER : env.PROD_USER
                    def targetWorkspace = isTestServer ? env.TEST_WORKSPACE : env.PROD_WORKSPACE
                    def sshCredential = isTestServer ? env.TEST_SSH_CREDENTIAL : env.PROD_SSH_CREDENTIAL
                    
                    echo "📁 파일 배포 시작 - ${isTestServer ? 'TEST' : 'PROD'} 서버"
                    
                    sshagent(credentials: [sshCredential]) {
                        sh """
                            # 파일 복사
                            ssh -o StrictHostKeyChecking=no -p ${targetPort} ${targetUser}@${targetServer} "mkdir -p ${targetWorkspace} && rm -rf ${targetWorkspace}/*"
                            scp -o StrictHostKeyChecking=no -P ${targetPort} -r ./* ${targetUser}@${targetServer}:${targetWorkspace}/
                        """
                    }
                }
            }
        }
        
        stage('Test Server Operations') {
            when {
                anyOf {
                    expression { env.CURRENT_ACTION == 'TEST_SERVER_START' }
                    expression { env.CURRENT_ACTION == 'TEST_SERVER_STOP' }
                }
            }
            steps {
                sshagent(credentials: ["${env.TEST_SSH_CREDENTIAL}"]) {
                    script {
                        def isStart = env.CURRENT_ACTION == 'TEST_SERVER_START'
                        echo "${isStart ? '🚀 테스트 서버 시작' : '🛑 테스트 서버 중지'}"
                        
                        if (isStart) {
                            // 테스트 서버 시작
                            sh """
                                ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ServerAliveCountMax=3 -p ${env.TEST_PORT} ${env.TEST_USER}@${env.TEST_SERVER} << 'EOF'

cd ${env.TEST_WORKSPACE}

# Conda 환경명 생성 함수 (Jenkins 환경 변수 사용)
get_conda_env_name() {
    local branch_name="\$1"
    local env_type="\$2"
    local deployer="\$3"
    
    # 브랜치명에서 특수문자 제거 및 소문자 변환
    clean_branch=\$(echo "\$branch_name" | sed 's/[^a-zA-Z0-9]/_/g' | tr '[:upper:]' '[:lower:]')
    
    # 최대 길이 제한 (15자)
    if [ \${#clean_branch} -gt 15 ]; then
        clean_branch=\$(echo "\$clean_branch" | cut -c1-15)
    fi
    
    if [ "\$env_type" = "test" ]; then
        echo "${env.CONDA_ENV_PREFIX}_${env.TEST_CONDA_ENV_SUFFIX}_\${clean_branch}"
    elif [ "\$env_type" = "prod" ]; then
        if [ -n "\$deployer" ]; then
            # 배포자명 정리
            clean_deployer=\$(echo "\$deployer" | sed 's/[^a-zA-Z0-9]/_/g' | tr '[:upper:]' '[:lower:]')
            if [ \${#clean_deployer} -gt 12 ]; then
                clean_deployer=\$(echo "\$clean_deployer" | cut -c1-12)
            fi
            echo "${env.CONDA_ENV_PREFIX}_${env.PROD_CONDA_ENV_SUFFIX}_\${clean_deployer}"
        else
            echo "${env.CONDA_ENV_PREFIX}_${env.PROD_CONDA_ENV_SUFFIX}_default"
        fi
    else
        echo "${env.CONDA_ENV_PREFIX}_unknown"
    fi
}

# 사용 가능한 포트 찾기 함수
find_available_port() {
    local min_port=\$1
    local max_port=\$2
    local port_type=\$3
    
    echo "사용 가능한 \$port_type 포트 찾는 중 (범위: \$min_port-\$max_port)"
    
    for port in \$(seq \$min_port \$max_port); do
        if command -v lsof >/dev/null 2>&1; then
            if ! lsof -Pi :\$port -sTCP:LISTEN >/dev/null 2>&1; then
                echo \$port
                return 0
            fi
        else
            if ! netstat -tln 2>/dev/null | grep ":\$port " >/dev/null; then
                echo \$port
                return 0
            fi
        fi
    done
    
    echo "ERROR: 사용 가능한 \$port_type 포트가 없습니다 (범위: \$min_port-\$max_port)" >&2
    return 1
}

# Conda 환경 활성화 함수
activate_conda_env() {
    local env_name="\$1"
    
    echo "Conda 환경 활성화 시도: \$env_name"
    
    # Conda 설치 경로 확인
    local conda_base=""
    if [ -f /opt/conda/bin/activate ]; then
        conda_base="/opt/conda"
    elif [ -f ~/miniconda3/bin/activate ]; then
        conda_base="~/miniconda3"
    elif [ -f ~/anaconda3/bin/activate ]; then
        conda_base="~/anaconda3"
    elif command -v conda >/dev/null 2>&1; then
        conda_base=\$(conda info --base)
    else
        echo "❌ Conda를 찾을 수 없습니다"
        return 1
    fi
    
    echo "Conda 기본 경로: \$conda_base"
    
    # Conda 환경 존재 확인
    if conda env list | grep -q "^\$env_name "; then
        echo "기존 Conda 환경 사용: \$env_name"
    else
        echo "새 Conda 환경 생성: \$env_name"
        conda create -n "\$env_name" python=3.9 -y --quiet
        if [ \$? -ne 0 ]; then
            echo "❌ Conda 환경 생성 실패: \$env_name"
            return 1
        fi
    fi
    
    # 환경 활성화
    if [ -f "\$conda_base/bin/activate" ]; then
        source "\$conda_base/bin/activate" "\$env_name"
    elif command -v conda >/dev/null 2>&1; then
        conda activate "\$env_name"
    else
        echo "❌ Conda 환경 활성화 실패"
        return 1
    fi
    
    echo "✅ Conda 환경 활성화 성공: \$env_name"
    echo "Python 경로: \$(which python)"
    echo "Python 버전: \$(python --version)"
    
    return 0
}

echo "=== 테스트 서버 시작 ==="
echo "Current user: \$(whoami)"
echo "Current directory: \$(pwd)"

# 현재 브랜치명 (Jenkins에서 전달받거나 Git에서 추출)
CURRENT_BRANCH="\${GIT_BRANCH:-\$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')}"
CURRENT_BRANCH=\$(echo "\$CURRENT_BRANCH" | sed 's|origin/||g')
echo "브랜치: \$CURRENT_BRANCH"

# Conda 환경명 생성
CONDA_ENV=\$(get_conda_env_name "\$CURRENT_BRANCH" "test" "")
echo "Conda 환경명: \$CONDA_ENV"

# 사용 가능한 포트 찾기
BACKEND_PORT=\$(find_available_port ${env.TEST_BACKEND_PORT_MIN} ${env.TEST_BACKEND_PORT_MAX} "backend")
if [ \$? -ne 0 ]; then
    echo "❌ Backend 포트를 찾을 수 없습니다"
    exit 1
fi

FRONTEND_PORT=\$(find_available_port ${env.TEST_FRONTEND_PORT_MIN} ${env.TEST_FRONTEND_PORT_MAX} "frontend")
if [ \$? -ne 0 ]; then
    echo "❌ Frontend 포트를 찾을 수 없습니다"
    exit 1
fi

echo "할당된 포트 - Backend: \$BACKEND_PORT, Frontend: \$FRONTEND_PORT"

# 기존 프로세스 정리 (해당 포트만)
echo "기존 프로세스 정리 중..."
if command -v lsof >/dev/null 2>&1; then
    lsof -ti:\$BACKEND_PORT | xargs -r kill -9 2>/dev/null || true
    lsof -ti:\$FRONTEND_PORT | xargs -r kill -9 2>/dev/null || true
else
    # 전체 범위에서 정리
    for port in \$(seq ${env.TEST_BACKEND_PORT_MIN} ${env.TEST_BACKEND_PORT_MAX}); do
        pkill -f "python.*main.py.*\$port" 2>/dev/null || true
    done
    for port in \$(seq ${env.TEST_FRONTEND_PORT_MIN} ${env.TEST_FRONTEND_PORT_MAX}); do
        pkill -f "npm.*start.*\$port" 2>/dev/null || true
    done
fi
sleep 2

# Conda 환경 활성화
if ! activate_conda_env "\$CONDA_ENV"; then
    echo "❌ Conda 환경 활성화 실패"
    exit 1
fi

# Backend 시작
if [ -f backend/main.py ]; then
    cd backend
    
    # 의존성 설치
    if [ -f requirements.txt ]; then
        echo "의존성 설치 중..."
        pip install -r requirements.txt --quiet
    else
        echo "기본 의존성 설치 중..."
        pip install fastapi uvicorn python-multipart --quiet
    fi
    
    # FastAPI 설치 확인
    python -c "import fastapi, uvicorn; print('✅ FastAPI, Uvicorn 사용 가능')" 2>/dev/null || {
        echo "❌ FastAPI 설치 실패, 재설치 중..."
        pip install fastapi uvicorn python-multipart
    }
    
    # 백엔드 시작
    TEST_BACKEND_LOG="/tmp/test_backend_\${BACKEND_PORT}.log"
    echo "테스트 백엔드 시작 중... (포트: \$BACKEND_PORT)"
    PORT=\$BACKEND_PORT nohup python main.py > \$TEST_BACKEND_LOG 2>&1 &
    BACKEND_PID=\$!
    echo "✅ 테스트 백엔드 시작됨 (PID: \$BACKEND_PID, 포트: \$BACKEND_PORT)"
    
    cd ..
    
    # Frontend 시작
    if [ -f frontend/package.json ]; then
        cd frontend
        
        # .env 파일 생성
        echo "REACT_APP_API_URL=http://${env.TEST_SERVER}:\$BACKEND_PORT" > .env
        echo "REACT_APP_ENV=TEST" >> .env
        echo "PORT=\$FRONTEND_PORT" >> .env
        
        echo "생성된 .env 파일:"
        cat .env
        
        # 프론트엔드 시작 (Next.js 포트 지정 개선)
        if command -v npm >/dev/null; then
            echo "프론트엔드 의존성 확인 중..."
            [ ! -d node_modules ] && npm install --silent
            
            echo "테스트 프론트엔드 시작 중... (포트: \$FRONTEND_PORT)"
            TEST_FRONTEND_LOG="/tmp/test_frontend_\${FRONTEND_PORT}.log"
            
            # Next.js 실행 방법 개선
            if [ -f "next.config.js" ] || [ -f "next.config.mjs" ] || grep -q "next" package.json 2>/dev/null; then
                # Next.js 프로젝트
                echo "Next.js 프로젝트 감지"
                
                # package.json에서 사용 가능한 스크립트 확인
                if npm run | grep -q "dev"; then
                    echo "npm run dev 명령어로 시작"
                    nohup npm run dev -- -p \$FRONTEND_PORT > \$TEST_FRONTEND_LOG 2>&1 &
                elif npm run | grep -q "start"; then
                    echo "npm run start 명령어로 시작 (포트 환경변수 설정)"
                    PORT=\$FRONTEND_PORT nohup npm run start > \$TEST_FRONTEND_LOG 2>&1 &
                else
                    echo "기본 Next.js 개발 서버로 시작"
                    nohup npx next dev -p \$FRONTEND_PORT > \$TEST_FRONTEND_LOG 2>&1 &
                fi
            elif grep -q "react-scripts" package.json 2>/dev/null; then
                # Create React App
                echo "React App 감지 (포트 환경변수 설정)"
                PORT=\$FRONTEND_PORT nohup npm start > \$TEST_FRONTEND_LOG 2>&1 &
            elif grep -q "vite" package.json 2>/dev/null; then
                # Vite 프로젝트
                echo "Vite 프로젝트 감지"
                nohup npm run dev -- --port \$FRONTEND_PORT > \$TEST_FRONTEND_LOG 2>&1 &
            else
                # 일반적인 방법
                echo "일반 프론트엔드 프로젝트 (포트 환경변수 사용)"
                PORT=\$FRONTEND_PORT nohup npm start > \$TEST_FRONTEND_LOG 2>&1 &
            fi
            
            echo "✅ 테스트 프론트엔드 시작됨 (포트: \$FRONTEND_PORT)"
        else
            echo "❌ npm을 찾을 수 없습니다"
        fi
        
        cd ..
    fi
    
    # 서비스 확인
    echo "서비스 시작 대기 중..."
    sleep 8
    
    echo ""
    echo "=== 테스트 서버 상태 확인 ==="
    if command -v lsof >/dev/null 2>&1; then
        lsof -i:\$BACKEND_PORT && echo "✅ 백엔드 실행 중 (포트: \$BACKEND_PORT)" || echo "❌ 백엔드 실행 실패 (포트: \$BACKEND_PORT)"
        lsof -i:\$FRONTEND_PORT && echo "✅ 프론트엔드 실행 중 (포트: \$FRONTEND_PORT)" || echo "❌ 프론트엔드 실행 실패 (포트: \$FRONTEND_PORT)"
    else
        netstat -tln 2>/dev/null | grep :\$BACKEND_PORT && echo "✅ 백엔드 실행 중 (포트: \$BACKEND_PORT)" || echo "❌ 백엔드 실행 실패 (포트: \$BACKEND_PORT)"
        netstat -tln 2>/dev/null | grep :\$FRONTEND_PORT && echo "✅ 프론트엔드 실행 중 (포트: \$FRONTEND_PORT)" || echo "❌ 프론트엔드 실행 실패 (포트: \$FRONTEND_PORT)"
    fi
    
    echo ""
    echo "=== 테스트 서버 정보 ==="
    echo "브랜치: \$CURRENT_BRANCH"
    echo "Conda 환경: \$CONDA_ENV"
    echo "Frontend: http://${env.TEST_SERVER}:\$FRONTEND_PORT"
    echo "Backend: http://${env.TEST_SERVER}:\$BACKEND_PORT"
    echo "API Docs: http://${env.TEST_SERVER}:\$BACKEND_PORT/docs"
    echo "로그 파일:"
    echo "  - Backend: \$TEST_BACKEND_LOG"
    echo "  - Frontend: \$TEST_FRONTEND_LOG"
    
    # 포트 정보 파일 저장 (다음 빌드에서 사용할 수 있도록)
    echo "BACKEND_PORT=\$BACKEND_PORT" > /tmp/test_server_ports.env
    echo "FRONTEND_PORT=\$FRONTEND_PORT" >> /tmp/test_server_ports.env
    echo "CONDA_ENV=\$CONDA_ENV" >> /tmp/test_server_ports.env
    echo "BRANCH=\$CURRENT_BRANCH" >> /tmp/test_server_ports.env
    
else
    echo "❌ backend/main.py를 찾을 수 없습니다"
    exit 1
fi

EOF
                            """
                        } else {
                            // 테스트 서버 중지
                            sh """
                                ssh -o StrictHostKeyChecking=no -p ${env.TEST_PORT} ${env.TEST_USER}@${env.TEST_SERVER} << 'EOF'

echo "=== 테스트 서버 중지 ==="

# 모든 테스트 포트 범위의 프로세스 종료
echo "테스트 서버 프로세스 종료 중..."

if command -v lsof >/dev/null 2>&1; then
    echo "포트 기반 프로세스 종료..."
    # Backend 포트 범위
    for port in \$(seq ${env.TEST_BACKEND_PORT_MIN} ${env.TEST_BACKEND_PORT_MAX}); do
        lsof -ti:\$port | xargs -r kill -9 2>/dev/null || true
    done
    # Frontend 포트 범위
    for port in \$(seq ${env.TEST_FRONTEND_PORT_MIN} ${env.TEST_FRONTEND_PORT_MAX}); do
        lsof -ti:\$port | xargs -r kill -9 2>/dev/null || true
    done
else
    echo "프로세스명 기반 종료..."
    pkill -f "python.*main.py" 2>/dev/null || true
    pkill -f "npm start" 2>/dev/null || true
fi

sleep 3

# 포트 정보 파일 정리
rm -f /tmp/test_server_ports.env

# 로그 파일 정리 (선택사항)
echo "로그 파일 정리 중..."
rm -f /tmp/test_backend_*.log
rm -f /tmp/test_frontend_*.log

echo "✅ 테스트 서버 중지 완료"

# 최종 확인
echo ""
echo "남은 프로세스 확인:"
ps aux | grep -E "(python.*main|npm start)" | grep -v grep || echo "테스트 서버 관련 프로세스 없음"

EOF
                            """
                        }
                    }
                }
            }
        }

        stage('Production Server Operations') {
            when {
                anyOf {
                    expression { env.CURRENT_ACTION == 'PROD_DEPLOY' }
                    expression { env.CURRENT_ACTION == 'PROD_RESTART' }
                    expression { env.CURRENT_ACTION == 'PROD_START' }
                    expression { env.CURRENT_ACTION == 'PROD_STOP' }
                }
            }
            steps {
                sshagent(credentials: ["${env.PROD_SSH_CREDENTIAL}"]) {
                    script {
                        echo "🏭 운영서버 작업: ${env.CURRENT_ACTION}"
                        
                        switch(env.CURRENT_ACTION) {
                            case 'PROD_DEPLOY':
                            case 'PROD_START':
                                // 운영서버 시작/배포
                                sh """
                                    ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ServerAliveCountMax=3 -p ${env.PROD_PORT} ${env.PROD_USER}@${env.PROD_SERVER} << 'EOF'

cd ${env.PROD_WORKSPACE}

# 운영 Conda 환경명 생성 함수 (Jenkins 환경 변수 사용)
get_prod_conda_env_name() {
    local deployer="\$1"
    
    if [ -n "\$deployer" ]; then
        # 배포자명 정리 (특수문자 제거, 소문자 변환)
        clean_deployer=\$(echo "\$deployer" | sed 's/[^a-zA-Z0-9]/_/g' | tr '[:upper:]' '[:lower:]')
        
        # 최대 길이 제한
        if [ \${#clean_deployer} -gt 12 ]; then
            clean_deployer=\$(echo "\$clean_deployer" | cut -c1-12)
        fi
        
        echo "${env.CONDA_ENV_PREFIX}_${env.PROD_CONDA_ENV_SUFFIX}_\${clean_deployer}"
    else
        echo "${env.CONDA_ENV_PREFIX}_${env.PROD_CONDA_ENV_SUFFIX}_default"
    fi
}

# Conda 환경 활성화 함수 (운영용)
activate_prod_conda_env() {
    local env_name="\$1"
    
    echo "운영 Conda 환경 활성화 시도: \$env_name"
    
    # Conda 설치 경로 확인
    local conda_base=""
    if [ -f /opt/conda/bin/activate ]; then
        conda_base="/opt/conda"
    elif [ -f ~/miniconda3/bin/activate ]; then
        conda_base="~/miniconda3"
    elif [ -f ~/anaconda3/bin/activate ]; then
        conda_base="~/anaconda3"
    elif command -v conda >/dev/null 2>&1; then
        conda_base=\$(conda info --base)
    else
        echo "❌ Conda를 찾을 수 없습니다"
        return 1
    fi
    
    # Conda 환경 존재 확인 및 생성
    if conda env list | grep -q "^\$env_name "; then
        echo "기존 운영 Conda 환경 사용: \$env_name"
    else
        echo "새 운영 Conda 환경 생성: \$env_name"
        conda create -n "\$env_name" python=3.9 -y --quiet
        if [ \$? -ne 0 ]; then
            echo "❌ 운영 Conda 환경 생성 실패: \$env_name"
            return 1
        fi
    fi
    
    # 환경 활성화
    if [ -f "\$conda_base/bin/activate" ]; then
        source "\$conda_base/bin/activate" "\$env_name"
    elif command -v conda >/dev/null 2>&1; then
        conda activate "\$env_name"
    else
        echo "❌ 운영 Conda 환경 활성화 실패"
        return 1
    fi
    
    echo "✅ 운영 Conda 환경 활성화 성공: \$env_name"
    echo "Python 경로: \$(which python)"
    echo "Python 버전: \$(python --version)"
    
    return 0
}

echo "=== 운영서버 ${env.CURRENT_ACTION == 'PROD_DEPLOY' ? '배포' : '시작'} ==="
echo "배포자: ${env.DEPLOYER_NAME ?: 'Unknown'}"
echo "시간: \$(date)"
echo "Backend port: ${env.PROD_BACKEND_PORT}"
echo "Frontend port: ${env.PROD_FRONTEND_PORT}"

# 운영 Conda 환경명 생성
PROD_CONDA_ENV=\$(get_prod_conda_env_name "${env.DEPLOYER_NAME ?: 'system'}")
echo "운영 Conda 환경명: \$PROD_CONDA_ENV"

# 기존 프로세스 정리
echo "기존 운영 프로세스 정리 중..."
if command -v lsof >/dev/null 2>&1; then
    lsof -ti:${env.PROD_BACKEND_PORT} | xargs -r kill -9 2>/dev/null || true
    lsof -ti:${env.PROD_FRONTEND_PORT} | xargs -r kill -9 2>/dev/null || true
else
    pkill -f "python.*main.*${env.PROD_BACKEND_PORT}" 2>/dev/null || true
    pkill -f "npm.*${env.PROD_FRONTEND_PORT}" 2>/dev/null || true
fi
sleep 3

# 운영 Conda 환경 활성화
if ! activate_prod_conda_env "\$PROD_CONDA_ENV"; then
    echo "❌ 운영 Conda 환경 활성화 실패"
    exit 1
fi

# Backend 시작
if [ -f backend/main.py ]; then
    cd backend
    
    # 운영 의존성 설치
    if [ -f requirements.txt ]; then
        echo "운영환경 의존성 설치 중..."
        pip install -r requirements.txt --quiet
    else
        echo "기본 운영 의존성 설치 중..."
        pip install fastapi uvicorn python-multipart --quiet
    fi
    
    # FastAPI 설치 확인
    python -c "import fastapi, uvicorn; print('✅ 운영환경 FastAPI, Uvicorn 사용 가능')" 2>/dev/null || {
        echo "❌ 운영환경 FastAPI 설치 실패, 재설치 중..."
        pip install fastapi uvicorn python-multipart
    }
    
    # 운영 백엔드 시작 (고급 포트 지정)
    PROD_LOG="/tmp/prod_backend.log"
    echo "운영 백엔드 시작 중... (Port: ${env.PROD_BACKEND_PORT})"
    
    # 프로덕션용 백엔드 시작 방식 (더 안정적)
    if grep -q "uvicorn" main.py 2>/dev/null; then
        # FastAPI with uvicorn (프로덕션 설정)
        echo "FastAPI 운영 서버 시작 (uvicorn with workers)"
        nohup python -c "
import uvicorn
import sys
import os
sys.path.insert(0, '.')
os.environ['PORT'] = '${env.PROD_BACKEND_PORT}'
os.environ['ENV'] = 'production'
from main import app
uvicorn.run(
    app, 
    host='0.0.0.0', 
    port=int('${env.PROD_BACKEND_PORT}'),
    workers=2,
    log_level='info',
    access_log=True
)
" > \$PROD_LOG 2>&1 &
    elif grep -q "gunicorn" requirements.txt 2>/dev/null || command -v gunicorn >/dev/null 2>&1; then
        # Gunicorn 사용 (더 프로덕션에 적합)
        echo "Gunicorn으로 운영 서버 시작"
        pip install gunicorn --quiet 2>/dev/null || true
        nohup gunicorn -w 2 -b 0.0.0.0:${env.PROD_BACKEND_PORT} main:app > \$PROD_LOG 2>&1 &
    elif grep -q "app.run" main.py 2>/dev/null; then
        # Flask 프로덕션 모드
        echo "Flask 운영 서버 시작"
        FLASK_ENV=production PORT=${env.PROD_BACKEND_PORT} nohup python main.py > \$PROD_LOG 2>&1 &
    elif grep -q "django" main.py 2>/dev/null || [ -f "manage.py" ]; then
        # Django 프로덕션
        echo "Django 운영 서버 시작"
        DJANGO_SETTINGS_MODULE=settings.production nohup python manage.py runserver 0.0.0.0:${env.PROD_BACKEND_PORT} > \$PROD_LOG 2>&1 &
    else
        # 일반적인 운영 방법
        echo "일반 Python 운영 서버 시작"
        PORT=${env.PROD_BACKEND_PORT} HOST=0.0.0.0 ENV=production nohup python main.py > \$PROD_LOG 2>&1 &
    fi
    
    BACKEND_PID=\$!
    echo "✅ 운영 백엔드 시작됨 (PID: \$BACKEND_PID)"
    
    cd ..
    
    # Frontend 시작
    if [ -f frontend/package.json ]; then
        cd frontend
        
        # 운영 .env 파일 생성
        echo "REACT_APP_API_URL=http://${env.PROD_SERVER}:${env.PROD_BACKEND_PORT}" > .env
        echo "REACT_APP_ENV=PRODUCTION" >> .env
        echo "PORT=${env.PROD_FRONTEND_PORT}" >> .env
        
        echo "운영 .env 파일 생성됨:"
        cat .env
        
        # 운영 프론트엔드 시작 (프로덕션 빌드)
        if command -v npm >/dev/null; then
            echo "운영 프론트엔드 의존성 설치 중..."
            [ ! -d node_modules ] && npm install --silent
            
            echo "운영 프론트엔드 시작 중... (Port: ${env.PROD_FRONTEND_PORT})"
            PROD_FRONTEND_LOG="/tmp/prod_frontend.log"
            
            # 프로덕션 환경에 맞는 실행 방법
            if [ -f "next.config.js" ] || [ -f "next.config.mjs" ] || grep -q "next" package.json 2>/dev/null; then
                # Next.js 프로덕션
                echo "Next.js 프로덕션 빌드 및 시작"
                
                # 빌드가 필요한지 확인
                if [ ! -d ".next" ] || [ ! -f ".next/BUILD_ID" ]; then
                    echo "Next.js 빌드 중..."
                    npm run build --silent
                fi
                
                # 프로덕션 서버 시작
                if npm run | grep -q "start"; then
                    PORT=${env.PROD_FRONTEND_PORT} nohup npm run start > \$PROD_FRONTEND_LOG 2>&1 &
                else
                    PORT=${env.PROD_FRONTEND_PORT} nohup npx next start -p ${env.PROD_FRONTEND_PORT} > \$PROD_FRONTEND_LOG 2>&1 &
                fi
            elif grep -q "react-scripts" package.json 2>/dev/null; then
                # Create React App 프로덕션
                echo "React App 프로덕션 빌드 및 시작"
                
                # 빌드 확인
                if [ ! -d "build" ]; then
                    echo "React App 빌드 중..."
                    npm run build --silent
                fi
                
                # serve 패키지를 사용한 정적 서빙
                if ! command -v serve >/dev/null 2>&1; then
                    npm install -g serve --silent
                fi
                nohup serve -s build -l ${env.PROD_FRONTEND_PORT} > \$PROD_FRONTEND_LOG 2>&1 &
                
            elif grep -q "vite" package.json 2>/dev/null; then
                # Vite 프로덕션
                echo "Vite 프로덕션 빌드 및 시작"
                
                # 빌드 확인
                if [ ! -d "dist" ]; then
                    echo "Vite 빌드 중..."
                    npm run build --silent
                fi
                
                # preview 모드로 실행
                nohup npm run preview -- --port ${env.PROD_FRONTEND_PORT} > \$PROD_FRONTEND_LOG 2>&1 &
            else
                # 일반적인 프로덕션 실행
                echo "일반 프론트엔드 프로덕션 시작"
                
                # 가능하다면 빌드 실행
                if npm run | grep -q "build"; then
                    echo "프로덕션 빌드 중..."
                    npm run build --silent 2>/dev/null || true
                fi
                
                PORT=${env.PROD_FRONTEND_PORT} NODE_ENV=production nohup npm start > \$PROD_FRONTEND_LOG 2>&1 &
            fi
            
            echo "✅ 운영 프론트엔드 시작됨"
        fi
        
        cd ..
    fi
    
    # 운영 서비스 확인
    echo "운영 서비스 시작 대기 중..."
    sleep 10
    
    echo ""
    echo "=== 운영서버 상태 확인 ==="
    if command -v lsof >/dev/null 2>&1; then
        lsof -i:${env.PROD_BACKEND_PORT} && echo "✅ 운영 백엔드 실행 중" || echo "❌ 운영 백엔드 실행 실패"
        lsof -i:${env.PROD_FRONTEND_PORT} && echo "✅ 운영 프론트엔드 실행 중" || echo "❌ 운영 프론트엔드 실행 실패"
    fi
    
    # HTTP 상태 확인
    if command -v curl >/dev/null 2>&1; then
        echo ""
        echo "HTTP 상태 확인 중..."
        if curl -s --connect-timeout 10 http://localhost:${env.PROD_BACKEND_PORT} >/dev/null 2>&1; then
            echo "✅ 운영 백엔드 API 응답 정상"
        else
            echo "⚠️ 운영 백엔드 API 응답 확인 필요"
        fi
    fi
    
    echo ""
    echo "=== 🚀 운영서버 배포 완료 ==="
    echo "브랜치: \$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
    echo "Conda 환경: \$PROD_CONDA_ENV"
    echo "Frontend: http://${env.PROD_SERVER}:${env.PROD_FRONTEND_PORT}"
    echo "Backend: http://${env.PROD_SERVER}:${env.PROD_BACKEND_PORT}"
    echo "API Docs: http://${env.PROD_SERVER}:${env.PROD_BACKEND_PORT}/docs"
    echo "배포 시간: \$(date)"
    echo "배포자: ${env.DEPLOYER_NAME ?: 'Unknown'}"
    
    # 운영 배포 정보 저장
    echo "PROD_BACKEND_PORT=${env.PROD_BACKEND_PORT}" > /tmp/prod_server_info.env
    echo "PROD_FRONTEND_PORT=${env.PROD_FRONTEND_PORT}" >> /tmp/prod_server_info.env
    echo "PROD_CONDA_ENV=\$PROD_CONDA_ENV" >> /tmp/prod_server_info.env
    echo "DEPLOYER=${env.DEPLOYER_NAME ?: 'Unknown'}" >> /tmp/prod_server_info.env
    echo "DEPLOY_TIME=\$(date)" >> /tmp/prod_server_info.env
    
else
    echo "❌ backend/main.py를 찾을 수 없습니다"
    exit 1
fi

EOF
                                """
                                break
                            
                            case 'PROD_RESTART':
                                // 운영서버 재시작
                                sh """
                                    ssh -o StrictHostKeyChecking=no -p ${env.PROD_PORT} ${env.PROD_USER}@${env.PROD_SERVER} << 'EOF'

# 운영 정보 로드 함수
load_prod_info() {
    if [ -f /tmp/prod_server_info.env ]; then
        source /tmp/prod_server_info.env
        echo "기존 운영 정보 로드됨:"
        echo "  - Conda 환경: \$PROD_CONDA_ENV"
        echo "  - 배포자: \$DEPLOYER"
        return 0
    else
        echo "기존 운영 정보를 찾을 수 없습니다. 기본값 사용"
        PROD_CONDA_ENV="quantas_prod_default"
        return 1
    fi
}

echo "=== 운영서버 재시작 ==="

# 기존 운영 정보 로드
load_prod_info

# 1단계: 기존 프로세스 중지
echo "기존 운영 프로세스 중지 중..."
if command -v lsof >/dev/null 2>&1; then
    lsof -ti:${env.PROD_BACKEND_PORT} | xargs -r kill -TERM 2>/dev/null || echo "백엔드 프로세스 없음"
    lsof -ti:${env.PROD_FRONTEND_PORT} | xargs -r kill -TERM 2>/dev/null || echo "프론트엔드 프로세스 없음"
else
    pkill -TERM -f "python.*main.*${env.PROD_BACKEND_PORT}" 2>/dev/null || echo "백엔드 프로세스 없음"
    pkill -TERM -f "npm.*${env.PROD_FRONTEND_PORT}" 2>/dev/null || echo "프론트엔드 프로세스 없음"
fi

# 정상 종료 대기
echo "정상 종료 대기 중..."
sleep 5

# 강제 종료 (필요시)
if command -v lsof >/dev/null 2>&1; then
    lsof -ti:${env.PROD_BACKEND_PORT} | xargs -r kill -9 2>/dev/null || true
    lsof -ti:${env.PROD_FRONTEND_PORT} | xargs -r kill -9 2>/dev/null || true
fi

echo "✅ 운영서버 프로세스 중지 완료"

# 2단계: 서비스 재시작
cd ${env.PROD_WORKSPACE}

# 기존 Conda 환경 활성화
echo "기존 운영 Conda 환경 활성화: \$PROD_CONDA_ENV"
if [ -f /opt/conda/bin/activate ]; then
    source /opt/conda/bin/activate "\$PROD_CONDA_ENV"
elif [ -f ~/miniconda3/bin/activate ]; then
    source ~/miniconda3/bin/activate "\$PROD_CONDA_ENV"
elif [ -f ~/anaconda3/bin/activate ]; then
    source ~/anaconda3/bin/activate "\$PROD_CONDA_ENV"
elif command -v conda >/dev/null 2>&1; then
    conda activate "\$PROD_CONDA_ENV"
else
    echo "❌ Conda 환경 활성화 실패"
    exit 1
fi

echo "Python 경로: \$(which python)"

# Backend 재시작
if [ -f backend/main.py ]; then
    cd backend
    PROD_LOG="/tmp/prod_backend.log"
    echo "운영 백엔드 재시작 중..."
    PORT=${env.PROD_BACKEND_PORT} nohup python main.py > \$PROD_LOG 2>&1 &
    echo "운영 백엔드 재시작됨"
    cd ..
fi

# Frontend 재시작
if [ -f frontend/package.json ]; then
    cd frontend
    if command -v npm >/dev/null; then
        PROD_FRONTEND_LOG="/tmp/prod_frontend.log"
        echo "운영 프론트엔드 재시작 중..."
        nohup npm start > \$PROD_FRONTEND_LOG 2>&1 &
        echo "운영 프론트엔드 재시작됨"
    fi
    cd ..
fi

sleep 8
echo "✅ 운영서버 재시작 완료"
echo "재시작 시간: \$(date)" >> /tmp/prod_server_info.env

EOF
                                """
                                break
                            
                            case 'PROD_STOP':
                                // 운영서버 중지
                                sh """
                                    ssh -o StrictHostKeyChecking=no -p ${env.PROD_PORT} ${env.PROD_USER}@${env.PROD_SERVER} << 'EOF'

echo "=== 운영서버 중지 ==="

# 정상 종료 시도 (SIGTERM)
echo "운영서버 정상 종료 시도 중..."
if command -v lsof >/dev/null 2>&1; then
    lsof -ti:${env.PROD_BACKEND_PORT} | xargs -r kill -TERM 2>/dev/null || echo "운영 백엔드 프로세스 없음"
    lsof -ti:${env.PROD_FRONTEND_PORT} | xargs -r kill -TERM 2>/dev/null || echo "운영 프론트엔드 프로세스 없음"
else
    pkill -TERM -f "python.*main.*${env.PROD_BACKEND_PORT}" 2>/dev/null || echo "운영 백엔드 프로세스 없음"
    pkill -TERM -f "npm.*${env.PROD_FRONTEND_PORT}" 2>/dev/null || echo "운영 프론트엔드 프로세스 없음"
fi

# 정상 종료 대기
echo "정상 종료 대기 중 (10초)..."
sleep 10

# 강제 종료 (필요시)
echo "잔여 프로세스 강제 종료 중..."
if command -v lsof >/dev/null 2>&1; then
    lsof -ti:${env.PROD_BACKEND_PORT} | xargs -r kill -9 2>/dev/null || true
    lsof -ti:${env.PROD_FRONTEND_PORT} | xargs -r kill -9 2>/dev/null || true
fi

echo "✅ 운영서버 중지 완료"
echo "중지 시간: \$(date)"

# 중지 정보 업데이트
if [ -f /tmp/prod_server_info.env ]; then
    echo "STOP_TIME=\$(date)" >> /tmp/prod_server_info.env
fi

EOF
                                """
                                break
                        }
                    }
                }
            }
        }

        stage('Health Check') {
            when {
                anyOf {
                    expression { env.CURRENT_ACTION == 'TEST_SERVER_START' }
                    expression { env.CURRENT_ACTION == 'PROD_DEPLOY' }
                    expression { env.CURRENT_ACTION == 'PROD_START' }
                    expression { env.CURRENT_ACTION == 'PROD_RESTART' }
                }
            }
            steps {
                script {
                    def isTestServer = env.CURRENT_ACTION == 'TEST_SERVER_START'
                    def targetServer = isTestServer ? env.TEST_SERVER : env.PROD_SERVER
                    def targetPort = isTestServer ? env.TEST_PORT : env.PROD_PORT
                    def targetUser = isTestServer ? env.TEST_USER : env.PROD_USER
                    def sshCredential = isTestServer ? env.TEST_SSH_CREDENTIAL : env.PROD_SSH_CREDENTIAL
                    def envName = isTestServer ? 'TEST' : 'PROD'
                    
                    echo "🔍 ${envName} 서버 상태 확인"
                    
                    sshagent(credentials: [sshCredential]) {
                        sh """
                            ssh -o StrictHostKeyChecking=no -p ${targetPort} ${targetUser}@${targetServer} << 'EOF'

echo "=== ${envName} 서버 Health Check (15초 후) ==="
sleep 15

if [ "${isTestServer}" = "true" ]; then
    # 테스트 서버 - 동적 포트 정보 로드
    if [ -f /tmp/test_server_ports.env ]; then
        source /tmp/test_server_ports.env
        echo "테스트 서버 정보 로드됨:"
        echo "  - Backend Port: \$BACKEND_PORT"
        echo "  - Frontend Port: \$FRONTEND_PORT"
        echo "  - Conda 환경: \$CONDA_ENV"
        echo "  - 브랜치: \$BRANCH"
        
        # 포트 상태 확인
        if command -v lsof >/dev/null 2>&1; then
            echo ""
            echo "포트 상태 확인 (lsof):"
            lsof -i:\$BACKEND_PORT && echo "✅ Backend port \$BACKEND_PORT 활성" || echo "❌ Backend port \$BACKEND_PORT 비활성"
            lsof -i:\$FRONTEND_PORT && echo "✅ Frontend port \$FRONTEND_PORT 활성" || echo "❌ Frontend port \$FRONTEND_PORT 비활성"
        else
            echo "포트 상태 확인 (netstat):"
            netstat -tln 2>/dev/null | grep :\$BACKEND_PORT && echo "✅ Backend port \$BACKEND_PORT 활성" || echo "❌ Backend port \$BACKEND_PORT 비활성"
            netstat -tln 2>/dev/null | grep :\$FRONTEND_PORT && echo "✅ Frontend port \$FRONTEND_PORT 활성" || echo "❌ Frontend port \$FRONTEND_PORT 비활성"
        fi
        
        # HTTP 응답 테스트
        if command -v curl >/dev/null 2>&1; then
            echo ""
            echo "HTTP 응답 테스트:"
            echo -n "Backend API (\$BACKEND_PORT) 테스트... "
            if curl -s --connect-timeout 5 --max-time 10 http://localhost:\$BACKEND_PORT >/dev/null 2>&1; then
                echo "✅ 정상 응답"
            else
                echo "❌ 응답 없음 또는 오류"
            fi
            
            echo -n "Frontend (\$FRONTEND_PORT) 테스트... "
            if curl -s --connect-timeout 5 --max-time 10 http://localhost:\$FRONTEND_PORT >/dev/null 2>&1; then
                echo "✅ 정상 응답"
            else
                echo "❌ 응답 없음 또는 오류"
            fi
        fi
        
        # 로그 확인
        echo ""
        echo "=== 테스트 서버 로그 (마지막 10줄) ==="
        BACKEND_LOG="/tmp/test_backend_\${BACKEND_PORT}.log"
        FRONTEND_LOG="/tmp/test_frontend_\${FRONTEND_PORT}.log"
        
        if [ -f \$BACKEND_LOG ]; then
            echo "Backend 로그 (\$BACKEND_LOG):"
            tail -10 \$BACKEND_LOG
        else
            echo "Backend 로그 없음"
        fi
        
        if [ -f \$FRONTEND_LOG ]; then
            echo ""
            echo "Frontend 로그 (\$FRONTEND_LOG):"
            tail -10 \$FRONTEND_LOG
        else
            echo "Frontend 로그 없음"
        fi
        
        echo ""
        echo "=== 테스트 서버 접속 정보 ==="
        echo "Frontend: http://${targetServer}:\$FRONTEND_PORT"
        echo "Backend: http://${targetServer}:\$BACKEND_PORT"
        echo "API Docs: http://${targetServer}:\$BACKEND_PORT/docs"
        
    else
        echo "❌ 테스트 서버 포트 정보를 찾을 수 없습니다"
    fi
else
    # 운영 서버 - 고정 포트
    BACKEND_PORT="${env.PROD_BACKEND_PORT}"
    FRONTEND_PORT="${env.PROD_FRONTEND_PORT}"
    
    # 운영 서버 정보 로드
    if [ -f /tmp/prod_server_info.env ]; then
        source /tmp/prod_server_info.env
        echo "운영 서버 정보 로드됨:"
        echo "  - Conda 환경: \$PROD_CONDA_ENV"
        echo "  - 배포자: \$DEPLOYER"
        echo "  - 배포 시간: \$DEPLOY_TIME"
    fi
    
    # 포트 상태 확인
    if command -v lsof >/dev/null 2>&1; then
        echo ""
        echo "포트 상태 확인 (lsof):"
        lsof -i:\$BACKEND_PORT && echo "✅ Backend port \$BACKEND_PORT 활성" || echo "❌ Backend port \$BACKEND_PORT 비활성"
        lsof -i:\$FRONTEND_PORT && echo "✅ Frontend port \$FRONTEND_PORT 활성" || echo "❌ Frontend port \$FRONTEND_PORT 비활성"
    else
        echo "포트 상태 확인 (netstat):"
        netstat -tln 2>/dev/null | grep :\$BACKEND_PORT && echo "✅ Backend port \$BACKEND_PORT 활성" || echo "❌ Backend port \$BACKEND_PORT 비활성"
        netstat -tln 2>/dev/null | grep :\$FRONTEND_PORT && echo "✅ Frontend port \$FRONTEND_PORT 활성" || echo "❌ Frontend port \$FRONTEND_PORT 비활성"
    fi
    
    # HTTP 응답 테스트
    if command -v curl >/dev/null 2>&1; then
        echo ""
        echo "HTTP 응답 테스트:"
        echo -n "Backend API (\$BACKEND_PORT) 테스트... "
        if curl -s --connect-timeout 5 --max-time 10 http://localhost:\$BACKEND_PORT >/dev/null 2>&1; then
            echo "✅ 정상 응답"
        else
            echo "❌ 응답 없음 또는 오류"
        fi
        
        echo -n "Frontend (\$FRONTEND_PORT) 테스트... "
        if curl -s --connect-timeout 5 --max-time 10 http://localhost:\$FRONTEND_PORT >/dev/null 2>&1; then
            echo "✅ 정상 응답"
        else
            echo "❌ 응답 없음 또는 오류"
        fi
    fi
    
    # 로그 확인
    echo ""
    echo "=== 운영 서버 로그 (마지막 10줄) ==="
    if [ -f /tmp/prod_backend.log ]; then
        echo "Backend 로그:"
        tail -10 /tmp/prod_backend.log
    else
        echo "Backend 로그 없음"
    fi
    
    if [ -f /tmp/prod_frontend.log ]; then
        echo ""
        echo "Frontend 로그:"
        tail -10 /tmp/prod_frontend.log
    else
        echo "Frontend 로그 없음"
    fi
    
    echo ""
    echo "=== 운영 서버 접속 정보 ==="
    echo "Frontend: http://${targetServer}:\$FRONTEND_PORT"
    echo "Backend: http://${targetServer}:\$BACKEND_PORT"
    echo "API Docs: http://${targetServer}:\$BACKEND_PORT/docs"
fi

echo ""
echo "프로세스 상태:"
ps aux | grep -E "(python.*main|npm start)" | grep -v grep || echo "관련 프로세스 없음"

echo ""
echo "=== Health Check 완료 ==="

EOF
                        """
                    }
                }
            }
        }
    }
    
    post {
        always {
            script {
                def currentBranch = env.BRANCH_NAME ?: env.GIT_BRANCH?.replace('origin/', '') ?: 'unknown'
                
                echo "=== 빌드 요약 ==="
                echo "브랜치: ${currentBranch}"
                echo "액션: ${env.CURRENT_ACTION}"
                echo "자동 배포: ${env.AUTO_TEST_DEPLOY ?: 'false'}"
                echo "빌드 시간: ${new Date()}"
                
                if (env.DEPLOYER_NAME) {
                    echo "배포자: ${env.DEPLOYER_NAME}"
                }
            }
        }
        success {
            script {
                def currentBranch = env.BRANCH_NAME ?: env.GIT_BRANCH?.replace('origin/', '') ?: 'unknown'
                
                switch(env.CURRENT_ACTION) {
                    case 'TEST_SERVER_START':
                        echo "🎉 테스트 서버 시작 성공!"
                        echo "📍 동적 포트가 할당되었습니다. Health Check 결과를 확인하세요."
                        
                        if (env.AUTO_TEST_DEPLOY == 'true') {
                            echo ""
                            echo "ℹ️ DEV 브랜치 자동 배포 완료"
                            echo "🔹 브랜치별 Conda 환경이 생성되었습니다"
                            echo "🔹 사용 가능한 포트가 자동으로 할당되었습니다"
                            echo "테스트 완료 후 main 브랜치로 머지하여 운영 배포를 진행하세요"
                        }
                        break
                        
                    case 'TEST_SERVER_STOP':
                        echo "🛑 테스트 서버 중지 성공!"
                        echo "모든 테스트 포트 범위(Backend: ${env.TEST_BACKEND_PORT_MIN}-${env.TEST_BACKEND_PORT_MAX}, Frontend: ${env.TEST_FRONTEND_PORT_MIN}-${env.TEST_FRONTEND_PORT_MAX})의 프로세스가 정리되었습니다."
                        break
                        
                    case 'PROD_DEPLOY':
                        echo "🚀 운영서버 배포 성공!"
                        echo "Frontend: http://${env.PROD_SERVER}:${env.PROD_FRONTEND_PORT}"
                        echo "Backend: http://${env.PROD_SERVER}:${env.PROD_BACKEND_PORT}"
                        echo "API Docs: http://${env.PROD_SERVER}:${env.PROD_BACKEND_PORT}/docs"
                        echo "배포자: ${env.DEPLOYER_NAME}"
                        echo "🔹 배포자별 Conda 환경이 생성되었습니다"
                        break
                        
                    case 'PROD_RESTART':
                        echo "🔄 운영서버 재시작 성공!"
                        echo "기존 Conda 환경이 유지되었습니다"
                        break
                        
                    case 'PROD_START':
                        echo "▶️ 운영서버 시작 성공!"
                        break
                        
                    case 'PROD_STOP':
                        echo "⏹️ 운영서버 중지 성공!"
                        break
                }
                
                // 다음 단계 안내
                if (env.CURRENT_ACTION == 'TEST_SERVER_START' && currentBranch.startsWith('dev')) {
                    echo ""
                    echo "📋 다음 단계:"
                    echo "1. Health Check 결과에서 할당된 포트 확인"
                    echo "2. 테스트 서버에서 기능 확인"
                    echo "3. 문제없으면 main 브랜치로 머지"
                    echo "4. Jenkins에서 PROD_DEPLOY 액션으로 운영 배포"
                }
                
                // 포트 정보 안내
                if (env.CURRENT_ACTION == 'TEST_SERVER_START') {
                    echo ""
                    echo "💡 테스트 서버 특징:"
                    echo "- 동적 포트 할당: 사용 가능한 포트 자동 선택"
                    echo "- 브랜치별 Conda 환경: 격리된 개발 환경"
                    echo "- 포트 범위: Backend(${env.TEST_BACKEND_PORT_MIN}-${env.TEST_BACKEND_PORT_MAX}), Frontend(${env.TEST_FRONTEND_PORT_MIN}-${env.TEST_FRONTEND_PORT_MAX})"
                }
            }
        }
        failure {
            script {
                echo "❌ ${env.CURRENT_ACTION} 실패!"
                echo "로그를 확인하여 문제를 해결하세요."
                
                // 실패 시 로그 위치 안내
                def isTestServer = env.CURRENT_ACTION?.startsWith('TEST_')
                def targetServer = isTestServer ? env.TEST_SERVER : env.PROD_SERVER
                def targetPort = isTestServer ? env.TEST_PORT : env.PROD_PORT
                def targetUser = isTestServer ? env.TEST_USER : env.PROD_USER
                
                echo ""
                echo "디버깅 정보:"
                echo "SSH: ssh -p ${targetPort} ${targetUser}@${targetServer}"
                
                if (isTestServer) {
                    echo "테스트 서버 포트 정보: cat /tmp/test_server_ports.env"
                    echo "테스트 로그 위치: /tmp/test_backend_[PORT].log, /tmp/test_frontend_[PORT].log"
                } else {
                    echo "운영 서버 정보: cat /tmp/prod_server_info.env"
                    echo "운영 로그 위치: /tmp/prod_backend.log, /tmp/prod_frontend.log"
                }
                
                echo "Conda 환경 목록: conda env list"
            }
        }
        unstable {
            echo "⚠️ 빌드가 불안정한 상태입니다. 로그를 확인하세요."
        }
    }
}

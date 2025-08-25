pipeline {
    agent any
    
    parameters {
        choice(
            name: 'ACTION',
            choices: ['DEPLOY', 'STOP'],
            description: 'Select action to perform'
        )
    }

    stages {
        stage('Deploy Files') {
            when {
                expression { params.ACTION == 'DEPLOY' }
            }
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        sh '''
                            # 파일 복사
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 "mkdir -p /home/nextits4/workspace/quantas && rm -rf /home/nextits4/workspace/quantas/*"
                            scp -o StrictHostKeyChecking=no -P 2226 -r ./* nextits4@127.0.0.1:/home/nextits4/workspace/quantas/
                        '''
                    }
                }
            }
        }
        
        stage('Start Services') {
            when {
                expression { params.ACTION == 'DEPLOY' }
            }
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        sh '''
                            ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ServerAliveCountMax=3 -p 2226 nextits4@127.0.0.1 << 'EOF'
cd /home/nextits4/workspace/quantas

echo "=== Environment Setup ==="
echo "Current user: $(whoami)"
echo "Current directory: $(pwd)"
echo "Available Python versions:"
which python3 && python3 --version || echo "Python3 not found"
which python && python --version || echo "Python not found"

echo ""
echo "=== Cleanup existing services ==="
# 기존 프로세스 정리 (더 안전하게)
echo "Killing existing processes..."
if command -v lsof >/dev/null 2>&1; then
    lsof -ti:6010 | xargs -r kill -9 2>/dev/null || true
    lsof -ti:6009 | xargs -r kill -9 2>/dev/null || true
else
    echo "lsof not available, using pkill"
fi

pkill -f "python.*main.py" 2>/dev/null || true
pkill -f "npm start" 2>/dev/null || true
sleep 2

echo "Process cleanup completed"

echo ""
echo "=== Starting Backend ==="

# Backend 존재 확인
if [ ! -f backend/main.py ]; then
    echo "❌ backend/main.py not found!"
    echo "Directory contents:"
    ls -la
    echo "Backend directory:"
    ls -la backend/ 2>/dev/null || echo "backend directory not found"
    exit 1
fi

echo "✅ Found backend/main.py"

# Backend 실행 (더 간단하게)
echo "Starting backend in background..."

cd backend
echo "Current backend directory: $(pwd)"

# Python 명령어 결정
PYTHON_CMD="python3"
if ! command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python"
fi

echo "Using Python command: $PYTHON_CMD"

# 의존성 설치 (간단히)
echo "Installing basic dependencies..."
$PYTHON_CMD -m pip install fastapi uvicorn python-multipart --quiet --user 2>/dev/null || echo "Pip install failed, continuing..."

# main.py 미리보기
echo "main.py preview:"
head -5 main.py 2>/dev/null || echo "Cannot preview main.py"

# 백엔드 시작 (더 간단한 방법)
echo "Starting backend server..."
nohup $PYTHON_CMD main.py > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
echo "Backend started with PID: $BACKEND_PID"

# 원래 디렉토리로 돌아가기
cd ..

# 시작 대기
echo "Waiting for backend to start..."
sleep 5

# 프로세스 확인
if ps -p $BACKEND_PID > /dev/null 2>&1; then
    echo "✅ Backend process is running"
else
    echo "❌ Backend process failed"
    echo "Backend log:"
    cat /tmp/backend.log 2>/dev/null || echo "No backend log"
fi

# 포트 확인
echo "Checking port 6010..."
if command -v lsof >/dev/null 2>&1; then
    if lsof -i:6010 >/dev/null 2>&1; then
        echo "✅ Port 6010 is active"
    else
        echo "❌ Port 6010 is not active"
    fi
else
    # netstat 사용
    if netstat -tln 2>/dev/null | grep :6010 >/dev/null; then
        echo "✅ Port 6010 is active (netstat)"
    else
        echo "❌ Port 6010 is not active (netstat)"
    fi
fi

# 백엔드 로그 출력
echo ""
echo "=== Backend Logs ==="
if [ -f /tmp/backend.log ]; then
    echo "Backend log (first 15 lines):"
    head -15 /tmp/backend.log
    echo ""
    echo "Backend log (last 15 lines):"
    tail -15 /tmp/backend.log
else
    echo "No backend log found"
fi

echo ""
echo "=== Starting Frontend ==="
if [ -f frontend/package.json ]; then
    cd frontend
    
    echo "REACT_APP_API_URL=http://127.0.0.1:6010" > .env
    echo "REACT_APP_ENV=production" >> .env
    
    if command -v npm >/dev/null; then
        echo "Installing frontend dependencies..."
        [ ! -d node_modules ] && npm install --silent 2>/dev/null || echo "npm install failed"
        
        echo "Starting frontend..."
        nohup npm start > /tmp/frontend.log 2>&1 &
        echo "Frontend started"
    else
        echo "npm not found"
    fi
    cd ..
else
    echo "❌ Frontend package.json not found"
fi

echo ""
echo "=== Final Status ==="
sleep 3

# 최종 확인
echo "Final process check:"
ps aux | grep -E "(python.*main|npm start)" | grep -v grep || echo "No target processes"

echo ""
echo "Final port check:"
if command -v lsof >/dev/null 2>&1; then
    lsof -i:6010 2>/dev/null && echo "Backend port active" || echo "Backend port inactive"
    lsof -i:6009 2>/dev/null && echo "Frontend port active" || echo "Frontend port inactive"
else
    netstat -tln 2>/dev/null | grep :6010 && echo "Backend port active" || echo "Backend port inactive"
    netstat -tln 2>/dev/null | grep :6009 && echo "Frontend port active" || echo "Frontend port inactive"
fi

echo ""
echo "=== Deployment Complete ==="
echo "Backend: http://127.0.0.1:6010"
echo "Frontend: http://127.0.0.1:6009"
echo "API Docs: http://127.0.0.1:6010/docs"

EOF
                        '''
                    }
                }
            }
        }
        
        stage('Health Check') {
            when {
                expression { params.ACTION == 'DEPLOY' }
            }
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        sh '''
                            ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -p 2226 nextits4@127.0.0.1 << 'EOF'

echo "=== Health Check (10s after deployment) ==="
sleep 10

# 서비스 응답 테스트
if command -v curl >/dev/null 2>&1; then
    echo "Testing backend API..."
    if curl -s --connect-timeout 5 http://localhost:6010 >/dev/null 2>&1; then
        echo "✅ Backend responding"
    else
        echo "⚠️ Backend not responding"
    fi
    
    echo "Testing frontend..."
    if curl -s --connect-timeout 5 http://localhost:6009 >/dev/null 2>&1; then
        echo "✅ Frontend responding"
    else
        echo "⚠️ Frontend not responding"
    fi
else
    echo "curl not available, skipping HTTP tests"
fi

# 최신 로그 출력
echo ""
echo "=== Latest Logs ==="
if [ -f /tmp/backend.log ]; then
    echo "Backend log (last 10 lines):"
    tail -10 /tmp/backend.log
else
    echo "No backend log"
fi

if [ -f /tmp/frontend.log ]; then
    echo ""
    echo "Frontend log (last 10 lines):"
    tail -10 /tmp/frontend.log
else
    echo "No frontend log"
fi

EOF
                        '''
                    }
                }
            }
        }
        
        stage('Stop Services') {
            when {
                expression { params.ACTION == 'STOP' }
            }
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        sh '''
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 << 'EOF'

echo "=== Stopping Services ==="

# 포트 기반 종료
if command -v lsof >/dev/null 2>&1; then
    echo "Using lsof to stop services"
    lsof -ti:6010 | xargs -r kill -9 2>/dev/null || echo "No backend process"
    lsof -ti:6009 | xargs -r kill -9 2>/dev/null || echo "No frontend process"
else
    echo "lsof not available, using pkill"
    pkill -f "python.*main.py" 2>/dev/null || echo "No backend process"
    pkill -f "npm start" 2>/dev/null || echo "No frontend process"
fi

sleep 2

echo "Services stopped"

EOF
                        '''
                    }
                }
            }
        }
    }
    
    post {
        always {
            script {
                if (params.ACTION == 'DEPLOY') {
                    echo "=== BUILD SUMMARY ==="
                    echo "Build completed. Check service status manually if needed:"
                    echo "SSH: ssh -p 2226 nextits4@127.0.0.1"
                    echo "Backend log: tail -f /tmp/backend.log"
                    echo "Frontend log: tail -f /tmp/frontend.log"
                }
            }
        }
        success {
            script {
                if (params.ACTION == 'DEPLOY') {
                    echo '🎉 Deployment Successful!'
                    echo 'Frontend: http://127.0.0.1:6009'
                    echo 'Backend: http://127.0.0.1:6010'
                    echo 'API Docs: http://127.0.0.1:6010/docs'
                } else {
                    echo '🛑 Services Stopped Successfully!'
                }
            }
        }
        failure {
            echo '❌ Build failed. Check logs above.'
        }
    }
}

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
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 '
                                cd /home/nextits4/workspace/quantas
                                
                                echo "=== Environment Setup ==="
                                
                                # Conda 환경 체크 및 설정
                                if [ -f /opt/conda/bin/activate ]; then
                                    echo "Found Conda installation"
                                    source /opt/conda/bin/activate quantas
                                    echo "Conda environment activated: $(conda info --envs | grep '*')"
                                    python --version
                                else
                                    echo "Conda not found, using system Python"
                                    python3 --version || python --version
                                fi
                                
                                echo ""
                                echo "=== Cleanup existing services ==="
                                # 기존 프로세스 정리
                                echo "Killing existing processes..."
                                lsof -ti:6010 | xargs -r kill -9 2>/dev/null || true
                                lsof -ti:6009 | xargs -r kill -9 2>/dev/null || true
                                pkill -f "python.*main.py" 2>/dev/null || true
                                pkill -f "npm start" 2>/dev/null || true
                                sleep 3
                                
                                echo "Current processes after cleanup:"
                                ps aux | grep -E "(python.*main|npm start)" | grep -v grep || echo "No target processes running"
                                
                                echo ""
                                echo "=== Starting Backend ==="
                                
                                # Backend 존재 확인
                                if [ ! -f backend/main.py ]; then
                                    echo "❌ backend/main.py not found!"
                                    ls -la backend/ 2>/dev/null || echo "backend directory not found"
                                    exit 1
                                fi
                                
                                echo "✅ Found backend/main.py"
                                
                                # Backend 디렉토리로 이동하되 환경을 유지
                                (
                                    cd backend
                                    echo "Current directory: $(pwd)"
                                    ls -la
                                    
                                    # 환경 재설정 (서브쉘에서)
                                    if [ -f /opt/conda/bin/activate ]; then
                                        source /opt/conda/bin/activate quantas
                                        echo "Conda reactivated in backend directory"
                                    fi
                                    
                                    # Python 경로 확인
                                    which python || which python3
                                    python --version 2>/dev/null || python3 --version
                                    
                                    # Requirements 설치
                                    if [ -f requirements.txt ]; then
                                        echo "Installing backend dependencies..."
                                        pip install -r requirements.txt --quiet
                                    else
                                        echo "No requirements.txt found, installing common deps..."
                                        pip install uvicorn fastapi python-multipart --quiet
                                    fi
                                    
                                    # 추가 의존성 설치 시도
                                    echo "Installing additional dependencies..."
                                    pip install fastapi uvicorn python-multipart --quiet || echo "Some deps install failed"
                                    
                                    # main.py 내용 확인
                                    echo ""
                                    echo "=== main.py Preview ==="
                                    head -n 10 main.py 2>/dev/null || echo "Cannot preview main.py"
                                    
                                    # Python 실행 가능 여부 테스트
                                    echo ""
                                    echo "=== Python Test ==="
                                    python -c "import sys; print('Python executable works')" 2>/dev/null || python3 -c "import sys; print('Python3 executable works')" || echo "Python test failed"
                                    
                                    # FastAPI 임포트 테스트
                                    python -c "import fastapi; print('FastAPI available')" 2>/dev/null || echo "FastAPI import failed"
                                    
                                    # 백엔드 시작
                                    echo ""
                                    echo "=== Starting Backend Server ==="
                                    
                                    # Python 실행 방법 결정
                                    PYTHON_CMD="python"
                                    if ! command -v python >/dev/null 2>&1; then
                                        PYTHON_CMD="python3"
                                    fi
                                    
                                    echo "Using Python command: $PYTHON_CMD"
                                    
                                    # 백그라운드에서 시작
                                    nohup $PYTHON_CMD main.py > /tmp/backend.log 2>&1 &
                                    BACKEND_PID=$!
                                    echo "Backend started with PID: $BACKEND_PID"
                                    
                                    # PID 저장
                                    echo $BACKEND_PID > /tmp/backend.pid
                                    
                                ) || {
                                    echo "❌ Backend startup failed in subshell"
                                    exit 1
                                }
                                
                                # 백엔드 시작 대기 및 확인
                                echo ""
                                echo "=== Backend Startup Verification ==="
                                sleep 3
                                
                                # PID 확인
                                if [ -f /tmp/backend.pid ]; then
                                    BACKEND_PID=$(cat /tmp/backend.pid)
                                    echo "Checking backend PID: $BACKEND_PID"
                                    
                                    if ps -p $BACKEND_PID > /dev/null 2>&1; then
                                        echo "✅ Backend process is running (PID: $BACKEND_PID)"
                                    else
                                        echo "❌ Backend process not found (PID: $BACKEND_PID)"
                                        echo "Process list:"
                                        ps aux | grep python | grep -v grep || echo "No Python processes"
                                    fi
                                else
                                    echo "❌ Backend PID file not found"
                                    echo "Python processes:"
                                    ps aux | grep python | grep -v grep || echo "No Python processes"
                                fi
                                
                                # 로그 확인
                                sleep 2
                                echo ""
                                echo "=== Backend Initial Logs ==="
                                if [ -f /tmp/backend.log ]; then
                                    echo "Backend log exists, size: $(wc -l < /tmp/backend.log) lines"
                                    echo "--- First 20 lines ---"
                                    head -n 20 /tmp/backend.log
                                    echo "--- Last 10 lines ---"
                                    tail -n 10 /tmp/backend.log
                                else
                                    echo "❌ Backend log file not found"
                                fi
                                
                                # 포트 확인
                                sleep 3
                                echo ""
                                echo "=== Backend Port Check ==="
                                if lsof -i:6010 >/dev/null 2>&1; then
                                    echo "✅ Backend port (6010) is active"
                                    lsof -i:6010
                                else
                                    echo "❌ Backend port (6010) is not active"
                                    echo "Checking alternative ports..."
                                    lsof -i:8000 2>/dev/null || echo "Port 8000 not active"
                                    lsof -i:8080 2>/dev/null || echo "Port 8080 not active"
                                fi
                                
                                # 백엔드가 실행되지 않은 경우 추가 디버그
                                if ! lsof -i:6010 >/dev/null 2>&1; then
                                    echo ""
                                    echo "=== Backend Debug Information ==="
                                    echo "Current working directory: $(pwd)"
                                    echo "Backend directory contents:"
                                    ls -la backend/ || echo "Backend directory not accessible"
                                    
                                    echo ""
                                    echo "Full backend log:"
                                    cat /tmp/backend.log 2>/dev/null || echo "No backend log available"
                                    
                                    echo ""
                                    echo "Python processes:"
                                    ps aux | grep python | grep -v grep
                                    
                                    echo ""
                                    echo "Network connections:"
                                    netstat -tln 2>/dev/null | grep -E "(600|800)" || echo "No relevant ports found"
                                    
                                    echo ""
                                    echo "❌ Backend startup failed - check logs above"
                                fi
                                
                                echo ""
                                echo "=== Starting Frontend ==="
                                if [ -f frontend/package.json ]; then
                                    cd frontend
                                    
                                    # .env 생성
                                    echo "REACT_APP_API_URL=http://127.0.0.1:6010" > .env
                                    echo "REACT_APP_ENV=production" >> .env
                                    
                                    if command -v npm >/dev/null; then
                                        echo "Installing frontend dependencies..."
                                        [ ! -d node_modules ] && npm install --silent
                                        
                                        echo "Starting frontend server..."
                                        nohup npm start > /tmp/frontend.log 2>&1 &
                                        FRONTEND_PID=$!
                                        echo "Frontend started with PID: $FRONTEND_PID"
                                    fi
                                    cd ..
                                else
                                    echo "❌ Frontend package.json not found"
                                fi
                                
                                echo ""
                                echo "=== Final Status Check ==="
                                sleep 5
                                
                                # 최종 포트 확인
                                echo "Port status:"
                                for port in 6010 6009; do
                                    if lsof -i:$port >/dev/null 2>&1; then
                                        echo "✅ Port $port: ACTIVE"
                                    else
                                        echo "❌ Port $port: INACTIVE"
                                    fi
                                done
                                
                                echo ""
                                echo "=== Service URLs ==="
                                echo "Backend: http://127.0.0.1:6010"
                                echo "Frontend: http://127.0.0.1:6009"
                                echo "API Docs: http://127.0.0.1:6010/docs"
                                echo ""
                                echo "💡 Monitor logs:"
                                echo "   Backend: tail -f /tmp/backend.log"
                                echo "   Frontend: tail -f /tmp/frontend.log"
                            '
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
                            echo "=== Post-Deployment Health Check ==="
                            
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 '
                                sleep 10
                                
                                echo "=== Service Health Check (10s after start) ==="
                                
                                # 백엔드 헬스체크
                                echo "Testing backend connectivity..."
                                if curl -s --connect-timeout 5 http://localhost:6010 >/dev/null 2>&1; then
                                    echo "✅ Backend API responding"
                                elif curl -s --connect-timeout 5 http://localhost:6010/health >/dev/null 2>&1; then
                                    echo "✅ Backend health endpoint responding"
                                elif curl -s --connect-timeout 5 http://localhost:6010/docs >/dev/null 2>&1; then
                                    echo "✅ Backend docs endpoint responding"
                                else
                                    echo "⚠️ Backend not responding to HTTP requests"
                                    
                                    echo "Process check:"
                                    ps aux | grep "python.*main.py" | grep -v grep || echo "No backend process found"
                                    
                                    echo "Port check:"
                                    lsof -i:6010 2>/dev/null || echo "Port 6010 not in use"
                                    
                                    echo "Recent backend logs:"
                                    tail -n 20 /tmp/backend.log 2>/dev/null || echo "No backend log"
                                fi
                                
                                # 프론트엔드 헬스체크
                                echo ""
                                echo "Testing frontend connectivity..."
                                if curl -s --connect-timeout 5 http://localhost:6009 >/dev/null 2>&1; then
                                    echo "✅ Frontend responding"
                                else
                                    echo "⚠️ Frontend not responding"
                                    ps aux | grep "npm start" | grep -v grep || echo "No frontend process found"
                                fi
                                
                                echo ""
                                echo "=== Final Logs Summary ==="
                                if [ -f /tmp/backend.log ]; then
                                    echo "Backend log (last 15 lines):"
                                    tail -n 15 /tmp/backend.log
                                    echo ""
                                fi
                                
                                if [ -f /tmp/frontend.log ]; then
                                    echo "Frontend log (last 10 lines):"
                                    tail -n 10 /tmp/frontend.log
                                    echo ""
                                fi
                            '
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
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 '
                                echo "=== Stopping Services ==="
                                
                                # 실행 중인 서비스 확인
                                echo "=== Current Service Status ==="
                                lsof -i:6010 2>/dev/null && echo "Backend (6010) is running" || echo "Backend (6010) not running"
                                lsof -i:6009 2>/dev/null && echo "Frontend (6009) is running" || echo "Frontend (6009) not running"
                                
                                # 포트 기반으로 프로세스 종료
                                echo ""
                                echo "=== Stopping Services ==="
                                echo "Stopping backend (port 6010)..."
                                lsof -ti:6010 | xargs -r kill -9 2>/dev/null || echo "No backend process found"
                                
                                echo "Stopping frontend (port 6009)..."
                                lsof -ti:6009 | xargs -r kill -9 2>/dev/null || echo "No frontend process found"
                                
                                # 프로세스 이름으로도 정리
                                echo "Cleaning up by process name..."
                                pkill -f "python.*main.py" 2>/dev/null || echo "No Python main.py process found"
                                pkill -f "npm start" 2>/dev/null || echo "No npm start process found"
                                pkill -f "node.*react-scripts" 2>/dev/null || echo "No React process found"
                                
                                # PID 파일 정리
                                rm -f /tmp/backend.pid
                                
                                sleep 3
                                
                                # 최종 확인
                                echo ""
                                echo "=== Final Status Check ==="
                                lsof -i:6010 2>/dev/null && echo "⚠️ Backend (6010) still running!" || echo "✅ Backend (6010) stopped"
                                lsof -i:6009 2>/dev/null && echo "⚠️ Frontend (6009) still running!" || echo "✅ Frontend (6009) stopped"
                                
                                echo ""
                                echo "=== Services Stop Complete ==="
                            '
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
                    sh '''
                        echo "=== POST-BUILD SUMMARY ==="
                        ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 '
                            echo "Final process status:"
                            ps aux | grep -E "(python.*main|npm start)" | grep -v grep || echo "No target processes running"
                            
                            echo ""
                            echo "Final port status:"
                            lsof -i:6010 2>/dev/null || echo "Port 6010 inactive"
                            lsof -i:6009 2>/dev/null || echo "Port 6009 inactive"
                            
                            if [ -f /tmp/backend.log ]; then
                                echo ""
                                echo "Backend log summary (last 10 lines):"
                                tail -n 10 /tmp/backend.log
                            fi
                        '
                    '''
                }
            }
        }
        success {
            script {
                if (params.ACTION == 'DEPLOY') {
                    echo '🎉 Deployment Successful!'
                    echo '================================'
                    echo 'Access your application:'
                    echo 'Frontend: http://127.0.0.1:6009'
                    echo 'Backend: http://127.0.0.1:6010'
                    echo 'API Docs: http://127.0.0.1:6010/docs'
                    echo '================================'
                } else {
                    echo '🛑 Services Stopped Successfully!'
                }
            }
        }
        failure {
            script {
                if (params.ACTION == 'DEPLOY') {
                    echo '❌ Deployment failed. Check logs above for details.'
                } else {
                    echo '❌ Stop operation failed.'
                }
            }
        }
    }
}

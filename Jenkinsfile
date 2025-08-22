pipeline {
    agent any

    stages {
        stage('Deploy and Run') {
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        sh '''
                            # 파일 복사
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 "mkdir -p /home/nextits4/workspace/quantas && rm -rf /home/nextits4/workspace/quantas/*"
                            scp -o StrictHostKeyChecking=no -P 2226 -r ./* nextits4@127.0.0.1:/home/nextits4/workspace/quantas/
                            
                            # 서버 실행
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 '
                                cd /home/nextits4/workspace/quantas
                                
                                # procps 설치 (ps 명령어 포함)
                                echo "=== Installing process tools ==="
                                sudo dnf install -y procps-ng 2>/dev/null || sudo yum install -y procps-ng 2>/dev/null || echo "procps already installed or not available"
                                
                                # Conda 환경 확인
                                echo "=== Environment Setup ==="
                                if [ -f /opt/conda/bin/activate ]; then
                                    source /opt/conda/bin/activate quantas
                                    echo "Conda environment activated"
                                else
                                    echo "Warning: Conda not found. Using system Python"
                                    which python3 || which python
                                fi
                                
                                # 기존 프로세스 종료
                                echo "=== Stopping existing processes ==="
                                # Python 프로세스 종료
                                if command -v pgrep >/dev/null 2>&1; then
                                    pgrep -f "python.*main.py" | xargs -r kill -9 || true
                                    pgrep -f "npm.*start" | xargs -r kill -9 || true
                                else
                                    ps aux 2>/dev/null | grep "[p]ython.*main.py" | awk "{print \\$2}" | xargs -r kill -9 || true
                                    ps aux 2>/dev/null | grep "[n]pm.*start" | awk "{print \\$2}" | xargs -r kill -9 || true
                                fi
                                sleep 3
                                
                                # 백엔드 의존성 설치 및 실행
                                echo "=== Starting backend ==="
                                if [ -f backend/main.py ]; then
                                    cd backend
                                    # Python 의존성 설치 (필요한 경우)
                                    pip install uvicorn fastapi python-multipart || echo "Dependencies already installed"
                                    nohup python main.py > /tmp/backend.log 2>&1 &
                                    BACKEND_PID=$!
                                    echo "Backend started with PID: $BACKEND_PID"
                                    cd ..
                                else
                                    echo "Backend main.py not found"
                                    ls -la backend/ 2>/dev/null || echo "Backend directory not found"
                                fi
                                
                                # 프론트엔드 환경 설정 및 실행
                                echo "=== Starting frontend ==="
                                if [ -f frontend/package.json ]; then
                                    cd frontend
                                    
                                    # .env 파일 생성 (없는 경우)
                                    if [ ! -f .env ]; then
                                        echo "Creating .env file..."
                                        cat > .env << EOF
REACT_APP_API_URL=http://127.0.0.1:8502
REACT_APP_ENV=production
EOF
                                    fi
                                    
                                    if command -v npm >/dev/null 2>&1; then
                                        # 의존성 설치 (필요한 경우)
                                        if [ ! -d node_modules ]; then
                                            echo "Installing npm dependencies..."
                                            npm install
                                        fi
                                        nohup npm start > /tmp/frontend.log 2>&1 &
                                        FRONTEND_PID=$!
                                        echo "Frontend started with PID: $FRONTEND_PID"
                                    else
                                        echo "npm not found"
                                    fi
                                    cd ..
                                else
                                    echo "Frontend package.json not found"
                                    ls -la frontend/ 2>/dev/null || echo "Frontend directory not found"
                                fi
                                
                                # 프로세스 상태 확인
                                echo "=== Process Status Check ==="
                                sleep 5
                                
                                # 백엔드 확인
                                if command -v pgrep >/dev/null 2>&1; then
                                    BACKEND_COUNT=$(pgrep -f "python.*main.py" | wc -l)
                                    FRONTEND_COUNT=$(pgrep -f "npm.*start" | wc -l)
                                else
                                    BACKEND_COUNT=$(ps aux 2>/dev/null | grep "[p]ython.*main.py" | wc -l || echo 0)
                                    FRONTEND_COUNT=$(ps aux 2>/dev/null | grep "[n]pm.*start" | wc -l || echo 0)
                                fi
                                
                                echo "Backend processes: $BACKEND_COUNT"
                                echo "Frontend processes: $FRONTEND_COUNT"
                                
                                # 포트 확인
                                echo "=== Port Status ==="
                                if command -v netstat >/dev/null 2>&1; then
                                    netstat -tlnp 2>/dev/null | grep ":8502" && echo "Backend port 8502 active" || echo "Backend port 8502 not active"
                                    netstat -tlnp 2>/dev/null | grep ":8503" && echo "Frontend port 8503 active" || echo "Frontend port 8503 not active"
                                else
                                    echo "netstat not available, skipping port check"
                                fi
                                
                                # 로그 확인
                                echo "=== Logs ==="
                                if [ -f /tmp/backend.log ]; then
                                    echo "Backend log (last 5 lines):"
                                    tail -n 5 /tmp/backend.log
                                else
                                    echo "No backend log found"
                                fi
                                
                                if [ -f /tmp/frontend.log ]; then
                                    echo "Frontend log (last 5 lines):"
                                    tail -n 5 /tmp/frontend.log
                                else
                                    echo "No frontend log found"
                                fi
                                
                                echo "=== Access URLs ==="
                                echo "Backend API: http://127.0.0.1:8502"
                                echo "Backend Docs: http://127.0.0.1:8502/docs"
                                echo "Frontend App: http://127.0.0.1:8503"
                                echo "Deployment completed!"
                            '
                        '''
                    }
                }
            }
        }
    }
    
    post {
        success {
            echo 'Deployment successful!'
            echo 'Access URLs:'
            echo 'Backend: http://127.0.0.1:8502'
            echo 'Frontend: http://127.0.0.1:8503'
        }
        failure {
            echo 'Deployment failed. Check logs for details.'
        }
    }
}

pipeline {
    agent any

    stages {
        stage('Build and Run on Remote Server') {
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        sh '''
                            # 1. 원격 서버에 디렉토리 생성 및 정리
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 "
                                mkdir -p /home/nextits4/workspace/quantas
                                rm -rf /home/nextits4/workspace/quantas/*
                            "
                            
                            # 2. Jenkins workspace의 파일들을 원격 서버로 복사
                            scp -o StrictHostKeyChecking=no -P 2226 -r ./* nextits4@127.0.0.1:/home/nextits4/workspace/quantas/
                            
                            # 3. 원격 서버에서 애플리케이션 실행
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 "
                                cd /home/nextits4/workspace/quantas
                                
                                # Conda 환경 활성화
                                echo 'Activating Conda environment...'
                                if [ -f /opt/conda/bin/activate ]; then
                                    source /opt/conda/bin/activate quantas
                                    echo 'Conda environment activated'
                                else
                                    echo 'Warning: Conda not found. Using system Python'
                                    which python3 || which python
                                fi
                                
                                # 기존 프로세스 종료 (pgrep 대신 ps 사용)
                                echo 'Stopping existing processes...'
                                # Python 프로세스 종료
                                ps aux | grep '[p]ython.*main.py' | awk '{print \$2}' | xargs -r kill -9 || true
                                # npm/node 프로세스 종료
                                ps aux | grep '[n]pm.*start' | awk '{print \$2}' | xargs -r kill -9 || true
                                ps aux | grep '[n]ode.*start' | awk '{print \$2}' | xargs -r kill -9 || true
                                sleep 3
                                
                                # 백엔드 서버 실행 (올바른 경로)
                                echo 'Starting backend server...'
                                if [ -d backend ] && [ -f backend/main.py ]; then
                                    cd backend/
                                    nohup python main.py > /tmp/backend.log 2>&1 &
                                    BACKEND_PID=\$!
                                    echo \"Backend started successfully (PID: \$BACKEND_PID)\"
                                    cd ..
                                else
                                    echo 'ERROR: Backend directory or main.py not found!'
                                    echo 'Current directory contents:'
                                    ls -la
                                fi
                                
                                # 프론트엔드 서버 실행 (올바른 경로)
                                echo 'Starting frontend server...'
                                if [ -d frontend ] && [ -f frontend/package.json ]; then
                                    cd frontend/
                                    if command -v npm >/dev/null 2>&1; then
                                        # 의존성 설치 (필요한 경우)
                                        if [ ! -d node_modules ]; then
                                            echo 'Installing npm dependencies...'
                                            npm install
                                        fi
                                        nohup npm start > /tmp/frontend.log 2>&1 &
                                        FRONTEND_PID=\$!
                                        echo \"Frontend started successfully (PID: \$FRONTEND_PID)\"
                                    else
                                        echo 'ERROR: npm not found. Please install Node.js'
                                    fi
                                    cd ..
                                else
                                    echo 'ERROR: Frontend directory or package.json not found!'
                                    echo 'Current directory contents:'
                                    ls -la
                                fi
                                
                                # 프로세스 상태 확인 (ps 사용)
                                echo 'Checking server status...'
                                sleep 3
                                echo 'Running processes:'
                                
                                # Python 프로세스 확인
                                PYTHON_PROCESSES=\$(ps aux | grep '[p]ython.*main.py' | wc -l)
                                if [ \$PYTHON_PROCESSES -gt 0 ]; then
                                    echo \"Backend: \$PYTHON_PROCESSES python process(es) running\"
                                    ps aux | grep '[p]ython.*main.py'
                                else
                                    echo 'Backend: No python processes running'
                                fi
                                
                                # npm/node 프로세스 확인
                                NPM_PROCESSES=\$(ps aux | grep '[n]pm\\|[n]ode' | grep -v grep | wc -l)
                                if [ \$NPM_PROCESSES -gt 0 ]; then
                                    echo \"Frontend: \$NPM_PROCESSES npm/node process(es) running\"
                                    ps aux | grep '[n]pm\\|[n]ode' | grep -v grep
                                else
                                    echo 'Frontend: No npm/node processes running'
                                fi
                                
                                # 로그 파일 확인
                                echo 'Log file status:'
                                if [ -f /tmp/backend.log ]; then
                                    echo 'Backend log (last 5 lines):'
                                    tail -n 5 /tmp/backend.log
                                else
                                    echo 'No backend log file found'
                                fi
                                
                                if [ -f /tmp/frontend.log ]; then
                                    echo 'Frontend log (last 5 lines):'
                                    tail -n 5 /tmp/frontend.log
                                else
                                    echo 'No frontend log file found'
                                fi
                                
                                echo 'Deployment completed successfully!'
                            "
                        '''
                    }
                }
            }
        }
    }
    
    post {
        always {
            echo 'Pipeline execution completed'
        }
        success {
            echo 'Deployment successful! Check the logs above for server status.'
        }
        failure {
            echo 'Deployment failed. Check the console output for details.'
        }
    }
}

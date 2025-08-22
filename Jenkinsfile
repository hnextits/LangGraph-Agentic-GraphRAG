pipeline {
    agent any

    stages {
        stage('Build and Run on Remote Server') {
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        // nextits_ai_4 컨테이너에 원격 접속하여 명령어 실행
                        sh '''
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 "
                                # 변수 설정
                                WORKSPACE_DIR=/home/nextits4/workspace
                                PROJECT_DIR=\\$WORKSPACE_DIR/quantas
                                REPO_URL=https://github.com/hnextits/nextitslm.git
                                
                                # 1. 작업 공간 디렉토리 생성
                                echo Creating workspace directory if not exists...
                                mkdir -p \\$WORKSPACE_DIR
                                cd \\$WORKSPACE_DIR
                                
                                # 2. Git repository 처리 (clone 또는 pull)
                                if [ -d \\$PROJECT_DIR ] && [ -d \\$PROJECT_DIR/.git ]; then
                                    echo Project directory exists. Pulling latest changes...
                                    cd \\$PROJECT_DIR
                                    git stash || true
                                    git pull origin main
                                else
                                    echo Project directory does not exist. Cloning repository...
                                    rm -rf \\$PROJECT_DIR
                                    git clone \\$REPO_URL \\$PROJECT_DIR
                                    cd \\$PROJECT_DIR
                                fi

                                # 3. Conda 환경 활성화
                                echo Activating Conda environment...
                                if [ -f /opt/conda/bin/activate ]; then
                                    source /opt/conda/bin/activate quantas
                                    echo Conda environment activated
                                else
                                    echo Warning: Conda not found. Using system Python
                                    which python3 || which python
                                fi
                                
                                # 4. 기존 프로세스 종료 (포트 충돌 방지)
                                echo Stopping existing processes...
                                killall python || true
                                killall npm || true
                                killall node || true
                                sleep 3

                                # 5. 백엔드 서버 실행 (백그라운드에서 실행)
                                echo Starting backend server...
                                BACKEND_DIR=\\$PROJECT_DIR/nextitslm/backend
                                if [ -d \\$BACKEND_DIR ] && [ -f \\$BACKEND_DIR/main.py ]; then
                                    cd \\$BACKEND_DIR
                                    nohup python main.py > /tmp/backend.log 2>&1 &
                                    echo Backend started successfully
                                else
                                    echo ERROR: Backend directory or main.py not found!
                                    echo Current directory structure:
                                    ls -la \\$PROJECT_DIR/
                                    [ -d \\$PROJECT_DIR/nextitslm ] && ls -la \\$PROJECT_DIR/nextitslm/
                                fi

                                # 6. 프론트엔드 서버 실행 (백그라운드에서 실행)
                                echo Starting frontend server...
                                FRONTEND_DIR=\\$PROJECT_DIR/nextitslm/frontend
                                if [ -d \\$FRONTEND_DIR ] && [ -f \\$FRONTEND_DIR/package.json ]; then
                                    cd \\$FRONTEND_DIR
                                    if command -v npm >/dev/null 2>&1; then
                                        # 의존성이 설치되어 있는지 확인
                                        if [ ! -d node_modules ]; then
                                            echo Installing npm dependencies...
                                            npm install
                                        fi
                                        nohup npm start > /tmp/frontend.log 2>&1 &
                                        echo Frontend started successfully
                                    else
                                        echo ERROR: npm not found. Please install Node.js
                                    fi
                                else
                                    echo ERROR: Frontend directory or package.json not found!
                                    echo Current directory structure:
                                    ls -la \\$PROJECT_DIR/
                                    [ -d \\$PROJECT_DIR/nextitslm ] && ls -la \\$PROJECT_DIR/nextitslm/
                                fi
                                
                                # 7. 프로세스 상태 확인
                                echo Checking server status...
                                sleep 5
                                echo Running processes:
                                ps aux | grep -E python.*main || echo No backend processes running
                                ps aux | grep -E npm.*start || echo No frontend processes running
                                
                                # 8. 로그 파일 확인
                                echo Log file status:
                                if [ -f /tmp/backend.log ]; then
                                    echo Backend log last 3 lines:
                                    tail -n 3 /tmp/backend.log
                                fi
                                if [ -f /tmp/frontend.log ]; then
                                    echo Frontend log last 3 lines:
                                    tail -n 3 /tmp/frontend.log
                                fi

                                echo Servers deployment completed.
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
            echo 'Deployment successful! Servers are running.'
        }
        failure {
            echo 'Deployment failed. Check the console output for details.'
        }
    }
}

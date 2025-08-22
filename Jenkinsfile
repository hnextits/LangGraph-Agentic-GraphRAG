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
                                # 1. 이 프로젝트를 빌드할 작업 공간으로 이동
                                cd /home/nextits4/workspace/quantas

                                # 2. 최신 소스 코드를 받아옴
                                git pull

                                # 3. Conda 환경 활성화
                                echo "Activating Conda environment..."
                                source /opt/conda/bin/activate quantas

                                # 4. 백엔드 서버 실행 (백그라운드에서 실행)
                                echo "Starting backend server..."
                                cd nextitslm/backend/
                                nohup python main.py &

                                # 5. 프론트엔드 서버 실행 (백그라운드에서 실행)
                                echo "Starting frontend server..."
                                cd nextitslm/frontend/
                                nohup npm start &

                                echo "Servers started."
                            "
                        '''
                    }
                }
            }
        }
    }
}

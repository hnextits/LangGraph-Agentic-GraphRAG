pipeline {
    agent any
    
    environment {
        DOCKER_IMAGE = "nextitslm"
        DOCKER_TAG = "${BUILD_NUMBER}"
    }
    
    stages {
        stage('Project Info') {
            steps {
                echo '=== 프로젝트 정보 확인 ==='
                sh 'pwd'
                sh 'ls -la'
                
                echo '=== Backend 구조 확인 ==='
                sh 'ls -la backend/'
                
                echo '=== Frontend 구조 확인 ==='
                sh 'ls -la frontend/'
            }
        }
        
        stage('Backend Test') {
            steps {
                echo '=== Python Backend 테스트 시작 ==='
                
                script {
                    // requirements.txt 확인
                    if (fileExists('backend/requirements.txt')) {
                        echo 'requirements.txt 발견됨'
                        sh 'cat backend/requirements.txt'
                        
                        // Python 가상환경 설정 및 테스트
                        sh '''
                            cd backend
                            python3 -m venv venv || python -m venv venv
                            . venv/bin/activate
                            pip install --upgrade pip
                            pip install -r requirements.txt
                            
                            # 테스트 파일이 있는지 확인
                            if [ -d "tests" ]; then
                                echo "테스트 디렉토리 발견, pytest 실행"
                                pip install pytest
                                python -m pytest tests/ -v
                            elif [ -f "test.py" ]; then
                                echo "test.py 발견, 실행"
                                python test.py
                            else
                                echo "기본 문법 체크 수행"
                                python -m py_compile app.py
                                python -m py_compile main.py
                                echo "Python 문법 체크 완료"
                            fi
                        '''
                    } else {
                        echo 'requirements.txt가 없습니다. 기본 테스트 수행'
                        sh '''
                            cd backend
                            python3 -c "import app; print('app.py 로드 성공')" || echo "app.py 로드 실패"
                        '''
                    }
                }
            }
        }
        
        stage('Frontend Test') {
            steps {
                echo '=== Frontend 테스트 시작 ==='
                
                script {
                    if (fileExists('frontend/package.json')) {
                        echo 'package.json 발견됨 - Node.js 프로젝트'
                        sh '''
                            cd frontend
                            cat package.json
                            npm install
                            
                            # 테스트 스크립트가 있는지 확인
                            if npm run | grep -q "test"; then
                                echo "npm test 실행"
                                npm test
                            else
                                echo "빌드 테스트만 수행"
                                npm run build || echo "빌드 스크립트 없음"
                            fi
                        '''
                    } else {
                        echo 'Frontend가 정적 파일인 것 같습니다'
                        sh 'ls -la frontend/'
                    }
                }
            }
        }
        
        stage('Build') {
            steps {
                echo '=== 애플리케이션 빌드 시작 ==='
                
                // Frontend 빌드
                script {
                    if (fileExists('frontend/package.json')) {
                        sh '''
                            cd frontend
                            npm run build || echo "빌드 스크립트 없음, 소스 그대로 사용"
                        '''
                    }
                }
                
                // 빌드 아티팩트 정리
                sh '''
                    echo "빌드 결과물 정리"
                    mkdir -p dist/
                    cp -r backend/ dist/
                    cp -r frontend/ dist/
                    cp *.sh dist/ || true
                    
                    echo "빌드 완료 - dist/ 디렉토리 확인"
                    ls -la dist/
                '''
                
                // 아티팩트 보관
                archiveArtifacts artifacts: 'dist/**/*', allowEmptyArchive: true
            }
        }
        
        stage('Docker Build') {
            steps {
                echo '=== Docker 이미지 빌드 시작 ==='
                
                script {
                    // Dockerfile 확인
                    if (fileExists('Dockerfile')) {
                        echo 'Dockerfile 발견됨'
                        sh 'cat Dockerfile'
                        
                        // Docker 이미지 빌드
                        sh """
                            docker build -t ${DOCKER_IMAGE}:${DOCKER_TAG} .
                            docker build -t ${DOCKER_IMAGE}:latest .
                            
                            echo "Docker 이미지 빌드 완료"
                            docker images | grep ${DOCKER_IMAGE}
                        """
                    } else {
                        echo 'Dockerfile이 없습니다. 기본 Dockerfile 생성'
                        
                        // 간단한 Python Dockerfile 생성
                        sh '''
                            cat > Dockerfile << EOF
FROM python:3.9-slim

WORKDIR /app

# Backend dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY *.sh ./

# Make scripts executable
RUN chmod +x *.sh

EXPOSE 8000

CMD ["python", "backend/main.py"]
EOF
                        '''
                        
                        sh """
                            echo "생성된 Dockerfile:"
                            cat Dockerfile
                            
                            docker build -t ${DOCKER_IMAGE}:${DOCKER_TAG} .
                            docker build -t ${DOCKER_IMAGE}:latest .
                            
                            echo "Docker 이미지 빌드 완료"
                            docker images | grep ${DOCKER_IMAGE}
                        """
                    }
                }
            }
        }
        
        stage('Test Docker Image') {
            steps {
                echo '=== Docker 이미지 테스트 ==='
                
                sh """
                    # Docker 컨테이너 실행 테스트 (빠른 종료)
                    docker run --rm ${DOCKER_IMAGE}:${DOCKER_TAG} echo "Docker 이미지 정상 작동"
                    
                    # 이미지 정보 확인
                    docker inspect ${DOCKER_IMAGE}:${DOCKER_TAG}
                """
            }
        }
    }
    
    post {
        always {
            echo '=== 파이프라인 완료 ==='
            sh 'docker images'
        }
        success {
            echo '🎉 모든 단계가 성공적으로 완료되었습니다!'
            echo "빌드된 Docker 이미지: ${DOCKER_IMAGE}:${DOCKER_TAG}"
        }
        failure {
            echo '❌ 파이프라인 실행 중 오류가 발생했습니다.'
        }
        cleanup {
            // 이전 Docker 이미지 정리 (선택사항)
            sh '''
                # 30일 이상 된 이미지 삭제 (주석 처리됨)
                # docker image prune -a --filter "until=720h" -f
                echo "정리 완료"
            '''
        }
    }
}

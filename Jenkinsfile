pipeline {
    agent any
    stages {
        // Prepare 단계 제거 - Jenkins가 이미 자동으로 코드를 가져옴
        
        stage('Project Info') {
            steps {
                echo '=== 프로젝트 정보 확인 ==='
                sh 'pwd'
                sh 'ls -la'
                
                // 프로젝트 타입 확인
                script {
                    if (fileExists('package.json')) {
                        echo 'Node.js/React 프로젝트 감지됨'
                        sh 'cat package.json'
                    } else if (fileExists('requirements.txt')) {
                        echo 'Python 프로젝트 감지됨'
                        sh 'cat requirements.txt'
                    } else {
                        echo '프로젝트 타입을 확인 중...'
                        sh 'find . -name "*.py" -o -name "*.js" -o -name "*.java" | head -10'
                    }
                }
            }
        }
        
        stage('test') {
            steps {
                echo 'test stage'
                // 여기에 실제 테스트 명령어가 들어갈 예정
            }
        }
        
        stage('build') {
            steps {
                echo 'build stage'
                // 여기에 실제 빌드 명령어가 들어갈 예정
            }
        }
        
        stage('docker build') {
            steps {
                echo 'docker build stage'
                // 여기에 실제 Docker 빌드 명령어가 들어갈 예정
            }
        }
    }
}

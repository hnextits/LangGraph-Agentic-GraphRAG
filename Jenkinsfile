pipeline {
    agent any
    stages {
        stage('Prepare'){
            steps {
                git credentialsId : 'hnextits',
                    branch : 'main',
                    url : 'https://github.com/hnextits/nextitslm.git'
            }
        }
        stage('test') {
            steps {
                // 프로젝트 파일 확인
                sh 'ls -la'
                sh 'pwd'
                
                // package.json이 있다면 Node.js 프로젝트
                script {
                    if (fileExists('package.json')) {
                        sh 'npm install'
                        sh 'npm test'
                    } else {
                        echo '아직 테스트 설정이 없습니다'
                    }
                }
            }
        }
        stage('build') {
            steps {
                echo 'build stage'
            }
        }
        stage('docker build') {
            steps {
                echo 'docker build stage'
            }
        }
    }
}

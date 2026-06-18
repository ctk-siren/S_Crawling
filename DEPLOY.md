# Oracle Cloud 배포 가이드

세이렌 크롤링 대시보드를 Oracle Cloud Free Tier 서버에 올려 24시간 자동 운영한다.
서버 OS 는 Ubuntu 기준으로 적고, Oracle Linux 차이는 각 단계에 따로 표시한다.

> 전제 — Oracle Cloud 인스턴스(VM)가 이미 생성돼 있고, 공인 IP 와 SSH 접속이 가능해야 한다.
> 접속 예: `ssh -i 내키.pem ubuntu@<공인IP>`  (Oracle Linux 는 사용자명이 `opc`)

---

## 1. 서버 기본 패키지 설치

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```
Oracle Linux:
```bash
sudo dnf install -y python3 git
```

## 2. 코드 가져오기 (GitHub Private)

Private 저장소라 인증이 필요하다. 둘 중 하나.
- **개인 액세스 토큰(PAT)** — 클론 시 비밀번호 자리에 토큰 입력
- **배포용 SSH 키** — 서버에서 `ssh-keygen` 후 공개키를 GitHub 저장소 Deploy keys 에 등록

```bash
cd ~
git clone https://github.com/<계정>/<저장소>.git Siren_crawling
cd Siren_crawling
```

## 3. 가상환경 + 패키지 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-deploy.txt
```

## 4. 서비스키 파일 생성 (g2b·iris API 용)

`service_key.txt` 는 깃에 올라가지 않으므로 서버에서 직접 만든다.
```bash
echo '여기에_data.go.kr_인증키' > service_key.txt
```
> g2b·iris 를 쓰지 않으면 이 단계는 건너뛰어도 된다(나머지 3개 사이트는 키 없이 동작).

## 5. 실행 테스트

```bash
# 수집·DB·웹이 뜨는지 임시로 확인
.venv/bin/gunicorn --workers 1 --threads 4 --bind 0.0.0.0:5000 wsgi:app
```
다른 터미널에서 `curl http://localhost:5000` 가 HTML 을 반환하면 정상. 확인 후 Ctrl+C.

## 6. 방화벽 열기 (port 5000) — 2곳 모두 열어야 함

### 6-1. OCI 보안 목록(Security List) — 클라우드 콘솔
Oracle Cloud 콘솔 → 해당 VCN → Security Lists → Ingress Rules 추가
- Source CIDR: `0.0.0.0/0`
- IP Protocol: TCP
- Destination Port Range: `5000`

### 6-2. 인스턴스 자체 방화벽
Ubuntu(iptables):
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 5000 -j ACCEPT
sudo netfilter-persistent save
```
Oracle Linux(firewalld):
```bash
sudo firewall-cmd --permanent --add-port=5000/tcp
sudo firewall-cmd --reload
```

## 7. systemd 서비스 등록 (자동 시작·재시작)

`siren.service` 파일의 `User`, `WorkingDirectory`, `ExecStart` 경로를 서버에 맞게 수정한 뒤:
```bash
sudo cp siren.service /etc/systemd/system/siren.service
sudo systemctl daemon-reload
sudo systemctl enable --now siren
sudo systemctl status siren      # active(running) 확인
journalctl -u siren -f           # 로그 실시간 보기
```

## 8. 접속

브라우저에서 `http://<공인IP>:5000` 접속.
- 1페이지(공고)에서 **지금 수집**을 한 번 눌러 즉시 데이터를 채운다.
- 이후 매일 오전 8시(KST) 자동 수집된다.

---

## 코드 업데이트 배포

로컬에서 커밋·푸시한 뒤 서버에서:
```bash
cd ~/Siren_crawling
git pull
source .venv/bin/activate
pip install -r requirements.txt -r requirements-deploy.txt   # 의존성 바뀐 경우만
sudo systemctl restart siren
```

## (선택) 80포트로 보기 좋게 — nginx 리버스 프록시

5000 대신 일반 웹 포트(80)로 접속하려면 nginx 를 앞에 둔다.
```bash
sudo apt install -y nginx
sudo tee /etc/nginx/sites-available/siren >/dev/null <<'EOF'
server {
    listen 80;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF
sudo ln -s /etc/nginx/sites-available/siren /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx
```
이 경우 6단계에서 5000 대신 **80** 포트를 연다. (gunicorn 은 그대로 5000 유지)

---

## 문제 해결

| 증상 | 확인 |
|------|------|
| 접속이 안 됨 | 방화벽 2곳(6-1 OCI, 6-2 인스턴스) 모두 열었는지 |
| 서비스가 안 뜸 | `journalctl -u siren -n 50` 로그 확인. 경로·사용자명 오타 흔함 |
| g2b·iris 0건 | `service_key.txt` 내용·승인 상태 확인. 키 없으면 빈 결과는 정상 |
| 자동 수집이 두 번 됨 | gunicorn 워커가 1개인지 확인(`--workers 1`) |
| 시간대가 안 맞음 | 스케줄러는 Asia/Seoul 고정. 서버 시계와 무관하게 08:00 KST 실행 |

## 참고 — 메모리(1GB) 주의
- gunicorn 워커 1개 + 스레드 4개로 충분하다. 워커를 늘리지 말 것(메모리·스케줄러 중복).
- 수집은 하루 1회 약 20초짜리 작업이라 상시 부하는 거의 없다.

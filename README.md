# ToyotaGPT Jetson VLM Platform

車載カメラ、YOLO、VLM、CAN-FD、GNSS、AWSを統合した
NVIDIA Jetson AGX Orin向けVLMプラットフォーム。

このリポジトリには、アプリケーションコード、Docker構成、
設定ファイル、評価スクリプトなどを保存する。

モデル本体、実行ログ、動画、認証情報、キャッシュなどの
大容量または実行環境依存データはGit管理対象外とする。


# 1. 基準開発環境

基準Jetson:

- NVIDIA Jetson AGX Orin Developer Kit 64GB
- Ubuntu 22.04.5
- JetPack 6.2
- L4T R36.5.0
- Kernel 5.15系
- Docker CE
- Docker Compose
- NVIDIA Container Toolkit
- CUDA対応PyTorch
- FastAPI
- Ultralytics YOLO
- Hugging Face Transformers

基準ストレージ:

    /mnt/vlm_data

基準プロジェクトパス:

    /mnt/vlm_data/vlm-platform


# 2. システム概要

主要データフロー:

    Camera / Video
          |
          v
       Vision
          |
          +----> YOLO
          |
          +----> VLM
                    |
                    v
            Event / Risk 判定
                    |
                    v
            Secondary Validation
                    |
                    v
              Event Bundle
                    |
                    v
              AWS Upload
              S3 + DynamoDB

並行して以下を取得する。

- Camera
- CAN-FD
- GNSS
- YOLO推論結果
- VLM推論結果

FastAPI / Web UIから状態確認および制御を行う。


# 3. 主なディレクトリ

    app/
      api/                  FastAPI / Web UI API
      modules/
        can/                CAN decode
        detection/          YOLO
        input/              Camera / Video input
        pipeline/           Inference pipeline
        policy/             Event / Risk / Speech policy
        speech/             Speech / TTS
        vlm/                VLM backend
        workers/            CAN / GPS / YOLO / VLM / Upload workers
      runtime/              Runtime state / Event buffer

    docker/
      Dockerfile.jetson
      Dockerfile.ollama_jetson

    scripts/                Utility scripts
    tools/                  Utility tools
    vlm_eval/               VLM evaluation
    yolo_eval/              YOLO evaluation

    config.yaml
    docker-compose.jetson.yml
    requirements.txt
    requirements.hf.current.txt


# 4. Gitに含まれないもの

.gitignoreにより以下はGit管理対象外。

- .cache/
- logs/
- .env
- .env.*
- __pycache__/
- *.pyc
- *.pt
- *.pth
- *.onnx
- *.engine
- *.safetensors
- data/*.MOV
- data/*.mov
- data/*.mp4
- data/*.avi
- data/*.mkv
- core.*
- 各種backup / temporary file

したがって、別Jetsonへgit cloneしただけでは
完全な実行環境にはならない。

特に以下は別途準備が必要。

- Hugging Face VLM model
- YOLO model weights
- Camera driver
- CAN-FD driver
- GNSS device
- AWS credentials
- Docker / NVIDIA Container Toolkit
- /mnt/vlm_data のストレージ環境


# 5. 新しいJetsonへのGit clone

既存環境と同じパス構成にする場合:

    sudo mkdir -p /mnt/vlm_data
    sudo chown $USER:$USER /mnt/vlm_data
    cd /mnt/vlm_data
    git clone https://github.com/TMC-Masaki/toyotagpt-prj.git vlm-platform
    cd /mnt/vlm_data/vlm-platform


# 6. Jetson環境確認

L4T:

    cat /etc/nv_tegra_release

Kernel:

    uname -a

Docker:

    docker --version

Docker Compose:

    docker compose version

NVIDIA Runtime:

    docker info | grep -i runtime

Jetson performance mode:

    sudo nvpmodel -q

必要に応じて:

    sudo jetson_clocks

性能問題を調査する場合:

    tegrastats


# 7. VLM

Primary VLM基準モデル:

    Qwen/Qwen2.5-VL-7B-Instruct

Hugging Faceモデル本体はGitには含めない。

モデルは新Jetsonで取得するか、
基準JetsonのHugging Face cacheをコピーする。

候補cache場所:

    ~/.cache/huggingface/

または環境によって:

    /mnt/vlm_data/vlm-platform/.cache/huggingface/

実際のmount先はdocker-compose.jetson.ymlを確認すること。


# 8. YOLO

YOLO weight (*.pt) はGit管理対象外。

使用してきたweight例:

    yolov8n.pt
    yolov8s.pt
    yolov8m.pt

新Jetsonでは必要なweightを別途配置し、
config.yamlの設定と一致させる。


# 9. Camera

基準Camera:

    TIER IV C1-120
    Sony ISX021
    1920 x 1280 @ 30fps
    YUV422

SerDes:

    Serializer   MAX9295A
    Deserializer MAX96712

基準環境ではTIER IV GMSL camera driverを使用。

Camera device確認:

    ls -l /dev/video*

可能なら:

    v4l2-ctl --list-devices

/dev/video0 等の番号はJetson個体や接続状態によって
変化する可能性があるため必ず確認する。


# 10. CAN-FD

使用デバイス:

    IXXAT USB-to-CAN FD

LinuxではSocketCANを使用する。

現在の基準interface:

    can2

確認:

    ip -details link show can2

CAN受信確認:

    candump can2

3BFのみ確認する例:

    candump can2,3BF:7FF

関連実装:

    app/modules/workers/can_worker.py
    app/modules/can/can_decoder.py
    app/api/can_api.py

CAN signal定義はconfig.yamlを参照する。

別Jetsonではinterface名がcan2とは限らないため、
必ず実機確認する。


# 11. GNSS

GNSS関連実装:

    app/modules/workers/gps_worker.py
    app/api/gnss_api.py

GNSS deviceおよび接続設定は、
新しいJetson側のデバイス構成とconfig.yamlを確認する。


# 12. AWS

Event承認後にAWSへアップロードする。

使用サービス:

    Amazon S3
    Amazon DynamoDB

基準設定:

    Region:
    ap-northeast-1

    S3 bucket:
    toyotagpt-masaki

    S3 prefix:
    events

    DynamoDB table:
    toyotagpt-eventdb

AWS credentialはGit管理対象外。

一時credential使用例:

    export AWS_ACCESS_KEY_ID='...'
    export AWS_SECRET_ACCESS_KEY='...'
    export AWS_SESSION_TOKEN='...'
    export AWS_DEFAULT_REGION='ap-northeast-1'

AWS認証確認:

    aws sts get-caller-identity

注意:
ホスト側でexportしたcredentialは、
すでに起動中のDocker containerには自動反映されない。

credential更新後は必要に応じてcontainerを再作成する。

    cd /mnt/vlm_data/vlm-platform
    sudo -E docker compose -f docker-compose.jetson.yml down
    sudo -E docker compose -f docker-compose.jetson.yml up -d


# 13. Docker起動

    cd /mnt/vlm_data/vlm-platform
    sudo -E docker compose -f docker-compose.jetson.yml up -d

状態確認:

    sudo docker compose -f docker-compose.jetson.yml ps

アプリログ:

    sudo docker logs -f vlm_platform


# 14. API確認

FastAPI:

    http://127.0.0.1:8000

Health:

    curl -sS http://127.0.0.1:8000/health

Config:

    curl -sS http://127.0.0.1:8000/config | jq

UI state:

    curl -sS http://127.0.0.1:8000/ui/state | jq

CAN status:

    curl -sS http://127.0.0.1:8000/can/status | jq

CAN signals:

    curl -sS http://127.0.0.1:8000/can/signals | jq

Scheduler:

    curl -sS http://127.0.0.1:8000/scheduler/status | jq


# 15. Local Event Logs

Event保存先:

    /mnt/vlm_data/logs/events/

主な状態:

    pending/
    approved/
    rejected/
    failed/
    uploaded/
    sessions/

Event bundleには環境に応じて以下が保存される。

- frames/primary_input.jpg
- primary_result.txt
- primary_result.json
- secondary_input.json
- secondary_result.txt
- secondary_result.json
- metadata.json
- can_snapshot.json
- gnss_snapshot.json
- clip_pre20s.mp4
- yolo_result.json
- upload_status.json

これらruntime dataはGit管理対象外。


# 16. 別Jetsonでの動作確認順序

一度に全システムをデバッグせず、
下位レイヤから順番に確認する。

1. JetPack / L4T
2. NVMe mount
3. Docker
4. NVIDIA Container Toolkit
5. Camera driver
6. /dev/videoX
7. IXXAT USB-CAN
8. SocketCAN interface
9. candump
10. GNSS
11. YOLO weight
12. Hugging Face VLM model
13. config.yaml
14. Docker build / start
15. /health
16. Camera input
17. YOLO
18. VLM
19. CAN API
20. GNSS API
21. Event save
22. Secondary validation
23. AWS upload


# 17. Git運用

変更前:

    cd /mnt/vlm_data/vlm-platform
    git status

変更確認:

    git status
    git diff

保存:

    git add .
    git commit -m "変更内容"
    git push

別Jetson等で最新化:

    git pull


# 18. Repository

Repository:

    https://github.com/TMC-Masaki/toyotagpt-prj.git

Main branch:

    main

初回Jetson snapshot:

    69a2093
    Initial import of ToyotaGPT Jetson VLM platform


# 19. 注意事項

このGit repositoryだけでハードウェア環境まで
完全再現されるわけではない。

特に以下はJetson個体ごとの差異を確認する。

- /dev/videoX
- CAN interface name
- USB device mapping
- GNSS device
- NVMe mount point
- JetPack / L4T
- Camera driver
- CAN driver
- CUDA / PyTorch compatibility
- Hugging Face model cache
- YOLO weights
- AWS temporary credentials

別Jetsonへの展開時は、
基準Jetsonとの差分を確認してから設定変更すること。

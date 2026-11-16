#!/bin/sh
# Azure 경고 규칙 — 서버가 멈추거나 자원이 모자라면 메일로 알린다. 맥에서 az CLI 로그인 뒤 한 번 실행한다.
#
#   sh deploy/azure_alerts.sh 받을메일주소
#
# 만드는 것 (리소스 그룹 waferai-rg, VM waferai-vm 기준 — 다르면 RG · VM 환경변수로 바꾼다)
#   · 작업 그룹 waferai-ops        메일 받을 곳
#   · waferai-vm-down              VM 가용성 < 1 (5분)        — 서버가 꺼짐
#   · waferai-cpu-high             CPU 평균 > 85% (15분)      — 추론이 몰려 느려짐
#   · waferai-memory-low           사용 가능 메모리 < 300MB (15분)
# 디스크와 백업은 VM 지표로 볼 수 없어 웹 화면(모델 관리 › 서버 상태)에서 본다.
# Azure for Students 크레딧에서 경고 규칙 3개는 무료 한도 안이다.
set -eu
EMAIL="${1:?받을 메일 주소를 인자로 주세요: sh deploy/azure_alerts.sh you@example.com}"
RG="${RG:-waferai-rg}"
VM="${VM:-waferai-vm}"

vm_id=$(az vm show -g "$RG" -n "$VM" --query id -o tsv)
az monitor action-group create -g "$RG" -n waferai-ops --short-name waferai \
    --action email ops "$EMAIL" -o none
group_id=$(az monitor action-group show -g "$RG" -n waferai-ops --query id -o tsv)

az monitor metrics alert create -g "$RG" -n waferai-vm-down --scopes "$vm_id" \
    --condition "avg VmAvailabilityMetric < 1" --window-size 5m --evaluation-frequency 1m \
    --severity 1 --action "$group_id" --description "WaferAI 서버가 응답하지 않습니다" -o none
az monitor metrics alert create -g "$RG" -n waferai-cpu-high --scopes "$vm_id" \
    --condition "avg Percentage CPU > 85" --window-size 15m --evaluation-frequency 5m \
    --severity 3 --action "$group_id" --description "WaferAI 서버 CPU 가 15분 넘게 85% 이상입니다" -o none
az monitor metrics alert create -g "$RG" -n waferai-memory-low --scopes "$vm_id" \
    --condition "avg Available Memory Bytes < 314572800" --window-size 15m --evaluation-frequency 5m \
    --severity 3 --action "$group_id" --description "WaferAI 서버의 사용 가능 메모리가 300MB 아래입니다" -o none

echo "경고 규칙 3개를 만들었습니다. 확인 메일이 오면 구독을 확인하세요."
az monitor metrics alert list -g "$RG" --query "[].{name:name, enabled:enabled, severity:severity}" -o table

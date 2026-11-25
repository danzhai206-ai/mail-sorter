# 裏で動いているWeb画面（ポート8000のサーバー）を止める
# 実行: powershell -ExecutionPolicy Bypass -File scripts\stop_web.ps1

$conns = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $conns) {
    Write-Host "サーバーは動いていません。"
    exit 0
}
foreach ($id in ($conns.OwningProcess | Sort-Object -Unique)) {
    Stop-Process -Id $id -Force
}
Write-Host "サーバーを止めました。"

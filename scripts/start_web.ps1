# Web画面（API）を裏で起動して、準備ができたらブラウザで開く
# 実行: powershell -ExecutionPolicy Bypass -File scripts\start_web.ps1
# 止める: powershell -ExecutionPolicy Bypass -File scripts\stop_web.ps1
#
# ・すでに動いていれば、起動はせずにブラウザを開くだけ
# ・ターミナルを閉じてもサーバーは止まらない（裏で動き続ける）
# ・サーバーの記録は data\web.log に残る

param([string]$Page = "docs")   # 開くページ。トップ画面なら: -Page ""

$root   = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$base   = "http://127.0.0.1:8000"
$log    = Join-Path $root "data\web.log"
$errLog = Join-Path $root "data\web.err.log"

function Test-Server {
    # /health に聞いて、返事があれば「動いている」
    try {
        $r = Invoke-WebRequest "$base/health" -UseBasicParsing -TimeoutSec 2
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (Test-Server) {
    Write-Host "サーバーはすでに動いています。"
} else {
    if (-not (Test-Path $python)) {
        Write-Host "Python が見つかりません: $python" -ForegroundColor Red
        exit 1
    }
    Write-Host "サーバーを起動しています..."
    Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.web:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput $log -RedirectStandardError $errLog | Out-Null

    # 準備ができるまで最大30秒待つ（待たずに開くと「つながらない」になる）
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Server) { $ready = $true; break }
    }
    if (-not $ready) {
        Write-Host "起動できませんでした。原因は次の記録に出ています:" -ForegroundColor Red
        Get-Content $errLog -Tail 20 -Encoding utf8
        exit 1
    }
    Write-Host "起動しました。"
}

Start-Process "$base/$Page"
Write-Host "ブラウザで $base/$Page を開きました。"

# Runs the companies marked local_only (e.g. Tesla) from this PC.
# Task Scheduler calls this every 2 hours. Output goes to local_run.log.
Set-Location -Path $PSScriptRoot

$hookFile = Join-Path $PSScriptRoot "local_webhook.txt"
if (-not (Test-Path $hookFile)) {
    cmd /c "echo %date% %time% missing local_webhook.txt >> local_run.log"
    exit 1
}
$env:DISCORD_WEBHOOK = (Get-Content $hookFile -Raw).Trim()

# keep the log from growing forever: trim to the last 2000 lines past 1 MB
$log = Join-Path $PSScriptRoot "local_run.log"
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 1MB)) {
    $tail = Get-Content $log -Tail 2000
    Set-Content -Path $log -Value $tail -Encoding Ascii
}

cmd /c "echo === %date% %time% >> local_run.log"
cmd /c "python scraper.py --local >> local_run.log 2>&1"

# ตั้งค่าให้ระบบทำงานเองตลอด 24 ชม.
#  1) ดึงข้อมูลจาก Yahoo ทุกเที่ยงคืน (ถ้าเครื่องปิดอยู่ตอนนั้น จะดึงทันทีเมื่อเปิดเครื่อง)
#  2) เปิดเว็บ Streamlit เองทุกครั้งที่เข้าสู่ระบบ Windows
#  3) เปิดลิงก์ออนไลน์ Cloudflare Tunnel เองทุกครั้งที่เข้าสู่ระบบ Windows
#  4) ปิดโหมด Sleep / Hibernate ตอนเสียบปลั๊ก
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "โฟลเดอร์โปรเจกต์: $dir"

# ---- ติดตั้ง cloudflared ถ้ายังไม่มี
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue) -and
    -not (Test-Path "$env:ProgramFiles\cloudflared\cloudflared.exe") -and
    -not (Test-Path "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe")) {
    Write-Host "กำลังติดตั้ง cloudflared ..."
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

$user = "$env:USERDOMAIN\$env:USERNAME"
function New-Task($name, $bat, $trigger, $limitHours) {
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c start `"$name`" /min `"$dir\$bat`"" -WorkingDirectory $dir
    $limit = if ($limitHours -gt 0) { New-TimeSpan -Hours $limitHours } else { [TimeSpan]::Zero }
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit $limit -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive
    Register-ScheduledTask -TaskName $name -TaskPath "\ProjuctFin\" -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "  ตั้งค่าแล้ว: $name"
}

New-Task "Update data (midnight)" "update_data.bat" (New-ScheduledTaskTrigger -Daily -At "00:00") 1
New-Task "Web" "start_web.bat" (New-ScheduledTaskTrigger -AtLogOn -User $user) 0
$t = New-ScheduledTaskTrigger -AtLogOn -User $user; $t.Delay = "PT30S"
New-Task "Tunnel" "start_tunnel.bat" $t 0

# ---- ไม่ให้เครื่องเข้าโหมด Sleep ตอนเสียบปลั๊ก
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
Write-Host "  ปิดโหมด Sleep/Hibernate (ตอนเสียบปลั๊ก) แล้ว"

# ---- เริ่มทำงานทันที
Start-ScheduledTask -TaskPath "\ProjuctFin\" -TaskName "Web"
Start-Sleep -Seconds 10
Start-ScheduledTask -TaskPath "\ProjuctFin\" -TaskName "Tunnel"
Write-Host "กำลังเปิดเว็บและลิงก์ออนไลน์ (รอประมาณ 30 วินาที) ..."
$url = $null
for ($i = 0; $i -lt 30 -and -not $url; $i++) {
    Start-Sleep -Seconds 2
    $m = Select-String -Path "$dir\tunnel_log.txt" -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -Last 1
    if ($m) { $url = $m.Matches[0].Value }
}
Write-Host ""
Write-Host "================ เสร็จแล้ว ================"
Write-Host " เว็บในเครื่อง : http://localhost:8501"
if ($url) { Write-Host " เว็บออนไลน์   : $url" } else { Write-Host " เว็บออนไลน์   : ยังไม่พบลิงก์ ดับเบิลคลิก show_url.bat อีกครั้งในอีกสักครู่" }
Write-Host " ดึงข้อมูลอัตโนมัติ : ทุกวันเวลา 00:00 (ดูผลในไฟล์ update_log.txt)"
Write-Host "==========================================="

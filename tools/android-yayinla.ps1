# Yeni Android surumunu yayina hazirlar.
# 1) Android Studio'da app/build.gradle.kts icinde versionCode'u 1 artir, derle (Run ya da Generate APK)
# 2) Bu scripti calistir (android-yayinla.bat)
# 3) GitHub Desktop'ta commit + push -> arkadaslarina bildirim gider
$ErrorActionPreference = "Stop"
$pc = Resolve-Path (Join-Path $PSScriptRoot "..")
$android = Join-Path (Split-Path $pc -Parent) "FindHouseInNL-Android"
if (-not (Test-Path $android)) { throw "Android projesi bulunamadi: $android" }

$gradle = Get-Content (Join-Path $android "app\build.gradle.kts") -Raw
$code = [int]([regex]::Match($gradle, 'versionCode\s*=\s*(\d+)').Groups[1].Value)
$name = [regex]::Match($gradle, 'versionName\s*=\s*"([^"]+)"').Groups[1].Value

$jsonPath = Join-Path $pc "version.json"
if (Test-Path $jsonPath) {
    $old = Get-Content $jsonPath -Raw | ConvertFrom-Json
    if ($old.android.versionCode -ge $code) {
        Write-Host "UYARI: versionCode ($code) yayindaki surumden ($($old.android.versionCode)) buyuk degil." -ForegroundColor Yellow
        Write-Host "Android Studio'da app/build.gradle.kts icinde versionCode'u artirip tekrar derle." -ForegroundColor Yellow
        exit 1
    }
}

$apk = Get-ChildItem -Path (Join-Path $android "app\build") -Recurse -Filter *.apk -ErrorAction SilentlyContinue |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $apk) { throw "APK bulunamadi. Once Android Studio'da derle." }
Copy-Item $apk.FullName (Join-Path $pc "FindHouseInNL.apk") -Force

$notes = Read-Host "Bu surumde ne degisti? (bos birakabilirsin)"
$obj = [ordered]@{ android = [ordered]@{
    versionCode = $code; versionName = $name
    url = "https://ener001.github.io/FindhouseNL/FindHouseInNL.apk"; notes = $notes } }
$json = $obj | ConvertTo-Json -Depth 3
[System.IO.File]::WriteAllText($jsonPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host ""
Write-Host "Tamam: surum $name ($code) hazir ($($apk.Name), $([math]::Round($apk.Length/1MB,1)) MB)." -ForegroundColor Green
Write-Host "Simdi GitHub Desktop'ta commit + push yap; birkac dakika icinde arkadaslarina bildirim gider."

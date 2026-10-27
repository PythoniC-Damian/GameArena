$ErrorActionPreference='Stop'
$repo=Split-Path $PSScriptRoot -Parent
$tools=Join-Path $repo '.local-test/android-private'
$env:JAVA_HOME=(Get-ChildItem "$tools/jdk" -Directory | Select-Object -First 1).FullName
$env:ANDROID_HOME=Join-Path $tools 'sdk'
$env:GRADLE_USER_HOME=Join-Path $tools 'gradle-cache'
$env:GAMEARENA_ANDROID_KEYSTORE=Join-Path $tools 'owner.jks'
$passFile=Join-Path $tools 'signing-password.txt'
if(!(Test-Path $passFile)){
 $bytes=New-Object byte[] 32
 [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
 [IO.File]::WriteAllText($passFile,[Convert]::ToBase64String($bytes))
}
$env:GAMEARENA_ANDROID_STORE_PASSWORD=[IO.File]::ReadAllText($passFile)
try {
 if(!(Test-Path $env:GAMEARENA_ANDROID_KEYSTORE)){
  & "$env:JAVA_HOME/bin/keytool.exe" -genkeypair -keystore $env:GAMEARENA_ANDROID_KEYSTORE -storepass:env GAMEARENA_ANDROID_STORE_PASSWORD -keypass:env GAMEARENA_ANDROID_STORE_PASSWORD -alias gamearena-private -keyalg RSA -keysize 3072 -validity 10000 -dname 'CN=GameArena Private Preview'
  if($LASTEXITCODE -ne 0){throw 'Signing key generation failed'}
 }
 $gradle=Join-Path $tools 'gradle/gradle-8.11.1/bin/gradle.bat'
 & $gradle -p $PSScriptRoot --console=plain assembleRelease
 if($LASTEXITCODE -ne 0){throw 'Android build failed'}
 $out=Join-Path $repo 'private-apk'
 New-Item -ItemType Directory -Force $out | Out-Null
 Copy-Item "$PSScriptRoot/app/build/outputs/apk/release/app-release.apk" "$out/GameArena-private.apk" -Force
 & "$env:ANDROID_HOME/build-tools/35.0.0/apksigner.bat" verify --verbose --print-certs "$out/GameArena-private.apk"
 if($LASTEXITCODE -ne 0){throw 'APK signature verification failed'}
 Get-FileHash "$out/GameArena-private.apk" -Algorithm SHA256
} finally { Remove-Item Env:GAMEARENA_ANDROID_STORE_PASSWORD -ErrorAction SilentlyContinue }

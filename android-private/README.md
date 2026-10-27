# GameArena private Android preview

This is a signed Android Trusted Web Activity for the existing GameArena mobile website, not a separate native UI. It uses the phone browser's engine, cookies and website permissions. Google login and checkout stay in the browser security model. Internet access and the existing backend are required.

## Private installation
Copy `private-apk/GameArena-private.apk` to your Android phone by USB or your own private transfer. Open it using Files and allow that source to install apps when Android asks. Install **GameArena Private** and sign in normally. There is no store publication or public download endpoint. Anyone receiving a copy could install it; it is privately distributed, not cryptographically restricted to one phone.

Chrome or another browser supporting Trusted Web Activities must be installed and updated. Until the website's `/.well-known/assetlinks.json` is deployed with this APK's signing fingerprint, the browser may show its toolbar. Other domains, including Google and Paystack, can show browser controls by design. No app-specific admin access, wallet credits or payment bypass is included.

## Building and updates
The first build uses verified official Java 17, Android SDK 35 / build-tools 35.0.0, Gradle 8.11.1 and Android Gradle Plugin 8.9.2. With these in `.local-test/android-private`, run `./android-private/build-private.ps1` in PowerShell. SDK package installation requires Google's SDK licence acceptance. Android Browser Helper 2.5.0 with stable AndroidX Browser 1.8.0 is pinned for the preview.

Keep `.local-test/android-private/owner.jks` and `signing-password.txt` private and backed up securely. They are ignored by Git, along with APKs, tool downloads and build caches. Reuse the same key and increase versionCode for an installable update. Never put server secrets or Google client secrets into this project.

No public-store billing, distribution or policy review has been performed. On-phone login, payment return, back navigation, downloads and full-screen verification must be tested by the owner before wider distribution.


## Verified build (27 October 2026)
Release build and lint passed. APK signature verification passed; package metadata and website association JSON were checked. APK size: 986,358 bytes. SHA-256: 3573E3E14B88CF1E7A3733274383AC84AE93012B87B95101A9F67F3FB617AF40. Physical-device testing is still required. The APK and signing key were not published.


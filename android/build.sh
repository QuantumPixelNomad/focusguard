#!/bin/sh
# Builds FocusGuard for Android without Gradle or the full Android SDK.
# Needs: a JDK, aapt2, dalvik-exchange (dx), zipalign, apksigner, and an Android platform jar.
#   ANDROID_JAR=/path/to/android.jar ./build.sh
set -eu
cd "$(dirname "$0")"
: "${ANDROID_JAR:?Set ANDROID_JAR to an Android platform jar (API 34 or newer)}"
KEYSTORE="${KEYSTORE:-$PWD/focusguard-release.jks}"
: "${KEYPASS:?Set KEYPASS to the password of your signing keystore (a new keystore is made with it if none exists)}"
OUT=build
rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"

aapt2 compile --dir res -o "$OUT/res.zip"
aapt2 link -o "$OUT/base.apk" -I "$ANDROID_JAR" --manifest AndroidManifest.xml -A assets \
    --java "$OUT/gen" --min-sdk-version 29 --target-sdk-version 34 "$OUT/res.zip"

javac -nowarn -Xlint:-options --release 8 -encoding UTF-8 -cp "$ANDROID_JAR" -d "$OUT/classes" \
    $(find src "$OUT/gen" -name '*.java')
dalvik-exchange --dex --min-sdk-version=26 --output="$OUT/dex/classes.dex" "$OUT/classes"

cp "$OUT/base.apk" "$OUT/unaligned.apk"
(cd "$OUT/dex" && zip -q -j ../unaligned.apk classes.dex)
zipalign -f 4 "$OUT/unaligned.apk" "$OUT/aligned.apk"

if [ ! -f "$KEYSTORE" ]; then
    keytool -genkeypair -keystore "$KEYSTORE" -storepass "$KEYPASS" -keypass "$KEYPASS" -alias focusguard \
        -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=FocusGuard" >/dev/null 2>&1
fi
apksigner sign --ks "$KEYSTORE" --ks-pass "pass:$KEYPASS" --key-pass "pass:$KEYPASS" \
    --out "$OUT/focusguard-android.apk" "$OUT/aligned.apk"
apksigner verify --min-sdk-version 29 "$OUT/focusguard-android.apk"
echo "Built $OUT/focusguard-android.apk"

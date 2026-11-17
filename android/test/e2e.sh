#!/bin/bash
# End to end: real FocusGuard service (sandboxed) -> stand-in relay -> the phone's relay and policy code on a JVM.
set -u
TREE=${1:-/mnt/project-files/focusguard/}; HERE=$(cd "$(dirname "$0")/.." && pwd)
R=$(mktemp -d /tmp/fge.XXXX); mkdir -p $R/etc; echo "127.0.0.1 localhost" > $R/etc/hosts
export FOCUSGUARD_ROOT=$R FOCUSGUARD_PORT=47713 PYTHONPATH=$TREE FOCUSGUARD_LINK_SERVER=http://127.0.0.1:47714 PYTHONDONTWRITEBYTECODE=1
python3 $HERE/test/mini_ntfy.py 47714 & NT=$!
python3 -m focusguard.daemon & DM=$!
trap "kill $NT $DM 2>/dev/null; rm -rf $R" EXIT
sleep 2
call() { python3 -c "import sys,json; from focusguard import client; print(json.dumps(client.call(sys.argv[1], **json.loads(sys.argv[2]))))" "$1" "$2"; }
call set_config '{"config":{"schedules":[{"name":"Night","days":[0,1,2,3,4,5,6],"start":"03:00","end":"03:05","enabled":true}],"web":{"categories":["social","video"],"custom_blocked":["example.org"]},"apps":{"categories":["games"]},"youtube":{"mode":"filter"}}}' | cut -c1-60
CODE=$(call link_create '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['code'])")
echo "link code created"
java -cp $HERE/build/test:$HERE/build/classes:$ANDROID_JAR RelayProbe http://127.0.0.1:47714 $CODE 40 2>&1 | grep -v JAVA_TOOL &
PR=$!
sleep 8;  echo "--- PC: start a 25 minute session"; call start_session '{"minutes":25}'
sleep 10; echo "--- PC: stop the session";          call stop_session '{}'
sleep 10; echo "--- PC: add the news category";     call set_config '{"config":{"web":{"categories":["news"]},"youtube":{"mode":"block"}}}' | cut -c1-30
wait $PR
echo "--- a phone that was off reads the stored messages:"
java -cp $HERE/build/test:$HERE/build/classes:$ANDROID_JAR RelayProbe http://127.0.0.1:47714 $CODE 2>&1 | grep -v JAVA_TOOL
echo "--- a phone with the wrong code:"
java -cp $HERE/build/test:$HERE/build/classes:$ANDROID_JAR RelayProbe http://127.0.0.1:47714 ABCD-EFGH-JKMN-PQRS 2>&1 | grep -v JAVA_TOOL
call status '{}' | python3 -c "import sys,json; print('PC phone_link:', json.load(sys.stdin)['status']['phone_link'])"

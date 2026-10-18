#!/bin/bash
#
# Bisect the docker flags used by app/worker/tasks.py to find which one
# causes the converter image to SIGABRT (exit 134) on this Linux host.
#
# Run on the production server (where the failure reproduces).
# Requires: a non-empty uploaded zip already in the prod media volume.
#
# Output: one line per flag set tested. Stops at the first FAIL — the
# label on that line names the flag group that broke the run.

set -u

MEDIA_VOLUME="ardesign-prod_media_data"
IMAGE="${CONVERTER_IMAGE:-ismayilovh/ardesign-converter:latest}"
TEST_ZIP="/tmp/bisect-test.zip"
LOG="/tmp/bisect-stdout.log"

# ---- prep: extract one uploaded zip to /tmp so we can feed it in --------

echo "[prep] Locating a test zip in volume $MEDIA_VOLUME..."
TEST_SRC=$(docker run --rm -v "$MEDIA_VOLUME":/m alpine sh -c "find /m/uploads -name '*.zip' 2>/dev/null | head -1")
if [ -z "$TEST_SRC" ]; then
  echo "ERROR: no zip found under /uploads in $MEDIA_VOLUME."
  echo "       Upload at least one zip via the frontend first, then rerun."
  exit 1
fi
echo "[prep] Using $TEST_SRC"

docker run --rm -v "$MEDIA_VOLUME":/m -v /tmp:/out alpine sh -c "cp \"$TEST_SRC\" /out/$(basename $TEST_ZIP) && chmod 644 /out/$(basename $TEST_ZIP)"
if [ ! -s "$TEST_ZIP" ]; then
  echo "ERROR: $TEST_ZIP was not created or is empty."
  exit 1
fi
echo "[prep] Copied to $TEST_ZIP ($(stat -c%s "$TEST_ZIP") bytes)"
echo ""

# ---- the inner test: create+copy+start with the given flag set ----------

run_test() {
  local label="$1"
  shift
  local name="bisect-$$-$RANDOM"
  docker rm -f "$name" >/dev/null 2>&1 || true

  docker create --name "$name" "$@" --entrypoint bash "$IMAGE" -c '/app/converter/venv/bin/python3.11 -c "import zipfile, os; os.makedirs(\"/tmp/work\", exist_ok=True); zipfile.ZipFile(\"/tmp/model.zip\").extractall(\"/tmp/work\")" && MODEL=$(find /tmp/work -type f \( -iname "*.obj" -o -iname "*.stl" -o -iname "*.stp" -o -iname "*.iges" -o -iname "*.glb" -o -iname "*.fbx" \) | head -1) && cd /tmp/work && xvfb-run -a /app/converter/venv/bin/python3.11 /app/converter/main.py "$MODEL"' >/dev/null
  docker cp "$TEST_ZIP" "$name":/tmp/model.zip >/dev/null
  docker start -a "$name" >"$LOG" 2>&1
  local code=$?
  docker rm -f "$name" >/dev/null 2>&1 || true

  if [ $code -eq 0 ]; then
    printf "  [PASS]            %s\n" "$label"
    return 0
  else
    printf "  [FAIL exit=%-4d] %s\n" "$code" "$label"
    echo "  --- last 30 lines of converter output:"
    tail -30 "$LOG" | sed 's/^/      /'
    return 1
  fi
}

# ---- bisection: flags added cumulatively in the same order tasks.py does

echo "Running bisection. The first FAIL line names the culprit."
echo ""

run_test "baseline (--init only, matches tasks.py PID 1)"   --init                                                                                                     || exit 0
run_test "+ mem/cpu limits"                                 --init --memory 2g --memory-swap 2g --cpus 1.5                                                              || exit 0
run_test "+ --pids-limit 100"                               --init --memory 2g --memory-swap 2g --cpus 1.5 --pids-limit 100                                             || exit 0
run_test "+ --network none"                                 --init --memory 2g --memory-swap 2g --cpus 1.5 --pids-limit 100 --network none                              || exit 0
run_test "+ --security-opt no-new-privileges"               --init --memory 2g --memory-swap 2g --cpus 1.5 --pids-limit 100 --network none --security-opt no-new-privileges                    || exit 0
run_test "+ --cap-drop ALL"                                 --init --memory 2g --memory-swap 2g --cpus 1.5 --pids-limit 100 --network none --security-opt no-new-privileges --cap-drop ALL     || exit 0

echo ""
echo "All flag combinations PASSED on this host. The SIGABRT you saw from"
echo "the worker is not caused by these flags — something else is going on."
echo "Check worker logs around the next real conversion attempt."

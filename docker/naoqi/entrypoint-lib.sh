# What both versions' entrypoints share (entrypoint-2.1.sh, entrypoint-2.8.sh source it): writing the
# autoload copy our modules load from (in place of the built-ins they replace), starting naoqi-bin,
# waiting for a settled service list, checking the replacements answer, and marking boot complete. Each version's script reads as its
# exact procedure; see specs/container/container.md ("Entrypoint") and specs/container/service-replacement.md.
#
# Any failure exits non-zero after terminating naoqi-bin, so a failed boot shows as an exited
# container, never as a half-robot. Tunables (images never change them; the host-side tests do):
# NAOQI_SIM_READY_TRIES, NAOQI_SIM_SETTLE_POLLS, NAOQI_SIM_POLL_INTERVAL, NAOQI_SIM_QICLI_TIMEOUT,
# NAOQI_SIM_QICLI_HANGS, NAOQI_HOME.
set -u
NAOQI_HOME=${NAOQI_HOME:-/opt/naoqi}
cd "$NAOQI_HOME"
INTERVAL=${NAOQI_SIM_POLL_INTERVAL:-1}
TRIES=${NAOQI_SIM_READY_TRIES:-120}
SETTLE=${NAOQI_SIM_SETTLE_POLLS:-3}
QICLI_TIMEOUT=${NAOQI_SIM_QICLI_TIMEOUT:-5}  # seconds a qicli call may take
HANGS=${NAOQI_SIM_QICLI_HANGS:-3}            # consecutive unanswered polls that fail the boot
PROGRESS=10                                  # polls between two "still waiting" lines
NAOQI_PID=
URL=

log() { echo "[entrypoint] $*"; }

fail() {
  log "$1"
  [ -n "$NAOQI_PID" ] && kill -TERM "$NAOQI_PID" 2>/dev/null
  exit 1
}

# qi <qicli arguments...>: qicli, killed after QICLI_TIMEOUT seconds (exit status 124). A NAOqi
# that stopped answering, or a call that hangs, would otherwise freeze the boot without a word,
# and the container would only turn unhealthy minutes later. Plain bash: the host-side tests run
# this on macOS, which has no `timeout`.
qi() {
  local pid watcher status
  qicli "$@" &
  pid=$!
  ( sleep "$QICLI_TIMEOUT"; kill -KILL "$pid" 2>/dev/null ) >/dev/null 2>&1 &
  watcher=$!
  wait "$pid"
  status=$?
  if kill "$watcher" 2>/dev/null; then wait "$watcher" 2>/dev/null; else status=124; fi
  return "$status"
}

# call <Service.method> [args...]: a qicli call to NAOqi from inside the container.
call() { qi call "$@" --qi-url "$URL"; }

# write_autoload <left out entries> [<anchor>:<entry>,<entry>...]...: AUTOLOAD, a copy of the suite's
# autoload.ini with the left out entries commented out (`#replaced <entry>`) and each anchor's
# entries inserted right after it, in order. A missing entry or anchor fails the boot: a suite
# without them would otherwise boot without our modules.
write_autoload() {
  local suite=$NAOQI_HOME/etc/naoqi/autoload.ini left=$1 item
  shift
  AUTOLOAD=${TMPDIR:-/tmp}/autoload.ini
  for item in $left "${@%%:*}"; do
    grep -qx "$item" "$suite" || fail "$suite has no entry $item"
  done
  awk -v left="$left" -v inserts="$*" '
    BEGIN {
      n = split(left, l, " "); for (i = 1; i <= n; i++) out[l[i]] = 1
      n = split(inserts, s, " "); for (i = 1; i <= n; i++) { split(s[i], kv, ":"); after[kv[1]] = kv[2] }
    }
    {
      if ($0 in out) print "#replaced " $0; else print
      if ($0 in after) { n = split(after[$0], e, ","); for (i = 1; i <= n; i++) print e[i] }
    }' "$suite" > "$AUTOLOAD" || fail "writing $AUTOLOAD failed"
}

# start_naoqi <url the entrypoint reaches NAOqi on> <naoqi-bin arguments...>
start_naoqi() {
  URL=$1
  shift
  naoqi-bin "$@" &
  NAOQI_PID=$!
  trap 'kill -TERM $NAOQI_PID 2>/dev/null' TERM INT
}

# wait_for_naoqi <services...>: until every one is registered AND the service list has not changed
# for SETTLE polls: NAOqi finished booting (on 2.8 the package services keep registering for a few
# seconds after naoqi-service's last autoload entry).
wait_for_naoqi() {
  local services previous= stable=0 present i listing missing hung=0
  for i in $(seq 1 "$TRIES"); do
    listing=$(qi info --qi-url "$URL" 2>/dev/null)
    if [ $? -eq 124 ]; then  # a hang; a refused connection (NAOqi not listening yet) is not one
      hung=$((hung + 1))
      log "qicli info did not answer in ${QICLI_TIMEOUT}s ($hung in a row)"
      [ "$hung" -lt "$HANGS" ] || fail "NAOqi stopped answering: qicli info timed out $HANGS times in a row"
    else
      hung=0
    fi
    services=$(printf '%s\n' "$listing" | sed -n 's/^[0-9]* \[\(.*\)\]$/\1/p')
    present=1
    missing=
    for s in "$@"; do
      printf '%s\n' "$services" | grep -qx "$s" || { present=; missing="$missing $s"; }
    done
    if [ $((i % PROGRESS)) -eq 0 ]; then
      if [ -n "$present" ]; then log "still waiting: the service list is still changing (poll $i)"
      else log "still waiting for:$missing (poll $i)"; fi
    fi
    if [ -n "$present" ]; then
      if [ "$services" = "$previous" ]; then stable=$((stable + 1)); else stable=0; fi
      if [ "$stable" -ge "$SETTLE" ]; then
        log "NAOqi ready after $i polls, $(printf '%s\n' "$services" | wc -l | tr -d ' ') services"
        return
      fi
    else
      stable=0
    fi
    previous=$services
    kill -0 "$NAOQI_PID" 2>/dev/null || fail "naoqi-bin exited"
    sleep "$INTERVAL"
  done
  fail "NAOqi not ready after $TRIES polls (waiting for $* and a stable service list): giving up"
}

# check_answer <what> <names...>: every name must answer. Our modules load inside NAOqi's boot, where
# an import failure (launchPythonModule does not report one) or a library that registers nothing
# shows only as a missing name: a replaced name (the built-in is left out and nothing took its
# place), a name our modules add, or a built-in we add to the autoload.
check_answer() {
  local what=$1 answered i
  shift
  for m in "$@"; do
    answered=
    for i in $(seq 1 10); do
      if qi info "$m" --qi-url "$URL" >/dev/null 2>&1; then answered=1; break; fi
      sleep "$INTERVAL"
    done
    [ -n "$answered" ] || fail "$what service $m does not answer once NAOqi booted"
  done
}

# vision_2d <services...>: puts each vision module's detection in 2D, as on a real NAO, which has no
# depth camera (bobby: fast person tracking, find person head, people perception and movement
# detection all 2D). The desktop's virtual robot declares one (camera index 2) that nothing feeds,
# so in their default 3D mode the trackers never find anyone and ALBasicAwareness, after its first
# look, never follows a person (specs/container/naoqi-fidelity.md).
vision_2d() {
  local m
  for m in "$@"; do
    call "$m._setDetectionMode" 2D >/dev/null 2>&1 || fail "$m._setDetectionMode 2D failed"
  done
}

# mark_ready: the whole sequence succeeded. Then wait on naoqi-bin (signals are forwarded to it).
mark_ready() {
  call NaoqiSim.setReady >/dev/null 2>&1 || fail "NaoqiSim.setReady failed: the status module is not loaded"
  log "naoqi-sim ready"
  wait "$NAOQI_PID"
}

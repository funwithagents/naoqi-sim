# What both versions' entrypoints share (entrypoint-2.1.sh, entrypoint-2.8.sh source it): writing the
# autoload copy our modules load from (in place of the built-ins they replace), starting naoqi-bin,
# waiting for a settled service list, checking the replacements answer, and marking boot complete. Each version's script reads as its
# exact procedure; see specs/container/container.md ("Entrypoint") and specs/container/service-replacement.md.
#
# Any failure exits non-zero after terminating naoqi-bin, so a failed boot shows as an exited
# container, never as a half-robot. Tunables (images never change them; the host-side tests do):
# NAOQI_SIM_READY_TRIES, NAOQI_SIM_SETTLE_POLLS, NAOQI_SIM_POLL_INTERVAL, NAOQI_SIM_QICLI_TIMEOUT, NAOQI_SIM_MOVE_TIMEOUT,
# NAOQI_SIM_QICLI_HANGS, NAOQI_HOME.
set -u
NAOQI_HOME=${NAOQI_HOME:-/opt/naoqi}
cd "$NAOQI_HOME"
INTERVAL=${NAOQI_SIM_POLL_INTERVAL:-1}
TRIES=${NAOQI_SIM_READY_TRIES:-120}
SETTLE=${NAOQI_SIM_SETTLE_POLLS:-3}
QICLI_TIMEOUT=${NAOQI_SIM_QICLI_TIMEOUT:-5}  # seconds a qicli call may take
MOVE_TIMEOUT=${NAOQI_SIM_MOVE_TIMEOUT:-60}  # seconds a call that moves the robot may take
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
  kill "$watcher" 2>/dev/null
  wait "$watcher" 2>/dev/null
  # Killed by the watcher: SIGKILL, 128 + 9. Whether the watcher has exited yet says nothing (on a
  # loaded machine it may still be running just after its kill), so the status alone tells.
  [ "$status" -eq 137 ] && status=124
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

# robot_model <this NAOqi's default robot version>: the robot the config names (NAOQI_SIM_ROBOT_TYPE
# and NAOQI_SIM_ROBOT_VERSION; a NAO of the default version without them), as the suite's model
# file, which NAOqi's model preference is pointed at before NAOqi starts. Exports the file's path:
# the status module publishes the RobotConfig keys it lists (specs/container/container.md, "The
# robot model"; specs/container/status-service.md, "The robot's keys").
robot_model() {
  local type=${NAOQI_SIM_ROBOT_TYPE:-nao} version=${NAOQI_SIM_ROBOT_VERSION:-$1} file
  local preference=$NAOQI_HOME/etc/naoqi/ALRobotModel.xml copy=${TMPDIR:-/tmp}/ALRobotModel.xml
  case $type-$version in
    nao-v4) file=NAOH25V40.xml ;;
    nao-v5) file=NAOH25V50.xml ;;
    nao-v6) file=NAOH25V60.xml ;;
    *) fail "unknown robot: $type $version" ;;
  esac
  NAOQI_SIM_ROBOT_MODEL_FILE=$NAOQI_HOME/share/alrobotmodel/models/$file
  [ -f "$NAOQI_SIM_ROBOT_MODEL_FILE" ] || fail "this NAOqi has no $type $version: no model file $file"
  [ -f "$preference" ] || fail "no model preference $preference"
  sed "s/value=\"[^\"]*\.xml\"/value=\"$file\"/" "$preference" > "$copy" \
    && grep -q "value=\"$file\"" "$copy" && cat "$copy" > "$preference" \
    || fail "pointing $preference at $file failed"
  export NAOQI_SIM_ROBOT_MODEL_FILE
  log "robot: $type $version ($file)"
}

# loopback_to_naoqi <NAOqi's port>: robot software connects to 127.0.0.1:9559, which a robot's NAOqi
# serves and 2.8's gateway holds on the sim. Redirect the container's own connections there to NAOqi,
# once (container.md, "Network layout"). A host that refuses the NET_ADMIN capability leaves the
# port to the gateway: logged, and the boot goes on. Exports what 127.0.0.1:9559 is for the status
# module (NaoqiSim/Loopback9559).
loopback_to_naoqi() {
  local spec="OUTPUT -o lo -p tcp -d 127.0.0.1 --dport 9559 -j REDIRECT --to-ports $1" err
  if iptables -w -t nat -C $spec 2>/dev/null || err=$(iptables -w -t nat -A $spec 2>&1); then
    NAOQI_SIM_LOOPBACK_9559=naoqi
    log "127.0.0.1:9559 is NAOqi: the container's own connections there go to port $1"
  else
    NAOQI_SIM_LOOPBACK_9559=gateway
    log "127.0.0.1:9559 stays the gateway: ${err:-iptables failed} (no NET_ADMIN capability?)"
  fi
  export NAOQI_SIM_LOOPBACK_9559
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
# depth camera (a real NAO 2.1: fast person tracking, find person head, people perception and
# movement detection all 2D). The desktop's virtual robot declares one (camera index 2) that nothing feeds,
# so in their default 3D mode the trackers never find anyone and ALBasicAwareness, after its first
# look, never follows a person (specs/container/naoqi-fidelity.md).
vision_2d() {
  local m
  for m in "$@"; do
    call "$m._setDetectionMode" 2D >/dev/null 2>&1 || fail "$m._setDetectionMode 2D failed"
  done
}

# choose_languages: chooses each installed language in turn, the robot's own (the first) last, as a
# NAO 6's settings page does when its user picks a language: speech, recognition, then the dialog.
# The 2.8 dialog writes its grammar for the languages chosen this way, at its next preload, and
# gives it to the recognition (specs/services/speech-recognition.md, "What it listens for").
# A language the recognition does not have (no model in the engine) is left out.
choose_languages() {
  local languages=${NAOQI_SIM_LANGUAGES:-English} language i service recognised
  recognised=$(call ALSpeechRecognition.getAvailableLanguages 2>/dev/null) || fail "ALSpeechRecognition.getAvailableLanguages failed"
  IFS=, read -r -a languages <<<"$languages"
  for ((i = ${#languages[@]} - 1; i >= 0; i--)); do
    language=${languages[i]}
    if [[ $recognised != *"\"$language\""* ]]; then
      log "$language is not chosen: the recognition does not have it"
      continue
    fi
    for service in ALTextToSpeech ALSpeechRecognition ALDialog; do
      call "$service.setLanguage" "$language" >/dev/null 2>&1 || fail "$service.setLanguage $language failed"
    done
  done
}

# dialog_language: 2.1's dialog in the robot's language (the first installed), as a NAO's settings page
# sets it; its speech and recognition start in it by themselves. Left out, logged, when the
# recognition does not have it (specs/services/speech-recognition.md).
dialog_language() {
  local languages=${NAOQI_SIM_LANGUAGES:-English} recognised
  local language=${languages%%,*}
  recognised=$(call ALSpeechRecognition.getAvailableLanguages 2>/dev/null) || fail "ALSpeechRecognition.getAvailableLanguages failed"
  if [[ $recognised != *"\"$language\""* ]]; then
    log "the dialog stays in its own language: the recognition does not have $language"
    return
  fi
  call ALDialog.setLanguage "$language" >/dev/null 2>&1 || fail "ALDialog.setLanguage $language failed"
}

# allow_life_state_changes: the 2.1 desktop suite's ALAutonomousLife refuses every setState ("Calls to
# the setState method are not currently allowed") until this call; a real NAO 2.1 accepts them
# (specs/container/autonomous-life.md, "Switching Life on").
allow_life_state_changes() {
  # A hidden method (--hidden), and a bool, not the string "true" (--json).
  local out
  out=$(call ALAutonomousLife._setStateChangeEnabled true --hidden --json 2>&1) || fail "ALAutonomousLife._setStateChangeEnabled failed: $out"
}

# move <Service.method> [args...]: a call that moves the robot, for seconds (a rest is about 5 s,
# sitting down 12 to 16 s), so bounded by MOVE_TIMEOUT rather than the answers' QICLI_TIMEOUT.
move() {
  local out
  out=$(QICLI_TIMEOUT=$MOVE_TIMEOUT call "$@" 2>&1) || fail "$1 failed: $out"
}

# robot_state: the robot as the config's setup block asks when the sim is ready
# (specs/container/autonomous-life.md, "The state at boot"): Life first, since switching it on
# stands the robot up, then the posture, then the stiffness. The config has refused the
# combinations a NAO cannot be in.
robot_state() {
  local posture=${NAOQI_SIM_ROBOT_POSTURE:-crouch} stiffness=${NAOQI_SIM_ROBOT_STIFFNESS:-off}
  local life=${NAOQI_SIM_ROBOT_LIFE:-off} out
  [[ $life == on ]] && move ALAutonomousLife.setState solitary
  case $posture in
    crouch)
      if [[ $stiffness == on ]]; then
        move ALMotion.wakeUp
        move ALRobotPosture.goToPosture '"Crouch"' 0.8 --json
      else
        move ALMotion.rest
      fi
      ;;
    stand) [[ $life == on ]] || move ALMotion.wakeUp ;;
    sit)
      [[ $life == on ]] || move ALMotion.wakeUp
      move ALRobotPosture.goToPosture '"Sit"' 0.8 --json
      out=$(call ALRobotPosture.getPosture 2>&1)
      [[ $out == *Sit* ]] || fail "the robot did not sit: ALRobotPosture.getPosture answered $out"
      # Stiffness off where it sits: rest() would crouch it.
      [[ $stiffness == on ]] || move ALMotion.setStiffnesses '"Body"' 0.0 --json
      ;;
    *) fail "unknown posture $posture" ;;
  esac
  log "robot: $posture, stiffness $stiffness, life $life"
}

# mark_ready: the whole sequence succeeded. Then wait on naoqi-bin (signals are forwarded to it).
mark_ready() {
  call NaoqiSim.setReady >/dev/null 2>&1 || fail "NaoqiSim.setReady failed: the status module is not loaded"
  log "naoqi-sim ready"
  wait "$NAOQI_PID"
}

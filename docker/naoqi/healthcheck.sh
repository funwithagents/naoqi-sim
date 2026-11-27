#!/bin/bash
# Docker healthcheck: healthy once the NaoqiSim service, reached on the public port (2.8: through
# the suite's gateway, 2.1: the broker), says the entrypoint finished and the replacements answer.
# 2.8 (NAOQI_SIM_HEALTH_VIA=address): the container's own address, as 127.0.0.1:9559 is NAOqi itself
# once the entrypoint's loopback redirect is in place, past the gateway clients go through.
host=127.0.0.1
if [ "${NAOQI_SIM_HEALTH_VIA:-}" = address ]; then
  address=$(hostname -I 2>/dev/null)
  address=${address%%[[:space:]]*}
  [ -n "$address" ] && host=$address
fi
out=$(qicli call NaoqiSim.isReady --qi-url "tcp://$host:${NAOQI_SIM_PUBLIC_PORT:-9559}" 2>/dev/null) || exit 1
# 2.1's qicli prints `NaoqiSim.isReady: true`; 2.8's prints `true` and then its [W] warnings on stdout.
first=${out%%$'\n'*}
case "${first##*: }" in
  true) exit 0 ;;
  *) exit 1 ;;
esac

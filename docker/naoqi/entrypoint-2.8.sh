#!/bin/bash
# NAOqi 2.8 entrypoint. naoqi-bin is a launcher on the loopback port 9558: the classic modules run
# in naoqi-service, the suite's packages run as services under ALServiceManager, and the core
# package's qi-secure-gateway serves the public port 9559, relaying every process, as on a NAO 6.
# Our modules are qi.Session services in naoqi-service, which connect to NAOQI_SIM_INTERNAL_PORT.
#
# Our modules take the place of ALTextToSpeech and ALAudioPlayer in NAOqi's own boot: naoqi-service
# loads an autoload copy without the built-ins' libraries and with ours right after pythonbridge
# (the relay, the loader, which loads our Python modules, then the C++ fronts, with the hidden
# signals ALAnimatedSpeech connects to). The package services that call them (ALDialog,
# ALAnimatedSpeech...) register after them (specs/container/service-replacement.md, "Replacing a
# built-in"; specs/container/container.md, "Entrypoint").
. "$(dirname "$0")/entrypoint-lib.sh"

LEFT_OUT="audioplayer ttsinterface peopleperception sittingpeopledetection engagementzones gazeanalysis wavingdetection" # ALAudioPlayer's and ALTextToSpeech's libraries; ALPeoplePerception's and the four modules chained to its graph (specs/services/perception-stubs.md)
OURS="naoqi_sim_audio_device_relay,naoqi_sim_loader,naoqi_sim_speech_front,naoqi_sim_audio_player_front"
MODULES="naoqi_sim_status_qiservice naoqi_sim_speech_qiservice naoqi_sim_audio_device_qiservice naoqi_sim_audio_player_qiservice naoqi_sim_face_detection_qiservice naoqi_sim_people_perception_qiservice naoqi_sim_perception_stubs_qiservice" # ours, loaded by the loader in order
REPLACED="ALTextToSpeech ALAudioPlayer ALPeoplePerception" # the built-in names our modules take
ADDED="ALAudioDevice _NaoqiSimAudioRelay _NaoqiSimTextToSpeech _NaoqiSimAudioPlayer ALFaceDetection ALEngagementZones ALGazeAnalysis ALSittingPeopleDetection ALWavingDetection _UserIdentification _NaoqiSimPerceptionSources" # names no built-in holds, which we register (after ALFaceDetection: stubs)
# Registered last at boot: the last autoload entry, and the package services that call our modules.
LAST="ALPanoramaCompass ALAnimatedSpeech ALDialog ALAutonomousLife"

# The tracking libraries stay: the people-perception sources they read, loaded right after
# ALModularity registers (specs/services/perception-stubs.md, "The tracking processes").
KEPT="_ALFastPersonTracking _ALFindPersonHead"
write_autoload "$LEFT_OUT" "pythonbridge:$OURS" "modularityperception:naoqi_sim_perception_sources"
export NAOQI_SIM_MODULARITY_PROGRAMS="$NAOQI_HOME/share/naoqi/vision/mds/peopleperception_sources.mds"
export NAOQI_SIM_PYTHON_MODULES="$MODULES" NAOQI_SIM_MODULES_DIR="$NAOQI_HOME/modules"
export NAOQI_SIM_INTERNAL_PORT=9558  # inherited by naoqi-service, where our modules read it
start_naoqi tcp://127.0.0.1:9558 \
  --qi-listen-url tcp://127.0.0.1:9558 --autoload-file "$AUTOLOAD" "$@"
wait_for_naoqi ALLauncher ALPythonBridge $LAST
check_answer replaced $REPLACED
check_answer added $ADDED
check_answer "kept built-in" $KEPT
vision_2d _ALFastPersonTracking _ALFindPersonHead ALMovementDetection
mark_ready

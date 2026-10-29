#!/bin/bash
# NAOqi 2.1 entrypoint. One naoqi-bin process holds every module and is itself the broker on the
# public port 9559; our modules are naoqi.ALModule objects registered on that broker.
#
# Our modules take the place of ALTextToSpeech and ALAudioPlayer in NAOqi's own boot: naoqi-bin
# loads an autoload copy without the built-ins' library and with ours right after pythonbridge
# (the relay, the loader, which loads our Python modules, then the C++ fronts), so every module it
# loads afterwards finds them. The copy also gets the built-ins a NAO autoloads but the desktop
# suite does not, at a NAO's places (specs/container/service-replacement.md, "Replacing a built-in";
# specs/container/container.md, "Entrypoint"; specs/container/naoqi-fidelity.md, "Matching a real NAOqi robot's modules").
. "$(dirname "$0")/entrypoint-lib.sh"

LEFT_OUT="audioout peopleperception sittingpeopledetection engagementzones gazeanalysis wavingdetection" # ALTextToSpeech's and ALAudioPlayer's library; ALPeoplePerception's and the four modules chained to its graph (specs/services/perception-stubs.md)
OURS="naoqi_sim_audio_device_relay,naoqi_sim_loader,naoqi_sim_speech_front,naoqi_sim_audio_player_front"
MODULES="naoqi_sim_status_almodule naoqi_sim_speech_almodule naoqi_sim_audio_device_almodule naoqi_sim_audio_player_almodule naoqi_sim_face_detection_almodule naoqi_sim_people_perception_almodule naoqi_sim_perception_stubs_almodule" # ours, loaded by the loader in order
REPLACED="ALTextToSpeech ALAudioPlayer ALPeoplePerception" # the built-in names our modules take
ADDED="ALAudioDevice _NaoqiSimAudioRelay _NaoqiSimTextToSpeech _NaoqiSimAudioPlayer ALFaceDetection ALEngagementZones ALGazeAnalysis ALSittingPeopleDetection" # names no built-in holds, which we register (the last three: stubs)
# The built-ins a NAO 2.1 autoloads and the desktop suite does not (expressiveness after
# behaviormanager; awareness, blinking and autonomous moves before autonomouslife), and the names
# they register.
ADDED_ENTRIES="behaviormanager:expressiveness alpanoramacompass:basicawareness,autonomousblinking,autonomousmoves"
BUILTINS="_ALExpressiveness ALBasicAwareness _ALAutonomousBlinking ALAutonomousMoves"
LAST="ALDialog"                           # registered last at boot (dialog, the last entry)

write_autoload "$LEFT_OUT" "pythonbridge:$OURS" $ADDED_ENTRIES
export NAOQI_SIM_PYTHON_MODULES="$MODULES" NAOQI_SIM_MODULES_DIR="$NAOQI_HOME/modules"
start_naoqi tcp://127.0.0.1:9559 -b 0.0.0.0 -p 9559 --autoload-file "$AUTOLOAD" "$@"
wait_for_naoqi ALLauncher ALPythonBridge $LAST
check_answer replaced $REPLACED
check_answer added $ADDED
check_answer "added built-in" $BUILTINS
vision_2d ALFastPersonTracking ALFindPersonHead ALMovementDetection
mark_ready

# What is simulated

naoqi-sim runs Aldebaran's own NAOqi, so most of what a NAO does is NAOqi itself doing it: motion, postures, behaviors, the dialog engine, Autonomous Life, ALMemory, the package manager. This page lists what naoqi-sim adds or replaces so that the rest behaves as on a robot, and what connects the robot to your machine. Where it falls short of a real NAO is in [reference/differences-from-a-nao.md](reference/differences-from-a-nao.md).

## The robot

| | |
|---|---|
| **NAOqi 2.1.4.13 and 2.8.7.4** | Aldebaran's desktop NAOqi of each version, in its own Docker image, on `127.0.0.1:9559` |
| **A NAO V4, V5 or V6** | 2.1 runs a NAO V5 by default, or a V4; 2.8 runs a NAO V6. The robot's `RobotConfig/Body/Type` and `RobotConfig/Body/Version` keys say which, as on a robot |
| **Any qi client** | Choregraphe, Python or C++ scripts, existing applications: no naoqi-sim-specific code |
| **Packages** | Behaviors, dialog topics and applications install from Choregraphe or over qi, and stay installed between runs |
| **The robot's animations** | The `animations/Stand/Gestures/...` behaviors a NAO ships with, so animated speech moves as on a robot |
| **Its state at start** | Crouched and at rest by default; a config can start it standing, stiff, or with Autonomous Life on |

## Speech and sound

| | |
|---|---|
| **`ALTextToSpeech`** | A real voice on your loudspeaker, with a NAO's API, tags, events and timing; a child's voice in English and French. `ALAnimatedSpeech` and the Say boxes work on top of it, and stop as on a robot |
| **Languages** | Thirteen: English, French, German, Dutch, Swedish, Spanish, Brazilian, Czech, Italian, Polish, Portuguese, Russian, Turkish. English and French are installed by default; the others are a config field, downloaded on first use |
| **`ALAudioPlayer`** | Sound files (WAV, OGG), volume and pan, loops, sound sets, mixed with the voice |
| **`ALAudioDevice`** | The robot's four microphones, fed from your microphone or from sounds a test plays; a module subscribes and receives the buffers as on a NAO. The robot hears its own voice, as a NAO does |
| **`ALSpeechRecognition`** | Recognises what the microphones hear, in the thirteen languages, with a NAO's API and events; the dialog listens through it |

## Vision and people

| | |
|---|---|
| **`ALVideoDevice`** | Both head cameras, fed from your webcam or from the 3D scene as the robot's cameras see it |
| **`ALFaceDetection`** | Detects faces in the camera images, `FaceDetected` in a NAO's format |
| **`ALPeoplePerception`** | The people around the robot, with their distance and position, from the detected faces |
| **`ALEngagementZones`** | Sorts those people into the robot's zones |
| **`ALBasicAwareness`, `ALTracker`** | NAOqi's own: the robot turns to the people it sees and follows them |

## Autonomous Life and dialog

| | |
|---|---|
| **`ALAutonomousLife`** | NAOqi's own, on both versions: `solitary` and `interactive`, focused activities, launch conditions that depend on people |
| **`ALDialog`** | NAOqi's own, listening through the speech recognition and speaking through the voice |
| **Stopping an activity** | Each version's gesture: the three head sensors held three seconds on 2.1; a hand over the top camera and the front sensor on 2.8 |

## Touch and controls

| | |
|---|---|
| **Touch sensors** | The 13 head, hand and foot sensors, pressed from the controls page, from Python or over HTTP; `ALTouch` and the touch events follow |
| **The controls page** | A web page on `127.0.0.1` to wake the robot up or rest it, set its stiffness and posture, switch Life on and off, touch its sensors, cover a camera, stop the running activity; mute your microphone or your loudspeakers |

## The window

| | |
|---|---|
| **A 3D view of the robot** | [naoqi-viewer](https://github.com/funwithagents/naoqi-viewer) shows the robot moving as NAOqi moves it, in a scene, with Aldebaran's meshes if you installed them |
| **What the robot sees and perceives** | The two camera images and the people NAOqi lists, drawn in the window |
| **A scene to test in** | Faces and objects a test puts in front of the robot, which its cameras render and its perception detects |

## For programs and tests

| | |
|---|---|
| **The `naoqi-sim` command** | Run a robot from a terminal with a few options, or from a config file |
| **A Python API** | `NaoqiSim`: start, stop, play a sound into the microphones, place a face in the scene, press a sensor, capture what the robot said |
| **The `NaoqiSim` service** | Tells a client it is on naoqi-sim, with the versions and what feeds each sense |
| **Headless** | No window, no sound device, no microphone needed: it runs on a server and in CI |

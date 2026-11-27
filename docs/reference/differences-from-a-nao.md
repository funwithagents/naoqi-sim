# Differences from a real NAO

naoqi-sim behaves like a NAO in its API: the same services, the same calls, the same events. Its NAOqi is Aldebaran's desktop build, made to run on a computer, not a robot's, and there is no body: nothing is simulated physically. This page lists what follows from that, so you know what a test on naoqi-sim does and does not tell you about the robot.

The design reference, with every difference measured and dated, is [specs/container/naoqi-fidelity.md](../../specs/container/naoqi-fidelity.md).

## No physics

- **The robot cannot fall, slip or collide with anything.** NAOqi moves the joints where it is asked and the window shows them. A motion that would make a real NAO fall plays without a problem.
- **No inertial sensor on 2.8.** The 2.8 robot has no accelerometer or gyroscope; 2.1's reports an upright torso whatever the robot does.

## Hardware that is not there

- **The services of the robot's hardware and system are absent**: `ALSystem`, sound localization, photo and video capture, landmark and barcode detection, infrared, laser, among others. A NAO V5 on 2.1 has 117 public services and the 2.1 sim 87; the 77 they share have the same methods. A program that needs the NAOqi version reads it from the `NaoqiSim` service.
- **Far fewer hardware keys in ALMemory.** 2.1 has the joints' `Device/SubDeviceList` keys, a few per joint where a robot has dozens; 2.8 has none, so the joints' temperature keys are missing and the Motor Heat and Get Temperature boxes find no value.
- **LEDs cannot be read back.** `ALLeds` accepts every command, but there is no LED state behind it: `getIntensity` fails.
- **No body id on a NAO V6.** A V4 or V5 reports the placeholder its model file carries.
- **A depth camera that a NAO does not have, on 2.1.** The 2.1 virtual robot lists a third, depth camera, which nothing feeds.

## Postures

- **The 2.8 robot cannot reliably sit.** Without an inertial sensor, NAOqi's posture manager takes the lean of the Stand-to-Sit transition for a perturbation. A config that starts it sitting is refused; Stand, StandInit, StandZero and Crouch work.
- **On 2.1, a standing robot is sometimes read as lying** for about two seconds during animations: `ALRobotPosture.getPostureFamily()` turns to `LyingBack` or `LyingBelly` while the joints stand. No fall is detected; a program that reacts to the posture family may be misled.

## Senses

- **The voice is not a NAO's.** It is an open-source voice per language (a child's voice in English and French), with a NAO's API, tags, events and timing. `sayToFileAndPlay` and `getLanguageEncoding` are missing.
- **Speech recognition is another engine.** It recognises the phrases the robot is listening for, in thirteen languages, with a NAO's API and events; what it accepts and its confidence values are its own, so thresholds tuned on the sim need checking on the robot.
- **Faces are detected, not recognised.** `ALFaceDetection` finds faces; learning a face and recognising a person do nothing. Gaze analysis, sitting-people and waving detection answer and report nothing.
- **A person's distance comes from the size of their face** in the image.
- **A webcam does not turn with the robot's head**, so the robot keeps turning towards a face that stays off-centre. The rendered cameras do turn.
- **Sound has no direction.** A microphone or a mono sound reaches all four of the robot's microphones alike, and there is no sound localization.

## Autonomous Life

- **Life is off when the robot starts**, and the robot is crouched, at rest. Switch it on from the controls page, with `ALAutonomousLife.setState("solitary")`, or in the config.
- **Nothing is installed but the robot's animations** (and, on 2.8, its tactile gestures and its signs and feedback). Dialog topics, applications and the launcher that starts them are yours to install, as on a robot out of the box.
- **On 2.1, activities whose launch conditions read the battery, the temperature, the posture or the time are not launched by themselves**: the robot's plugins that write those conditions do not exist on the desktop NAOqi. Conditions on people work on both versions.

## The window

- **One NAO model for every robot.** A NAO V4, V5 or V6 is drawn, and its cameras rendered, the same.

## What you can rely on

Anything that is NAOqi's own logic runs as on the robot, because it is the same code: `ALMotion`'s joint trajectories and kinematics, `ALRobotPosture`'s transitions (with the two exceptions above), behaviors and their timelines, `ALDialog`'s rules, `ALAutonomousLife`'s states and focus, ALMemory and its events, the package manager. What naoqi-sim replaces (the voice, the sound player, the microphones, speech recognition, face detection, people perception) keeps a NAO's API and event sequences.

So a program that passes on naoqi-sim is right in what it asks NAOqi and in how it reacts to what NAOqi says. Whether the robot stays on its feet, hears you across the room and recognises your face is still to be tried on the robot.

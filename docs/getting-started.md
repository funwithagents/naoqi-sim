# Getting started

Your first simulated NAO: install naoqi-sim, build its images, run the robot, connect to it, stop it. Allow about half an hour, most of it the one-time image build.

## 1. Check what you need

- macOS on Apple silicon, Linux x86_64 or Windows x64.
- Docker, running: `docker info` must answer.
- [uv](https://docs.astral.sh/uv/): `uv --version` must answer. uv installs the right Python itself.
- Free disk: about 11 GB for NAOqi 2.8, 7 GB for 2.1, 16 GB for both.

## 2. Install

```bash
uv tool install --python 3.12 "naoqi-sim[viewer,webcam] @ git+https://github.com/funwithagents/naoqi-sim"
```

This gives you the `naoqi-sim` command. The `viewer` and `webcam` extras are what the window and the webcam need; leave them out on a server.

## 3. Build the images

```bash
naoqi-sim fetch-and-build-images --naoqi 2.8
```

naoqi-sim downloads Aldebaran's desktop NAOqi, the robot's animations and the C++ SDK for NAOqi 2.8 from Aldebaran's public repositories, checks their hashes, builds the Docker images and boots the robot once to verify it. This takes about 20 minutes and is done once. Use `--naoqi 2.1` for a NAO V5, or `--naoqi 2.1 2.8` for both; each version you add is more to download and store.

## 4. Get the NAO's meshes (optional)

```bash
naoqi-sim fetch-meshes
```

The window can draw the robot with Aldebaran's own meshes. They are under CC BY-NC-ND 4.0 (non-commercial): the command shows the license and installs them once you type `yes`. Without them the robot is drawn with simple shapes, and everything else works the same.

## 5. Run the robot

```bash
naoqi-sim run --naoqi 2.8 --viewer --mic --controls
```

The terminal shows each step of the start, then:

```
NAOqi 2.8 (sim): NAOqi 2.8.7.4 ready at tcp://127.0.0.1:9559 (Ctrl-C to stop)
NAOqi 2.8 (sim): controls at http://127.0.0.1:9564/
```

You now have:

- **a window** showing the robot, crouched and at rest, with what its two cameras see in the corner;
- **the controls page** in your browser, to wake it up, change its posture, switch Autonomous Life on, touch its sensors and cover its cameras;
- **its ears**: your microphone (macOS asks for access once);
- **its voice** on your loudspeaker.

The **Mic** and **Robot** buttons at the top right of the controls page mute your microphone (switched off: the robot hears silence) and your loudspeakers (the robot speaks on, unheard).

On the controls page, click **Wake up**, then **Stand**.

## 6. Connect to it

The robot is at `127.0.0.1`, port 9559, as a NAO on your network would be at its own address.

**Choregraphe**: *Connection > Connect to…*, the fixed IP `127.0.0.1`, port 9559. Then run a behavior: a Say box speaks on your loudspeaker, an animation moves the robot in the window.

**A Python script**, with the `qi` package (it came with naoqi-sim; in a project of yours, see [guides/python.md](guides/python.md)):

```python
import qi

session = qi.Session()
session.connect("tcp://127.0.0.1:9559")
session.service("ALTextToSpeech").say("Hello!")
session.service("ALMotion").wakeUp()
session.service("ALRobotPosture").goToPosture("Stand", 0.8)
```

**Autonomous Life**: on the controls page, switch **Life** on. The robot stands up, looks around and turns to the faces it sees; with `--webcam` added to the command, that face is yours. As on a NAO, what it then says and launches comes from the dialog topics and applications installed on it: install yours from Choregraphe, they stay installed from one run to the next.

## 7. Stop it

`Ctrl-C` in the terminal stops the robot and removes its containers. Closing the window alone does not stop it. If a run died without stopping (a closed laptop, a killed terminal), `naoqi-sim cleanup` removes what it left.

## Next

- Other options of `run`, and the other commands: [reference/cli.md](reference/cli.md).
- More languages, Life on at boot, another scene: a config file, [reference/configuration.md](reference/configuration.md).
- What the robot can and cannot do: [features.md](features.md), [reference/differences-from-a-nao.md](reference/differences-from-a-nao.md).
- Starting the robot from your own program or your tests: [guides/python.md](guides/python.md).

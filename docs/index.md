# Documentation

naoqi-sim's documentation, by what you want to do. The [README](../README.md) is the landing page: what naoqi-sim is, how to install it and the first run.

## By task

| I want to… | Read |
|---|---|
| run a simulated NAO for the first time | [getting-started.md](getting-started.md): install, build the images, run, connect Choregraphe or a script, stop |
| know what the simulated robot can do | [features.md](features.md): what is simulated, service by service |
| know where it differs from a real NAO | [reference/differences-from-a-nao.md](reference/differences-from-a-nao.md) |
| choose the NAOqi version, the robot, the window, the webcam, the microphone | [reference/cli.md](reference/cli.md): the options of `naoqi-sim run` |
| change the languages, start with Autonomous Life on, pick a scene, record the audio | [reference/configuration.md](reference/configuration.md): the config file, every field |
| start and stop the robot from a Python program, or in tests and CI | [guides/python.md](guides/python.md) |
| find out why it does not start | [reference/troubleshooting.md](reference/troubleshooting.md): ports, files on disk, common errors |

## The references

- [reference/cli.md](reference/cli.md): every command of `naoqi-sim` and every option.
- [reference/configuration.md](reference/configuration.md): every field of the config file, with its default and what it needs.
- [reference/differences-from-a-nao.md](reference/differences-from-a-nao.md): what the simulated robot does not do as a real one.
- [reference/troubleshooting.md](reference/troubleshooting.md): where naoqi-sim keeps its files, which ports it takes, and what its errors mean.

The design behind every page is in [specs/](../specs/_index.md), one spec per concept; [specs/_overview.md](../specs/_overview.md) is the architecture. The specs are the design with its reasons and measurements; these pages are the user's view of it.

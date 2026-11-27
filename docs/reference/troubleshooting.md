# Troubleshooting

## Ports

naoqi-sim listens on `127.0.0.1` only, on fixed ports, so one robot runs per machine.

| Port | What | When |
|---|---|---|
| 9559 | NAOqi: what every qi client connects to | Always |
| 9562 | The robot's loudspeakers: the containers send the audio to play | Always |
| 9563 | The robot's microphones: the container fetches what they hear | With a microphone (`--mic`) or the fake audio source |
| 9564 | The controls page | With `--controls`; the port is a config field |

`127.0.0.1:9559 is taken` at the start means another naoqi-sim runs, or one died without stopping: `naoqi-sim status` shows it, `naoqi-sim cleanup` removes it. A real NAOqi or Choregraphe's own virtual robot on the same machine takes 9559 too.

## Files on disk

| What | Where |
|---|---|
| The downloads (suites, robot images, SDKs) and the list of verified images | `~/Library/Application Support/naoqi-sim/image-data` on macOS, `~/.local/share/naoqi-sim/image-data` on Linux, `%LOCALAPPDATA%\naoqi-sim\image-data` on Windows; `docker/image-data/` in a checkout of the repository |
| The Docker images | Docker's own storage: `docker images "naoqi-sim/*"` |
| The packages you installed on the robot | Docker volumes `naoqi-sim_packages-2.1` and `naoqi-sim_packages-2.8` |
| The voices and recognition models of the languages you added | Docker volume `naoqi-sim_language-packs` |
| Aldebaran's NAO meshes | naoqi-viewer's own user data folder, shared by every project on the machine: `~/Library/Application Support/naoqi-viewer/meshes` on macOS, `~/.local/share/naoqi-viewer/meshes` on Linux, under `%LOCALAPPDATA%` on Windows; `naoqi-sim fetch-meshes --remove` deletes them |

- `NAOQI_SIM_IMAGE_DATA=<folder>` points naoqi-sim at another download folder, so a checkout and an installed naoqi-sim can share one copy.
- To reset the robot's installed packages: `docker volume rm naoqi-sim_packages-2.8` (or `-2.1`) while nothing runs.
- To drop a NAOqi version you no longer run: `docker rmi naoqi-sim/naoqi:2.1.4.13` (or `:2.8.7.4`), then delete its folder (`2.1` or `2.8`) in the download folder.
- To free everything: remove the three volumes, the images and the download folder.

## Common errors

| Message says | What to do |
|---|---|
| Docker is not available | Start Docker Desktop, OrbStack or the Docker daemon; `docker info` must answer |
| The images are missing, or were built by another naoqi-sim | `naoqi-sim fetch-and-build-images --naoqi <version>`, as the message says |
| This config needs the viewer | Install naoqi-sim with the `viewer` extra (`naoqi-sim[viewer]`), or drop `--viewer` |
| A webcam source needs OpenCV | Install naoqi-sim with the `webcam` extra (`naoqi-sim[webcam]`), or drop `--webcam` |
| The webcam or the microphone cannot be opened | On macOS, allow your terminal in *System Settings > Privacy & Security > Camera* (or *Microphone*), then restart the terminal |
| A port is in use | See "Ports" above |
| The boot failed, with the end of a log | `naoqi-sim logs` has the whole log. A boot on a heavily loaded machine can miss its checks: run it again with less running |
| `which NAOqi?` | Name the version: `--naoqi 2.1` or `--naoqi 2.8` |
| A config key, then a reason (`robot.version: ...`) | The option or the config field named is wrong: [configuration.md](configuration.md) |

## Things that surprise

- **The first start with a new language is slow**: its voice and its recognition model are downloaded (tens of seconds; Swedish's model is 290 MB), once.
- **Closing the window does not stop the robot.** Ctrl-C in the terminal does.
- **The robot hears itself**, as a NAO does: with `--mic` and loudspeakers, what it says comes back through your microphone too. Use a headset if the dialog reacts to its own voice.

Something else: [open an issue](https://github.com/funwithagents/naoqi-sim/issues) with the command you ran, the message, and the output of `naoqi-sim status` and `naoqi-sim logs --tail 200`.

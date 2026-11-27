# The `naoqi-sim` command

| Command | Does |
|---|---|
| [`naoqi-sim fetch-and-build-images`](#fetch-and-build-images) | Downloads Aldebaran's software for the NAOqi versions you name, builds the images and verifies them. Once per machine |
| [`naoqi-sim fetch-meshes`](#fetch-meshes) | Installs Aldebaran's NAO meshes for the window, after a license prompt. Optional |
| [`naoqi-sim run`](#run) | Runs a simulated NAO in the foreground, until Ctrl-C |
| [`naoqi-sim config`](#config) | Prints the config of a robot, to start a config file of your own |
| [`naoqi-sim status`](#status-logs-cleanup) | The containers and the robot's state |
| [`naoqi-sim logs`](#status-logs-cleanup) | The containers' logs |
| [`naoqi-sim cleanup`](#status-logs-cleanup) | Removes what a run that died without stopping left behind |

`naoqi-sim --verbose <command>` adds debug logging, including the container's whole log during a start.

## `fetch-and-build-images`

```
naoqi-sim fetch-and-build-images --naoqi VERSION [VERSION ...] [--image-data DIR]
```

Fetches what each NAOqi version's image is built from (Aldebaran's desktop NAOqi, the robot's animations package extracted from the public robot image, the C++ SDK; all from Aldebaran's public repositories, each checked against a pinned hash), builds the NAOqi image and the three engines' images (speech, face detection, speech recognition), then boots each version once to verify it.

- **`--naoqi` is required**, with one version or both (`--naoqi 2.1 2.8`). Nothing of a version you do not name is downloaded, built or stored: about 7 GB for 2.1 and 11 GB for 2.8, of which 1.5 GB (the engines) is shared.

- It keeps what is already downloaded and rebuilds only what changed.
- Run it again after upgrading naoqi-sim: `run` refuses images built by another version and says so.
- `--image-data DIR` keeps the downloads in `DIR` instead of the default folder ([troubleshooting.md](troubleshooting.md#files-on-disk)).

## `fetch-meshes`

```
naoqi-sim fetch-meshes [--force] [--remove] [--archive PATH]
```

Installs Aldebaran's NAO meshes, so the window shows the real robot instead of placeholder shapes. The meshes are under CC BY-NC-ND 4.0 (non-commercial): the command shows the license and installs nothing until you type `yes`. They are installed once for every project on the machine. It needs the `viewer` extra, and is the same as naoqi-viewer's own `fetch-meshes`.

- `--remove` deletes the installed meshes; `--force` installs them again.
- `--archive PATH` installs from a local copy of the archive instead of downloading it.

## `run`

```
naoqi-sim run --naoqi VERSION [--robot TYPE] [--robot-version VERSION]
              [--viewer] [--webcam] [--mic] [--controls]
naoqi-sim run --config FILE
```

Starts the robot, prints `ready at tcp://127.0.0.1:9559` once any qi client can connect, and stays in the foreground. Ctrl-C stops the robot and removes its containers.

| Option | What it does | Needs |
|---|---|---|
| `--naoqi VERSION` | The NAOqi version: `2.1` or `2.8`. Required | |
| `--robot TYPE` | The robot: `nao`. Left out, the NAOqi version's robot | |
| `--robot-version VERSION` | The robot's version: `v4`, `v5` or `v6`. Left out, `v5` on NAOqi 2.1 and `v6` on 2.8 | |
| `--viewer` | Opens the 3D window, with the two camera images and the people the robot perceives, and feeds both of the robot's cameras what they see in the scene | The `viewer` extra |
| `--webcam` | Feeds the robot's top camera your default webcam. With `--viewer` the bottom camera still sees the scene; without, it is not fed | The `webcam` extra |
| `--mic` | Lets the robot hear your default microphone | |
| `--controls` | Serves the controls page and opens it in your browser | |
| `--config FILE` | Runs the robot a JSON config file describes, instead of every option above | |

- **`--naoqi` is required**: there is no default NAOqi version.
- **With `--naoqi` alone** the robot runs with no window, no camera, no microphone and no controls page, speaking on your loudspeaker. It needs no extra.
- **Which robots each NAOqi runs**: 2.1 a NAO V5 (the default) or V4; 2.8 a NAO V6. Another pair is refused: `robot.version: NAOqi 2.8 does not run a nao v5; it runs: nao v6`.
- **The options or a file, never both**: with `--config`, any other robot option is an error. A run from a file is described by that file alone.
- **A webcam does not turn with the robot's head.** The robot detects you, but its awareness keeps turning the head while you stay off-centre in the image. To check head tracking, use `--viewer` without `--webcam`.
- A missing extra, a missing image, Docker not running or a taken port stops the start before anything runs, with a message saying what to do.

Exit codes: 0 after Ctrl-C, 2 for a wrong option or config (the message names the config key), 1 for any other failure, 130 when Ctrl-C interrupts the start.

## `config`

```
naoqi-sim config --naoqi VERSION [the same options as run]
naoqi-sim config --config FILE
```

Prints, as JSON, the config `run` would run with the same options: every field of every block, at its value. It starts nothing and needs neither Docker nor the images.

```bash
naoqi-sim config --naoqi 2.8 --viewer --mic > my-nao.json
# edit my-nao.json: more languages, Autonomous Life on, another scene...
naoqi-sim run --config my-nao.json
```

With `--config FILE` it prints that file with every default filled in, which checks the file and shows the fields it left out. The fields are described in [configuration.md](configuration.md).

## `status`, `logs`, `cleanup`

These work from any terminal, while a robot runs in another one or after it died.

- **`naoqi-sim status`** prints each container's state and health, then the naoqi-sim and NAOqi versions, whether the robot is ready and what feeds its cameras and microphones. It exits 0 when the robot is ready and 1 otherwise, for scripts.
- **`naoqi-sim logs [--follow] [--tail N]`** shows the containers' logs.
- **`naoqi-sim cleanup`** removes the containers of a run that died without stopping (a killed terminal, a closed laptop), keeping the installed packages. If a run is still alive it changes nothing and says to press Ctrl-C in that run's terminal.

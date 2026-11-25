# Test sentences for the live speech recognition tests

The WAV files here are the sentences `tests-e2e/test_speech_recognition_live.py` plays into the fake room for the robot to hear: 16 kHz, mono, 16-bit, one sentence per file, named after it (`english-hello_robot.wav` is "hello robot").

They are a real person's voice: the project's author, recorded through a NAO 2.1's front microphone (so the robot's fan noise is in them, as it is in what a NAO hears), and contributed under the project's licence (Apache-2.0). No synthesised or third-party audio is used.

To record them again, or in another voice, run `record.py` against a NAO on your network (`uv run python tests-e2e/speech/record.py <robot-ip>`, SSH access as `nao` needed). It prints the sentences to say, records them through the robot's `ALAudioRecorder` and cuts the take into these files. Only commit a voice whose owner agrees to it being published under the project's licence, and check that the tests pass with it: the recogniser should hear each sentence when it is in the vocabulary.

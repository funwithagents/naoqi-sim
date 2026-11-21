# Test sentences for the live speech recognition tests

The WAV files here are the sentences `tests-e2e/test_speech_recognition_live.py` plays into the fake room for the robot to hear: 16 kHz, mono, 16-bit. They were synthesised once with [Piper](https://github.com/OHF-Voice/piper1-gpl) by `generate.py` and are committed, so the tests never synthesise. To change a sentence or a voice, edit `generate.py`, run it (`uv run python tests-e2e/speech/generate.py`, Docker needed) and listen to the result. Piper's synthesis varies a little from run to run, so check a new take against the recogniser before committing it. Any recording of the same sentences can replace these files, a human one included, as long as its licence allows it to be committed.

The speech is synthetic (text-to-speech), not a recording of a person.

## Voices

Both voices were trained from scratch on a permissively licensed dataset, not fine-tuned from another voice.

| Language | Piper voice (piper-voices v1.0.0) | Dataset | Dataset licence |
|---|---|---|---|
| English | `en_US-ljspeech-medium` | [LJ Speech](https://keithito.com/LJ-Speech-Dataset/) | public domain |
| French | `fr_FR-mls-medium`, speaker 14 | [Multilingual LibriSpeech](https://www.openslr.org/94/) (Pratap et al., 2020) | CC BY 4.0 |

The French voice is credited here as CC BY 4.0 requires: it was trained on Multilingual LibriSpeech, by V. Pratap, Q. Xu, A. Sriram, G. Synnaeve and R. Collobert, published under CC BY 4.0.

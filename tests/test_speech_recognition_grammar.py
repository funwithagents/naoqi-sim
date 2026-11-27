"""The phrases ALSpeechRecognition listens for: the dialog's `#BNF+EMV1.1` grammar expanded to
whole phrases (specs/services/speech-recognition.md, "What it listens for"), on grammars written
for these tests in the dialog's format."""

import itertools

import naoqi_sim_speech_recognition_grammar as grammar
import pytest

pytestmark = pytest.mark.container_code

# What the 2.1 dialog writes for two topics, in its own layout: activatable rules per topic,
# a start rule over them, slots it fills with addWordListToSlot.
BNF = """#BNF+EMV1.1;
!grammar "BNFtestEnglish";
!start <start>;
!pronounce get PRONAS "guete";
!slot<robotname>;
!activatable<greet trig>;
!activatable<greet sub r10>;
!activatable<fruit trig>;
<start>:<greet trig>|<greet sub>|<fruit trig>;
<greet trig>:<r1>|<r2>;
<greet sub>:<greet sub r10>;
<greet sub r10>:<r10>;
<fruit trig>:<r3>;
<r1>:hello [there] <robotname>;
<r2>:(good morning|good evening)[<robotname>];
<r10>:how are you;
<r3>:<...>I want (an apple|a banana)<...>;
<r4>:never used;
"""


def phrases(active, slots=None, text=BNF):
    return grammar.Grammar(text).phrases(set(active), slots or {})


def test_the_header_names_the_grammar_its_start_and_its_slots():
    g = grammar.Grammar(BNF)
    assert g.name == "BNFtestEnglish" and g.start == "start"
    assert g.slots == {"robotname"}
    assert g.activatable == {"greet trig", "greet sub r10", "fruit trig"}


def test_only_the_activated_rules_are_listened_for():
    assert sorted(phrases({"start", "greet trig"})) == [
        "good evening",
        "good morning",
    ]  # the slot is empty: the rules that need it give nothing
    assert sorted(phrases({"start", "fruit trig"})) == [
        "<...> I want a banana <...>",
        "<...> I want an apple <...>",
    ]
    assert phrases({"greet trig", "fruit trig"}) == []  # the start rule is not active


def test_a_slot_is_filled_with_the_words_the_dialog_gave():
    slots = {"robotname": ["nao", "leo the robot"]}
    assert sorted(phrases({"start", "greet trig"}, slots)) == [
        "good evening",
        "good evening leo the robot",
        "good evening nao",
        "good morning",
        "good morning leo the robot",
        "good morning nao",
        "hello leo the robot",
        "hello nao",
        "hello there leo the robot",
        "hello there nao",
    ]


def test_a_sub_rule_needs_its_own_activation():
    # the dialog activates a topic's sub-rules one by one, once one of its rules answered
    assert phrases({"start", "greet trig"}).count("how are you") == 0
    assert phrases({"start", "greet sub r10"}) == ["how are you"]


def test_a_repeat_is_taken_once_and_words_with_apostrophes_kept():
    text = """#BNF+EMV1.1;
!start <start>;
<start>:<r1>;
<r1>: !repeat(([please](stop talking |be quiet)),1,10) |comment tu(t'appelles);
"""
    assert sorted(phrases({"start"}, text=text)) == [
        "be quiet",
        "comment tu t'appelles",
        "please be quiet",
        "please stop talking",
        "stop talking",
    ]


def test_the_expansion_is_capped_and_gives_the_short_alternatives_first(monkeypatch):
    # 30 x 30 x 30 phrases in one rule: the cap keeps the first ones, shortest first.
    words = " | ".join(f"w{i}" for i in range(30))
    text = (
        "#BNF+EMV1.1;\n!start <start>;\n<start>:<r1>|<r2>;\n"
        f"<r1>:[({words})] [({words})] ({words});\n<r2>:other;\n"
    )
    monkeypatch.setattr(grammar, "MAX_PER_RULE", 100)
    found = phrases({"start"}, text=text)
    # 100 generated from the long rule (some twice: "[] [w0] w0" and "[w0] [] w0"), and the
    # other rule's phrase
    assert 60 <= len(found) <= 101 and found[-1] == "other"
    assert found[0] == "w0"  # the optional parts left out first


def test_a_grammar_that_refers_to_itself_ends():
    text = "#BNF+EMV1.1;\n!start <start>;\n<start>:<r1>;\n<r1>:again [<r1>];\n"
    found = phrases({"start"}, text=text)
    assert found[0] == "again" and len(found) <= grammar.MAX_PER_RULE


def test_a_big_sub_rule_inside_unknown_speech_is_kept_whole():
    # an application launcher: "<...> <names> <...>" with hundreds of names
    names = "|".join(f"app{i}" for i in range(900))
    text = (
        "#BNF+EMV1.1;\n!start <start>;\n<start>:<r1>;\n<r1>:<...><names><...>;\n"
        f"<names>:{names};\n"
    )
    found = phrases({"start"}, text=text)
    assert len(found) == 900 and found[899] == "<...> app899 <...>"


def test_a_malformed_rule_is_an_error():
    with pytest.raises(grammar.GrammarError):
        grammar.Grammar("#BNF+EMV1.1;\n<start>:(hello;\n")


def test_a_full_dialog_sized_grammar_expands_quickly():
    # 40 topics of 3 rules with 8-way alternatives: the size of a robot's full dialog content.
    lines = ["#BNF+EMV1.1;", "!start <start>;"]
    tops = []
    for t in range(40):
        lines.append(f"!activatable<t{t} trig>;")
        lines.append(f"<t{t} trig>:<a{t}>|<b{t}>|<c{t}>;")
        alt = "|".join(f"x{t}_{i}" for i in range(8))
        for r in "abc":
            lines.append(f"<{r}{t}>:[please] ({alt}) [({alt})] now;")
        tops.append(f"<t{t} trig>")
    lines.append("<start>:{};".format("|".join(tops)))
    text = "\n".join(lines) + "\n"
    active = {"start"} | {f"t{t} trig" for t in range(40)}
    found = grammar.Grammar(text).phrases(active, {})
    assert len(found) == 40 * 2 * 8 * 9  # a topic's three rules say the same
    assert len(set(found)) == len(found)
    assert all(p.endswith(" now") for p in itertools.islice(found, 50))

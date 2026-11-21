# -*- coding: utf-8 -*-
"""The phrases ALSpeechRecognition listens for, from what a dialog gives it (Python 2.7, inside
NAOqi; importable under Python 3 so the host's fast tier tests it).

The 2.1 dialog writes its grammar as text (`#BNF+EMV1.1`) and asks the recognition to compile it;
`Grammar` reads that text and expands the rules the dialog activated to whole phrases, which is
what the engine listens for (specs/services/speech-recognition.md, "What it listens for"). The
2.8 dialog hands over no grammar: the module asks it for each activated topic's sentences
(`ALDialog.generateSentences`), and `sentences` reads that file.
"""
import io
import itertools
import re

GARBAGE = "<...>"  # unknown speech allowed here (word spotting, a dialog's wildcard)
MAX_ALTERNATIVES = 1000  # alternatives kept per position of a sequence, shortest first
MAX_PER_RULE = 3000  # phrases kept per alternative of the start rule
MAX_DEPTH = 40  # rule references followed, against a grammar that refers to itself

_TOKEN = re.compile(r"\s*(<[^>]*>|!repeat|[()\[\]|,]|[^\s()\[\]|,<>!]+)", re.UNICODE)
_RULE = re.compile(r"<([^>]+)>\s*:(.*)$", re.UNICODE | re.DOTALL)


def read_text(path):
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


class GrammarError(ValueError):
    pass


class Grammar(object):
    """A `#BNF+EMV1.1` grammar: its rules, slots, activatable rules and start rule."""

    def __init__(self, text):
        self.name = ""
        self.start = "start"
        self.rules = {}  # name -> parsed body
        self.slots = set()
        self.activatable = set()
        for statement in text.split(";"):
            s = statement.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("!grammar"):
                self.name = s[len("!grammar"):].strip().strip('"')
            elif s.startswith("!start"):
                self.start = s[len("!start"):].strip().strip("<>")
            elif s.startswith("!slot"):
                self.slots.add(s[len("!slot"):].strip().strip("<>"))
            elif s.startswith("!activatable"):
                self.activatable.add(s[len("!activatable"):].strip().strip("<>"))
            elif s.startswith("!"):
                continue  # !pronounce and the others: nothing to listen for
            else:
                m = _RULE.match(s)
                if m:
                    self.rules[m.group(1)] = _Parser(m.group(2)).parse()

    def phrases(self, active, slots):
        """The phrases of the start rule, if it is active: the activatable rules not in `active`
        left out, each slot given its words from `slots` (name -> list of phrases), a repeat
        taken once, shortest alternatives first, capped."""
        if self.start not in active or self.start not in self.rules:
            return []
        body = self.rules[self.start]
        branches = body[1] if body[0] == "alt" else [body]
        found = []
        seen = set()
        for branch in branches:
            for words in itertools.islice(self._gen(branch, active, slots, 0), MAX_PER_RULE):
                phrase = " ".join(w for w in words if w)
                if phrase and phrase != GARBAGE and phrase not in seen:
                    seen.add(phrase)
                    found.append(phrase)
        return found

    def _gen(self, node, active, slots, depth):
        kind = node[0]
        if kind == "word":
            yield (node[1],)
        elif kind == "garbage":
            yield (GARBAGE,)
        elif kind == "ref":
            name = node[1]
            if name in self.slots:
                for phrase in slots.get(name, ()):
                    yield tuple(phrase.split())
            elif name in self.activatable and name not in active:
                return
            elif name in self.rules and depth < MAX_DEPTH:
                for words in self._gen(self.rules[name], active, slots, depth + 1):
                    yield words
        elif kind == "opt":
            yield ()
            for words in self._gen(node[1], active, slots, depth):
                yield words
        elif kind == "alt":
            # round robin over the alternatives: a long one does not hide the others
            gens = [self._gen(child, active, slots, depth) for child in node[1]]
            while gens:
                alive = []
                for g in gens:
                    try:
                        yield next(g)
                        alive.append(g)
                    except StopIteration:
                        pass
                gens = alive
        elif kind == "seq":
            for words in self._seq(node[1], active, slots, depth):
                yield words

    def _seq(self, items, active, slots, depth):
        if not items:
            yield ()
            return
        head = list(itertools.islice(self._gen(items[0], active, slots, depth), MAX_ALTERNATIVES))
        if not head:
            return
        for rest in self._seq(items[1:], active, slots, depth):
            for words in head:
                yield words + rest


class _Parser(object):
    """A rule's body -> nested tuples: ("alt", [..]), ("seq", [..]), ("opt", x), ("ref", name),
    ("word", w), ("garbage",). `!repeat(x, min, max)` is x."""

    def __init__(self, text):
        self.tokens = _TOKEN.findall(text)
        self.pos = 0

    def parse(self):
        node = self._alt()
        if self.pos != len(self.tokens):
            raise GrammarError("unexpected %r" % self.tokens[self.pos])
        return node

    def _peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _take(self, expected=None):
        token = self._peek()
        if token is None or (expected is not None and token != expected):
            raise GrammarError("expected %r, got %r" % (expected, token))
        self.pos += 1
        return token

    def _alt(self):
        branches = [self._seq()]
        while self._peek() == "|":
            self._take("|")
            branches.append(self._seq())
        return ("alt", branches) if len(branches) > 1 else branches[0]

    def _seq(self):
        items = []
        while self._peek() not in (None, ")", "]", "|", ","):
            token = self._take()
            if token == "(":
                items.append(self._alt())
                self._take(")")
            elif token == "[":
                items.append(("opt", self._alt()))
                self._take("]")
            elif token == "!repeat":
                self._take("(")
                items.append(self._alt())
                while self._peek() == ",":  # the bounds
                    self._take(",")
                    self._take()
                self._take(")")
            elif token == GARBAGE:
                items.append(("garbage",))
            elif token.startswith("<"):
                items.append(("ref", token[1:-1]))
            else:
                items.append(("word", token))
        return ("seq", items)


_SENTENCE = re.compile(r"^\((\S+)[^)]*\)\s*(.*)$", re.UNICODE)


def sentences(text):
    """The user rules' sentences of a file `ALDialog.generateSentences` wrote: one line per
    sentence, `(<kind> model:... topic:... lang:... line:n) <sentence>`, kinds `u`, `u1`...,
    `u^private` kept, `concept` and the others left out; the trailing punctuation dropped."""
    found = []
    seen = set()
    for line in text.splitlines():
        m = _SENTENCE.match(line.strip())
        if not m or not m.group(1).startswith("u"):
            continue
        sentence = m.group(2).strip().rstrip("?!.,;: ").strip()
        if sentence and sentence not in seen:
            seen.add(sentence)
            found.append(sentence)
    return found

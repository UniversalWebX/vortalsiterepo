"""STScript — a small, Scratch-like language for custom bot commands.

Design constraints, in order of importance:

1. **No `eval`, no `exec`, no imports.** Scripts are parsed into a fixed set of
   node types and walked by an interpreter that only knows those types. There
   is no path from script text to Python execution, so a malicious script
   can't reach the filesystem, the network, the bot token or the database.

2. **Everything is bounded.** Statement count, loop iterations, nesting depth,
   output count, wall-clock time and string length all have hard ceilings. A
   script cannot hang the bot or spam a channel.

3. **The interpreter performs no side effects.** It returns a list of
   *requested actions*; the cog decides whether the author is allowed to do
   each one. That keeps permission checks out of the language.

Example:

    say Hello {user.name}!
    set count to 3
    repeat {count}
        say Loop number {loop}
    end
    random roll from 1 to 6
    if {roll} > 3
        say You rolled {roll} — nice.
    else
        say You rolled {roll} — unlucky.
    end
"""

from __future__ import annotations

import random as _random
import re
import time
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------- limits

MAX_LINES = 300
MAX_STATEMENTS = 2000      # total executed statements per run
MAX_ITERATIONS = 500       # per repeat loop
MAX_DEPTH = 5              # nested blocks
MAX_ACTIONS = 15           # messages/roles a single run may request
MAX_RUNTIME = 5.0          # seconds of wall clock
MAX_STRING = 1500
MAX_WAIT = 10.0            # total seconds a script may sleep

BLOCK_OPENERS = ("repeat", "if", "while")


class STError(Exception):
    """Raised for both parse and runtime problems; carries a line number."""

    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.message = message
        self.line = line

    def __str__(self) -> str:
        return f"Line {self.line}: {self.message}" if self.line else self.message


# ------------------------------------------------------------------ AST

@dataclass
class Node:
    kind: str
    line: int
    args: dict = field(default_factory=dict)
    body: list["Node"] = field(default_factory=list)
    orelse: list["Node"] = field(default_factory=list)


@dataclass
class Action:
    """Something the script wants the bot to do. The cog decides if it may."""

    kind: str
    data: dict


# ---------------------------------------------------------------- parser

COMPARATORS = ("==", "!=", ">=", "<=", ">", "<", "contains", "is not", "is")


def _split_condition(text: str, line: int) -> tuple[str, str, str]:
    for op in COMPARATORS:
        pattern = rf"\s{re.escape(op)}\s" if op.isalpha() or " " in op else re.escape(op)
        match = re.search(pattern, text)
        if match:
            left = text[: match.start()].strip()
            right = text[match.end():].strip()
            normalised = {"is": "==", "is not": "!="}.get(op.strip(), op.strip())
            if not left or not right:
                raise STError(f"Incomplete comparison: `{text}`", line)
            return left, normalised, right
    raise STError(
        f"I can't read the condition `{text}`. Use something like "
        "`if {score} > 10` or `if {name} is Alex`.",
        line,
    )


def parse(source: str) -> list[Node]:
    lines = source.replace("\r\n", "\n").split("\n")
    if len(lines) > MAX_LINES:
        raise STError(f"Scripts are limited to {MAX_LINES} lines.")

    # (body_list, opener_kind, opener_line, node) for each open block
    stack: list[tuple[list[Node], str, int, Node | None]] = []
    program: list[Node] = []
    current = program

    for number, raw in enumerate(lines, 1):
        text = raw.strip()
        if not text or text.startswith(("#", "//")):
            continue

        lowered = text.lower()
        word = lowered.split(" ", 1)[0]
        rest = text[len(word):].strip()

        if word == "end":
            if not stack:
                raise STError("`end` without a matching block.", number)
            current, _, _, _ = stack.pop()
            continue

        if word == "else":
            if not stack or stack[-1][1] != "if":
                raise STError("`else` can only follow an `if`.", number)
            _, _, _, node = stack[-1]
            current = node.orelse
            continue

        if word in BLOCK_OPENERS:
            if len(stack) >= MAX_DEPTH:
                raise STError(f"Blocks can only nest {MAX_DEPTH} deep.", number)

            if word == "repeat":
                if not rest:
                    raise STError("`repeat` needs a count, e.g. `repeat 3`.", number)
                node = Node("repeat", number, {"count": rest})
            elif word == "while":
                left, op, right = _split_condition(rest, number)
                node = Node("while", number, {"left": left, "op": op, "right": right})
            else:
                left, op, right = _split_condition(rest, number)
                node = Node("if", number, {"left": left, "op": op, "right": right})

            current.append(node)
            stack.append((current, word, number, node))
            current = node.body
            continue

        current.append(_parse_statement(word, rest, text, number))

    if stack:
        _, kind, line, _ = stack[-1]
        raise STError(f"`{kind}` block opened here was never closed with `end`.", line)
    return program


def _parse_statement(word: str, rest: str, whole: str, line: int) -> Node:
    if word == "say":
        if not rest:
            raise STError("`say` needs something to say.", line)
        return Node("say", line, {"text": rest})

    if word == "reply":
        return Node("say", line, {"text": rest, "ephemeral": True})

    if word == "dm":
        return Node("dm", line, {"text": rest})

    if word == "embed":
        title, _, body = rest.partition("|")
        if not title.strip():
            raise STError("`embed` needs a title, e.g. `embed Hello | World`.", line)
        return Node("embed", line, {"title": title.strip(), "body": body.strip()})

    if word == "set":
        match = re.match(r"^(\w+)\s+to\s+(.+)$", rest, re.IGNORECASE)
        if not match:
            raise STError("Use `set name to value`.", line)
        return Node("set", line, {"name": match.group(1), "value": match.group(2)})

    if word == "add":
        match = re.match(r"^(.+?)\s+to\s+(\w+)$", rest, re.IGNORECASE)
        if not match:
            raise STError("Use `add 1 to name`.", line)
        return Node("add", line, {"value": match.group(1), "name": match.group(2)})

    if word == "random":
        match = re.match(r"^(\w+)\s+from\s+(.+?)\s+to\s+(.+)$", rest, re.IGNORECASE)
        if not match:
            raise STError("Use `random name from 1 to 10`.", line)
        return Node(
            "random",
            line,
            {"name": match.group(1), "low": match.group(2), "high": match.group(3)},
        )

    if word == "wait":
        if not rest:
            raise STError("`wait` needs a number of seconds.", line)
        return Node("wait", line, {"seconds": rest})

    if word == "role":
        match = re.match(r"^(add|remove)\s+(.+)$", rest, re.IGNORECASE)
        if not match:
            raise STError("Use `role add <role id or name>`.", line)
        return Node(
            "role", line, {"action": match.group(1).lower(), "role": match.group(2)}
        )

    if word == "stop":
        return Node("stop", line, {})

    raise STError(
        f"I don't know the command `{word}`. Try `/stscript help` for the list.", line
    )


# ------------------------------------------------------------ interpreter

NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")
TOKEN_RE = re.compile(r"\d+\.?\d*|[-+*/%()]")


def _display(value: Any) -> str:
    """Whole numbers print as 150, not 150.0 — script authors write `add 50 to
    coins` and expect to see an integer."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _as_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    return float(text) if NUMBER_RE.match(text) else None


def _arith(expression: str, line: int) -> float | None:
    """Evaluate + - * / % over numbers only.

    A hand-rolled shunting-yard rather than eval(): eval on user input would
    hand script authors arbitrary Python, which is the whole thing this
    language exists to avoid.
    """
    tokens = TOKEN_RE.findall(expression)
    if not tokens or "".join(tokens).replace(" ", "") != expression.replace(" ", ""):
        return None

    precedence = {"+": 1, "-": 1, "*": 2, "/": 2, "%": 2}
    output: list[float] = []
    operators: list[str] = []

    def apply(op: str) -> None:
        if len(output) < 2:
            raise STError(f"Malformed expression `{expression}`.", line)
        b, a = output.pop(), output.pop()
        if op in "/%" and b == 0:
            raise STError("Division by zero.", line)
        output.append(
            {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else 0, "%": a % b if b else 0}[op]
        )

    for token in tokens:
        if NUMBER_RE.match(token):
            output.append(float(token))
        elif token == "(":
            operators.append(token)
        elif token == ")":
            while operators and operators[-1] != "(":
                apply(operators.pop())
            if not operators:
                raise STError("Unbalanced brackets.", line)
            operators.pop()
        else:
            while (
                operators
                and operators[-1] != "("
                and precedence.get(operators[-1], 0) >= precedence[token]
            ):
                apply(operators.pop())
            operators.append(token)

    while operators:
        op = operators.pop()
        if op == "(":
            raise STError("Unbalanced brackets.", line)
        apply(op)

    return output[0] if len(output) == 1 else None


class Interpreter:
    def __init__(self, variables: dict[str, Any] | None = None, rng=_random):
        self.vars: dict[str, Any] = dict(variables or {})
        self.actions: list[Action] = []
        self.statements = 0
        self.waited = 0.0
        self.rng = rng
        self.started = 0.0
        self._stopped = False

    # -- values -----------------------------------------------------------

    def interpolate(self, text: str, line: int) -> str:
        def replace(match: re.Match) -> str:
            key = match.group(1).strip()
            if key not in self.vars:
                raise STError(f"Unknown variable `{{{key}}}`.", line)
            return _display(self.vars[key])

        result = re.sub(r"\{([^{}]+)\}", replace, str(text))
        if len(result) > MAX_STRING:
            raise STError(f"Text longer than {MAX_STRING} characters.", line)
        return result

    def value_of(self, raw: str, line: int) -> Any:
        filled = self.interpolate(raw, line).strip()
        number = _as_number(filled)
        if number is not None:
            return number
        computed = _arith(filled, line)
        return computed if computed is not None else filled

    # -- execution --------------------------------------------------------

    def run(self, program: list[Node]) -> list[Action]:
        self.started = time.monotonic()
        self._execute(program)
        return self.actions

    def _tick(self, line: int) -> None:
        self.statements += 1
        if self.statements > MAX_STATEMENTS:
            raise STError(
                f"Script did more than {MAX_STATEMENTS} steps — check for a runaway loop.",
                line,
            )
        if time.monotonic() - self.started > MAX_RUNTIME:
            raise STError(f"Script ran longer than {MAX_RUNTIME} seconds.", line)

    def _emit(self, action: Action, line: int) -> None:
        if len(self.actions) >= MAX_ACTIONS:
            raise STError(
                f"Scripts may only send {MAX_ACTIONS} things per run.", line
            )
        self.actions.append(action)

    # Explicit dispatch table rather than getattr(self, "_do_" + kind).
    # Node.kind can only ever be one of these (the parser sets it), but an
    # explicit map means no string from a script can ever name a method.
    def _handlers(self) -> dict:
        return {
            "say": self._do_say,
            "dm": self._do_dm,
            "embed": self._do_embed,
            "set": self._do_set,
            "add": self._do_add,
            "random": self._do_random,
            "wait": self._do_wait,
            "role": self._do_role,
            "stop": self._do_stop,
            "repeat": self._do_repeat,
            "while": self._do_while,
            "if": self._do_if,
        }

    def _execute(self, nodes: list[Node]) -> None:
        handlers = self._handlers()
        for node in nodes:
            if self._stopped:
                return
            self._tick(node.line)
            handler = handlers.get(node.kind)
            if handler is None:
                raise STError(f"Unsupported statement `{node.kind}`.", node.line)
            handler(node)

    # -- statements -------------------------------------------------------

    def _do_say(self, node: Node) -> None:
        self._emit(
            Action(
                "say",
                {
                    "text": self.interpolate(node.args["text"], node.line),
                    "ephemeral": node.args.get("ephemeral", False),
                },
            ),
            node.line,
        )

    def _do_dm(self, node: Node) -> None:
        self._emit(
            Action("dm", {"text": self.interpolate(node.args["text"], node.line)}),
            node.line,
        )

    def _do_embed(self, node: Node) -> None:
        self._emit(
            Action(
                "embed",
                {
                    "title": self.interpolate(node.args["title"], node.line),
                    "body": self.interpolate(node.args["body"], node.line),
                },
            ),
            node.line,
        )

    def _do_set(self, node: Node) -> None:
        self.vars[node.args["name"]] = self.value_of(node.args["value"], node.line)

    def _do_add(self, node: Node) -> None:
        name = node.args["name"]
        current = _as_number(self.vars.get(name, 0))
        amount = _as_number(self.value_of(node.args["value"], node.line))
        if current is None or amount is None:
            raise STError(f"`add` only works on numbers (`{name}`).", node.line)
        self.vars[name] = current + amount

    def _do_random(self, node: Node) -> None:
        low = _as_number(self.value_of(node.args["low"], node.line))
        high = _as_number(self.value_of(node.args["high"], node.line))
        if low is None or high is None:
            raise STError("`random` needs two numbers.", node.line)
        if low > high:
            low, high = high, low
        self.vars[node.args["name"]] = self.rng.randint(int(low), int(high))

    def _do_wait(self, node: Node) -> None:
        seconds = _as_number(self.value_of(node.args["seconds"], node.line))
        if seconds is None or seconds < 0:
            raise STError("`wait` needs a positive number.", node.line)
        self.waited += seconds
        if self.waited > MAX_WAIT:
            raise STError(f"Total waiting is capped at {MAX_WAIT} seconds.", node.line)
        self._emit(Action("wait", {"seconds": seconds}), node.line)

    def _do_role(self, node: Node) -> None:
        self._emit(
            Action(
                "role",
                {
                    "action": node.args["action"],
                    "role": self.interpolate(node.args["role"], node.line),
                },
            ),
            node.line,
        )

    def _do_stop(self, node: Node) -> None:
        self._stopped = True

    def _do_repeat(self, node: Node) -> None:
        count = _as_number(self.value_of(node.args["count"], node.line))
        if count is None:
            raise STError("`repeat` needs a number.", node.line)
        count = int(count)
        if count < 0:
            raise STError("`repeat` can't be negative.", node.line)
        if count > MAX_ITERATIONS:
            raise STError(
                f"`repeat` is capped at {MAX_ITERATIONS} (you asked for {count}).",
                node.line,
            )
        outer = self.vars.get("loop")
        for index in range(count):
            if self._stopped:
                break
            self.vars["loop"] = index + 1
            self._tick(node.line)
            self._execute(node.body)
        # Restore the enclosing loop counter so nested loops don't clobber it.
        if outer is None:
            self.vars.pop("loop", None)
        else:
            self.vars["loop"] = outer

    def _do_while(self, node: Node) -> None:
        iterations = 0
        while self._compare(node):
            if self._stopped:
                break
            iterations += 1
            if iterations > MAX_ITERATIONS:
                raise STError(
                    f"`while` ran more than {MAX_ITERATIONS} times — it may never end.",
                    node.line,
                )
            self._tick(node.line)
            self._execute(node.body)

    def _do_if(self, node: Node) -> None:
        if self._compare(node):
            self._execute(node.body)
        else:
            self._execute(node.orelse)

    def _compare(self, node: Node) -> bool:
        left = self.value_of(node.args["left"], node.line)
        right = self.value_of(node.args["right"], node.line)
        op = node.args["op"]

        if op == "contains":
            return str(right).lower() in str(left).lower()

        ln, rn = _as_number(left), _as_number(right)
        if ln is not None and rn is not None:
            left, right = ln, rn
        elif op in (">", "<", ">=", "<="):
            # Comparing text with > is almost always a mistake, so say so
            # rather than silently comparing alphabetically.
            raise STError(
                f"Can't compare `{left}` and `{right}` with `{op}` — those aren't numbers.",
                node.line,
            )
        else:
            left, right = str(left).lower(), str(right).lower()

        return {
            "==": left == right,
            "!=": left != right,
            ">": left > right,
            "<": left < right,
            ">=": left >= right,
            "<=": left <= right,
        }[op]


def run_script(source: str, variables: dict[str, Any] | None = None) -> list[Action]:
    """Parse and run, returning the requested actions."""
    return Interpreter(variables).run(parse(source))


HELP_TEXT = """**Output**
`say <text>` — send a message
`reply <text>` — reply privately to whoever ran it
`dm <text>` — DM the runner
`embed <title> | <body>` — send an embed

**Variables**
`set name to <value>` — numbers, text, or maths like `5 * 3`
`add <n> to name` — increase a number
`random name from 1 to 10` — pick a random number
Use a variable with braces: `say You have {coins} coins`

**Control**
`repeat <n>` … `end` — loop, with `{loop}` as the counter
`while <a> <op> <b>` … `end` — loop while true
`if <a> <op> <b>` … `else` … `end` — branch
`stop` — end the script early
Operators: `==` `!=` `>` `<` `>=` `<=` `contains` `is` `is not`

**Other**
`wait <seconds>` — pause (10s total per script)
`role add <name or id>` / `role remove <…>` — needs Manage Roles
`#` starts a comment

**Built-in variables**
`{user}` `{user.name}` `{user.id}` `{server}` `{channel}` `{args}` `{arg1}`…"""

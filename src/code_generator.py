#!/usr/bin/env python3
"""Three-register code generator for a small, documented TAC language."""

from __future__ import annotations

import argparse
from bisect import bisect_left
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

REGISTERS = ("R0", "R1", "R2")
IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
ATOM = rf"(?:{IDENT}|-?\d+)"


class TACError(ValueError):
    """Raised when an input line is outside the supported TAC grammar."""


@dataclass(frozen=True)
class Instruction:
    op: str
    dest: Optional[str] = None
    left: Optional[str] = None
    right: Optional[str] = None
    label: Optional[str] = None
    target: Optional[str] = None
    comparator: Optional[str] = None
    operator: Optional[str] = None
    line: int = 0

    @property
    def uses(self) -> tuple[str, ...]:
        return tuple(x for x in (self.left, self.right) if x and is_variable(x))

    @property
    def defines(self) -> tuple[str, ...]:
        return (self.dest,) if self.dest else ()


def is_variable(token: str) -> bool:
    return re.fullmatch(IDENT, token) is not None


def parse_tac(text: str) -> list[Instruction]:
    """Parse assignments, I/O, labels, branches, and returns from TAC text."""
    result: list[Instruction] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        patterns = [
            (rf"(?P<label>{IDENT}):", "label"),
            (rf"goto\s+(?P<target>{IDENT})", "goto"),
            (rf"if\s+(?P<left>{ATOM})\s*(?P<cmp>==|!=|<=|>=|<|>)\s*(?P<right>{ATOM})\s+goto\s+(?P<target>{IDENT})", "if"),
            (rf"print\s+(?P<left>{ATOM})", "print"),
            (rf"read\s+(?P<dest>{IDENT})", "read"),
            (rf"return(?:\s+(?P<left>{ATOM}))?", "return"),
            (rf"(?P<dest>{IDENT})\s*=\s*(?P<left>{ATOM})\s*(?P<operator>[+\-*/])\s*(?P<right>{ATOM})", "binary"),
            (rf"(?P<dest>{IDENT})\s*=\s*(?P<left>{ATOM})", "copy"),
        ]
        for pattern, kind in patterns:
            match = re.fullmatch(pattern, line, flags=re.IGNORECASE)
            if not match:
                continue
            g = match.groupdict()
            if kind == "label":
                ins = Instruction(kind, label=g["label"], line=line_no)
            elif kind == "goto":
                ins = Instruction(kind, target=g["target"], line=line_no)
            elif kind == "if":
                ins = Instruction(kind, left=g["left"], right=g["right"],
                                  target=g["target"], comparator=g["cmp"], line=line_no)
            elif kind == "binary":
                ins = Instruction(kind, dest=g["dest"], left=g["left"],
                                  right=g["right"], operator=g["operator"], line=line_no)
            elif kind == "copy":
                ins = Instruction(kind, dest=g["dest"], left=g["left"], line=line_no)
            elif kind == "read":
                ins = Instruction(kind, dest=g["dest"], line=line_no)
            else:
                ins = Instruction(kind, left=g.get("left"), line=line_no)
            result.append(ins)
            break
        else:
            raise TACError(f"line {line_no}: unsupported TAC statement: {raw.strip()!r}")

    labels: dict[str, int] = {}
    for i, ins in enumerate(result):
        if ins.op == "label":
            if ins.label in labels:
                raise TACError(f"line {ins.line}: duplicate label {ins.label!r}")
            labels[ins.label] = i
    for ins in result:
        if ins.op in ("goto", "if") and ins.target not in labels:
            raise TACError(f"line {ins.line}: undefined label {ins.target!r}")
    return result


class NextUseIndex:
    """Sparse per-variable use positions; avoids an O(n*v) snapshot matrix."""

    def __init__(self, code: list[Instruction]):
        # Event kind 0 is a use and kind 1 is a definition. A definition ends
        # the current value's live range; at one instruction a read precedes
        # its write (for example, x = x + 1).
        positions: dict[str, list[tuple[int, int]]] = {}
        for index, ins in enumerate(code):
            for name in ins.uses:
                positions.setdefault(name, []).append((index, 0))
            for name in ins.defines:
                positions.setdefault(name, []).append((index, 1))
        self.positions = {name: tuple(indices) for name, indices in positions.items()}

    def next_use(self, name: Optional[str], index: int) -> Optional[int]:
        if name is None:
            return None
        uses = self.positions.get(name, ())
        offset = bisect_left(uses, (index, 0))
        if offset == len(uses) or uses[offset][1] == 1:
            return None
        return uses[offset][0]


def analyze_liveness(code: list[Instruction]) -> NextUseIndex:
    """Index uses by variable; queries return the nearest use at/after index.

    For n instructions and v distinct variables, building the sparse index takes
    O(n) expected time and O(n + v) space. A query is O(log n) by binary search.
    With three registers, getReg checks at most three victims per instruction,
    so allocation and next-use queries take O(n log n) time overall.
    """
    return NextUseIndex(code)


def _initial_memory_variables(code: list[Instruction]) -> set[str]:
    """Names read before a TAC definition are assumed to arrive in memory."""
    defined: set[str] = set()
    inputs: set[str] = set()
    for ins in code:
        inputs.update(name for name in ins.uses if name not in defined)
        defined.update(ins.defines)
    return inputs


class CodeGenerator:
    """Generate pseudo-assembly and maintain register/value descriptors."""

    def __init__(self, code: list[Instruction]):
        self.code = code
        self.next_uses = analyze_liveness(code)
        self.reg_to_var: dict[str, Optional[str]] = {r: None for r in REGISTERS}
        self.var_to_reg: dict[str, str] = {}
        self.memory_valid = _initial_memory_variables(code)
        self.spilled_values: set[str] = set()
        self.output: list[str] = []
        self.reload_count = 0
        self.spill_count = 0
        self.load_count = 0
        self.flush_store_count = 0

    def emit(self, line: str) -> None:
        self.output.append(line)

    def forget_reg(self, reg: str) -> None:
        old = self.reg_to_var[reg]
        if old is not None:
            self.var_to_reg.pop(old, None)
        self.reg_to_var[reg] = None

    def getReg(self, index: int, pinned: Iterable[str] = (), discard: Iterable[str] = ()) -> str:
        """Choose a register: empty first, else farthest-next-use non-pinned value."""
        pinned_set, discard_set = set(pinned), set(discard)
        for reg in REGISTERS:
            if self.reg_to_var[reg] is None and reg not in pinned_set:
                return reg
        candidates = [r for r in REGISTERS if r not in pinned_set]
        if not candidates:
            raise RuntimeError("getReg called with every register pinned")
        # A destination's old value is dead at a redefinition and can be discarded.
        victim_uses = {r: self.next_uses.next_use(self.reg_to_var[r], index) for r in candidates}
        chosen = max(candidates, key=lambda r: (
            self.reg_to_var[r] in discard_set,
            victim_uses[r] is None,
            victim_uses[r] if victim_uses[r] is not None else -1,
        ))
        victim = self.reg_to_var[chosen]
        if victim is not None and victim not in discard_set and victim not in self.memory_valid:
            self.emit(f"STORE {chosen}, {victim}    ; spill")
            self.memory_valid.add(victim)
            self.spilled_values.add(victim)
            self.spill_count += 1
        self.forget_reg(chosen)
        return chosen

    def load(self, value: str, index: int, pinned: Iterable[str] = (),
             discard: Iterable[str] = ()) -> str:
        if not is_variable(value):
            raise ValueError("constants do not occupy registers")
        if value in self.var_to_reg:
            return self.var_to_reg[value]
        reg = self.getReg(index, pinned, discard)
        is_spill_reload = value in self.spilled_values and value in self.memory_valid
        suffix = "    ; reload" if is_spill_reload else ""
        self.emit(f"LOAD {reg}, {value}{suffix}")
        if is_spill_reload:
            self.reload_count += 1
        else:
            self.load_count += 1
        self.reg_to_var[reg] = value
        self.var_to_reg[value] = reg
        return reg

    def bind(self, reg: str, variable: str) -> None:
        old = self.reg_to_var[reg]
        if old is not None and old != variable:
            self.var_to_reg.pop(old, None)
        previous = self.var_to_reg.get(variable)
        if previous is not None and previous != reg:
            self.forget_reg(previous)
        self.reg_to_var[reg] = variable
        self.var_to_reg[variable] = reg
        self.memory_valid.discard(variable)
        self.spilled_values.discard(variable)

    def flush(self) -> None:
        for reg in REGISTERS:
            variable = self.reg_to_var[reg]
            if variable is not None and variable not in self.memory_valid:
                self.emit(f"STORE {reg}, {variable}    ; flush")
                self.memory_valid.add(variable)
                self.flush_store_count += 1
        self.reg_to_var = {r: None for r in REGISTERS}
        self.var_to_reg.clear()

    def generate(self) -> str:
        for i, ins in enumerate(self.code):
            if ins.op in ("label", "goto", "if", "return"):
                self.flush()
            if ins.op == "label":
                self.emit(f"{ins.label}:")
            elif ins.op == "goto":
                self.emit(f"JMP {ins.target}")
            elif ins.op == "if":
                left = ins.left if not is_variable(ins.left) else self.load(ins.left, i)
                right = ins.right if not is_variable(ins.right) else self.load(
                    ins.right, i, {left} if left in REGISTERS else set())
                self.emit(f"CMP {left}, {right}")
                branch = {"==": "JE", "!=": "JNE", "<": "JL", ">": "JG",
                          "<=": "JLE", ">=": "JGE"}[ins.comparator]
                self.emit(f"{branch} {ins.target}")
                self.flush()
            elif ins.op == "read":
                reg = self.getReg(i, discard=(ins.dest,))
                self.emit(f"READ {reg}")
                self.bind(reg, ins.dest)
            elif ins.op == "print":
                value = ins.left if not is_variable(ins.left) else self.load(ins.left, i)
                self.emit(f"PRINT {value}")
            elif ins.op == "return":
                if ins.left is not None:
                    value = ins.left if not is_variable(ins.left) else self.load(ins.left, i)
                    self.emit(f"RET {value}")
                else:
                    self.emit("RET")
                self.flush()
            elif ins.op == "copy":
                # Compare TAC names before loading: a register name (R0) can
                # never equal the destination variable name (for example x).
                if is_variable(ins.left) and ins.left == ins.dest:
                    continue
                source = (ins.left if not is_variable(ins.left)
                          else self.load(ins.left, i, discard=(ins.dest,)))
                pinned = {source} if source in REGISTERS else set()
                reg = self.getReg(i, pinned, discard=(ins.dest,))
                self.emit(f"MOV {reg}, {source}")
                self.bind(reg, ins.dest)
            elif ins.op == "binary":
                # If the old destination is also a source, preserve it through
                # both operand loads. Otherwise it is safe to discard early.
                discard = (ins.dest,) if ins.dest not in ins.uses else ()
                left = (ins.left if not is_variable(ins.left)
                        else self.load(ins.left, i, discard=discard))
                pinned = {left} if left in REGISTERS else set()
                right = ins.right if not is_variable(ins.right) else self.load(
                    ins.right, i, {left} if left in REGISTERS else set(), discard)
                if right in REGISTERS:
                    pinned.add(right)
                reg = self.getReg(i, pinned, discard=(ins.dest,))
                mnemonic = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV"}[ins.operator]
                self.emit(f"{mnemonic} {reg}, {left}, {right}")
                self.bind(reg, ins.dest)
        self.flush()
        self.emit("HALT")
        return "\n".join(self.output)


def generate_code(text: str) -> str:
    return CodeGenerator(parse_tac(text)).generate()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="TAC file; reads stdin when omitted")
    parser.add_argument("-o", "--output", help="write assembly-like output to this file")
    args = parser.parse_args(argv)
    try:
        source = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
        assembly = generate_code(source)
    except (OSError, TACError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    if args.output:
        Path(args.output).write_text(assembly + "\n", encoding="utf-8")
    else:
        print(assembly)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

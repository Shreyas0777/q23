"""Tests for TAC parsing, three-register allocation, and pseudo-ISA semantics."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from code_generator import (  # noqa: E402
    CodeGenerator, TACError, analyze_liveness, generate_code, parse_tac,
)


def _value(token, regs, memory):
    if token in regs:
        return regs[token]
    try:
        return int(token)
    except ValueError:
        return memory[token]


def _compare(a, op, b):
    return {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b,
            ">": a > b, ">=": a >= b}[op]


def execute_assembly(assembly: str, initial=None, inputs=()):
    """Execute the emitted educational instruction set for test verification."""
    lines = assembly.splitlines()
    labels = {line[:-1]: i for i, line in enumerate(lines) if line.endswith(":")}
    regs, memory, prints = {}, dict(initial or {}), []
    input_values = iter(inputs)
    comparison = None
    return_value = None
    pc = 0
    while pc < len(lines):
        line = lines[pc]
        pc += 1
        if not line or line.endswith(":"):
            continue
        parts = line.split(";")[0].replace(",", " ").split()
        op, args = parts[0], parts[1:]
        if op == "HALT":
            break
        if op == "LOAD":
            regs[args[0]] = memory[args[1]]
        elif op == "STORE":
            memory[args[1]] = regs[args[0]]
        elif op == "MOV":
            regs[args[0]] = _value(args[1], regs, memory)
        elif op in ("ADD", "SUB", "MUL", "DIV"):
            a, b = _value(args[1], regs, memory), _value(args[2], regs, memory)
            regs[args[0]] = {"ADD": lambda: a+b, "SUB": lambda: a-b,
                             "MUL": lambda: a*b, "DIV": lambda: a//b}[op]()
        elif op == "READ":
            regs[args[0]] = next(input_values)
        elif op == "PRINT":
            prints.append(_value(args[0], regs, memory))
        elif op == "CMP":
            a, b = _value(args[0], regs, memory), _value(args[1], regs, memory)
            comparison = (a, b)
        elif op == "JMP":
            pc = labels[args[0]]
        elif op in ("JE", "JNE", "JL", "JLE", "JG", "JGE"):
            assert comparison is not None
            cmp_op = {"JE": "==", "JNE": "!=", "JL": "<", "JLE": "<=",
                      "JG": ">", "JGE": ">="}[op]
            if _compare(comparison[0], cmp_op, comparison[1]):
                pc = labels[args[0]]
        elif op == "RET":
            return_value = _value(args[0], regs, memory) if args else None
            break
        else:
            raise AssertionError(f"unknown generated opcode {op}")
    return memory, prints, return_value


def execute_tac(text, initial=None, inputs=()):
    """Independent reference execution of the documented TAC subset."""
    code = parse_tac(text)
    labels = {ins.label: i for i, ins in enumerate(code) if ins.op == "label"}
    env, prints = dict(initial or {}), []
    input_values = iter(inputs)
    pc = 0
    while pc < len(code):
        ins = code[pc]
        pc += 1
        atom = lambda x: int(x) if x.lstrip("-").isdigit() else env[x]
        if ins.op == "label":
            continue
        if ins.op == "read":
            env[ins.dest] = next(input_values)
        elif ins.op == "print":
            prints.append(atom(ins.left))
        elif ins.op == "copy":
            env[ins.dest] = atom(ins.left)
        elif ins.op == "binary":
            a, b = atom(ins.left), atom(ins.right)
            env[ins.dest] = {"+": lambda: a+b, "-": lambda: a-b,
                             "*": lambda: a*b, "/": lambda: a//b}[ins.operator]()
        elif ins.op == "if" and _compare(atom(ins.left), ins.comparator, atom(ins.right)):
            pc = labels[ins.target]
        elif ins.op == "goto":
            pc = labels[ins.target]
        elif ins.op == "return":
            return env, prints, atom(ins.left) if ins.left is not None else None
    return env, prints, None


def test_empty_input_emits_halt():
    assert generate_code("") == "HALT"


def test_single_literal_assignment():
    asm = generate_code("x = 42")
    assert execute_assembly(asm)[0]["x"] == 42


@pytest.mark.parametrize(("operator", "a", "b", "expected"), [
    ("+", 7, 5, 12), ("-", 20, 6, 14), ("*", 9, 3, 27), ("/", 19, 2, 9),
])
def test_arithmetic_semantics(operator, a, b, expected):
    tac = f"x = a {operator} b"
    expected_env, _, _ = execute_tac(tac, {"a": a, "b": b})
    actual_env, _, _ = execute_assembly(generate_code(tac), {"a": a, "b": b})
    assert actual_env["x"] == expected_env["x"] == expected


def test_initial_memory_values_do_not_get_spilled_without_need():
    gen = CodeGenerator(parse_tac("x = a + b"))
    asm = gen.generate()
    assert {"a", "b"} <= gen.memory_valid
    assert "; spill" not in asm
    assert gen.spill_count == 0
    assert gen.load_count == 2
    assert gen.reload_count == 0

    # With all registers occupied, redefinitions may discard the old
    # destination while loading operands, but must preserve active sources.
    for tac, initial, expected in (
        ("x = 1\na = 2\nb = 3\nx = y", {"y": 4}, 4),
        ("x = 1\na = 2\nb = 3\nx = y + 1", {"y": 4}, 5),
    ):
        overwrite = CodeGenerator(parse_tac(tac))
        assembly = overwrite.generate()
        actual, _, _ = execute_assembly(assembly, initial)
        reference, _, _ = execute_tac(tac, initial)
        assert actual["x"] == reference["x"] == expected
        assert not re.search(r"STORE R[0-2], x\s+; spill", assembly)

    self_copy = generate_code("x = x")
    assert self_copy == "HALT"

    # A destination that is also a source is active and must stay pinned.
    for tac, initial, expected in (
        ("x = x + y", {"x": 3, "y": 4}, 7),
        ("x = y + x", {"x": 3, "y": 4}, 7),
        ("x = x + x", {"x": 3}, 6),
    ):
        active_destination = CodeGenerator(parse_tac(tac))
        assembly = active_destination.generate()
        actual, _, _ = execute_assembly(assembly, initial)
        reference, _, _ = execute_tac(tac, initial)
        assert actual["x"] == reference["x"] == expected


def test_register_pressure_causes_real_spill_and_reload_and_correct_value():
    tac = "t1 = a + b\nt2 = c + d\nt3 = e + f\nt4 = t1 * t2\nx = t3 + t4"
    gen = CodeGenerator(parse_tac(tac))
    asm = gen.generate()
    actual, _, _ = execute_assembly(asm, dict(a=1, b=2, c=3, d=4, e=5, f=6))
    expected, _, _ = execute_tac(tac, dict(a=1, b=2, c=3, d=4, e=5, f=6))
    assert actual["x"] == expected["x"] == 32
    assert "; spill" in asm and "; reload" in asm
    spilled = re.findall(r"STORE R[0-2], (\w+)\s+; spill", asm)
    reloaded = re.findall(r"LOAD R[0-2], (\w+)\s+; reload", asm)
    assert spilled and set(spilled) & set(reloaded)
    assert gen.spill_count == asm.count("; spill")
    assert gen.reload_count == asm.count("; reload") >= 1


def test_allocator_uses_only_the_three_declared_registers():
    tac = "t1=a+b\nt2=c+d\nt3=e+f\nx=t1+t2\ny=x+t3"
    asm = generate_code(tac)
    used = {int(n) for n in re.findall(r"\bR(\d+)\b", asm)}
    assert used <= {0, 1, 2}
    assert used


def test_sparse_next_use_index_stops_at_redefinition():
    code = parse_tac("x = a + 1\nx = b + 1\ny = x + 1")
    index = analyze_liveness(code)
    assert index.next_use("x", 0) is None
    assert index.next_use("x", 1) is None
    assert index.next_use("x", 2) == 2
    assert len(index.positions) <= 4


def test_read_print_and_return_execute_correctly():
    tac = "read a\nx = a + 2\nprint x\nreturn x"
    expected = execute_tac(tac, inputs=[21])
    actual = execute_assembly(generate_code(tac), inputs=[21])
    assert actual[0]["x"] == expected[0]["x"] == 23
    assert actual[1] == expected[1] == [23]
    assert actual[2] == expected[2] == 23


def test_conditional_and_unconditional_branches_execute_correctly():
    tac = ("if a >= 5 goto high\nx = 1\ngoto done\n"
           "high:\nx = 2\ndone:\nprint x\nreturn x")
    for a, value in ((2, 1), (8, 2)):
        expected = execute_tac(tac, {"a": a})
        actual = execute_assembly(generate_code(tac), {"a": a})
        assert actual[0]["x"] == expected[0]["x"] == value
        assert actual[1:] == expected[1:] == ([value], value)


def test_sample_files_generate_valid_three_register_code():
    for path in (ROOT / "samples").glob("*.tac"):
        asm = generate_code(path.read_text(encoding="utf-8"))
        assert asm.endswith("HALT")
        assert not re.search(r"\bR[3-9]\d*\b", asm)


def test_comments_and_blank_lines_are_ignored():
    assert len(parse_tac("# note\n\n x = 2 # inline\n")) == 1


def test_labels_and_comparison_are_parsed_and_emitted():
    tac = "if a >= 10 goto done\nx = 1\ndone:"
    assert parse_tac(tac)[0].comparator == ">="
    assert "JGE done" in generate_code(tac)


@pytest.mark.parametrize("source", ["x =", "x = a ** b", "jump nowhere", "x = (a + b)"])
def test_malformed_tac_is_rejected(source):
    with pytest.raises(TACError):
        parse_tac(source)


def test_undefined_and_duplicate_labels_are_rejected():
    with pytest.raises(TACError, match="undefined label"):
        parse_tac("goto missing")
    with pytest.raises(TACError, match="duplicate label"):
        parse_tac("again:\nagain:")


def test_cli_writes_generated_output_file(tmp_path):
    source, output = tmp_path / "in.tac", tmp_path / "out.asm"
    source.write_text("x = 2 + 3", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(ROOT / "src" / "code_generator.py"),
                           str(source), "-o", str(output)], capture_output=True, text=True)
    assert proc.returncode == 0 and "ADD" in output.read_text(encoding="utf-8")


def test_cli_reports_invalid_tac():
    proc = subprocess.run([sys.executable, str(ROOT / "src" / "code_generator.py")],
                          input="x =", capture_output=True, text=True)
    assert proc.returncode != 0 and "unsupported TAC" in proc.stderr

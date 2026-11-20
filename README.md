# Q23 Three Register TAC Code Generator

This project translates a small three-address-code (TAC) language into readable assembly-like instructions for exactly three registers: `R0`, `R1`, and `R2`. It demonstrates register descriptors, next-use information, register reuse, spilling, and reloading. The target is educational pseudo-assembly; it is not directly executable on a real processor.

## Requirements

- Python 3.10 or newer
- No third-party packages to run the generator
- Install `requirements.txt` to run tests and rebuild the DOCX report

```powershell
python -m pip install -r requirements.txt
```

## Run

From the project folder:

```powershell
python src/code_generator.py samples/sample2.tac
```

Save output to a file:

```powershell
python src/code_generator.py samples/sample3.tac --output sample3.asm
```

Or pipe TAC through standard input:

```powershell
Get-Content samples/sample1.tac | python src/code_generator.py
```

Run all automated checks:

```powershell
python -m pytest -q
```

## TAC supported

One statement per line. `#` starts a comment.

```text
t1 = a + b       # +, -, *, /
x = t1           # copy or integer literal
read a
print x
if x >= 10 goto big
goto done
big:
return x
done:
```

Identifiers follow `[A-Za-z_][A-Za-z0-9_]*`; integer literals may be negative. Comparisons support `==`, `!=`, `<`, `<=`, `>`, `>=`. Labels must be unique and every branch target must be defined. Parenthesized expressions and unary operations are intentionally outside this TAC grammar; use temporaries to represent expression order.

## Example

Input (`samples/sample1.tac`):

```text
t1 = a + b
x = t1
```

Representative output (register choices follow allocation state):

```text
LOAD R0, a
LOAD R1, b
ADD R2, R0, R1
MOV R0, R2
STORE R0, x
HALT
```

The generated program expects source variables to be in memory initially. `LOAD`/`STORE` represent memory traffic. The output includes `; spill` comments when a dirty register value is written to memory during allocation.

## Project map

- `src/code_generator.py` - parser, liveness/next-use analysis, register allocator, pseudo-assembly emitter, and CLI.
- `tests/test_codegen.py` - parsing, error handling, CLI, register-pressure, spill/reload, and execution-equivalence tests.
- `samples/` - three TAC examples.
- `LEARNING_GUIDE.md` - worked explanation of the algorithm.
- `VIVA_PREPARATION.md` - review questions and answers.
- `AI_PROMPT_HISTORY.md` - honest record of AI assistance and corrections.
- `23_Q23_Report.docx` and `23_Q23_Report.pdf` - report, with personal fields left for completion.

## Test record

The latest run is recorded in `evidence/test_results.txt`. Tests include empty and one-statement inputs, all four arithmetic operators, read/print/return, conditional and unconditional branches, parser failures, label validation, genuine pressure-induced spills and reloads, CLI behavior, and independent TAC-versus-assembly execution. Re-run after edits.

## Complexity and limitations

For `n` instructions and `v` distinct variables, the sparse index stores O(n) use/definition events across O(v) lists. Building it takes expected O(n) time and O(n + v) space. Each nearest-use query uses binary search, O(log n). With three fixed registers and a constant number of queries per instruction, generation is O(n log n) worst-case and O(n + v) space including emitted code. Definition events stop the search for an older value at a later use of the same variable.

This is a simple teaching allocator. Next-use follows textual TAC event order; control-flow boundaries flush register contents instead of computing CFG-wide liveness. The pseudo-assembly test interpreter uses Python integer floor division; a real target must choose its own semantics. The program does not perform instruction scheduling, common-subexpression elimination, or target-specific register constraints. The allocator and tests were AI-assisted; study and adapt them honestly to the course's authorship requirements before submission.

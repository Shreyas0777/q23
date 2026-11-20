# Learning Guide Three Register Code Generation

## 1. The problem in plain language

Three-address code breaks an expression into small steps. For example, `x = a + b * c` is commonly represented as:

```text
t1 = b * c
x = a + t1
```

A processor cannot necessarily keep every value in a register. This assignment limits the machine to three working registers, `R0`, `R1`, and `R2`. The generator decides which values to load, which register to reuse, and when a value must be saved to memory so it can be used later.

The output is assembly-like teaching notation, not machine code. `LOAD`, `STORE`, `ADD`, and related instructions describe the intended operations.

## 2. Terms to know

- **TAC (three-address code):** a sequence of simple statements, usually with at most one operator on a right-hand side.
- **Register:** a small, fast storage location inside the target machine.
- **Register descriptor:** the generator's record of which variable currently lives in each register.
- **Next use:** the nearest later instruction that reads a value before replacing it.
- **Live value:** a value that will be read again in the future.
- **Spill:** save a register value to memory so the register can be reused.
- **Reload:** bring a previously saved value back from memory.
- **Immediate:** a literal operand encoded directly in an instruction, such as `7`.

The generator tracks both `reg_to_var` (register descriptor) and `var_to_reg` (address descriptor). The `memory_valid` set records values that have a current memory copy, including input variables present before their first TAC definition. When a changed value leaves its register before memory has a correct copy, it is spilled.

## 3. Supported input language

The parser accepts assignments, arithmetic operations, input/output, labels, jumps, comparisons, and returns. For example:

```text
t1 = a + b
x = t1 * 4
if x != 0 goto nonzero
print x
nonzero:
return x
```

Each operation is on its own line. A `#` begins a comment. Branch labels are checked before generation. Unsupported syntax produces a line-numbered error rather than being silently translated.

## 4. Translation pipeline

1. **Parse:** turn each nonempty line into an `Instruction` with fields such as operation, destination, operands, and source line number.
2. **Validate labels:** reject duplicate definitions and missing jump targets.
3. **Index next-use events:** build sparse per-variable event lists. A read is ordered before a definition at the same instruction, so `x = x + 1` sees the old `x`; a later definition ends the search for that value.
4. **Load operands:** constants can be used as immediate values. Variables are reused from a register when possible; otherwise they are loaded from memory.
5. **Choose a destination:** `getReg()` selects an empty register first. Otherwise it prefers an explicitly discarded destination, then a dead value, then the unpinned value with farthest next use. A stale value is stored unless it is the old destination being redefined. Active source registers stay pinned.
6. **Emit the operation:** generate a three-operand instruction such as `ADD R2, R0, R1` and update both descriptors.
7. **Flush at control flow and exit:** save changed register values and clear descriptors at branches, labels, returns, and program end. This simple policy makes values visible in memory across basic-block boundaries.

### Why next-use helps

Suppose all three registers contain values and the allocator needs one more destination. Evicting a value used in the very next instruction would force an immediate reload. Evicting a value whose next use is much later usually avoids that immediate cost. If no later use exists, the allocator prefers that value as a victim. It still stores a dirty victim unless it is the old destination being redefined; general dead-store elimination is not implemented.

## 5. Worked example

Input:

```text
t1 = a + b
x = t1 * 2
print x
```

Assume memory initially holds `a = 3` and `b = 4`.

| Step | Action | Register state after action |
|---|---|---|
| 1 | Load `a` | `R0=a` |
| 2 | Load `b` | `R0=a`, `R1=b` |
| 3 | Add into `t1` | `R0=a`, `R1=b`, `R2=t1=7` |
| 4 | Multiply `t1` by immediate 2 into `x` | `R0=a`, `R1=b`, `R2=x=14` |
| 5 | Print `x` | output value 14 |
| 6 | Flush at end | `x` stored to memory |

The exact register choice can vary if the allocator policy changes. The observable result should remain 14.

## 6. Reading the code

Open `src/code_generator.py` and follow these functions:

- `parse_tac(text)` recognizes and validates the TAC grammar.
- `analyze_liveness(code)` creates sparse use/definition event lists for the variables.
- `CodeGenerator.getReg(index, pinned)` selects a register and spills a victim if required.
- `CodeGenerator.load(value, index, pinned)` reuses a variable, performs a regular memory load, or records a spill reload.
- `CodeGenerator.bind(reg, variable)` updates both descriptors after a definition.
- `CodeGenerator.flush()` makes changed values available in memory at a block boundary.
- `CodeGenerator.generate()` handles each instruction and emits pseudo-assembly.
- `main()` provides the file, standard-input, and output-file command-line interface.

Important invariant: a register being used as an operand for the current instruction is pinned. `getReg()` must not evict it, including while loading a second operand. This subtle case is covered by spill/reload semantic tests.

## 7. How to verify by hand

For each TAC statement, track a small table with three register columns, the names stored in memory, and the next use of each value. Whenever the generated output says `STORE`, update memory. Whenever it says `LOAD`, copy the memory value into that register. Evaluate the arithmetic and check the final `STORE` or `PRINT` against direct TAC evaluation.

The test suite includes a tiny interpreter for this pseudo-assembly and a separate TAC evaluator. Comparing them catches mistakes that merely checking for an `ADD` opcode would miss.

## 8. Test strategy

Tests cover empty input, a single immediate assignment, each arithmetic operator, copying and printing, all three registers, forced spills and reloads, sample TAC files, comments, branches, duplicate and missing labels, malformed syntax, and command-line behavior. The test interpreter validates actual values for representative programs. Run `python -m pytest -q` after changes.

## 9. Complexity in terms of program size

Let `n` be the TAC instruction count and `v` the number of distinct variables. There are at most two use events and one definition event per instruction. Building the per-variable index takes expected O(n) time and O(n + v) space. A next-use query uses binary search and takes O(log n). The allocator checks at most three registers at each instruction, so generation is O(n log n) worst-case and O(n + v) space including the index and emitted code. The implementation does not copy a complete variable-to-next-use dictionary for every instruction.

## 10. What this project does not solve

Next-use is computed from the textual stream rather than a full control-flow graph. Flushing at each control-flow boundary is a conservative simplification, but this is not a production compiler. The language uses integer literals and a small arithmetic/comparison subset; it has no arrays, pointers, function calls, floating point, or target-specific calling convention. The generated instruction set is illustrative.

## 11. Suggested viva preparation

Be able to explain why TAC uses temporaries, how a register descriptor differs from a memory/address descriptor, when a value must be spilled, how next use chooses a victim, what the three register invariant means, and why branches require values to be available beyond the current block. Trace at least one example by hand and describe the bug that occurs if a live operand is evicted while loading another operand.

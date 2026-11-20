# Q23 Viva Preparation Questions and Answers

Use these as study notes. Explain each answer in your own words and be ready to trace the supplied program rather than memorizing definitions.

1. **What is three-address code?**  An intermediate representation in which each instruction performs a small operation, commonly with one destination and at most two operands. Complex expressions are split using temporary variables.

2. **Why use an intermediate representation?**  It separates source-language parsing from target-machine code generation and makes transformations and translation easier to reason about.

3. **What is register allocation?**  The process of assigning program values to a limited set of machine registers while preserving program results.

4. **Which registers does this project use?**  Exactly `R0`, `R1`, and `R2`. `getReg()` only chooses from this fixed set.

5. **What is a register descriptor?**  A mapping from each register to the variable currently stored in it. Here it is `reg_to_var`.

6. **What is an address descriptor?**  A mapping from a variable/value to the locations that hold its current value, such as a register or memory. `var_to_reg` and `memory_valid` represent a simplified version.

7. **What is a next-use table?**  Information indicating where a variable will next be read. The allocator uses it to decide which value is least urgent to keep in a register.

8. **How is next use computed here?**  The analysis stores sparse use and definition events by variable. Binary search finds the next event; a definition event ends the search for an older value generation. It does not keep a full variable dictionary snapshot for every instruction.

9. **How does `getReg()` choose a register?**  It selects an empty, non-pinned register first. Otherwise it prefers a discardable old destination, then a dead value, then the unpinned value with farthest next use; dirty victims are stored unless explicitly discarded.

10. **What is spilling?**  Writing a register value to memory to free the register for another value. A later use may require a reload.

11. **When can a spill store be skipped?**  When memory already has the current value or the victim is the old destination being redefined. Dead values are preferred as victims, but this implementation still stores a dirty dead value unless it is explicitly discarded; general dead-store elimination is not implemented.

12. **What is reloading?**  In this project, the reload counter marks a memory load that restores a value previously written by a genuine spill. An ordinary first-time input-memory load is counted separately.

13. **What is an immediate operand?**  A literal encoded directly in an operation, such as the `2` in `MUL R0, R1, 2`. It does not consume a register.

14. **Why pin source registers?**  The current instruction still needs their values. Evicting a source while choosing or loading another operand would change the value used by the operation.

15. **What bug can happen when loading two operands?**  If loading the second operand is allowed to evict the first, an operation can use the wrong register contents. The generator passes active operand registers as pinned to `getReg()`.

16. **Why flush around control-flow instructions?**  A branch target may be reached from another path, so relying on the current register contents is unsafe. Writing values to memory and clearing descriptors gives each basic block a consistent starting point.

17. **What TAC is accepted?**  Copies, integer literals, `+ - * /`, `read`, `print`, comparisons and conditional jumps, unconditional `goto`, labels, and `return`. One statement per line; comments start with `#`.

18. **How does the parser handle an invalid line?**  It raises a `TACError` with the source line number instead of silently generating partial code.

19. **How are labels checked?**  A first pass records label locations and rejects duplicates; a second check ensures every branch target exists.

20. **What is the time complexity?**  For n instructions and v variables, sparse event construction is expected O(n) time and O(n+v) space. Each query is O(log n) by binary search, and at most three register candidates are checked per instruction, giving O(n log(n+1)) total generation time and O(n+v) space.

21. **Why is the output called assembly-like?**  Its opcodes and memory operations illustrate target instructions, but they are not encoded for a real processor or assembler.

22. **How is a first-time load different from a reload?**  Both emit `LOAD`, but only a load after a tracked spill is marked `; reload` and increments `reload_count`. The initial load increments `load_count`.

23. **How are the results checked?**  Tests compare a small interpreter of generated pseudo-assembly with direct evaluation of TAC for representative cases, and also check parsing, errors, spills, reloads, CLI behavior, and sample inputs.

24. **What does an empty input produce?**  A valid minimal program containing `HALT`.

25. **What are the main limitations?**  The language is intentionally small, next-use analysis is textual rather than full CFG dataflow, and the output has no real target calling convention or machine encoding.

26. **How would you extend it?**  Add a control-flow graph and block-level liveness, support more data types and instructions, define a real target ISA, and test the emitted code with that ISA's assembler or simulator.

27. **What lesson did the spill/reload tests reveal?**  Checking only that `STORE` and `LOAD` appear is insufficient. A register trace can still be wrong, so result values must be compared against an independent TAC calculation.

28. **What should be explained about AI assistance?**  State truthfully which parts were drafted or debugged with AI, identify concrete errors found, and describe the corrections and independent checks. Do not claim authorship or testing that did not occur.

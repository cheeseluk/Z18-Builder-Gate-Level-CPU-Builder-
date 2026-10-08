# Z18100 CPU — Architecture Specification

This document specifies the **Z18100**, the teaching CPU from CMU **18-100 Introduction to Electrical and Computer Engineering** (Lectures 06 "von Neumann Machine" and 07 "CPU–GPU Integrated"). It is written so that a simulator can be built or adapted to match the lecture exactly.

Sources: the full "Z18100 General Purpose Computer" schematic, plus the lecture's slide-by-slide walkthrough of the example program. Where the walkthrough and a static slide disagree, **the walkthrough wins**. Items not shown in the lecture are marked **[ASSUMED]**.

---

## 1. Summary

| Property | Value |
|---|---|
| Architecture | von Neumann: one memory holds both instructions and data |
| Data width | 8 bits, two's complement for arithmetic |
| Address width | 4 bits (16 memory locations) |
| Memory | 16 × 8-bit RAM |
| Instruction width | 8 bits = 4-bit **op code** + 4-bit **address/operand** |
| Opcodes | 10 (0–9), decoded by a 4-to-10 decoder; 10–15 are undefined |
| General registers | R0, R1, R2, R3 (8 bits each) |
| Other state | Instruction Register (IR), Program Counter (PC), MUX register, ALU input latches A and B, ALU Output latch, flags N / Z / O |
| Buses | 8-bit Data Bus, 4-bit Address Bus, Control Bus (memory WE, memory RE) |
| Instruction cycle | Fetch (load IR from memory), then Decode/Execute |

---

## 2. Components

### 2.1 Buses
- **Data Bus (8 bits, MSB…LSB).** Connects memory, the IR input, the R1–R3 inputs, and the R0 output.
- **Address Bus (4 bits).** Drives the memory address. It is also read by the MUX and DEMUX select lines and by the PC's load input. Exactly one source drives it at a time, chosen by a pair of clock-controlled transmission gates (TGs):
  - **PC → Address Bus** through a TG enabled by **CLK̄**, during fetch.
  - **IR[3:0] → Address Bus** through a TG enabled by **CLK**, during execute.
- **Control Bus.** Two lines: **WE** (memory write enable) and **RE** (memory read enable). Several sources assert them through tri-state drivers tied to logic 1, so each line is effectively the OR of its sources.

### 2.2 Memory (RAM, 16 × 8)
- 4-bit address from the Address Bus; 8-bit data to and from the Data Bus.
- **Read (RE = 1, WE = 0):** memory places `M[addr]` on the Data Bus.
- **Write (WE = 1, RE = 0):** memory stores the Data Bus value into `M[addr]`.

### 2.3 Registers R1, R2, R3
- **D input:** Data Bus. **WE:** decoder output 1, 2, 3 respectively.
- **Q output:** goes only to the MUX. These registers never drive the Data Bus.
- They are loaded from memory and used as ALU sources.

### 2.4 Register R0 (result / accumulator)
- **D input:** the ALU **Output** latch. It is *not* connected to the Data Bus input.
- **WE:** decoder output 0.
- **Q output:** drives the Data Bus when **RE** (decoder output 9) is active. This is the only path from a register to memory.
- R0 is **not** a MUX input, so a result must go through memory before it can feed the ALU again.

### 2.5 MUX (4 → 1, 8 bits wide, "MUX (w/registers)")
- **Select:** S1 = Address Bus bit 1, S0 = Address Bus bit 0, i.e. `operand[1:0]`.
- **E (enable):** decoder output 4.
- **Inputs:**

| S1 S0 | Input | Connected to |
|---|---|---|
| 00 | D0 | not connected |
| 01 | D1 | **R3** |
| 10 | D2 | **R2** |
| 11 | D3 | **R1** |

  Note the reversed order: select 1 → R3, select 3 → R1.
- The lecture labels it "MUX (w/registers)": when enabled, it **latches** the selected register's value and holds it. The DEMUX uses that held value on a later instruction.
- **[ASSUMED]** Selecting D0 latches 0.

### 2.6 DEMUX (1 → 2, 8 bits wide)
- **Input:** the MUX's latched value.
- **Select:** S0 = Address Bus bit 0 = `operand[0]`.
- **E (enable):** decoder output 5.
- **F0 → ALU latch A** (`operand[0] = 0`); **F1 → ALU latch B** (`operand[0] = 1`).

### 2.7 ALU
- Input latches **A** and **B** (8 bits each), loaded only through the DEMUX.
- Control inputs: **+** (decoder output 6) and **−** (decoder output 7).
- Result goes into the 8-bit **Output** latch, which feeds R0's D input.
- **Subtraction is `A − B`.** The walkthrough computes 7 − 5 = 2 with A = 7 and B = 5.
- Arithmetic is 8-bit two's complement and wraps on overflow.
- **Flags** (latched on each ADD/SUB and held until the next one):
  - **N (Negative):** bit 7 of the result is 1.
  - **Z (Zero):** the result is 0.
  - **O (Overflow):** signed overflow occurred.
  - Only **N** feeds any logic: through an inverter into the branch AND gate. Z and O are displayed but unused.

### 2.8 Instruction Register (IR, 8 bits)
- **D input:** Data Bus. **WE:** the fetch signal (§4).
- **IR[7:4] (op code)** goes to the 4-to-10 decoder.
- **IR[3:0] (address/operand)** goes to the Address Bus through the CLK-enabled TG.
- The lecture draws the op code in green and the operand in red.

### 2.9 Program Counter (PC)
- Holds the address of the instruction being fetched or executed. It is displayed as 8 bits (e.g. `0000 1001`), but only the low 4 bits are used.
- **D input:** the operand field from the Address Bus side of the IR TG, used as the jump target.
- **WE:** the output of an **AND gate** with inputs **decoder output 8** and **NOT N**.
- **Q output:** goes to the Address Bus through the CLK̄-enabled TG.
- **Clock + Counter:** the lecture labels the clock/counter circuit that advances the PC between instructions.
- A small trapezoid block labeled **"0"** sits between the PC and the Control Bus. During fetch its output is 1; it asserts memory **RE** through a tri-state driver and asserts **IR WE**. The lecture does not detail its internals. A simulator can treat it as "fetch phase active."

### 2.10 Decoder (4 → 10) and Control Signals

| Decoder output | Signals asserted during execute |
|---|---|
| 0 | R0 WE |
| 1 | R1 WE, memory RE |
| 2 | R2 WE, memory RE |
| 3 | R3 WE, memory RE |
| 4 | MUX E |
| 5 | DEMUX E |
| 6 | ALU **+** |
| 7 | ALU **−** |
| 8 | AND gate input: PC WE only if N = 0 |
| 9 | R0 RE, memory WE |

The full schematic also draws decoder output 0 to a memory-RE driver. The lecture's walkthrough of opcode 0 highlights only R0 WE. Either way, nothing latches the Data Bus during opcode 0, so the effect is the same.

---

## 3. Instruction Set

**Format:** `[7:4] op code | [3:0] address/operand`

| Op code | Binary | Assembly (lecture style) | Operation | Operand |
|---|---|---|---|---|
| 0 | `0000` | `Move R0, Output` | `R0 ← Output` | ignored |
| 1 | `0001` | `Load R1, Mx` | `R1 ← M[x]` | memory address |
| 2 | `0010` | `Load R2, Mx` | `R2 ← M[x]` | memory address |
| 3 | `0011` | `Load R3, Mx` | `R3 ← M[x]` | memory address |
| 4 | `0100` | `MUX s` | `MUXreg ← Reg(s)`, where s = `operand[1:0]`: 1 → R3, 2 → R2, 3 → R1, 0 → none | register select |
| 5 | `0101` | `DEMUX d` | `operand[0] = 0`: `A ← MUXreg`; `1`: `B ← MUXreg` | 0 = A, 1 = B |
| 6 | `0110` | `Add` | `Output ← A + B`; update N, Z, O | ignored |
| 7 | `0111` | `Sub` | `Output ← A − B`; update N, Z, O | ignored |
| 8 | `1000` | `Jump-if-not-negative x` | if `N = 0`: `PC ← x` | jump target |
| 9 | `1001` | `Store Mx, R0` | `M[x] ← R0` | memory address |
| 10–15 | `1010`–`1111` | — | undefined (the decoder has no outputs for them) | — |

Moving one register into the ALU takes two instructions: `MUX` then `DEMUX`. A full `R0 ← Rx − Ry` therefore takes 6 instructions: MUX, DEMUX (→B), MUX, DEMUX (→A), Sub, Move R0.

**Ignore two lecture slides when implementing:**
- The "Write a Program to Do It" slide (`Load RA, X → 01011111`, `Add RC, RA, RB → 10000001`, …) is a *generic* illustration of compiler and assembler output. It is **not** Z18100 encoding.
- The slide captioned "Load R2, M13" shows machine code `0110 1101`. The IR on the surrounding walkthrough slides shows `0010 1101`, which is correct.

---

## 4. Instruction Cycle and Timing

Each instruction has a fetch phase and a decode/execute phase. The two address TGs use opposite clock phases, so the PC and the IR operand never drive the Address Bus at the same time.

**Fetch (CLK̄ active):**
1. `Address Bus ← PC`.
2. The fetch logic (the "0" block) asserts memory RE and IR WE: `IR ← M[PC]`.
3. The decoder outputs are not acting yet. **[ASSUMED]** The decoder is gated to the execute phase.

**Decode / Execute (CLK active):**
1. `Address Bus ← IR[3:0]`.
2. The decoder activates the signals for `IR[7:4]` (§2.10), and the operation in §3 takes effect.

**PC update between instructions:**
- Normally `PC ← PC + 1`, via the Clock + Counter.
- If opcode 8 executes with N = 0, then `PC ← operand`, and the next fetch reads `M[operand]`. The walkthrough shows this: after `1000 0001` at PC = 9, the PC display becomes `0000 0001`, and the next instruction fetched is `M[1]`.
- Initial PC = 0.

**Halting:** the lecture has no halt instruction; the example simply ends after address 10. **[ASSUMED]** The simulator should stop when it fetches an undefined opcode (10–15), an uninitialized word (`xxxxxxxx`), or when the PC runs past 15.

---

## 5. Reference Program (from the lecture)

**Algorithm (lecture flowchart):**
```
a = 7, b = 5
loop:  a = a − b
       if a ≥ 0: goto loop
store a
```

**Initial memory.** These are the instruction words as they appear in the IR during the walkthrough. The memory tables on some static slides contain typos: address 3 is shown as `01010000`, and one slide swaps addresses 3 and 5. The walkthrough IR values below are the ones that produce the lecture's results.

| Addr | Data | Op / operand | Assembly |
|---|---|---|---|
| 0 | `0010 1101` | 2 / 13 | `Load R2, M13` → R2 = b = 5 |
| 1 | `0011 1110` | 3 / 14 | `Load R3, M14` → R3 = a |
| 2 | `0100 0010` | 4 / 2 | `MUX 2` (R2) |
| 3 | `0101 0001` | 5 / 1 | `DEMUX 1` → B = b |
| 4 | `0100 0001` | 4 / 1 | `MUX 1` (R3) |
| 5 | `0101 0000` | 5 / 0 | `DEMUX 0` → A = a |
| 6 | `0111 1111` | 7 / 15 | `Sub` → Output = a − b |
| 7 | `0000 1111` | 0 / 15 | `Move R0, Output` |
| 8 | `1001 1110` | 9 / 14 | `Store M14, R0` (a is stored back to M14) |
| 9 | `1000 0001` | 8 / 1 | `Jump-if-not-negative 1` |
| 10 | `1001 1111` | 9 / 15 | `Store M15, R0` (final result) |
| 11 | `xxxxxxxx` | — | uninitialized |
| 12 | `xxxxxxxx` | — | uninitialized |
| 13 | `0000 0101` | data | b = 5 |
| 14 | `0000 0111` | data | a = 7 |
| 15 | `0000 0000` | data | result slot. The "Load Instructions and Data" slide shows `00000000`; later slides show `00000010`. It is overwritten before it is read, so either works. |

### Expected trace (use as the acceptance test)

**Pass 1:**

| PC | Instruction | Effect |
|---|---|---|
| 0 | `Load R2, M13` | R2 = `00000101` (5) |
| 1 | `Load R3, M14` | R3 = `00000111` (7) |
| 2 | `MUX 2` | MUXreg = 5 |
| 3 | `DEMUX 1` | B = 5 |
| 4 | `MUX 1` | MUXreg = 7 |
| 5 | `DEMUX 0` | A = 7 |
| 6 | `Sub` | Output = `00000010` (2); N = 0 |
| 7 | `Move R0, Output` | R0 = 2 |
| 8 | `Store M14, R0` | M14 = `00000010` |
| 9 | `Jump-if-not-negative 1` | N = 0 → PC ← 1 |

**Pass 2:**

| PC | Instruction | Effect |
|---|---|---|
| 1 | `Load R3, M14` | R3 = 2 |
| 2–5 | MUX/DEMUX | B = 5, A = 2 |
| 6 | `Sub` | Output = `11111101` (−3); N = 1 |
| 7 | `Move R0, Output` | R0 = −3 |
| 8 | `Store M14, R0` | M14 = `11111101` |
| 9 | `Jump-if-not-negative 1` | N = 1 → not taken, PC ← 10 |
| 10 | `Store M15, R0` | M15 = `11111101` |
| 11 | `xxxxxxxx` | halt |

**Final state:** R0 = `11111101` (−3), R1 = 0 (never loaded), R2 = 5, R3 = 2, A = 2, B = 5, Output = −3, N = 1, M14 = M15 = `11111101`.

---

## 6. What the Simulator Should Display

The lecture teaches by animating the schematic, so the simulator should expose the same state:
- R0–R3, the MUX register, A, B, Output, flags N / Z / O.
- IR (op code in green, operand in red, as in the lecture), PC (as `0000 xxxx`).
- All 16 memory words, with an arrow marking the address currently on the Address Bus.
- The current Data Bus and Address Bus values.
- Which control signals are active: the decoder output, memory RE/WE, each register's WE/RE, MUX E, DEMUX E, ALU + / −, the AND gate output, and which TG (PC or IR) is driving the Address Bus.
- Single-step by instruction, and ideally by phase (fetch vs. execute).

---

## 7. Out of Scope

The lectures also cover a 4-stage pipeline, caches, and GPU/CPU integration as supplementary material. **None of these are part of the Z18100.** It is a single-cycle-per-phase, non-pipelined, cacheless machine.

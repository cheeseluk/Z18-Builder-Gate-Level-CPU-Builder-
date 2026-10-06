# z18_cpu.py
# The Z18100 "golden model", simulated down to single bits.
#
# The Z18100 (CMU 18-100, lectures 06-07) is an 8-bit von Neumann machine:
# 16 words of memory hold both the program and its data. Every instruction
# takes two clock phases:
#   fetch   (CLK = 0): the PC drives the address bus and IR <- M[PC]
#   execute (CLK = 1): IR[3:0] drives the address bus, the decoder turns
#                      IR[7:4] into control signals, and the latches they
#                      enable load at the end of the phase
#
# computeSignals(cpu) works out the value on every wire and control line
# for the phase that is about to run, WITHOUT changing cpu (like
# traceInstruction in ../datapath.py). stepPhase(cpu) computes those signals
# and then commits them, the way the clock edge would.
#
# The logic is built from gates (notGate, andGate, ...) and full adders, so
# every intermediate bit can be shown to the learner. No graphics here.

# The sizes and the op codes come from the instruction table in z18_isa.py.
# The operand field drives the address bus, so here it is ADDR_MASK.
from z18_isa import (MEM_WORDS, WORD_BITS, OPCODE_COUNT, WORD_MASK,
                     OPERAND_MASK as ADDR_MASK, INSTRUCTIONS, MUX_INPUTS)

ADDR_BITS = 4

# Short names for each opcode (the assembler has the full syntax)
OPCODE_NAMES = [instruction['name'] for instruction in INSTRUCTIONS]

# What the MUX's four data inputs are wired to (note the reversed order)
MUX_INPUT_REGS = [None] + [name.lower() for name in MUX_INPUTS[1:]]

# Every latch a phase can load, in display order
LATCH_NAMES = ['ir', 'pc', 'r0', 'r1', 'r2', 'r3', 'muxReg', 'a', 'b', 'out',
               'n', 'z', 'o']

# The two phases of one instruction
PHASES = ['fetch', 'execute']


######################################################################
# Bits
######################################################################

def getBit(value, i):
    # Bit i of value (bit 0 is the least significant)
    return (value >> i) & 1

def toBits(value, width):
    # [msb, ..., lsb], e.g. toBits(5, 4) == [0, 1, 0, 1]
    bits = []
    for i in range(width - 1, -1, -1):
        bits.append(getBit(value, i))
    return bits

def fromBits(bits):
    # The inverse of toBits
    value = 0
    for bit in bits:
        value = value * 2 + bit
    return value

def toSigned(value):
    # Reads an 8-bit pattern as two's complement: 0b11111101 -> -3
    if value == None:
        return None
    value = value & WORD_MASK
    if value >= 0x80:
        return value - 0x100
    return value

def formatBits(value, width=WORD_BITS, spaced=True):
    # 45 -> '0010 1101'. An unknown value (None) shows as x's, as in the
    # lecture's memory table.
    if value == None:
        text = 'x' * width
    else:
        text = ''
        for bit in toBits(value, width):
            text += str(bit)
    if spaced and width == 8:
        return text[:4] + ' ' + text[4:]
    return text


######################################################################
# Gates (every signal below is built from these)
######################################################################

def notGate(a):
    return 1 - a

def andGate(*inputs):
    for bit in inputs:
        if bit == 0:
            return 0
    return 1

def orGate(*inputs):
    for bit in inputs:
        if bit == 1:
            return 1
    return 0

def xorGate(a, b):
    return orGate(andGate(a, notGate(b)), andGate(notGate(a), b))

def transmissionGate(enable, value):
    # A switch: passes value when enabled, otherwise the output floats
    # (None = high impedance, nothing driving it)
    if enable == 1:
        return value
    return None


######################################################################
# Building blocks
######################################################################

def fullAdder(a, b, carryIn):
    # One column of binary addition. Returns (sum, carryOut).
    halfSum = xorGate(a, b)
    total = xorGate(halfSum, carryIn)
    carryOut = orGate(andGate(a, b), andGate(carryIn, halfSum))
    return total, carryOut

def runAdder(a, b, subtract):
    # The ALU: 8 full adders in a chain (ripple carry). To subtract, every
    # bit of B goes through an XOR with subtract (inverting it) and the
    # first carry-in is 1, so the adder computes A + ~B + 1 = A - B.
    columns = []
    carry = subtract
    result = 0
    for i in range(WORD_BITS):
        aBit = getBit(a, i)
        bBit = xorGate(getBit(b, i), subtract)
        total, carryOut = fullAdder(aBit, bBit, carry)
        columns.append({'a': aBit, 'b': bBit, 'carryIn': carry,
                        'sum': total, 'carryOut': carryOut})
        result += total << i
        carry = carryOut
    zeroInputs = []
    for column in columns:
        zeroInputs.append(notGate(column['sum']))
    return {'a': a, 'b': b, 'subtract': subtract, 'columns': columns,
            'result': result, 'carryOut': carry,
            'n': getBit(result, WORD_BITS - 1),
            'z': andGate(*zeroInputs),
            # signed overflow: the carry into the sign bit differs from the
            # carry out of it
            'o': xorGate(columns[-1]['carryIn'], columns[-1]['carryOut'])}

def decoderOutput(k, opcodeBits, enable):
    # Output k of the 4-to-10 decoder: an AND gate that is 1 only when the
    # op code bits spell k. Where k has a 0 bit, the gate gets NOT of it.
    # It asks: Does k == opcodeBits and is enable 1.
    inputs = [enable]
    pattern = toBits(k, 4)
    for j in range(4):
        if pattern[j] == 1:
            inputs.append(opcodeBits[j])
        else:
            inputs.append(notGate(opcodeBits[j]))
    return andGate(*inputs)

def runDecoder(opcode, enable):
    # Returns a list of 10 bits. An unknown op code (IR holds xxxxxxxx) or
    # an undefined one (10-15) turns every output off.
    if opcode == None:
        return [0] * OPCODE_COUNT
    opcodeBits = toBits(opcode, 4)
    outputs = []
    for k in range(OPCODE_COUNT):
        outputs.append(decoderOutput(k, opcodeBits, enable))
    return outputs

def runMux(select, inputs):
    # 4-to-1 multiplexer, one bit column at a time:
    # out[i] = OR over k of (select == k AND input_k[i])
    s1 = getBit(select, 1)
    s0 = getBit(select, 0)
    selectLines = [andGate(notGate(s1), notGate(s0)),
                   andGate(notGate(s1), s0),
                   andGate(s1, notGate(s0)),
                   andGate(s1, s0)]
    result = 0
    for i in range(WORD_BITS):
        terms = []
        for k in range(4):
            terms.append(andGate(selectLines[k], getBit(inputs[k], i)))
        result += orGate(*terms) << i
    return result


######################################################################
# The machine
######################################################################

def makeCPU(memory):
    # memory: 16 entries, each 0-255 or None (uninitialized, 'xxxxxxxx')
    mem = list(memory) + [None] * (MEM_WORDS - len(memory))
    return {'mem': mem[:MEM_WORDS],
            'pc': 0, 'ir': None,
            'r0': 0, 'r1': 0, 'r2': 0, 'r3': 0,
            'muxReg': 0, 'a': 0, 'b': 0, 'out': 0,
            'n': 0, 'z': 0, 'o': 0,
            'phase': 'fetch',          # the phase that runs next
            'halted': False, 'status': 'Ready',
            'halfCycles': 0,           # phases run so far
            'instrCount': 0,           # instructions finished so far
            'changed': [],             # latches the last phase loaded
            'changedMem': None,        # address the last phase wrote
            'lastSignals': None}       # signals of the last phase run

def readMemory(cpu, address):
    # A floating address bus (None) reads nothing we can know
    if address == None:
        return None
    return cpu['mem'][address & ADDR_MASK]


######################################################################
# Signals for one phase (reads cpu, never changes it)
######################################################################

def computeClock(cpu, sig):
    phase = cpu['phase']
    sig['phase'] = phase
    sig['clk'] = 1 if phase == 'execute' else 0
    sig['clkBar'] = notGate(sig['clk'])
    # The "0" block under the PC: its output is 1 for the whole fetch phase
    sig['fetch'] = sig['clkBar']

def computeAddressBus(cpu, sig):
    ir = cpu['ir']
    sig['ir'] = ir
    sig['opcode'] = None
    sig['operand'] = None
    if ir != None:
        sig['opcode'] = ir >> 4
        sig['operand'] = ir & ADDR_MASK
    sig['pc'] = cpu['pc']
    # Two transmission gates on opposite clock phases: exactly one drives
    sig['tgPc'] = sig['clkBar']
    sig['tgIr'] = sig['clk']
    fromPc = transmissionGate(sig['tgPc'], cpu['pc'] & ADDR_MASK)
    fromIr = transmissionGate(sig['tgIr'], sig['operand'])
    sig['addrBus'] = fromPc
    if fromPc == None:
        sig['addrBus'] = fromIr

def computeControl(cpu, sig):
    # The decoder only acts during execute [ASSUMED in the spec]
    d = runDecoder(sig['opcode'], sig['clk'])
    sig['decoder'] = d
    sig['decoderOn'] = None            # which output is on, if any
    for k in range(OPCODE_COUNT):
        if d[k] == 1:
            sig['decoderOn'] = k
    # The control bus: each line is an OR of tri-state drivers tied to 1
    sig['memRE'] = orGate(sig['fetch'], d[1], d[2], d[3])
    sig['memWE'] = d[9]
    sig['irWE'] = sig['fetch']
    sig['r0WE'] = d[0]
    sig['r1WE'] = d[1]
    sig['r2WE'] = d[2]
    sig['r3WE'] = d[3]
    sig['muxE'] = d[4]
    sig['demuxE'] = d[5]
    sig['aluAdd'] = d[6]
    sig['aluSub'] = d[7]
    sig['r0RE'] = d[9]
    # Jump-if-not-negative: PC WE = d8 AND NOT N
    sig['nFlag'] = cpu['n']
    sig['notN'] = notGate(cpu['n'])
    sig['pcWE'] = andGate(d[8], sig['notN'])

def computeDataBus(cpu, sig):
    # At most one device drives the data bus at a time
    address = sig['addrBus']
    sig['memData'] = readMemory(cpu, address)     # the word at the address
    sig['dataBusDriver'] = None
    sig['dataBus'] = None
    if sig['memRE'] == 1:
        sig['dataBusDriver'] = 'mem'
        sig['dataBus'] = sig['memData']           # None if uninitialized
    elif sig['r0RE'] == 1:
        sig['dataBusDriver'] = 'r0'
        sig['dataBus'] = cpu['r0']

def computeDatapath(cpu, sig):
    address = sig['addrBus']
    if address == None:
        address = 0                    # only when halting on xxxxxxxx
    # MUX: select lines are address bus bits 1 and 0. D0 is not connected
    # (reads as 0) [ASSUMED]; D1 = R3, D2 = R2, D3 = R1.
    sig['muxSel'] = address & 3
    muxInputs = [0]
    for name in MUX_INPUT_REGS[1:]:
        muxInputs.append(cpu[name])
    sig['muxInputs'] = muxInputs
    sig['muxOut'] = runMux(sig['muxSel'], muxInputs)
    # DEMUX: select is address bus bit 0; F0 -> A, F1 -> B
    sig['demuxSel'] = address & 1
    sig['demuxIn'] = cpu['muxReg']
    sig['demuxF0'] = transmissionGate(
        andGate(sig['demuxE'], notGate(sig['demuxSel'])), cpu['muxReg'])
    sig['demuxF1'] = transmissionGate(
        andGate(sig['demuxE'], sig['demuxSel']), cpu['muxReg'])
    # ALU: the adder always computes; + or - decides the mode and loads
    # the Output latch
    sig['alu'] = runAdder(cpu['a'], cpu['b'], sig['aluSub'])
    sig['aluLoad'] = orGate(sig['aluAdd'], sig['aluSub'])
    sig['aluOut'] = cpu['out']         # Output latch -> R0's D input
    # PC: the Clock + Counter adds 1; a taken jump loads the address bus
    sig['pcPlus1'] = cpu['pc'] + 1
    sig['nextPc'] = cpu['pc']
    if sig['phase'] == 'execute':
        sig['nextPc'] = sig['pcPlus1']
        if sig['pcWE'] == 1:
            sig['nextPc'] = address

def computeWireValues(cpu, sig):
    # Values on wires that simply carry a latch's output (so every wire
    # in the schematic can look its value up in sig)
    sig['pcOut'] = cpu['pc'] & ADDR_MASK
    for name in ['r0', 'r1', 'r2', 'r3']:
        sig[name + 'Out'] = cpu[name]
    sig['aOut'] = cpu['a']
    sig['bOut'] = cpu['b']
    sig['aluResult'] = sig['alu']['result']
    alu = sig['alu']
    sig['aluFlags'] = fromBits([alu['n'], alu['z'], alu['o']])
    for k in range(OPCODE_COUNT):
        sig['d' + str(k)] = sig['decoder'][k]

def computeWrites(cpu, sig):
    # What each enabled latch will hold after this phase's clock edge
    writes = dict()
    if sig['phase'] == 'fetch':
        writes['ir'] = sig['dataBus']
        sig['writes'] = writes
        sig['memWrite'] = None
        return
    for reg in ['r1', 'r2', 'r3']:
        if sig[reg + 'WE'] == 1:
            writes[reg] = sig['dataBus']
    if sig['r0WE'] == 1:
        writes['r0'] = cpu['out']
    if sig['muxE'] == 1:
        writes['muxReg'] = sig['muxOut']
    if sig['demuxF0'] != None:
        writes['a'] = sig['demuxF0']
    if sig['demuxF1'] != None:
        writes['b'] = sig['demuxF1']
    if sig['aluLoad'] == 1:
        alu = sig['alu']
        writes['out'] = alu['result']
        writes['n'] = alu['n']
        writes['z'] = alu['z']
        writes['o'] = alu['o']
    writes['pc'] = sig['nextPc']
    sig['memWrite'] = None
    if sig['memWE'] == 1:
        sig['memWrite'] = (sig['addrBus'], sig['dataBus'])
    sig['writes'] = writes

def findStop(cpu, sig):
    # Sets sig['halt'] or sig['error'] if this phase stops the machine
    sig['halt'] = None
    sig['error'] = None
    if sig['phase'] == 'fetch':
        if cpu['pc'] >= MEM_WORDS:
            sig['halt'] = f"PC ran past address {MEM_WORDS - 1}"
        return
    if sig['ir'] == None:
        sig['halt'] = (f"IR holds xxxxxxxx (M[{cpu['pc']}] was never set), "
                       'so no decoder output turns on')
    elif sig['opcode'] >= OPCODE_COUNT:
        sig['halt'] = (f"op code {formatBits(sig['opcode'], 4)} is "
                       'undefined: the decoder has no output for it')
    else:
        for name in sig['writes']:
            if sig['writes'][name] == None:
                sig['error'] = (f'{name.upper()} would load xxxxxxxx '
                                f"(M[{sig['addrBus']}] was never set)")

def computeSignals(cpu):
    # Every wire and control line for the phase about to run.
    # Does not change cpu. Returns None once the cpu has halted.
    if cpu['halted']:
        return None
    sig = dict()
    computeClock(cpu, sig)
    computeAddressBus(cpu, sig)
    computeControl(cpu, sig)
    computeDataBus(cpu, sig)
    computeDatapath(cpu, sig)
    computeWireValues(cpu, sig)
    computeWrites(cpu, sig)
    findStop(cpu, sig)
    return sig


######################################################################
# Running (the clock edge)
######################################################################

def halt(cpu, status):
    cpu['halted'] = True
    cpu['status'] = status

def commitSignals(cpu, sig):
    # The clock edge: every enabled latch loads its new value
    for name in sig['writes']:
        if cpu[name] != sig['writes'][name]:
            cpu['changed'].append(name)
        cpu[name] = sig['writes'][name]
    if sig['memWrite'] != None:
        address, value = sig['memWrite']
        cpu['mem'][address] = value
        cpu['changedMem'] = address
    if sig['phase'] == 'fetch':
        cpu['phase'] = 'execute'
    else:
        cpu['phase'] = 'fetch'
        cpu['instrCount'] += 1

def stepPhase(cpu):
    # Runs one clock phase (fetch or execute). Returns its signals, or
    # None if the cpu had already halted.
    sig = computeSignals(cpu)
    if sig == None:
        return None
    cpu['changed'] = []
    cpu['changedMem'] = None
    cpu['lastSignals'] = sig
    cpu['halfCycles'] += 1
    if sig['halt'] != None:
        halt(cpu, 'Halted: ' + sig['halt'])
    elif sig['error'] != None:
        halt(cpu, 'Error: ' + sig['error'])
    else:
        commitSignals(cpu, sig)
    return sig

def stepInstruction(cpu):
    # Runs phases until the current instruction is done (or the cpu halts)
    stepPhase(cpu)
    while cpu['phase'] == 'execute' and not cpu['halted']:
        stepPhase(cpu)

def runToEnd(cpu, maxPhases=10000):
    count = 0
    while not cpu['halted'] and count < maxPhases:
        stepPhase(cpu)
        count += 1
    if not cpu['halted']:
        halt(cpu, 'Error: phase limit reached (infinite loop?)')
    return cpu


######################################################################
# Saving and restoring (for Back and the timeline)
######################################################################

def saveState(cpu):
    # Everything is a number, None, or a list of those, so a shallow copy
    # plus copies of the two lists is a full snapshot. lastSignals is never
    # changed after it is made, so it can be shared.
    state = dict(cpu)
    state['mem'] = list(cpu['mem'])
    state['changed'] = list(cpu['changed'])
    return state

def loadState(cpu, state):
    for key in state:
        cpu[key] = state[key]
    cpu['mem'] = list(state['mem'])
    cpu['changed'] = list(state['changed'])

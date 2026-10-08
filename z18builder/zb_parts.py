# zb_parts.py
# The primitive parts of the Z18 kit: each one's ports, parameters and
# behaviour. No graphics here.
#
# A definition is a dict:
#   name, label, level (0 gates, 1 blocks, 2 units), shape (how the view
#   draws it), params (defaults), help (one or two sentences)
#   layout(params) -> (width, height, ports), each port a dict
#       {name, dir ('in'/'out'), width, dx, dy} (dx, dy from the top-left)
#   evaluate(params, inputs, state) -> {outPort: value}
# and for parts that hold state (registers, RAM, the clock):
#   initState(params), commit(params, inputs, state) -> new state,
#   problem(params, inputs, state) -> a message if the commit would store
#   an unknown value, else None
#
# The Z18100 behaviour comes straight from ../z18100/z18_cpu.py (runAdder,
# runMux, fullAdder, decoderOutput, ...), so a part computes exactly what
# the lecture machine computes.

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(HERE)
for folder in [PROJECT_DIR, os.path.join(PROJECT_DIR, 'z18100')]:
    if folder not in sys.path:
        sys.path.append(folder)

from z18_cpu import (fullAdder, runAdder, runMux, decoderOutput, toBits,
                     xorGate, andGate)
from zb_values import Z, X, mask, isKnown

GRID = 10
RAM_WORDS = 16
MAX_WIDTH = 8
MAX_INPUTS = 8


def makePort(name, direction, width, dx, dy):
    return {'name': name, 'dir': direction, 'width': width, 'dx': dx,
            'dy': dy}

def makeDefinition(name, label, level, shape, params, layout, evaluate,
                   help, initState=None, commit=None, problem=None,
                   tristate=()):
    return {'name': name, 'label': label, 'level': level, 'kind': 'primitive',
            'shape': shape, 'params': params, 'layout': layout,
            'evaluate': evaluate, 'help': help, 'initState': initState,
            'commit': commit, 'problem': problem,
            'tristate': set(tristate)}


######################################################################
# Logic with unknowns
######################################################################

def notValue(value, width):
    if not isKnown(value):
        return X
    return ~value & mask(width)

def andValues(values, width):
    # A known all-0 input decides the result even if others are unknown
    for value in values:
        if value == 0:
            return 0
    result = mask(width)
    for value in values:
        if not isKnown(value):
            return X
        result &= value
    return result

def orValues(values, width):
    # A known all-1 input decides the result even if others are unknown
    for value in values:
        if value == mask(width):
            return mask(width)
    result = 0
    for value in values:
        if not isKnown(value):
            return X
        result |= value
    return result

def xorValues(values, width):
    result = 0
    for value in values:
        if not isKnown(value):
            return X
        result ^= value
    return result

def passValue(value):
    # What a wire into a part delivers: floating (Z) reads as unknown
    if value == Z:
        return X
    return value

def enabled(value):
    # 1 -> True, 0 -> False, anything else -> None (unknown)
    if value == 1:
        return True
    if value == 0:
        return False
    return None


######################################################################
# Layout helpers
######################################################################

def gateRows(count):
    # y offsets for count inputs and the height, so the output (at half the
    # height) lands on the grid: an even count skips the middle row
    rows = []
    if count % 2 == 1:
        for i in range(count):
            rows.append(GRID * (i + 1))
        return rows, GRID * (count + 1)
    middle = count // 2 + 1
    position = 1
    while len(rows) < count:
        if position != middle:
            rows.append(GRID * position)
        position += 1
    return rows, GRID * (count + 2)

def registerWidth(bits):
    # Enough room for one cell per bit
    if bits > 4:
        return 80
    if bits > 1:
        return 60
    return 40

def rangeWidth(pair):
    high, low = pair
    return high - low + 1


######################################################################
# Level 0: gates and wiring
######################################################################

def layoutOneInOneOut(params):
    width = params['width']
    return 40, 20, [makePort('in', 'in', width, 0, 10),
                    makePort('out', 'out', width, 40, 10)]

def evalNot(params, inputs, state):
    return {'out': notValue(passValue(inputs['in']), params['width'])}

def evalBuffer(params, inputs, state):
    return {'out': passValue(inputs['in'])}

def layoutGate(params):
    rows, height = gateRows(params['inputs'])
    ports = []
    for i in range(len(rows)):
        ports.append(makePort('in' + str(i), 'in', params['width'], 0,
                              rows[i]))
    ports.append(makePort('out', 'out', params['width'], 50, height // 2))
    return 50, height, ports

def gateInputs(params, inputs):
    values = []
    for i in range(params['inputs']):
        values.append(passValue(inputs['in' + str(i)]))
    return values

def evalAnd(params, inputs, state):
    return {'out': andValues(gateInputs(params, inputs), params['width'])}

def evalOr(params, inputs, state):
    return {'out': orValues(gateInputs(params, inputs), params['width'])}

def evalNand(params, inputs, state):
    width = params['width']
    return {'out': notValue(andValues(gateInputs(params, inputs), width),
                            width)}

def evalNor(params, inputs, state):
    width = params['width']
    return {'out': notValue(orValues(gateInputs(params, inputs), width),
                            width)}

def evalXor(params, inputs, state):
    return {'out': xorValues(gateInputs(params, inputs), params['width'])}

def layoutTG(params):
    width = params['width']
    return 40, 40, [makePort('in', 'in', width, 0, 20),
                    makePort('en', 'in', 1, 20, 0),
                    makePort('out', 'out', width, 40, 20)]

def evalTG(params, inputs, state):
    # A switch: passes its input when en = 1, otherwise the output floats
    on = enabled(inputs['en'])
    if on == None:
        return {'out': X}
    if on:
        return {'out': inputs['in']}
    return {'out': Z}

def layoutConst(params):
    return 30, 20, [makePort('out', 'out', params['width'], 30, 10)]

def evalConst(params, inputs, state):
    return {'out': params['value'] & mask(params['width'])}

def layoutSplit(params):
    ranges = params['ranges']
    height = GRID * (len(ranges) + 1)
    ports = [makePort('in', 'in', params['width'], 0, 10)]
    for i in range(len(ranges)):
        ports.append(makePort('out' + str(i), 'out', rangeWidth(ranges[i]),
                              30, GRID * (i + 1)))
    return 30, max(20, height), ports

def evalSplit(params, inputs, state):
    value = passValue(inputs['in'])
    outputs = dict()
    ranges = params['ranges']
    for i in range(len(ranges)):
        high, low = ranges[i]
        if isKnown(value):
            outputs['out' + str(i)] = (value >> low) & mask(high - low + 1)
        else:
            outputs['out' + str(i)] = X
    return outputs

def layoutMerge(params):
    widths = params['widths']
    ports = []
    for i in range(len(widths)):
        ports.append(makePort('in' + str(i), 'in', widths[i], 0,
                              GRID * (i + 1)))
    ports.append(makePort('out', 'out', sum(widths), 30, 10))
    return 30, max(20, GRID * (len(widths) + 1)), ports

def evalMerge(params, inputs, state):
    # in0 is the most significant piece
    result = 0
    widths = params['widths']
    for i in range(len(widths)):
        value = passValue(inputs['in' + str(i)])
        if not isKnown(value):
            return {'out': X}
        result = (result << widths[i]) | value
    return {'out': result}

def layoutExtend(params):
    return 40, 20, [makePort('in', 'in', params['from'], 0, 10),
                    makePort('out', 'out', params['to'], 40, 10)]

def evalExtend(params, inputs, state):
    # 'zero': pad with 0s on the left; 'repeat': copy a 1-bit input into
    # every bit (used to AND a whole word with one select line)
    value = passValue(inputs['in'])
    if not isKnown(value):
        return {'out': X}
    if params['mode'] == 'repeat':
        if value & 1:
            return {'out': mask(params['to'])}
        return {'out': 0}
    return {'out': value & mask(params['to'])}

def layoutPinIn(params):
    return 50, 20, [makePort('out', 'out', params['width'], 50, 10)]

def evalPinIn(params, inputs, state):
    return {'out': state}

def initPinIn(params):
    return 0

def layoutPinOut(params):
    return 50, 20, [makePort('in', 'in', params['width'], 0, 10)]

def evalNothing(params, inputs, state):
    return dict()

def layoutProbe(params):
    return 60, 20, [makePort('in', 'in', params['width'], 0, 10)]


######################################################################
# Level 1: blocks
######################################################################

def layoutHalfAdder(params):
    return 50, 40, [makePort('a', 'in', 1, 0, 10),
                    makePort('b', 'in', 1, 0, 30),
                    makePort('s', 'out', 1, 50, 10),
                    makePort('c', 'out', 1, 50, 30)]

def evalHalfAdder(params, inputs, state):
    a = passValue(inputs['a'])
    b = passValue(inputs['b'])
    if not (isKnown(a) and isKnown(b)):
        return {'s': X, 'c': X}
    return {'s': xorGate(a, b), 'c': andGate(a, b)}

def layoutFullAdder(params):
    return 40, 40, [makePort('a', 'in', 1, 0, 10),
                    makePort('b', 'in', 1, 0, 30),
                    makePort('cin', 'in', 1, 20, 0),
                    makePort('s', 'out', 1, 40, 20),
                    makePort('cout', 'out', 1, 20, 40)]

def evalFullAdder(params, inputs, state):
    values = []
    for name in ['a', 'b', 'cin']:
        values.append(passValue(inputs[name]))
    for value in values:
        if not isKnown(value):
            return {'s': X, 'cout': X}
    total, carryOut = fullAdder(values[0], values[1], values[2])
    return {'s': total, 'cout': carryOut}

def layoutMux2(params):
    width = params['width']
    return 30, 40, [makePort('in0', 'in', width, 0, 10),
                    makePort('in1', 'in', width, 0, 30),
                    makePort('sel', 'in', 1, 10, 40),
                    makePort('out', 'out', width, 30, 20)]

def layoutMux4(params):
    width = params['width']
    ports = []
    for k in range(4):
        ports.append(makePort('in' + str(k), 'in', width, 0, 10 + 20 * k))
    ports.append(makePort('sel', 'in', 2, 10, 80))
    ports.append(makePort('out', 'out', width, 30, 40))
    return 30, 80, ports

def evalMux(params, inputs, state, count):
    # runMux from the lecture model, one bit column at a time. Only the
    # selected input matters, so unknowns elsewhere are harmless.
    select = passValue(inputs['sel'])
    if not isKnown(select):
        return {'out': X}
    chosen = passValue(inputs['in' + str(select)])
    if not isKnown(chosen):
        return {'out': X}
    values = [0, 0, 0, 0]
    values[select] = chosen
    return {'out': runMux(select, values) & mask(params['width'])}

def evalMux2(params, inputs, state):
    return evalMux(params, inputs, state, 2)

def evalMux4(params, inputs, state):
    return evalMux(params, inputs, state, 4)

def layoutDemux(params):
    width = params['width']
    return 40, 80, [makePort('in', 'in', width, 0, 40),
                    makePort('sel', 'in', 1, 10, 80),
                    makePort('e', 'in', 1, 30, 80),
                    makePort('f0', 'out', width, 40, 10),
                    makePort('en0', 'out', 1, 40, 20),
                    makePort('f1', 'out', width, 40, 60),
                    makePort('en1', 'out', 1, 40, 70)]

def evalDemux(params, inputs, state):
    # f0 carries the input when e = 1 and sel = 0 (else it floats), and
    # en0 says so, so a register can use it as its WE. Same for f1.
    e = passValue(inputs['e'])
    sel = passValue(inputs['sel'])
    if not (isKnown(e) and isKnown(sel)):
        return {'f0': X, 'f1': X, 'en0': X, 'en1': X}
    en0 = andGate(e, 1 - sel)
    en1 = andGate(e, sel)
    outputs = {'en0': en0, 'en1': en1, 'f0': Z, 'f1': Z}
    if en0 == 1:
        outputs['f0'] = inputs['in']
    if en1 == 1:
        outputs['f1'] = inputs['in']
    return outputs

def layoutDecoder(params):
    count = params['outputs']
    height = GRID * (count + 1)
    ports = [makePort('in', 'in', params['bits'], 20, 0),
             makePort('en', 'in', 1, 0, (height // 20) * 10)]
    for k in range(count):
        ports.append(makePort('d' + str(k), 'out', 1, 40, GRID * (k + 1)))
    return 40, height, ports

def evalDecoder(params, inputs, state):
    # Output k is an AND gate that is 1 only when the input spells k
    count = params['outputs']
    bits = params['bits']
    en = passValue(inputs['en'])
    value = passValue(inputs['in'])
    outputs = dict()
    for k in range(count):
        if en == 0:
            outputs['d' + str(k)] = 0
        elif not (isKnown(en) and isKnown(value)):
            outputs['d' + str(k)] = X
        elif bits == 4:
            outputs['d' + str(k)] = decoderOutput(k, toBits(value, 4), en)
        else:
            outputs['d' + str(k)] = 1 if value == k else 0
    return outputs

def layoutRegister(params):
    bits = params['width']
    width = registerWidth(bits)
    if params['ports'] == 'top':
        # d from above and q below, like R0-R3 in the lecture
        return width, 40, [makePort('d', 'in', bits, width // 2, 0),
                           makePort('we', 'in', 1, 10, 40),
                           makePort('q', 'out', bits, width - 10, 40)]
    return width, 40, [makePort('d', 'in', bits, 0, 20),
                       makePort('we', 'in', 1, 10, 40),
                       makePort('q', 'out', bits, width, 20)]

def initRegister(params):
    if params['init'] == 'X':
        return X
    return 0

def evalRegister(params, inputs, state):
    return {'q': state}

def loadValue(state, we, d):
    # A latch at the clock edge: WE = 1 loads d, WE = 0 keeps the value
    on = enabled(we)
    if on == None:
        return X
    if on:
        return passValue(d)
    return state

def commitRegister(params, inputs, state):
    return loadValue(state, inputs['we'], inputs['d'])

def loadProblem(inputs):
    on = enabled(inputs['we'])
    if on == None:
        return 'its WE is unknown'
    if on and not isKnown(inputs['d']):
        return 'would load ' + 'x' * 8
    return None

def problemRegister(params, inputs, state):
    return loadProblem(inputs)

def layoutFlipFlops(params):
    # A register without WE (what is inside REG, behind its MUX)
    bits = params['width']
    width = registerWidth(bits)
    return width, 40, [makePort('d', 'in', bits, 0, 20),
                       makePort('q', 'out', bits, width, 20)]

def commitFlipFlops(params, inputs, state):
    # No WE: every clock edge loads d
    return passValue(inputs['d'])

def problemFlipFlops(params, inputs, state):
    # Loading x is only a problem when it loses a known value: inside a
    # REG, holding means loading q again, and a REG may hold x (the IR
    # does until its first fetch)
    if not isKnown(inputs['d']) and isKnown(state):
        return 'would load ' + 'x' * 8
    return None

def layoutCounter(params):
    bits = params['width']
    width = registerWidth(bits)
    return width, 40, [makePort('d', 'in', bits, 0, 20),
                       makePort('we', 'in', 1, 10, 40),
                       makePort('inc', 'in', 1, 30, 40),
                       makePort('q', 'out', bits, width, 20)]

def evalCounter(params, inputs, state):
    return {'q': state}

def countNext(state, inputs, width):
    # WE = 1 loads d; otherwise inc = 1 adds one
    load = enabled(inputs['we'])
    if load == None:
        return X
    if load:
        return passValue(inputs['d'])
    inc = enabled(inputs['inc'])
    if inc == None or not isKnown(state):
        return X
    if inc:
        return (state + 1) & mask(width)
    return state

def commitCounter(params, inputs, state):
    return countNext(state, inputs, params['width'])

def problemCounter(params, inputs, state):
    problem = loadProblem(inputs)
    if problem == None and enabled(inputs['we']) == False:
        if enabled(inputs['inc']) == None:
            return 'its inc is unknown'
    return problem


######################################################################
# Level 2: units
######################################################################

def layoutALU(params):
    return 60, 160, [makePort('a', 'in', 8, 0, 30),
                     makePort('b', 'in', 8, 0, 130),
                     makePort('plus', 'in', 1, 20, 160),
                     makePort('minus', 'in', 1, 40, 160),
                     makePort('n', 'out', 1, 60, 30),
                     makePort('z', 'out', 1, 60, 40),
                     makePort('o', 'out', 1, 60, 50),
                     makePort('out', 'out', 8, 60, 80),
                     makePort('go', 'out', 1, 60, 120)]

def evalALU(params, inputs, state):
    # runAdder from the lecture model: 8 full adders, B inverted and a
    # carry-in of 1 to subtract. go = plus OR minus loads Output and Flags.
    a = passValue(inputs['a'])
    b = passValue(inputs['b'])
    plus = passValue(inputs['plus'])
    minus = passValue(inputs['minus'])
    go = orValues([plus, minus], 1)
    if not (isKnown(a) and isKnown(b) and isKnown(minus)):
        return {'out': X, 'n': X, 'z': X, 'o': X, 'go': go}
    alu = runAdder(a, b, minus)
    return {'out': alu['result'], 'n': alu['n'], 'z': alu['z'],
            'o': alu['o'], 'go': go}

def layoutRAM(params):
    return 220, 330, [makePort('din', 'in', 8, 100, 0),
                      makePort('dout', 'out', 8, 140, 0),
                      makePort('re', 'in', 1, 40, 330),
                      makePort('we', 'in', 1, 80, 330),
                      makePort('addr', 'in', 4, 190, 330)]

def initRAM(params):
    return [X] * RAM_WORDS

def evalRAM(params, inputs, state):
    # RE = 1: the word at addr goes out (uninitialized words are X)
    on = enabled(inputs['re'])
    if on == None:
        return {'dout': X}
    if not on:
        return {'dout': Z}
    address = passValue(inputs['addr'])
    if not isKnown(address):
        return {'dout': X}
    return {'dout': state[address]}

def commitRAM(params, inputs, state):
    if enabled(inputs['we']) != True:
        return state
    address = passValue(inputs['addr'])
    if not isKnown(address):
        return state
    newState = list(state)
    newState[address] = passValue(inputs['din'])
    return newState

def problemRAM(params, inputs, state):
    on = enabled(inputs['we'])
    if on == None:
        return 'its WE is unknown'
    if on and not isKnown(inputs['addr']):
        return 'would write to an unknown address'
    if on and not isKnown(inputs['din']):
        return 'would store ' + 'x' * 8
    return None

def layoutIR(params):
    return 110, 40, [makePort('d', 'in', 8, 0, 20),
                     makePort('we', 'in', 1, 20, 40),
                     makePort('opcode', 'out', 4, 60, 40),
                     makePort('operand', 'out', 4, 90, 40),
                     makePort('q', 'out', 8, 110, 20)]

def evalIR(params, inputs, state):
    if not isKnown(state):
        return {'q': X, 'opcode': X, 'operand': X}
    return {'q': state, 'opcode': state >> 4, 'operand': state & 0xF}

def layoutPC(params):
    return 80, 40, [makePort('d', 'in', 4, 0, 20),
                    makePort('we', 'in', 1, 10, 40),
                    makePort('inc', 'in', 1, 30, 40),
                    makePort('q', 'out', 4, 80, 20)]

def evalPC(params, inputs, state):
    # The PC counts in 8 bits (as the lecture shows it); the address bus
    # only gets the low 4
    if not isKnown(state):
        return {'q': X}
    return {'q': state & 0xF}

def commitPC(params, inputs, state):
    return countNext(state, inputs, 8)

def layoutFlags(params):
    ports = []
    for i in range(3):
        name = 'nzo'[i]
        ports.append(makePort(name, 'in', 1, 0, 10 * (i + 1)))
        ports.append(makePort(name + 'q', 'out', 1, 80, 10 * (i + 1)))
    ports.append(makePort('we', 'in', 1, 40, 40))
    return 80, 40, ports

def initFlags(params):
    return {'n': 0, 'z': 0, 'o': 0}

def evalFlags(params, inputs, state):
    return {'nq': state['n'], 'zq': state['z'], 'oq': state['o']}

def commitFlags(params, inputs, state):
    newState = dict()
    for name in 'nzo':
        newState[name] = loadValue(state[name], inputs['we'], inputs[name])
    return newState

def problemFlags(params, inputs, state):
    on = enabled(inputs['we'])
    if on == None:
        return 'its WE is unknown'
    if on:
        for name in 'nzo':
            if not isKnown(inputs[name]):
                return f'{name.upper()} would load x'
    return None

def layoutClock(params):
    return 50, 40, [makePort('clk', 'out', 1, 50, 10),
                    makePort('clkBar', 'out', 1, 50, 30)]

def evalClock(params, inputs, state):
    # state is set by the simulator: 0 during fetch, 1 during execute
    return {'clk': state, 'clkBar': 1 - state}

def initClock(params):
    return 0


######################################################################
# The table of every primitive
######################################################################

def makePrimitives():
    width1 = {'width': 1}
    gate = {'inputs': 2, 'width': 1}
    defs = [
        # Level 0: gates and wiring
        makeDefinition('NOT', 'NOT', 0, 'not', dict(width1),
                       layoutOneInOneOut, evalNot,
                       'Inverts every bit: 0 becomes 1 and 1 becomes 0.'),
        makeDefinition('BUF', 'BUF', 0, 'buf', dict(width1),
                       layoutOneInOneOut, evalBuffer,
                       'Passes its input straight through. The lecture\'s '
                       '"0" fetch block is a buffer on CLK-bar.'),
        makeDefinition('AND', 'AND', 0, 'and', dict(gate), layoutGate,
                       evalAnd, '1 only when every input is 1. A 0 on '
                       'any input decides the output, even if others '
                       'are unknown.'),
        makeDefinition('OR', 'OR', 0, 'or', dict(gate), layoutGate, evalOr,
                       '1 when any input is 1.'),
        makeDefinition('NAND', 'NAND', 0, 'nand', dict(gate), layoutGate,
                       evalNand, 'NOT of AND.'),
        makeDefinition('NOR', 'NOR', 0, 'nor', dict(gate), layoutGate,
                       evalNor, 'NOT of OR: 1 only when every input is 0.'),
        makeDefinition('XOR', 'XOR', 0, 'xor', dict(gate), layoutGate,
                       evalXor, '1 when an odd number of inputs are 1.'),
        makeDefinition('TG', 'TG', 0, 'tg', {'width': 8}, layoutTG, evalTG,
                       'Transmission gate (tri-state buffer): passes its '
                       'input when en = 1, otherwise its output floats '
                       '(Z), so several of them can share one bus.',
                       tristate=['out']),
        makeDefinition('CONST', 'CONST', 0, 'const',
                       {'value': 0, 'width': 1}, layoutConst, evalConst,
                       'A fixed value (VCC = 1, GND = 0).'),
        makeDefinition('SPLIT', 'SPLIT', 0, 'split',
                       {'width': 8, 'ranges': [[7, 4], [3, 0]]},
                       layoutSplit, evalSplit,
                       'Takes bit ranges out of a wide wire, e.g. [7:4] '
                       'and [3:0] of the IR.'),
        makeDefinition('MERGE', 'MERGE', 0, 'merge', {'widths': [4, 4]},
                       layoutMerge, evalMerge,
                       'Joins narrow wires into a wide one (in0 is the '
                       'most significant piece).'),
        makeDefinition('EXTEND', 'EXT', 0, 'extend',
                       {'from': 4, 'to': 8, 'mode': 'zero'}, layoutExtend,
                       evalExtend, 'Widens a wire: "zero" pads with 0s; '
                       '"repeat" copies one bit into every bit.'),
        makeDefinition('PIN_IN', 'IN', 0, 'pinIn',
                       {'name': 'in', 'width': 1, 'side': 'auto'},
                       layoutPinIn, evalPinIn,
                       'An input of the part you are building. At the top '
                       'level it is a switch: click it in Run mode.',
                       initState=initPinIn),
        makeDefinition('PIN_OUT', 'OUT', 0, 'pinOut',
                       {'name': 'out', 'width': 1, 'side': 'auto'},
                       layoutPinOut,
                       evalNothing, 'An output of the part you are '
                       'building. At the top level it shows its value.'),
        makeDefinition('PROBE', 'PROBE', 0, 'probe', {'width': 8},
                       layoutProbe, evalNothing,
                       'Shows the value on a wire. Does nothing else.'),
        # Level 1: blocks
        makeDefinition('HALFADD', 'HA', 1, 'box', {}, layoutHalfAdder,
                       evalHalfAdder, 'Adds two bits: s = a XOR b, '
                       'c = a AND b.'),
        makeDefinition('FULLADD', 'FA', 1, 'box', {}, layoutFullAdder,
                       evalFullAdder, 'One column of binary addition: '
                       'a + b + carry in = s, plus a carry out.'),
        makeDefinition('MUX2', 'MUX', 1, 'mux', {'width': 8}, layoutMux2,
                       evalMux2, '2-to-1 multiplexer: out = in0 when '
                       'sel = 0, in1 when sel = 1.'),
        makeDefinition('MUX4', 'MUX', 1, 'mux', {'width': 8}, layoutMux4,
                       evalMux4, '4-to-1 multiplexer: sel (2 bits) picks '
                       'which input reaches out.'),
        makeDefinition('DEMUX', 'DEMUX', 1, 'demux', {'width': 8},
                       layoutDemux, evalDemux,
                       '1-to-2 demultiplexer: when e = 1, sel picks f0 or '
                       'f1 to carry the input (the other floats). en0 / '
                       'en1 say which, so they can be registers\' WE.',
                       tristate=['f0', 'f1']),
        makeDefinition('DECODER', 'DEC', 1, 'decoder',
                       {'bits': 4, 'outputs': 10}, layoutDecoder,
                       evalDecoder, 'Turns on output k when the input '
                       'is k (and en = 1). One AND gate per output.'),
        makeDefinition('REG', 'REG', 1, 'register',
                       {'width': 8, 'init': '0', 'ports': 'side'},
                       layoutRegister, evalRegister,
                       'A register of flip-flops: at the end of each clock '
                       'phase it loads d if WE = 1, and holds otherwise.',
                       initState=initRegister, commit=commitRegister,
                       problem=problemRegister),
        makeDefinition('DFF', 'D-FF', 1, 'register',
                       {'width': 8, 'init': '0'}, layoutFlipFlops,
                       evalRegister,
                       'D flip-flops, one per bit: at the end of every '
                       'clock phase they load d. Missions 6-8 build one '
                       'from gates.',
                       initState=initRegister, commit=commitFlipFlops,
                       problem=problemFlipFlops),
        makeDefinition('COUNTER', 'CNT', 1, 'register', {'width': 8},
                       layoutCounter, evalCounter,
                       'A register that can count: WE = 1 loads d, '
                       'otherwise inc = 1 adds 1.',
                       initState=lambda params: 0, commit=commitCounter,
                       problem=problemCounter),
        # Level 2: units
        makeDefinition('ALU', 'ALU', 2, 'alu', {}, layoutALU, evalALU,
                       'Adds (+) or subtracts (-) A and B with 8 full '
                       'adders, and sets the N Z O flags. go = + OR -.'),
        makeDefinition('RAM', 'RAM 16 x 8', 2, 'ram', {}, layoutRAM,
                       evalRAM, '16 words of 8 bits holding the program '
                       'and its data. RE = 1 puts M[addr] on dout; WE = 1 '
                       'stores din at the clock edge.',
                       initState=initRAM, commit=commitRAM,
                       problem=problemRAM, tristate=['dout']),
        makeDefinition('IR', 'IR', 2, 'register', {}, layoutIR, evalIR,
                       'Instruction register: an 8-bit register (starts as '
                       'xxxxxxxx) split into the op code [7:4] and the '
                       'operand [3:0].',
                       initState=lambda params: X, commit=commitRegister,
                       problem=problemRegister),
        makeDefinition('PC', 'PC (+1)', 2, 'register', {}, layoutPC, evalPC,
                       'Program counter: WE = 1 loads d (a jump), otherwise '
                       'inc = 1 adds 1. Its low 4 bits go out on q.',
                       initState=lambda params: 0, commit=commitPC,
                       problem=problemCounter),
        makeDefinition('FLAGS', 'Flags', 2, 'flags', {}, layoutFlags,
                       evalFlags, 'N Z O: three 1-bit registers loaded '
                       'together when WE = 1.',
                       initState=initFlags, commit=commitFlags,
                       problem=problemFlags),
        makeDefinition('CLOCK', 'CLK', 2, 'clock', {}, layoutClock,
                       evalClock, 'The clock: CLK = 0 in fetch, 1 in '
                       'execute. CLK-bar is its opposite.',
                       initState=initClock),
    ]
    table = dict()
    for definition in defs:
        table[definition['name']] = definition
    return table

PRIMITIVES = makePrimitives()

# The ports whose outputs may float, and the parts holding state
STATEFUL_TYPES = {'REG', 'DFF', 'COUNTER', 'RAM', 'IR', 'PC', 'FLAGS',
                  'CLOCK'}


def copyState(state):
    # States are ints, Z/X, a list (RAM) or a dict (Flags)
    if type(state) == list:
        return list(state)
    if type(state) == dict:
        return dict(state)
    return state

######################################################################
# SPLIT ranges and MERGE widths as text (bus notation)
######################################################################

def formatRanges(ranges):
    # [[7, 4], [3, 0]] -> '7:4 3:0'; a single bit is just its number
    pieces = []
    for high, low in ranges:
        pieces.append(str(high) if high == low else f'{high}:{low}')
    return ' '.join(pieces)

def bitsRanges(width):
    # One range per bit, high bit first
    return [[i, i] for i in range(width - 1, -1, -1)]

def nibbleRanges(width):
    # 4-bit pieces, lined up at bit 0: 8 -> 7:4 3:0, 6 -> 5:4 3:0
    ranges = []
    low = 0
    while low < width:
        ranges.insert(0, [min(width - 1, low + 3), low])
        low += 4
    return ranges

def parseJSONList(text):
    import json
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if type(value) == list else None

def parseRanges(text, width):
    # '7:4 3:0', '7:4, 3:0', '[7:4][3:0]', '4:7' (turned round), '7 6:0',
    # 'bits' / 'each' / '1x8', 'nibbles', or the old JSON [[7, 4], [3, 0]].
    # Returns (ranges, None) or (None, a message saying what is wrong).
    text = text.strip()
    lower = text.lower()
    if lower in ['bits', 'each', f'1x{width}', f'{width}x1']:
        return bitsRanges(width), None
    if lower in ['nibbles', 'nibble']:
        return nibbleRanges(width), None
    if text.startswith('[['):
        value = parseJSONList(text)
        if value == None or not all(type(p) == list and len(p) == 2 and
                                    all(type(n) == int for n in p)
                                    for p in value):
            return None, ('write the ranges like 7:4 3:0 (or the list '
                          '[[7, 4], [3, 0]])')
        pairs = value
    else:
        pairs = []
        for token in text.replace('[', ' ').replace(']', ' ').replace(
                ',', ' ').split():
            pair = parseRangeToken(token)
            if type(pair) == str:
                return None, pair
            pairs.append(pair)
    ranges = []
    for a, b in pairs:
        high, low = max(a, b), min(a, b)
        for bit in [high, low]:
            if not 0 <= bit < width:
                return None, (f'bit {bit} is outside a {width}-bit wire '
                              f'(bits {width - 1}..0)')
        ranges.append([high, low])
    if len(ranges) == 0:
        return None, ('a splitter needs at least one range, like 7:4 3:0 '
                      '(or "bits" for one output per bit)')
    return ranges, None

def parseRangeToken(token):
    # '7:4' -> [7, 4]; '7' -> [7, 7]; anything else -> a message
    if token.count(':') == 1:
        left, right = token.split(':')
        if left.isdigit() and right.isdigit():
            return [int(left), int(right)]
    elif token.isdigit():
        return [int(token), int(token)]
    for sign in ['-', '..', '_']:
        pieces = token.split(sign)
        if len(pieces) == 2 and all(p.isdigit() for p in pieces):
            return (f"'{token}' is not a range: write "
                    f'{pieces[0]}:{pieces[1]}')
    return f"'{token}' is not a range: write it like 7:4 (or 7 for one bit)"

def formatWidths(widths):
    # [4, 4] -> '4 4'; eight 1-bit pieces -> '1x8'
    if len(widths) > 2 and all(w == widths[0] for w in widths):
        return f'{widths[0]}x{len(widths)}'
    return ' '.join(str(w) for w in widths)

def parseWidths(text):
    # '4 4', '4,4', '4+4', '1x8' (eight 1-bit inputs; '8x1' too), or the
    # old JSON [4, 4]. Returns (widths, None) or (None, a message).
    text = text.strip().lower()
    if text.startswith('['):
        value = parseJSONList(text)
        if value == None or not all(type(w) == int for w in value):
            return None, 'write the widths like 4 4 (or 1x8)'
        widths = value
    elif text.count('x') == 1:
        left, right = [p.strip() for p in text.split('x')]
        if not (left.isdigit() and right.isdigit()):
            return None, f"'{text}' is not a size: write it like 1x8"
        # the smaller number is the width of each piece
        size, count = sorted([int(left), int(right)])
        widths = [size] * count
    else:
        widths = []
        for token in text.replace('+', ' ').replace(',', ' ').split():
            if not token.isdigit():
                return None, (f"'{token}' is not a width: write the widths "
                              'like 4 4 (or 1x8)')
            widths.append(int(token))
    if any(w < 1 for w in widths):
        return None, 'every piece needs at least 1 bit'
    if len(widths) < 2:
        return None, 'a MERGE joins at least 2 pieces, like 4 4'
    if sum(widths) > MAX_WIDTH:
        return None, (f'MERGE widths add up to {sum(widths)} bits; the most '
                      f'is {MAX_WIDTH}')
    return widths, None

def rangePresets(width):
    # [(label, ranges)] offered in the SPLIT menu for an input this wide
    presets = []
    def add(label, ranges):
        if ranges not in [r for l, r in presets]:
            presets.append((label, ranges))
    top = width - 1
    if width == 1:
        add('0 (the one bit)', [[0, 0]])
        return presets
    half = width // 2
    if width == 8:
        add('7:4 3:0 (nibbles)', nibbleRanges(8))
    else:
        add(f'{formatRanges([[top, half], [half - 1, 0]])} (halves)',
            [[top, half], [half - 1, 0]])
    add(f'bits ({width} x 1)', bitsRanges(width))
    add(f'{half - 1}:0 (low {half})' if half > 1 else '0 (low bit)',
        [[half - 1, 0]])
    add(f'{top}:{half} (high {width - half})' if width - half > 1 else
        f'{top} (high bit)', [[top, half]])
    add(f'{top} {top - 1}:0 (sign + rest)' if top > 1 else
        f'{top} 0', [[top, top], [top - 1, 0]])
    add(f'{top}:1 0' if top > 1 else '1 0', [[top, 1], [0, 0]])
    if width > 4:
        add('3:0 (low nibble)', [[3, 0]])
    if width >= 3:
        # the address bus's MUX and DEMUX selects in the lecture machine
        add('1:0 0 (MUX sel + DEMUX sel)', [[1, 0], [0, 0]])
    return presets

def widthPresets():
    # [(label, widths)] offered in the MERGE menu
    presets = [('4 4 (two nibbles)', [4, 4]), ('1x8 (eight bits)', [1] * 8),
               ('1x4 (four bits)', [1] * 4), ('2 2', [2, 2]),
               ('1x2 (two bits)', [1, 1])]
    return [(label, widths) for label, widths in presets
            if sum(widths) <= MAX_WIDTH]

def checkParams(typeName, params):
    # A message if params are not usable for this part, else None
    if 'width' in params and not 1 <= params['width'] <= MAX_WIDTH:
        return f'width must be 1 to {MAX_WIDTH}'
    if 'inputs' in params and not 2 <= params['inputs'] <= MAX_INPUTS:
        return f'inputs must be 2 to {MAX_INPUTS}'
    if typeName == 'SPLIT':
        if len(params['ranges']) == 0:
            return 'a splitter needs at least one range'
        for high, low in params['ranges']:
            if not 0 <= low <= high < params['width']:
                return f'range [{high}:{low}] is outside the input'
    if typeName == 'MERGE':
        if len(params['widths']) < 2 or sum(params['widths']) > MAX_WIDTH:
            return f'widths must be at least 2 pieces, {MAX_WIDTH} bits max'
    if typeName == 'EXTEND':
        if not 1 <= params['from'] <= params['to'] <= MAX_WIDTH:
            return 'from must be <= to (both 1 to 8)'
        if params['mode'] not in ['zero', 'repeat']:
            return 'mode must be zero or repeat'
    if typeName == 'DECODER':
        if not 1 <= params['bits'] <= 4:
            return 'bits must be 1 to 4'
        if not 1 <= params['outputs'] <= 1 << params['bits']:
            return 'too many outputs for that many bits'
    if typeName in ['PIN_IN', 'PIN_OUT'] and params.get('side', 'auto') \
            not in ['auto', 'left', 'right', 'top', 'bottom']:
        return 'side must be auto, left, right, top or bottom'
    if typeName in ['REG', 'DFF'] and params['init'] not in ['0', 'X']:
        return 'init must be 0 or X'
    if typeName == 'REG' and params['ports'] not in ['side', 'top']:
        return 'ports must be side or top'
    return None

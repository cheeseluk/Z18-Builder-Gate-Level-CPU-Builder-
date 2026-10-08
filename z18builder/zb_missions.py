# zb_missions.py
# Guided builds: from a full adder made of gates up to running the
# lecture's programs on a computer you wired yourself. Each mission has a
# goal, a starting circuit, the parts allowed, and a check. No graphics.
#
#   part missions:    the canvas is the inside of a part (its IN / OUT
#                     pins are the ports); checked with verifyPart, or
#                     against a Python function
#   machine missions: checked by running programs in lockstep with the
#                     golden model (zb_kit.runAndCompare), comparing only
#                     the tags the machine has

import os
import copy
import json
from zb_values import formatValue
from zb_parts import PRIMITIVES
from zb_circuit import (makeCircuit, addPart, removePart, validate,
                        definitionChanged, compositeInfo, portsMatch)
from zb_library import (makeUserPart, verifyPart, makeTester, runTester,
                        makeVectors, describeVector, saveUserPart,
                        truthTable, builtInExpected, pinsDiff)
from zb_sim import flatten, findTagged
from zb_kit import (KIT_LIBRARY, makeReferenceMachine, attachKit,
                    runAndCompare, TAG_NAMES, makeChecker, checkerGoTo,
                    phaseLabel, goldenWhy)
from zb_values import isKnown
from z18_assembler import assemble

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(HERE)
LECTURE_PROGRAMS = os.path.join(PROJECT_DIR, 'z18100', 'programs')
MISSION_PROGRAMS = os.path.join(HERE, 'programs')
PROGRESS_FILE = 'progress.json'
TEMP_NAME = '(mission check)'

GATES = ['NOT', 'BUF', 'AND', 'OR', 'NAND', 'NOR', 'XOR', 'CONST',
         'PIN_IN', 'PIN_OUT', 'PROBE']
WIRING = ['SPLIT', 'MERGE', 'EXTEND']


######################################################################
# Starting circuits
######################################################################

def pinsFor(typeName, name):
    # A sheet with the IN / OUT pins of a built-in part, ready to build
    # its inside
    circuit = makeCircuit(name)
    definition = PRIMITIVES[typeName]
    ports = definition['layout'](dict(definition['params']))[2]
    rows = {'in': 0, 'out': 0}
    for port in ports:
        if port['dir'] == 'in':
            addPart(KIT_LIBRARY, circuit, 'PIN_IN', 0, 20 + 60 * rows['in'],
                    {'name': port['name'], 'width': port['width']})
        else:
            addPart(KIT_LIBRARY, circuit, 'PIN_OUT', 500,
                    20 + 60 * rows['out'],
                    {'name': port['name'], 'width': port['width']})
        rows[port['dir']] += 1
    return circuit

def adderPins():
    circuit = makeCircuit('8-bit adder')
    for i, (name, width) in enumerate([('a', 8), ('b', 8), ('cin', 1)]):
        addPart(KIT_LIBRARY, circuit, 'PIN_IN', 0, 20 + 80 * i,
                {'name': name, 'width': width})
    for i, (name, width) in enumerate([('s', 8), ('cout', 1)]):
        addPart(KIT_LIBRARY, circuit, 'PIN_OUT', 600, 20 + 80 * i,
                {'name': name, 'width': width})
    return circuit

def pinsForPorts(name, ports):
    # A sheet with IN pins on the left and OUT pins on the right, for
    # [(name, 'in' | 'out', width)]
    circuit = makeCircuit(name)
    rows = {'in': 0, 'out': 0}
    for pinName, direction, width in ports:
        addPart(KIT_LIBRARY, circuit, 'PIN_IN' if direction == 'in' else
                'PIN_OUT', 0 if direction == 'in' else 500,
                20 + 60 * rows[direction], {'name': pinName, 'width': width})
        rows[direction] += 1
    return circuit

def referenceWithout(labels, keep=None):
    # The lecture machine with some parts taken out (their wires go too).
    # With keep, everything except those labels is taken out.
    circuit = makeReferenceMachine()
    for part in list(circuit['parts']):
        if (keep != None and part['label'] not in keep) or \
                (keep == None and part['label'] in labels):
            removePart(circuit, part['id'])
    return circuit


######################################################################
# The missions
######################################################################

def addExpected(inputs):
    total = inputs['a'] + inputs['b'] + inputs['cin']
    return {'s': total & 0xFF, 'cout': total >> 8}

def step(changes, expect, note):
    # One step of a sequence mission: set these pins, then check these
    return {'set': changes, 'expect': expect, 'note': note}

SR_PORTS = [('S', 'in', 1), ('R', 'in', 1), ('Q', 'out', 1),
            ('Qn', 'out', 1)]
DLATCH_PORTS = [('D', 'in', 1), ('E', 'in', 1), ('Q', 'out', 1)]
DFF_PORTS = [('D', 'in', 1), ('clk', 'in', 1), ('Q', 'out', 1)]
REGISTER_PORTS = [('d', 'in', 8), ('we', 'in', 1), ('clk', 'in', 1),
                  ('q', 'out', 8)]
GROUPS = {'part': 'Parts', 'sequence': 'Memory', 'machine': 'Machine'}

MISSIONS = [
    {'id': 'fulladd', 'title': 'Full adder', 'kind': 'part',
     'summary': 'Build one column of binary addition from gates',
     'goal': 'Build a full adder from gates: s = a XOR b XOR cin, and cout '
             '= 1 when two or more inputs are 1. The pins are placed for '
             'you. Every one of the 8 input rows is checked.',
     'allowed': GATES, 'start': lambda: pinsFor('FULLADD', 'Full adder'),
     'target': 'FULLADD', 'reward': 'My full adder',
     'what': 'a full adder from gates'},
    {'id': 'adder8', 'title': '8-bit adder', 'kind': 'part',
     'summary': 'Chain 8 full adders into a ripple-carry adder',
     'goal': 'Chain 8 full adders: each column\'s cout is the next '
             'column\'s cin. SPLIT a and b into bits, MERGE the sums into s. '
             's = a + b + cin (8 bits) and cout is the carry out of bit 7.',
     'allowed': GATES + WIRING + ['FULLADD', 'HALFADD'], 'allowMine': True,
     'start': adderPins,
     'ports': [('a', 'in', 8), ('b', 'in', 8), ('cin', 'in', 1),
               ('s', 'out', 8), ('cout', 'out', 1)],
     'expect': addExpected, 'reward': 'My 8-bit adder',
     'what': 'an 8-bit adder from full adders'},
    {'id': 'alu', 'title': 'ALU', 'kind': 'part',
     'summary': 'Add and subtract, with the N Z O flags',
     'goal': 'Build the ALU: out = a + b, or a - b when minus = 1 (invert '
             'B with XORs and carry in 1). n = bit 7, z = 1 when out is 0, '
             'o = carry into bit 7 XOR carry out. go = plus OR minus.',
     'allowed': GATES + WIRING + ['FULLADD', 'HALFADD'], 'allowMine': True,
     'start': lambda: pinsFor('ALU', 'ALU'), 'target': 'ALU',
     'reward': 'My ALU', 'what': 'the ALU from adders and gates'},
    {'id': 'decoder', 'title': 'Decoder 4 > 10',
     'kind': 'part', 'summary': 'One AND gate per op code',
     'goal': 'Build the op code decoder: output k is 1 when en = 1 and the '
             '4-bit input is k. Use one AND gate per output, with NOTs '
             'on the bits that are 0 in k. All 32 inputs are checked.',
     'allowed': GATES + WIRING, 'allowMine': True,
     'start': lambda: pinsFor('DECODER', 'Decoder'), 'target': 'DECODER',
     'reward': 'My decoder', 'what': 'the decoder from gates'},
    {'id': 'mux4', 'title': '4:1 MUX (8-bit)', 'kind': 'part',
     'summary': 'Pick one of four bytes with a 2-bit select',
     'goal': 'Build a 4-to-1 multiplexer: sel picks which of in0..in3 '
             'reaches out. Turn sel into 4 select lines, AND each with its '
             'input (EXTEND repeat spreads a bit over 8), then OR them.',
     'allowed': GATES + WIRING, 'allowMine': True,
     'start': lambda: pinsFor('MUX4', 'MUX 4:1'), 'target': 'MUX4',
     'reward': 'My MUX 4:1', 'what': 'a 4:1 MUX from gates'},
    # Memory: parts that remember, checked step by step from power-on.
    # Each step changes one input (so a correct latch never races), and
    # outputs are only checked after the first set or reset.
    {'id': 'srlatch', 'title': 'SR latch', 'kind': 'sequence',
     'summary': 'Two NOR gates that remember one bit',
     'goal': 'Cross two NOR gates: Q = NOR(R, Qn) and Qn = NOR(S, Q). '
             'S = 1 sets Q to 1, R = 1 resets it to 0, and with both at 0 '
             'it holds. At power-on it is x until it is first set or reset.',
     'allowed': GATES, 'what': 'an SR latch from gates',
     'start': lambda: pinsForPorts('SR latch', SR_PORTS),
     'ports': SR_PORTS, 'reward': 'My SR latch',
     'steps': [step({'R': 1}, {'Q': 0, 'Qn': 1}, 'reset'),
               step({'R': 0}, {'Q': 0, 'Qn': 1}, 'hold after reset'),
               step({'S': 1}, {'Q': 1, 'Qn': 0}, 'set'),
               step({'S': 0}, {'Q': 1, 'Qn': 0}, 'hold after set'),
               step({'S': 1}, {'Q': 1, 'Qn': 0}, 'set again'),
               step({'S': 0}, {'Q': 1, 'Qn': 0}, 'hold'),
               step({'R': 1}, {'Q': 0, 'Qn': 1}, 'reset'),
               step({'R': 0}, {'Q': 0, 'Qn': 1}, 'hold after reset')]},
    {'id': 'dlatch', 'title': 'Gated D latch', 'kind': 'sequence',
     'summary': 'Q follows D while E = 1, and holds when E = 0',
     'goal': 'Put an SR latch behind two AND gates: S = D AND E, R = (NOT '
             'D) AND E. While E = 1 the latch is open and Q follows D; when '
             'E goes to 0 it keeps the last value, whatever D does.',
     'allowed': GATES, 'allowMine': True, 'what': 'a D latch from gates',
     'start': lambda: pinsForPorts('D latch', DLATCH_PORTS),
     'ports': DLATCH_PORTS, 'reward': 'My D latch',
     'steps': [step({'E': 1}, {'Q': 0}, 'open: Q = D'),
               step({'D': 1}, {'Q': 1}, 'open: Q follows D'),
               step({'E': 0}, {'Q': 1}, 'close'),
               step({'D': 0}, {'Q': 1}, 'closed: it holds'),
               step({'E': 1}, {'Q': 0}, 'open again: Q = D'),
               step({'E': 0}, {'Q': 0}, 'close'),
               step({'D': 1}, {'Q': 0}, 'closed: it holds')]},
    {'id': 'dff', 'title': 'D flip-flop', 'kind': 'sequence',
     'summary': 'Two D latches: Q changes only when clk rises',
     'goal': 'Two D latches in a row: the first (master) is open while '
             'clk = 0, the second (slave) while clk = 1. So Q only changes '
             'when clk rises, and a change of D while clk = 1 waits for the '
             'next rising edge. A plain latch fails that step.',
     'allowed': GATES, 'allowMine': True,
     'what': 'a master-slave D flip-flop',
     'start': lambda: pinsForPorts('D flip-flop', DFF_PORTS),
     'ports': DFF_PORTS, 'reward': 'My D flip-flop',
     'steps': [step({'clk': 0}, {}, 'power on: the master is open'),
               step({'clk': 1}, {'Q': 0}, 'rising edge: Q = D'),
               step({'clk': 0}, {'Q': 0}, 'falling edge: no change'),
               step({'D': 1}, {'Q': 0}, 'D changes, no edge'),
               step({'clk': 1}, {'Q': 1}, 'rising edge: Q = D'),
               step({'D': 0}, {'Q': 1}, 'D changes while clk = 1: Q holds'),
               step({'clk': 0}, {'Q': 1}, 'falling edge: no change'),
               step({'clk': 1}, {'Q': 0}, 'rising edge: Q = D')]},
    {'id': 'register', 'title': '8-bit register', 'kind': 'sequence',
     'summary': 'A flip-flop 8 bits wide, with write enable',
     'goal': 'Gates work on whole words, so a flip-flop built 8 wide holds a '
             'byte. Feed q back through a MUX2 so an edge with we = 0 loads '
             'q again (it holds), and with we = 1 loads d. The first edge '
             'loads d = 0, so every bit is known.',
     'allowed': GATES + WIRING + ['MUX2'], 'allowMine': True,
     'what': 'an 8-bit register from gates',
     'start': lambda: pinsForPorts('register', REGISTER_PORTS),
     'ports': REGISTER_PORTS, 'reward': 'My register',
     'steps': [step({'we': 1}, {}, 'power on: d = 0, we = 1'),
               step({'clk': 1}, {'q': 0}, 'edge: q = d = 0'),
               step({'clk': 0}, {'q': 0}, 'falling edge'),
               step({'d': 0x5A}, {'q': 0}, 'd changes, no edge'),
               step({'clk': 1}, {'q': 0x5A}, 'edge with we = 1: load'),
               step({'clk': 0}, {'q': 0x5A}, 'falling edge'),
               step({'we': 0}, {'q': 0x5A}, 'we = 0'),
               step({'d': 0x33}, {'q': 0x5A}, 'd changes, no edge'),
               step({'clk': 1}, {'q': 0x5A}, 'edge with we = 0: hold'),
               step({'clk': 0}, {'q': 0x5A}, 'falling edge'),
               step({'we': 1}, {'q': 0x5A}, 'we = 1'),
               step({'clk': 1}, {'q': 0x33}, 'edge with we = 1: load'),
               step({'d': 0x11}, {'q': 0x33}, 'd changes, no edge')]},
    {'id': 'fetch', 'title': 'Fetch', 'kind': 'machine',
     'summary': 'PC -> address bus -> RAM -> data bus -> IR',
     'goal': 'Make the fetch phase work: during fetch (CLK = 0) the PC '
             'drives the address bus through a TG, the RAM reads (RE) and '
             'the IR loads (WE). During execute, CLK makes the PC count. '
             'Keep the tags PC, IR and RAM.',
     'allowed': None,
     'start': lambda: referenceWithout(None, keep=['RAM 16 x 8', 'IR',
                                                   'PC (+1)', 'Clock']),
     'programs': [os.path.join(MISSION_PROGRAMS, 'm_fetch.z18')],
     'tags': ['pc', 'ir', 'mem']},
    {'id': 'loads', 'title': 'Loads', 'kind': 'machine',
     'summary': 'Decoder outputs 1-3: memory into R1, R2, R3',
     'goal': 'Add the decoder (on CLK, from the op code) and R1, R2, R3 '
             '(tag them). Load Rk turns on output k: RAM RE (through an OR '
             'with the fetch line) and Rk WE. The IR operand drives the '
             'address bus during execute.',
     'allowed': None,
     'start': lambda: referenceWithout(['DEC 4>10', 'RE', 'R1', 'R2',
                                        'R3']),
     'programs': [os.path.join(MISSION_PROGRAMS, 'm_loads.z18')],
     'tags': ['pc', 'ir', 'mem', 'r1', 'r2', 'r3']},
    {'id': 'muxdemux', 'title': 'MUX, DEMUX, A and B',
     'kind': 'machine',
     'summary': 'Registers -> MUX reg -> A or B',
     'goal': 'Add the MUX (D0 = 0, D1 = R3, D2 = R2, D3 = R1), the MUX reg, '
             'the DEMUX and the A and B latches. The low bits of the '
             'address bus are the selects. Tag MUX reg, A and B.',
     'allowed': None,
     'start': lambda: referenceWithout(['MUX', 'MUX reg', 'DEMUX', 'A', 'B',
                                        '0 (D0)']),
     'programs': [os.path.join(MISSION_PROGRAMS, 'm_mux_demux.z18')],
     'tags': ['pc', 'ir', 'mem', 'muxReg', 'a', 'b']},
    {'id': 'store', 'title': 'Sub, Move and Store',
     'kind': 'machine', 'summary': 'Output latch, R0 and its bus buffer',
     'goal': 'Add the Output latch (loads on the ALU\'s go), R0 (loads '
             'Output on decoder output 0) and the TG that puts R0 on the '
             'data bus for Store (output 9, which is also RAM WE).',
     'allowed': None,
     'start': lambda: referenceWithout(['Output', 'R0', 'R0 RE']),
     'programs': [os.path.join(MISSION_PROGRAMS, 'm_alu_store.z18')],
     'tags': ['pc', 'ir', 'mem', 'out', 'r0']},
    {'id': 'jump', 'title': 'Jump', 'kind': 'machine',
     'summary': 'Jump-if-not-negative: N -> NOT -> AND -> PC WE',
     'goal': 'Finish the machine: PC WE = decoder output 8 AND NOT N. Then '
             'the lecture\'s loop program must run to the end exactly like '
             'the lecture machine.',
     'allowed': None,
     'start': lambda: referenceWithout(['NOT N', 'jump']),
     'programs': [os.path.join(LECTURE_PROGRAMS, 'lecture_loop.z18')],
     'tags': ['pc', 'ir', 'mem']},
    {'id': 'free', 'title': 'Free build', 'kind': 'machine',
     'summary': 'Your own Z18100 from scratch: all 6 demo programs',
     'goal': 'Build the whole computer on an empty canvas, from any parts '
             '(yours too). Tag IR, PC and RAM (and the registers, to have '
             'them checked). All 6 demo programs must match the lecture '
             'machine.',
     'allowed': None, 'start': lambda: makeCircuit('My Z18100'),
     'programs': [os.path.join(LECTURE_PROGRAMS, name) for name in
                  ['lecture_loop.z18', 'fibonacci.z18', 'flags.z18',
                   'max.z18', 'self_modify.z18', 'uninit_error.z18']],
     'tags': ['pc', 'ir', 'mem']},
]


# Numbers and groups follow the list order (progress is kept by id, so
# renumbering loses nothing)
for number, mission in enumerate(MISSIONS, 1):
    mission['number'] = number
    mission['group'] = GROUPS[mission['kind']]


def getMission(missionId):
    for mission in MISSIONS:
        if mission['id'] == missionId:
            return mission
    return None

def startCircuit(mission):
    circuit = mission['start']()
    circuit['name'] = f"Mission {mission['number']}: {mission['title']}"
    return circuit

def allowedTypes(mission, library):
    # The part types the mission lets you place, or None for any
    if mission['allowed'] == None:
        return None
    allowed = list(mission['allowed'])
    if mission.get('allowMine'):
        allowed += list(library['user'])
    return allowed


######################################################################
# Checks
######################################################################

def missionExpected(mission):
    # A function {input: value} -> {output: value} for a part mission, or
    # None
    if mission.get('target') != None:
        return builtInExpected(mission['target'])
    if mission.get('expect') != None:
        return mission['expect']
    return None

def missionPorts(mission):
    # [(name, dir, width)] of a part or sequence mission, in its order
    if mission.get('target') != None:
        definition = PRIMITIVES[mission['target']]
        return [(p['name'], p['dir'], p['width']) for p in
                definition['layout'](dict(definition['params']))[2]]
    return list(mission.get('ports', []))

def missionTable(library, mission, circuit):
    # The truth table of a part mission's circuit, with the expected column
    order = [name for name, direction, width in missionPorts(mission)]
    return truthTable(library, circuit, missionExpected(mission), order)

def notAllowedMessage(mission, part, allowed):
    what = mission.get('what', f"the {mission['title']}")
    label = f" (labelled '{part['label']}')" if part['label'] else ''
    kind = 'built-in ' if part['type'] in PRIMITIVES else 'part '
    names = []
    for typeName in allowed:
        if typeName in ['PIN_IN', 'PIN_OUT', 'PROBE']:
            continue
        names.append(PRIMITIVES[typeName]['name'] if typeName in PRIMITIVES
                     else typeName)
    return (f"This mission is about building {what}, so the {kind}"
            f"{part['type']}{label} can't be used. Allowed here: "
            f"{', '.join(names[:14])}" + (' ...' if len(names) > 14 else ''))

def checkMission(library, mission, circuit):
    # (ok, message)
    detail = checkMissionDetail(library, mission, circuit)
    return detail['ok'], detail['message']

def checkMissionDetail(library, mission, circuit):
    # {'ok', 'message', 'kind', 'table', 'failedRow', 'failedStep',
    #  'problem'}. A part mission that gives a wrong output comes with
    # its truth table and the index of a wrong row in it.
    detail = {'ok': False, 'message': '', 'kind': mission['kind'],
              'table': None, 'failedRow': None, 'failedStep': None,
              'problem': None}
    errors = [p for p in validate(library, circuit) if p['level'] == 'error']
    if len(errors) > 0:
        detail['message'] = 'Fix the wiring first: ' + errors[0]['text']
        detail['problem'] = errors[0]
        return detail
    allowed = allowedTypes(mission, library)
    if allowed != None:
        for part in circuit['parts']:
            if part['type'] not in allowed:
                detail['message'] = notAllowedMessage(mission, part,
                                                      allowed)
                detail['problem'] = {'level': 'error', 'code': 'notAllowed',
                                     'text': detail['message'], 'why': [],
                                     'fix': f"Delete the {part['type']} "
                                            'and build it from the allowed '
                                            'parts.',
                                     'parts': [part['id']]}
                return detail
    if mission['kind'] == 'part':
        ok, message, wrongOutputs = checkPart(library, mission, circuit)
        detail['ok'], detail['message'] = ok, message
        if wrongOutputs:
            table = missionTable(library, mission, circuit)
            detail['table'] = table
            for i in range(len(table['rows'])):
                if table['rows'][i]['wrong']:
                    detail['failedRow'] = i
                    break
        return detail
    if mission['kind'] == 'sequence':
        return checkSequence(library, mission, circuit, detail)
    ok, message = checkMachine(library, mission, circuit)
    detail['ok'], detail['message'] = ok, message
    return detail


######################################################################
# Sequence missions (Memory): step tables
######################################################################

def circuitPorts(circuit):
    # [{'name', 'dir', 'width'}] of a sheet's pins
    from zb_circuit import getPins
    inputs, outputs = getPins(circuit)
    return [{'name': p['params']['name'], 'width': p['params']['width'],
             'dir': 'in' if p['type'] == 'PIN_IN' else 'out'}
            for p in inputs + outputs]

def stepTable(library, mission, circuit):
    # Runs a sequence mission's steps from power-on on one tester:
    #   {'kind': 'steps', 'name', 'inputs', 'outputs', 'rows': [{'set',
    #    'note', 'expected', 'got', 'wrong', 'loop'}], 'hasExpected', ...}
    ports = mission['ports']
    inputs = [{'name': n, 'width': w} for n, d, w in ports if d == 'in']
    outputs = [{'name': n, 'width': w} for n, d, w in ports if d == 'out']
    table = {'kind': 'steps', 'name': circuit['name'], 'inputs': inputs,
             'outputs': outputs, 'rows': [], 'hasExpected': True,
             'exhaustive': True, 'total': len(mission['steps']),
             'stateful': True, 'reason': None}
    tester = makeTester(library, circuit)
    for item in mission['steps']:
        got = runTester(tester, item['set'])
        wrong = [name for name, value in item['expect'].items()
                 if got.get(name) != value]
        loop = tester['sim']['loopDetail']
        table['rows'].append({'set': dict(item['set']), 'note': item['note'],
                              'expected': dict(item['expect']), 'got': got,
                              'wrong': wrong,
                              'loop': loop['text'] if loop else None})
    return table

def checkSequence(library, mission, circuit, detail):
    message = pinsDiff(circuitPorts(circuit),
                       [{'name': n, 'dir': d, 'width': w}
                        for n, d, w in mission['ports']])
    if message != None:
        detail['message'] = message
        detail['problem'] = {'level': 'error', 'code': 'pins',
                             'text': message, 'why': [], 'fix': ''}
        return detail
    table = stepTable(library, mission, circuit)
    detail['table'] = table
    widths = {n: w for n, d, w in mission['ports']}
    current = dict()                   # the pins, as the steps set them
    for name, direction, width in mission['ports']:
        if direction == 'in':
            current[name] = 0
    rows = table['rows']
    for k in range(len(rows)):
        row = rows[k]
        before = dict(current)
        current.update(row['set'])
        if not row['wrong']:
            continue
        detail['failedStep'] = k
        changes = ', '.join(f'{n} = {v}' for n, v in current.items())
        was = ', '.join(f'{n} = {before[n]}' for n in row['set']
                        if before.get(n) != row['set'][n])
        name = row['wrong'][0]
        want = row['expected'][name]
        previous = rows[k - 1]['expected'].get(name) if k > 0 else None
        verb = 'stay' if previous == want else 'be'
        detail['message'] = (
            f"Step {k + 1} of {len(rows)} (\"{row['note']}\": {changes}"
            + (f', was {was}' if was else '') + f"): {name} should {verb} "
            f"{formatValue(want, widths[name])} but is "
            f"{formatValue(row['got'].get(name), widths[name])}.")
        if row['loop']:
            detail['message'] += ' ' + row['loop']
        return detail
    detail['ok'] = True
    detail['message'] = (f"All {len(rows)} steps are right: it remembers "
                         'like it should.')
    return detail

def checkPart(library, mission, circuit):
    # (ok, message, wrongOutputs): wrongOutputs is True when the pins are
    # right but some output is wrong
    definition = makeUserPart(library, TEMP_NAME, copy.deepcopy(circuit))
    try:
        if mission.get('target') != None:
            result = verifyPart(library, definition, mission['target'])
            return (result['ok'], result['message'],
                    result.get('mismatch') != None)
        return checkAgainstFunction(library, mission, definition)
    finally:
        library['user'].pop(TEMP_NAME, None)
        definitionChanged(library)

def checkAgainstFunction(library, mission, definition):
    ports = [{'name': name, 'dir': direction, 'width': width}
             for name, direction, width in mission['ports']]
    mine = compositeInfo(library, definition['name'])['layout'][2]
    if not portsMatch(mine, ports):
        return False, pinsDiff(mine, ports), False
    widths = {p['name']: p['width'] for p in ports}
    tester = makeTester(library, definition['circuit'])
    vectors, exhaustive = makeVectors(ports)
    for vector in vectors:
        expected = mission['expect'](vector)
        got = runTester(tester, vector)
        for name, value in expected.items():
            if got.get(name) != value:
                return False, (f"{name} should be "
                               f"{formatValue(value, widths[name])} but is "
                               f"{formatValue(got.get(name), widths[name])}"
                               f" for {describeVector(vector, ports)}"), True
    return True, f'Correct on {len(vectors)} inputs', False

def readProgram(path):
    # (memory, errors): a program with errors must not be run
    with open(path, encoding='utf-8') as f:
        memory, rows, errors = assemble(f.read())
    return memory, errors

def checkMachine(library, mission, circuit):
    sim = flatten(library, circuit)
    attachKit(sim)
    missing = []
    for tag in mission['tags']:
        if findTagged(sim, tag) == None:
            missing.append(TAG_NAMES[tag])
    if len(missing) > 0:
        return False, ('Tag these parts (select one, then t): ' +
                       ', '.join(missing))
    names = []
    for path in mission['programs']:
        name = os.path.basename(path)
        memory, errors = readProgram(path)
        if len(errors) > 0:
            lineNum, message = errors[0]
            return False, (f'{name} does not assemble (line {lineNum}: '
                           f'{message}). This is a problem with the '
                           'mission program, not with your machine.')
        count, difference = runAndCompare(sim, memory)
        if difference != None:
            checker = makeChecker(memory)
            checkerGoTo(checker, count)
            phaseName = 'fetch' if count % 2 == 1 else 'execute'
            where = phaseLabel(sim, checker['cpu'], phaseName)
            message = (f"{name}, {where}: "
                       f"{difference['message']}.")
            stopped = sim['halted'] and difference['field'] != 'halted'
            if stopped:
                message += f" (yours stopped: {sim['status']})"
            why = goldenWhy(sim, difference)
            detail = sim.get('stopDetail')
            if stopped or difference['field'] == 'halted':
                # the stop is the cause, not what loaded
                why = []
                if detail != None:
                    why = list(detail.get('why', []))
                    if detail.get('fix'):
                        why.append('Fix: ' + detail['fix'])
            if len(why) > 0:
                message += ' ' + ' '.join(why)
            return False, message
        if not sim['halted']:
            return False, neverHaltedMessage(sim, name, memory, count)
        names.append(name)
    return True, ('Your machine runs ' + ', '.join(names) +
                  ' exactly like the lecture machine.')

def neverHaltedMessage(sim, name, memory, count):
    # How long it ran, when the lecture's halts, and the PC's last values
    import z18_cpu
    cpu = z18_cpu.makeCPU(memory)
    phases = 0
    while not cpu['halted'] and phases < count:
        z18_cpu.stepPhase(cpu)
        phases += 1
    theirs = (f"the lecture's halts at phase {phases}" if cpu['halted']
              else "the lecture's doesn't either")
    text = f'{name} ran {count:,} phases without halting ({theirs}).'
    pc = findTagged(sim, 'pc')
    if pc != None:
        values = []
        for snap in sim['history'][-7:]:
            value = snap['states'][pc['index']]
            if isKnown(value) and (len(values) == 0 or values[-1] != value):
                values.append(value)
        if len(values) > 1:
            text += ' Your PC kept going ' + ' -> '.join(
                str(v) for v in values[-4:]) + '.'
    return text + ' Look at what drives PC WE.'

def rewardPart(library, mission, circuit, folder):
    # A finished part mission puts the part in My parts (verified).
    # Returns its name, or None.
    if mission['kind'] not in ['part', 'sequence']:
        return None
    name = mission['reward']
    definition = makeUserPart(library, name, copy.deepcopy(circuit))
    definition['circuit']['name'] = name
    if mission['kind'] == 'sequence':
        # checked by its step table, not a truth table; it remembers, so
        # it always runs detailed
        definition['verified'] = True
        definition['checkedBy'] = 'sequence'
        definitionChanged(library)
    elif mission.get('target') != None:
        verifyPart(library, definition, mission['target'])
    else:
        definition['verified'] = True
        definitionChanged(library)
    saveUserPart(definition, folder)
    return name


######################################################################
# Progress
######################################################################

def loadProgress(folder):
    try:
        with open(os.path.join(folder, PROGRESS_FILE), encoding='utf-8') as f:
            data = json.loads(f.read())
        return data if type(data) == dict else dict()
    except (OSError, ValueError):
        return dict()

def saveProgress(folder, progress):
    try:
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, PROGRESS_FILE), 'w',
                  encoding='utf-8') as f:
            f.write(json.dumps(progress, indent=1))
    except OSError:
        pass

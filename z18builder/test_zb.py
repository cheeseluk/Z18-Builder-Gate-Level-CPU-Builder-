# test_zb.py
# Run with: python z18builder/test_zb.py   (no window opens)

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(HERE)
for folder in [PROJECT_DIR, os.path.join(PROJECT_DIR, 'z18100'), HERE]:
    if folder not in sys.path:
        sys.path.append(folder)

import z18_cpu
from z18_assembler import assemble, assembleProgram
from zb_values import Z, X, formatValue, formatAll
from zb_parts import PRIMITIVES, gateRows, checkParams
from zb_circuit import (makeLibrary, makeCircuit, addPart, addWire,
                        addJunction, computeNets, checkNewWire, validate,
                        circuitToText, circuitFromText, splitWire,
                        removePart, nodeKey, findPart, wirePoints,
                        copyParts, pasteParts, movePart, partLayout)
from zb_sim import (flatten, stepPhase, stepInstruction, runToEnd,
                    goToStep, loadProgram, settle, taggedValues,
                    beginPhase, endPhase, snapshot)
from zb_library import (makeUserPart, verifyPart, packSelection,
                        makeTester, runTester, innerView, topView,
                        partToText, loadUserParts, saveUserPart)
from zb_kit import (makeReferenceMachine, attachKit, attachRecipes,
                    runAndCompare, RECIPES, expandToGates, makeChecker,
                    checkerStep, kitWarnings, PALETTE)

PROGRAM_DIR = os.path.join(PROJECT_DIR, 'z18100', 'programs')


def newLibrary():
    library = makeLibrary()
    attachRecipes(library)
    return library

def evaluate(typeName, inputs, params=None, state=None):
    definition = PRIMITIVES[typeName]
    allParams = dict(definition['params'])
    if params != None:
        allParams.update(params)
    return definition['evaluate'](allParams, inputs, state)

def readProgram(name):
    with open(os.path.join(PROGRAM_DIR, name), encoding='utf-8') as f:
        memory, rows, errors = assemble(f.read())
    assert(errors == [])
    return memory

def referenceSim(library=None):
    if library == None:
        library = newLibrary()
    sim = flatten(library, makeReferenceMachine())
    attachKit(sim)
    return sim


######################################################################
# Step 1: values and parts
######################################################################

def testValues():
    print('Testing values...', end='')
    assert(formatValue(45, 8) == '0010 1101')
    assert(formatValue(Z, 8) == 'ZZZZ ZZZZ')
    assert(formatValue(X, 8) == 'xxxx xxxx')
    assert(formatValue(0xFD, 8, 'dec') == '-3')
    assert(formatValue(5, 4, 'hex') == '0x5')
    assert(formatValue(1, 1) == '1')
    assert('(-3)' in formatAll(0xFD, 8))
    print('Passed!')

def testGates():
    print('Testing gates with unknowns...', end='')
    for a in [0, 1]:
        for b in [0, 1]:
            assert(evaluate('AND', {'in0': a, 'in1': b})['out'] == a & b)
            assert(evaluate('OR', {'in0': a, 'in1': b})['out'] == a | b)
            assert(evaluate('XOR', {'in0': a, 'in1': b})['out'] == a ^ b)
            assert(evaluate('NAND', {'in0': a, 'in1': b})['out'] ==
                   1 - (a & b))
            assert(evaluate('NOR', {'in0': a, 'in1': b})['out'] ==
                   1 - (a | b))
    # A deciding input wins over an unknown one
    assert(evaluate('AND', {'in0': 0, 'in1': X})['out'] == 0)
    assert(evaluate('AND', {'in0': 1, 'in1': Z})['out'] == X)
    assert(evaluate('OR', {'in0': 1, 'in1': X})['out'] == 1)
    assert(evaluate('OR', {'in0': 0, 'in1': X})['out'] == X)
    assert(evaluate('XOR', {'in0': 0, 'in1': X})['out'] == X)
    assert(evaluate('NOT', {'in': Z})['out'] == X)
    assert(evaluate('NOT', {'in': 0x0F}, {'width': 8})['out'] == 0xF0)
    # 8-bit, 3-input gates work bit by bit
    out = evaluate('AND', {'in0': 0xF0, 'in1': 0x3C, 'in2': 0xFF},
                   {'inputs': 3, 'width': 8})['out']
    assert(out == 0x30)
    assert(gateRows(2) == ([10, 30], 40))
    assert(gateRows(3) == ([10, 20, 30], 40))
    print('Passed!')

def testWiringParts():
    print('Testing TG, splitter, merger, extend...', end='')
    assert(evaluate('TG', {'in': 5, 'en': 1})['out'] == 5)
    assert(evaluate('TG', {'in': 5, 'en': 0})['out'] == Z)
    assert(evaluate('TG', {'in': 5, 'en': X})['out'] == X)
    out = evaluate('SPLIT', {'in': 0b00101101})
    assert(out == {'out0': 0b0010, 'out1': 0b1101})
    assert(evaluate('SPLIT', {'in': X})['out0'] == X)
    assert(evaluate('MERGE', {'in0': 0b0010, 'in1': 0b1101})['out'] == 45)
    assert(evaluate('EXTEND', {'in': 9})['out'] == 9)
    assert(evaluate('EXTEND', {'in': 1}, {'from': 1, 'to': 8,
                                          'mode': 'repeat'})['out'] == 255)
    assert(evaluate('CONST', {}, {'value': 7, 'width': 2})['out'] == 3)
    assert(checkParams('SPLIT', {'width': 4, 'ranges': [[5, 0]]}) != None)
    assert(checkParams('AND', {'inputs': 9, 'width': 1}) != None)
    print('Passed!')

def testBlocksMatchLecture():
    print('Testing blocks against z18_cpu...', end='')
    for a in [0, 1]:
        for b in [0, 1]:
            for c in [0, 1]:
                out = evaluate('FULLADD', {'a': a, 'b': b, 'cin': c})
                assert((out['s'], out['cout']) == z18_cpu.fullAdder(a, b, c))
    values = [0, 0x11, 0x22, 0x33]
    for sel in range(4):
        inputs = {'sel': sel}
        for k in range(4):
            inputs['in' + str(k)] = values[k]
        assert(evaluate('MUX4', inputs)['out'] ==
               z18_cpu.runMux(sel, values))
    # An unknown on an unselected input does not matter
    assert(evaluate('MUX2', {'in0': 3, 'in1': X, 'sel': 0})['out'] == 3)
    for opcode in range(16):
        out = evaluate('DECODER', {'in': opcode, 'en': 1})
        expected = z18_cpu.runDecoder(opcode, 1)
        for k in range(10):
            assert(out['d' + str(k)] == expected[k])
    assert(evaluate('DECODER', {'in': X, 'en': 0})['d3'] == 0)
    for a, b, minus in [(7, 5, 1), (100, 50, 0), (50, 50, 1), (2, 5, 1)]:
        out = evaluate('ALU', {'a': a, 'b': b, 'plus': 1 - minus,
                               'minus': minus})
        alu = z18_cpu.runAdder(a, b, minus)
        assert(out['out'] == alu['result'] and out['n'] == alu['n'])
        assert(out['z'] == alu['z'] and out['o'] == alu['o'])
        assert(out['go'] == 1)
    out = evaluate('DEMUX', {'in': 9, 'sel': 1, 'e': 1})
    assert(out == {'f0': Z, 'f1': 9, 'en0': 0, 'en1': 1})
    out = evaluate('DEMUX', {'in': 9, 'sel': 1, 'e': 0})
    assert(out['f1'] == Z and out['en1'] == 0)
    print('Passed!')

def testStatefulParts():
    print('Testing registers, counter, RAM...', end='')
    reg = PRIMITIVES['REG']
    params = dict(reg['params'])
    assert(reg['commit'](params, {'d': 5, 'we': 1}, 0) == 5)
    assert(reg['commit'](params, {'d': 5, 'we': 0}, 3) == 3)
    assert(reg['commit'](params, {'d': 5, 'we': X}, 3) == X)
    assert(reg['problem'](params, {'d': X, 'we': 1}, 0) != None)
    assert(reg['problem'](params, {'d': X, 'we': 0}, 0) == None)
    pc = PRIMITIVES['PC']
    assert(pc['commit']({}, {'d': 1, 'we': 0, 'inc': 1}, 9) == 10)
    assert(pc['commit']({}, {'d': 1, 'we': 1, 'inc': 1}, 9) == 1)
    assert(pc['evaluate']({}, {}, 17)['q'] == 1)
    ram = PRIMITIVES['RAM']
    memory = ram['initState']({})
    assert(ram['evaluate']({}, {'re': 1, 'addr': 3}, memory)['dout'] == X)
    assert(ram['evaluate']({}, {'re': 0, 'addr': 3}, memory)['dout'] == Z)
    memory = ram['commit']({}, {'we': 1, 'addr': 3, 'din': 42}, memory)
    assert(ram['evaluate']({}, {'re': 1, 'addr': 3}, memory)['dout'] == 42)
    ir = PRIMITIVES['IR']
    assert(ir['evaluate']({}, {}, 0x2D) == {'q': 0x2D, 'opcode': 2,
                                             'operand': 13})
    print('Passed!')


######################################################################
# Step 2: circuits
######################################################################

def makeAdderCircuit(library):
    # Two pins -> half adder -> two pins
    circuit = makeCircuit('ha')
    a = addPart(library, circuit, 'PIN_IN', 0, 0, {'name': 'a'})
    b = addPart(library, circuit, 'PIN_IN', 0, 40, {'name': 'b'})
    ha = addPart(library, circuit, 'HALFADD', 100, 0)
    s = addPart(library, circuit, 'PIN_OUT', 200, 0, {'name': 's'})
    c = addPart(library, circuit, 'PIN_OUT', 200, 40, {'name': 'c'})
    addWire(circuit, ['port', a['id'], 'out'], ['port', ha['id'], 'a'])
    addWire(circuit, ['port', b['id'], 'out'], ['port', ha['id'], 'b'])
    addWire(circuit, ['port', ha['id'], 's'], ['port', s['id'], 'in'])
    addWire(circuit, ['port', ha['id'], 'c'], ['port', c['id'], 'in'])
    return circuit

def testNets():
    print('Testing nets and wiring checks...', end='')
    library = newLibrary()
    circuit = makeCircuit()
    source = addPart(library, circuit, 'CONST', 0, 0)
    notA = addPart(library, circuit, 'NOT', 100, 0)
    notB = addPart(library, circuit, 'NOT', 100, 60)
    junction = addJunction(circuit, 60, 10)
    addWire(circuit, ['port', source['id'], 'out'],
            ['junction', junction['id']])
    addWire(circuit, ['junction', junction['id']],
            ['port', notA['id'], 'in'])
    addWire(circuit, ['junction', junction['id']],
            ['port', notB['id'], 'in'])
    nets = computeNets(library, circuit)
    netA = nets['nodeNet'][('port', notA['id'], 'in')]
    netB = nets['nodeNet'][('port', notB['id'], 'in')]
    assert(netA == netB)
    assert(nets['nodeNet'][('port', notA['id'], 'out')] != netA)
    # Width mismatch and two ordinary drivers are refused
    wide = addPart(library, circuit, 'NOT', 200, 0, {'width': 8})
    assert(checkNewWire(library, circuit, ['port', notA['id'], 'out'],
                        ['port', wide['id'], 'in']) != None)
    assert(checkNewWire(library, circuit, ['port', notA['id'], 'out'],
                        ['port', notB['id'], 'out']) != None)
    assert(checkNewWire(library, circuit, ['port', notA['id'], 'out'],
                        ['port', notB['id'], 'in']) != None)  # 2 drivers
    tgA = addPart(library, circuit, 'TG', 0, 200, {'width': 1})
    tgB = addPart(library, circuit, 'TG', 0, 300, {'width': 1})
    assert(checkNewWire(library, circuit, ['port', tgA['id'], 'out'],
                        ['port', tgB['id'], 'out']) == None)
    # An unconnected input is a warning
    problems = validate(library, circuit)
    assert(any(p['level'] == 'warning' for p in problems))
    print('Passed!')

def testSaveLoadAndEdit():
    print('Testing save, load, split, copy...', end='')
    library = newLibrary()
    circuit = makeReferenceMachine()
    text = circuitToText(circuit)
    again = circuitFromText(text)
    assert(circuitToText(again) == text)
    # Splitting a wire keeps its net and adds a junction
    circuit = makeAdderCircuit(library)
    wire = circuit['wires'][2]
    before = computeNets(library, circuit)['wireNet'][wire['id']]
    points = wirePoints(library, circuit, wire)
    junction = splitWire(library, circuit, wire['id'], points[0][0] + 10,
                         points[0][1])
    nets = computeNets(library, circuit)
    ha = circuit['parts'][2]
    assert(nets['nodeNet'][('junction', junction['id'])] ==
           nets['nodeNet'][('port', ha['id'], 's')])
    # Removing a part removes its wires; lone junctions go too
    removePart(circuit, ha['id'])
    assert(len(circuit['wires']) == 0 and len(circuit['junctions']) == 0)
    # Copy and paste keeps the wires between the copied parts
    circuit = makeAdderCircuit(library)
    ids = [p['id'] for p in circuit['parts']]
    newIds = pasteParts(circuit, copyParts(circuit, ids), 0, 200)
    assert(len(newIds) == 5 and len(circuit['wires']) == 8)
    # Moving a part keeps a bent wire's first segment straight
    circuit = makeReferenceMachine()
    ir = findPart(circuit, 'p2')
    movePart(library, circuit, ir, 0, 10)
    for wire in circuit['wires']:
        if wire['b'] == ['port', ir['id'], 'd']:
            assert(wire['via'][-1][1] == 110)
    print('Passed!')


######################################################################
# Step 3: the simulator
######################################################################

def testSettleAndWaves():
    print('Testing settling, waves, loops, contention...', end='')
    library = newLibrary()
    circuit = makeCircuit()
    source = addPart(library, circuit, 'PIN_IN', 0, 0, {'name': 'x'})
    last = source
    for i in range(3):
        gate = addPart(library, circuit, 'NOT', 100 * (i + 1), 0)
        addWire(circuit, ['port', last['id'], 'out'],
                ['port', gate['id'], 'in'])
        last = gate
    sim = flatten(library, circuit)
    settle(sim)
    # The value moves one NOT per wave
    waves = sorted(sim['netWave'].values())
    assert(waves == [0, 1, 2, 3])
    outNet = sim['nodeNet'][('port', (last['id'],), 'out')]
    assert(sim['nets'][outNet]['value'] == 1)
    # A ring of NOTs starting from nothing settles at X (unknown) ...
    ring = makeCircuit()
    gates = [addPart(library, ring, 'NOT', 100 * i, 0) for i in range(3)]
    for i in range(3):
        addWire(ring, ['port', gates[i]['id'], 'out'],
                ['port', gates[(i + 1) % 3]['id'], 'in'])
    sim = flatten(library, ring)
    stepPhase(sim)
    assert(not sim['halted'])
    # ... but one that starts from known values and is then let go
    # oscillates, and that is caught
    ring = makeCircuit()
    pin = addPart(library, ring, 'PIN_IN', 0, 0, {'name': 'go'})
    gate = addPart(library, ring, 'AND', 100, 0)
    inverter = addPart(library, ring, 'NOT', 200, 0)
    addWire(ring, ['port', pin['id'], 'out'], ['port', gate['id'], 'in0'])
    addWire(ring, ['port', gate['id'], 'out'],
            ['port', inverter['id'], 'in'])
    addWire(ring, ['port', inverter['id'], 'out'],
            ['port', gate['id'], 'in1'])
    tester = makeTester(library, ring)
    runTester(tester, {'go': 0})
    assert(tester['sim']['loopError'] == None)
    runTester(tester, {'go': 1})
    # (Round 2: the message now names the ring and says it oscillates)
    assert('oscillates' in tester['sim']['loopError'])
    # Two TGs on one wire: only a problem when both are on
    bus = makeCircuit()
    tgs = []
    for i in range(2):
        pin = addPart(library, bus, 'PIN_IN', 0, 100 * i,
                      {'name': 'en' + str(i)})
        value = addPart(library, bus, 'CONST', 0, 100 * i + 40,
                        {'value': i})
        tg = addPart(library, bus, 'TG', 100, 100 * i, {'width': 1})
        addWire(bus, ['port', pin['id'], 'out'], ['port', tg['id'], 'en'])
        addWire(bus, ['port', value['id'], 'out'], ['port', tg['id'], 'in'])
        tgs.append(tg)
    addWire(bus, ['port', tgs[0]['id'], 'out'], ['port', tgs[1]['id'],
                                                  'out'])
    tester = makeTester(library, bus)
    runTester(tester, {'en0': 1, 'en1': 0})
    assert(tester['sim']['contention'] == [])
    runTester(tester, {'en0': 0, 'en1': 0})
    assert(tester['sim']['contention'] == [])
    runTester(tester, {'en0': 1, 'en1': 1})
    assert(len(tester['sim']['contention']) == 1)
    print('Passed!')

def testHistory():
    print('Testing stepping back...', end='')
    sim = referenceSim()
    loadProgram(sim, readProgram('lecture_loop.z18'))
    states = [taggedValues(sim)]
    for i in range(12):
        stepPhase(sim)
        states.append(taggedValues(sim))
    goToStep(sim, 5)
    assert(taggedValues(sim) == states[5])
    assert(sim['halfCycles'] == 5)
    # Running on from the past gives the same results
    for i in range(7):
        stepPhase(sim)
    assert(taggedValues(sim) == states[12])
    goToStep(sim, 0)
    assert(taggedValues(sim) == states[0])
    print('Passed!')


######################################################################
# Step 4: the reference machine matches the lecture, phase by phase
######################################################################

def testLectureTrace():
    print('Testing the lecture trace...', end='')
    sim = referenceSim()
    phases, difference = runAndCompare(sim, readProgram('lecture_loop.z18'))
    assert(difference == None)
    values = taggedValues(sim)
    assert(values['r0'] == 0b11111101 and values['r2'] == 5)
    assert(values['r3'] == 2 and values['a'] == 2 and values['b'] == 5)
    assert(values['n'] == 1 and values['mem'][14] == 0b11111101)
    assert(values['mem'][15] == 0b11111101)
    assert(sim['status'].startswith('Halted'))
    print('Passed!')

def testAllProgramsLockstep():
    print('Testing every demo program in lockstep...', end='')
    sim = referenceSim()
    for name in sorted(os.listdir(PROGRAM_DIR)):
        if name.endswith('.z18'):
            phases, difference = runAndCompare(sim, readProgram(name))
            assert(difference == None), (name, difference)
    # And the builder's own mission programs
    folder = os.path.join(HERE, 'programs')
    for name in sorted(os.listdir(folder)):
        with open(os.path.join(folder, name), encoding='utf-8') as f:
            memory, rows, errors = assemble(f.read())
        assert(errors == []), (name, errors)
        phases, difference = runAndCompare(sim, memory)
        assert(difference == None), (name, difference)
    print('Passed!')

# Jump 4 skips the Load R2 at address 2; both paths then halt on an
# xxxxxxxx word (address 3, or address 5)
JUMP_PROGRAM = """.instruction 1010 Jump x = PC <- x
0:  Load R1, M15
    Jump 4
    Load R2, M15
4:  Load R3, M15
15: data 7
"""

def makeJumpMachine():
    # The reference machine plus an unconditional jump: an 11-output
    # DECODER, and an OR so that d10 (or the JNN AND) drives PC WE
    library = newLibrary()
    circuit = makeReferenceMachine()
    parts = circuit['parts']
    dec = [p for p in parts if p['type'] == 'DECODER'][0]
    andj = [p for p in parts if p['type'] == 'AND' and
            p['label'] == 'jump'][0]
    pc = [p for p in parts if p['ref'] == 'pc'][0]
    dec['params']['outputs'] = 11
    orj = addPart(library, circuit, 'OR', 1540, 160, label='jump or')
    for wire in circuit['wires']:
        if (wire['a'] == ['port', andj['id'], 'out'] and
                wire['b'] == ['port', pc['id'], 'we']):
            wire['b'] = ['port', orj['id'], 'in0']
            wire['via'] = []
    addWire(circuit, ['port', dec['id'], 'd10'], ['port', orj['id'], 'in1'])
    addWire(circuit, ['port', orj['id'], 'out'], ['port', pc['id'], 'we'])
    return library, circuit

def runDeclared(library, circuit, source, useIsa=True):
    result = assembleProgram(source)
    assert(result['errors'] == []), result['errors']
    sim = flatten(library, circuit)
    attachKit(sim)
    loadProgram(sim, result['memory'])
    if useIsa:
        sim['isa'] = result['isa']     # as zb_main.resetRun does
    runToEnd(sim)
    return sim, taggedValues(sim)

def testUnconditionalJump():
    print('Testing a declared Jump on a machine wired for it...', end='')
    assert(not assembleProgram(JUMP_PROGRAM)['isa']['standard'])
    library, circuit = makeJumpMachine()
    assert([p['message'] for p in validate(library, circuit)
            if p['level'] == 'error'] == [])
    # The jump machine skips Load R2
    sim, values = runDeclared(library, circuit, JUMP_PROGRAM)
    assert(values['r1'] == 7 and values['r2'] == 0 and values['r3'] == 7)
    assert('xxxxxxxx' in sim['status']), sim['status']
    # The lecture machine has no d10: Jump does nothing, so it falls
    # through to Load R2 (and halts on address 3)
    sim, values = runDeclared(newLibrary(), makeReferenceMachine(),
                              JUMP_PROGRAM)
    assert(values['r1'] == 7 and values['r2'] == 7 and values['r3'] == 0)
    # Without the program's instruction set, op 1010 halts, as before
    sim, values = runDeclared(library, circuit, JUMP_PROGRAM, useIsa=False)
    assert(values['r2'] == 0 and values['r3'] == 0)
    assert('1010' in sim['status'] and 'undefined' in sim['status'])
    # A lecture program still runs in lockstep on the jump machine
    sim = flatten(library, circuit)
    attachKit(sim)
    phases, difference = runAndCompare(sim,
                                       readProgram('lecture_loop.z18'))
    assert(difference == None), difference
    print('Passed!')

def testDeclaredCaptions():
    print('Testing captions with declared instructions...', end='')
    from zb_explain import phaseText, portText
    library, circuit = makeJumpMachine()
    result = assembleProgram(JUMP_PROGRAM)
    sim = flatten(library, circuit)
    attachKit(sim)
    loadProgram(sim, result['memory'])
    sim['isa'] = result['isa']
    stepPhase(sim)                     # fetch Load R1
    stepPhase(sim)                     # execute it
    stepPhase(sim)                     # fetch Jump 4
    assert(phaseText(sim).endswith('(execute, JUMP 4)')), phaseText(sim)
    print('Passed!')

def testCheckerFindsDifferences():
    print('Testing that the check spots a wrong machine...', end='')
    library = newLibrary()
    circuit = makeReferenceMachine()
    # Swap which registers the MUX reads: a classic wiring mistake
    mux = [p for p in circuit['parts'] if p['type'] == 'MUX4'][0]
    for wire in circuit['wires']:
        if wire['b'][:2] == ['port', mux['id']] and wire['b'][2] in ['in1',
                                                                   'in3']:
            wire['b'][2] = 'in3' if wire['b'][2] == 'in1' else 'in1'
            wire['via'] = []
    sim = flatten(library, circuit)
    attachKit(sim)
    phases, difference = runAndCompare(sim,
                                       readProgram('lecture_loop.z18'))
    assert(difference != None and difference['field'] == 'muxReg')
    assert(kitWarnings(sim) == [])
    print('Passed!')


######################################################################
# Step 5: parts made of parts
######################################################################

def testRecipesVerify():
    print('Testing that every recipe does its part\'s job...', end='')
    library = newLibrary()
    for typeName in ['HALFADD', 'FULLADD', 'MUX2', 'MUX4', 'DEMUX',
                     'DECODER', 'ALU']:
        params = dict(PRIMITIVES[typeName]['params'])
        definition = makeUserPart(library, 'my ' + typeName,
                                  RECIPES[typeName](params))
        result = verifyPart(library, definition, typeName)
        assert(result['ok']), (typeName, result['message'])
        assert(definition['verified'])
    # A wrong part is caught, with the inputs that show it
    circuit = RECIPES['HALFADD']({})
    for part in circuit['parts']:
        if part['type'] == 'XOR':
            part['type'] = 'OR'
    wrong = makeUserPart(library, 'bad HA', circuit)
    result = verifyPart(library, wrong, 'HALFADD')
    assert(not result['ok'] and result['mismatch']['output'] == 's')
    # Pins that don't match are reported, not tested
    result = verifyPart(library, wrong, 'FULLADD')
    assert(not result['ok'] and 'pins' in result['message'])
    print('Passed!')

def testGateLevelMachine():
    print('Testing the machine opened down to gates...', end='')
    library = newLibrary()
    gates = expandToGates(library, makeReferenceMachine())
    sim = flatten(library, gates)
    attachKit(sim)
    assert(len(sim['prims']) > 100)
    start = time.time()
    for name in ['lecture_loop.z18', 'flags.z18', 'max.z18']:
        phases, difference = runAndCompare(sim, readProgram(name))
        assert(difference == None), (name, difference)
    # Fast mode: the verified parts run as their built-in twins
    for definition in library['user'].values():
        if not definition['stateful']:
            verifyPart(library, definition, definition['implements'])
    for part in gates['parts']:
        part['mode'] = 'fast'
    fast = flatten(library, gates)
    attachKit(fast)
    assert(len(fast['prims']) < len(sim['prims']))
    phases, difference = runAndCompare(fast,
                                       readProgram('fibonacci.z18'))
    assert(difference == None)
    print(f'Passed! ({len(sim["prims"])} primitives at gate level)')

def testPacking():
    print('Testing packing parts into a new part...', end='')
    library = newLibrary()
    circuit = makeReferenceMachine()
    # Pack the ALU, Output and Flags into one part
    ids = [p['id'] for p in circuit['parts']
           if p['label'] in ['ALU', 'Output', 'Flags']]
    definition, part = packSelection(library, circuit, ids, 'ALU unit')
    assert(definition != None), part
    assert(definition['stateful'])
    sim = flatten(library, circuit)
    attachKit(sim)
    for name in ['lecture_loop.z18', 'flags.z18']:
        phases, difference = runAndCompare(sim, readProgram(name))
        assert(difference == None), (name, difference)
    # The part saves and loads
    folder = os.path.join(HERE, 'parts_test_tmp')
    saveUserPart(definition, folder)
    other = newLibrary()
    assert(loadUserParts(other, folder) == [])
    assert('ALU unit' in other['user'])
    for fileName in os.listdir(folder):
        os.remove(os.path.join(folder, fileName))
    os.rmdir(folder)
    print('Passed!')

def testInnerView():
    print('Testing looking inside running parts...', end='')
    library = newLibrary()
    circuit = makeReferenceMachine()
    sim = flatten(library, circuit)
    attachKit(sim)
    loadProgram(sim, readProgram('lecture_loop.z18'))
    for i in range(13):                 # into Sub's execute phase
        stepPhase(sim)
    beginPhase(sim)
    view = topView(circuit, sim)
    alu = [p for p in circuit['parts'] if p['type'] == 'ALU'][0]
    inside = innerView(library, view, alu)
    assert(inside['readOnly'])
    pinOut = [p for p in inside['circuit']['parts']
              if p['type'] == 'PIN_OUT' and p['params']['name'] == 'out'][0]
    value = inside['sim']['nets'][inside['sim']['nodeNet'][
        ('port', (pinOut['id'],), 'in')]]['value']
    aluOut = sim['nets'][sim['nodeNet'][('port', (alu['id'],), 'out')]]
    assert(value == aluOut['value'] == 2)       # 7 - 5
    # Inside the IR, the recipe's register holds the IR's value
    ir = [p for p in circuit['parts'] if p['type'] == 'IR'][0]
    inside = innerView(library, view, ir)
    reg = [p for p in inside['sim']['prims'] if p['label'] == 'IR'][0]
    assert(reg['state'] == 0b01111111)
    endPhase(sim)
    print('Passed!')

def testPalette():
    print('Testing the palette...', end='')
    for group, types in PALETTE:
        for typeName in types:
            assert(typeName in PRIMITIVES)
    print('Passed!')

######################################################################
# Step 7: editor actions on a fake app (no window)
######################################################################

import types
import shutil
import zb_editor

TEST_LAYOUT = {'buildCanvas': (158, 82, 790, 586),
               'runCanvas': (4, 82, 944, 586)}

def makeFakeApp(folder, root=None):
    # A stand-in for the cmu_graphics app, with every field zb_editor and
    # zb_view read. Files go to a scratch folder, not circuits/ or parts/.
    zb_editor.CIRCUIT_DIR = os.path.join(folder, 'circuits')
    zb_editor.PARTS_DIR = os.path.join(folder, 'parts')
    app = types.SimpleNamespace()
    if root == None:
        root = makeCircuit('test')
    zb_editor.initAppFields(app, TEST_LAYOUT, newLibrary(), root)
    return app

def screenOf(app, x, y):
    return zb_editor.toScreen(app, x, y)

def placeFake(app, typeName, x, y):
    zb_editor.startPlacing(app, typeName)
    zb_editor.placeAt(app, *screenOf(app, x, y))
    return zb_editor.getSelectedPart(app)

def portHit(part, portName):
    return {'kind': 'port', 'part': part['id'], 'port': portName,
            'end': ['port', part['id'], portName]}

def wireFake(app, partA, portA, partB, portB):
    zb_editor.startWire(app, ['port', partA['id'], portA])
    zb_editor.finishWire(app, portHit(partB, portB))

def settleRoot(app, inputs):
    # Runs the top level with the IN pins set; returns {OUT pin: value}
    tester = makeTester(app.library, app.root)
    return runTester(tester, inputs)

def testEditorActions():
    print('Testing editor actions on a fake app...', end='')
    folder = os.path.join(HERE, 'editor_test_tmp')
    app = makeFakeApp(folder)
    try:
        pin = placeFake(app, 'PIN_IN', 0, 0)
        gate = placeFake(app, 'NOT', 120, 0)
        out = placeFake(app, 'PIN_OUT', 240, 0)
        circuit = app.root
        assert(len(circuit['parts']) == 3)
        assert(pin['params']['name'] == 'in0')
        assert(out['params']['name'] == 'out0')
        assert(pin['x'] % 10 == 0 and pin['y'] % 10 == 0)   # on the grid
        # Wiring
        wireFake(app, pin, 'out', gate, 'in')
        wireFake(app, gate, 'out', out, 'in')
        assert(len(app.root['wires']) == 2)
        assert(app.problems == [])
        assert(settleRoot(app, {'in0': 1}) == {'out0': 0})
        # A wire that would join two outputs is refused
        wireFake(app, pin, 'out', gate, 'out')
        assert(len(app.root['wires']) == 2)
        assert(app.messageColor == 'error')
        # Undo takes the last wire away, redo puts it back
        zb_editor.undo(app)
        assert(len(app.root['wires']) == 1)
        zb_editor.redo(app)
        assert(len(app.root['wires']) == 2)
        # Moving by whole grid steps, and undo puts it back
        gate = findPart(app.root, gate['id'])
        x0, y0 = gate['x'], gate['y']
        app.selection = {'parts': {gate['id']}, 'wires': set(),
                         'junctions': set()}
        zb_editor.startMove(app, *screenOf(app, 130, 10))
        zb_editor.dragMove(app, *screenOf(app, 153, 38))
        zb_editor.endDrag(app)
        gate = findPart(app.root, gate['id'])
        assert((gate['x'], gate['y']) == (x0 + 20, y0 + 30))
        zb_editor.undo(app)
        gate = findPart(app.root, gate['id'])
        assert((gate['x'], gate['y']) == (x0, y0))
        # Deleting a part takes its wires; undo restores both
        app.selection = {'parts': {gate['id']}, 'wires': set(),
                         'junctions': set()}
        zb_editor.deleteSelection(app)
        assert(len(app.root['parts']) == 2 and app.root['wires'] == [])
        zb_editor.undo(app)
        assert(len(app.root['parts']) == 3)
        assert(len(app.root['wires']) == 2)
        # A width change drops the wires that no longer fit
        gate = findPart(app.root, gate['id'])
        assert(zb_editor.setParam(app, gate, 'width', '8') == None)
        assert(app.root['wires'] == [])
        assert(zb_editor.setParam(app, gate, 'width', 'nine') != None)
        zb_editor.undo(app)
        assert(len(app.root['wires']) == 2)
        # Copy and paste bring the wires between copied parts
        ids = {p['id'] for p in app.root['parts']}
        app.selection = {'parts': set(ids), 'wires': set(),
                         'junctions': set()}
        zb_editor.copySelection(app)
        zb_editor.paste(app)
        assert(len(app.root['parts']) == 6)
        assert(len(app.root['wires']) == 4)
        zb_editor.undo(app)
        assert(len(app.root['parts']) == 3)
        # Pack the NOT into a part; the circuit still works
        gate = [p for p in app.root['parts'] if p['type'] == 'NOT'][0]
        app.selection = {'parts': {gate['id']}, 'wires': set(),
                         'junctions': set()}
        zb_editor.packInto(app, 'Inverter')
        assert('Inverter' in app.library['user'])
        assert([p['type'] for p in app.root['parts']].count('Inverter')
               == 1)
        assert(settleRoot(app, {'in0': 0}) == {'out0': 1})
        assert(os.path.exists(os.path.join(zb_editor.PARTS_DIR,
                                           'Inverter.json')))
        # Verify it, look inside, edit inside (it must be verified again)
        zb_editor.verifyCurrent(app, 'NOT')
        assert(app.verifyResult['ok'])
        assert(app.library['user']['Inverter']['verified'])
        inverter = zb_editor.getSelectedPart(app)
        zb_editor.drillIn(app, inverter['id'])
        assert(app.path == [inverter['id']])
        assert(zb_editor.editingPartName(app) == 'Inverter')
        placeFake(app, 'PROBE', 100, 100)
        assert(not app.library['user']['Inverter']['verified'])
        assert(zb_editor.drillOut(app))
        assert(app.path == [])
        # Undo after packing puts the NOT back
        zb_editor.undo(app)
        zb_editor.undo(app)
        assert('NOT' in [p['type'] for p in app.root['parts']])
        # Built-in recipes are read-only inside
        alu = placeFake(app, 'ALU', 400, 0)
        zb_editor.drillIn(app, alu['id'])
        assert(app.view['readOnly'] and not zb_editor.isEditable(app))
        before = len(zb_editor.getCircuit(app)['parts'])
        placeFake(app, 'NOT', 0, 0)
        assert(len(zb_editor.getCircuit(app)['parts']) == before)
        zb_editor.drillOut(app)
        # New part: a blank sheet with two pins, opened for editing
        zb_editor.newUserPart(app, 'Blank')
        assert(zb_editor.editingPartName(app) == 'Blank')
        assert(len(zb_editor.getCircuit(app)['parts']) == 2)
        zb_editor.drillOut(app)
        # Autosave wrote the root circuit
        assert(os.path.exists(os.path.join(zb_editor.CIRCUIT_DIR,
                                           'autosave.json')))
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testWireBends():
    print('Testing wire bends and box select...', end='')
    folder = os.path.join(HERE, 'editor_test_tmp')
    app = makeFakeApp(folder)
    try:
        pin = placeFake(app, 'PIN_IN', 0, 0)
        out = placeFake(app, 'PIN_OUT', 300, 100)
        zb_editor.startWire(app, ['port', pin['id'], 'out'])
        zb_editor.addBend(app, *screenOf(app, 150, 200))
        zb_editor.finishWire(app, portHit(out, 'in'))
        points = wirePoints(app.library, app.root, app.root['wires'][0])
        for i in range(len(points) - 1):
            (x1, y1), (x2, y2) = points[i], points[i + 1]
            assert(x1 == x2 or y1 == y2), points      # only right angles
        # Box select picks the parts wholly inside the box
        zb_editor.selectBox(app, -100, -100, 100, 100, False)
        assert(app.selection['parts'] == {pin['id']})
        zb_editor.selectBox(app, -100, -100, 500, 500, True)
        assert(len(app.selection['parts']) == 2)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testPinSides():
    print('Testing pin sides on a user part...', end='')
    library = newLibrary()
    inner = makeCircuit('sides')
    addPart(library, inner, 'PIN_IN', 0, 0, {'name': 'a'})
    addPart(library, inner, 'PIN_IN', 0, 40, {'name': 'b', 'side': 'top'})
    addPart(library, inner, 'PIN_OUT', 200, 0, {'name': 'y'})
    makeUserPart(library, 'Sides', inner)
    part = addPart(library, makeCircuit(), 'Sides', 0, 0)
    width, height, ports = partLayout(library, part)
    where = {p['name']: (p['dx'], p['dy']) for p in ports}
    assert(where['a'] == (0, 20) and where['y'] == (width, 20))
    # (Round 3: ports are spread evenly, so one top port is centred)
    assert(where['b'] == (width // 2, 0))
    assert(checkParams('PIN_IN', {'name': 'a', 'width': 1,
                                  'side': 'middle'}) != None)
    print('Passed!')

def buildAdder8():
    from zb_kit import newBuild, put, putPin, link
    b = newBuild('adder')
    putPin(b, 'a', 'in', 'a', 8, 0, 20)
    putPin(b, 'b', 'in', 'b', 8, 0, 100)
    putPin(b, 'cin', 'in', 'cin', 1, 0, 180)
    ranges = [[7 - i, 7 - i] for i in range(8)]
    put(b, 'sa', 'SPLIT', 70, 10, {'width': 8, 'ranges': ranges})
    put(b, 'sb', 'SPLIT', 70, 100, {'width': 8, 'ranges': ranges})
    link(b, 'a.out', 'sa.in')
    link(b, 'b.out', 'sb.in')
    put(b, 'merge', 'MERGE', 400, 100, {'widths': [1] * 8})
    for i in range(8):
        put(b, f'fa{i}', 'FULLADD', 200, 70 * i)
        link(b, f'sa.out{7 - i}', f'fa{i}.a')
        link(b, f'sb.out{7 - i}', f'fa{i}.b')
        link(b, 'cin.out' if i == 0 else f'fa{i - 1}.cout', f'fa{i}.cin')
        link(b, f'fa{i}.s', f'merge.in{7 - i}')
    putPin(b, 's', 'out', 's', 8, 500, 100)
    putPin(b, 'cout', 'out', 'cout', 1, 500, 200)
    link(b, 'merge.out', 's.in')
    link(b, 'fa7.cout', 'cout.in')
    return b['circuit']

def testMissions():
    print('Testing the missions...', end='')
    import zb_missions
    library = newLibrary()
    reference = makeReferenceMachine()
    for mission in zb_missions.MISSIONS:
        if mission['kind'] == 'sequence':
            continue                   # (testSequenceMissions)
        start = zb_missions.startCircuit(mission)
        assert([p for p in validate(library, start)
                if p['level'] == 'error'] == [])
        ok, message = zb_missions.checkMission(library, mission, start)
        assert(not ok), mission['id']          # nothing is built yet
        if mission['kind'] == 'machine':
            solution = reference
        elif mission['id'] == 'adder8':
            solution = buildAdder8()
        else:
            solution = RECIPES[mission['target']](
                PRIMITIVES[mission['target']]['params'])
        ok, message = zb_missions.checkMission(library, mission, solution)
        assert(ok), (mission['id'], message)
    # A part mission refuses parts it asks you to build yourself
    ok, message = zb_missions.checkMission(
        library, zb_missions.getMission('adder8'), RECIPES['ALU']({}))
    assert(not ok)
    assert(library['user'] == dict())          # the check leaves no parts
    # A part mission's reward is a verified part
    folder = os.path.join(HERE, 'missions_test_tmp')
    try:
        mission = zb_missions.getMission('fulladd')
        name = zb_missions.rewardPart(library, mission,
                                      RECIPES['FULLADD']({}), folder)
        assert(library['user'][name]['verified'])
        progress = {'fulladd': True}
        zb_missions.saveProgress(folder, progress)
        assert(zb_missions.loadProgress(folder) == progress)
        assert(loadUserParts(newLibrary(), folder) == [])
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testShippedReference():
    print('Testing circuits/z18100_reference.json...', end='')
    from zb_circuit import loadCircuit
    shipped = loadCircuit(os.path.join(HERE, 'circuits',
                                       'z18100_reference.json'))
    assert(circuitToText(shipped) == circuitToText(makeReferenceMachine()))
    print('Passed!')

######################################################################
# Round 2, M1: the speed dial
######################################################################

def testSpeedLevels():
    print('Testing the speed dial...', end='')
    from zb_editor import (SPEEDS, FRAMES_PER_WAVE, START_ANIM_LEVEL,
                           speedLabel, changeAnimLevel, advanceWave)
    assert(SPEEDS == sorted(SPEEDS))
    for speed in [0.05, 0.1, 0.25, 0.5, 0.75, 1]:
        assert(speed in SPEEDS)
    assert(FRAMES_PER_WAVE[SPEEDS.index(1)] == 14)
    assert(FRAMES_PER_WAVE[-1] == 2)
    assert(SPEEDS[START_ANIM_LEVEL] == 1)
    assert(speedLabel(0.25) == '0.25×' and speedLabel(1) == '1×')
    assert(speedLabel(1.5) == '1.5×' and speedLabel(7) == '7×')
    folder = os.path.join(HERE, 'speed_test_tmp')
    app = makeFakeApp(folder)
    try:
        assert(app.animLevel == START_ANIM_LEVEL)
        for i in range(20):
            changeAnimLevel(app, +1)
        assert(app.animLevel == len(SPEEDS) - 1)
        for i in range(20):
            changeAnimLevel(app, -1)
        assert(app.animLevel == 0 and '0.05×' in app.message)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    # A wave at 0.5x takes twice as many frames as at 1x
    def framesForWave(level):
        waveT, frames = 0, 0
        while waveT < 1:
            waveT = advanceWave(waveT, 1, level)
            frames += 1
        return frames
    assert(framesForWave(SPEEDS.index(0.5)) ==
           2 * framesForWave(SPEEDS.index(1)))
    print('Passed!')

######################################################################
# Round 2, M2: SPLIT / MERGE in bus notation
######################################################################

def testRangeNotation():
    print('Testing SPLIT / MERGE notation...', end='')
    from zb_parts import parseRanges, formatRanges, parseWidths
    nibbles = [[7, 4], [3, 0]]
    for text in ['7:4 3:0', '7:4, 3:0', '[7:4][3:0]', '[7:4] [3:0]',
                 '4:7 0:3', '[[7,4],[3,0]]', 'nibbles']:
        assert(parseRanges(text, 8) == (nibbles, None)), text
    assert(parseRanges('7 6:0', 8)[0] == [[7, 7], [6, 0]])
    assert(parseRanges('bits', 4)[0] == [[3, 3], [2, 2], [1, 1], [0, 0]])
    ranges, message = parseRanges('9:0', 8)
    assert(ranges == None and 'bit 9' in message and '7..0' in message)
    ranges, message = parseRanges('7-4', 8)
    assert(ranges == None and '7:4' in message)
    for text in ['7:4 3:0', '7 6:0', '3:0', '1:0 0']:
        assert(formatRanges(parseRanges(text, 8)[0]) == text)
    assert(parseWidths('1x8') == ([1] * 8, None))
    assert(parseWidths('8x1') == ([1] * 8, None))
    assert(parseWidths('4+4') == ([4, 4], None))
    assert(parseWidths('4,4')[0] == [4, 4])
    assert(parseWidths('[4, 4]')[0] == [4, 4])
    widths, message = parseWidths('5 4')
    assert(widths == None and '9 bits' in message)
    # Through the editor: a SPLIT set to 3:0 keeps only wires that fit
    folder = os.path.join(HERE, 'split_test_tmp')
    app = makeFakeApp(folder)
    try:
        pin = placeFake(app, 'PIN_IN', 0, 0)
        assert(zb_editor.setParam(app, pin, 'width', '8') == None)
        split = placeFake(app, 'SPLIT', 120, 0)
        low = placeFake(app, 'PIN_OUT', 240, 0)
        high = placeFake(app, 'PIN_OUT', 240, 60)
        pin, split = findPart(app.root, pin['id']), findPart(app.root,
                                                             split['id'])
        for out in [low, high]:
            assert(zb_editor.setParam(app, findPart(app.root, out['id']),
                                      'width', '4') == None)
        wireFake(app, pin, 'out', split, 'in')
        wireFake(app, split, 'out0', findPart(app.root, high['id']), 'in')
        wireFake(app, split, 'out1', findPart(app.root, low['id']), 'in')
        assert(len(app.root['wires']) == 3)
        assert(zb_editor.setParam(app, split, 'ranges', '3:0') == None)
        split = findPart(app.root, split['id'])
        assert(split['params']['ranges'] == [[3, 0]])
        assert(len(app.root['wires']) == 2)     # out1 is gone
        message = zb_editor.setParam(app, split, 'ranges', '9:0')
        assert(message != None and 'bit 9' in message)
        assert(zb_editor.setParam(app, split, 'ranges', '[[7,4],[3,0]]')
               == None)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testRangePresets():
    print('Testing SPLIT / MERGE presets...', end='')
    from zb_parts import rangePresets, widthPresets
    for width in range(1, 9):
        for label, ranges in rangePresets(width):
            assert(checkParams('SPLIT', {'width': width, 'ranges': ranges})
                   == None), (width, label)
    for label, widths in widthPresets():
        assert(sum(widths) <= 8)
        assert(checkParams('MERGE', {'widths': widths}) == None)
    # Every splitter in the lecture machine (and the recipes) is a preset
    library = newLibrary()
    circuits = [makeReferenceMachine()]
    for typeName, recipe in RECIPES.items():
        circuits.append(recipe(dict(PRIMITIVES[typeName]['params'])))
    for circuit in circuits:
        for part in circuit['parts']:
            if part['type'] == 'SPLIT':
                width = part['params']['width']
                presets = [r for l, r in rangePresets(width)]
                assert(part['params']['ranges'] in presets), part['params']
            elif part['type'] == 'MERGE':
                presets = [w for l, w in widthPresets()]
                assert(part['params']['widths'] in presets), part['params']
    print('Passed!')

######################################################################
# Round 2, M3: loops of gates (latches)
######################################################################

def addSRGates(b, p, x, y, width=1):
    # A NOR latch: Qn = NOR(S, Q) is p+'n1', Q = NOR(R, Qn) is p+'n2'.
    # S goes to n1.in0 and R to n2.in1.
    from zb_kit import put, link
    put(b, p + 'n1', 'NOR', x, y, {'width': width})
    put(b, p + 'n2', 'NOR', x, y + 60, {'width': width})
    link(b, p + 'n2.out', p + 'n1.in1')
    link(b, p + 'n1.out', p + 'n2.in0')

def addDLatchGates(b, p, x, y, width=1):
    # S = AND(D, E), R = AND(NOT D, E) into a NOR latch. D goes to
    # p+'as.in0' and p+'not.in', E to p+'as.in1' and p+'ar.in1'; Q is
    # p+'n2.out'.
    from zb_kit import put, link
    put(b, p + 'not', 'NOT', x, y + 60, {'width': width})
    put(b, p + 'as', 'AND', x + 70, y, {'width': width})
    put(b, p + 'ar', 'AND', x + 70, y + 60, {'width': width})
    addSRGates(b, p, x + 150, y, width)
    link(b, p + 'not.out', p + 'ar.in0')
    link(b, p + 'as.out', p + 'n1.in0')
    link(b, p + 'ar.out', p + 'n2.in1')

def linkD(b, p, source):
    from zb_kit import link
    link(b, source, p + 'as.in0')
    link(b, source, p + 'not.in')

def linkE(b, p, source):
    from zb_kit import link
    link(b, source, p + 'as.in1')
    link(b, source, p + 'ar.in1')

def buildSRLatch():
    from zb_kit import newBuild, putPin, link
    b = newBuild('SR latch')
    putPin(b, 'S', 'in', 'S', 1, 0, 20)
    putPin(b, 'R', 'in', 'R', 1, 0, 120)
    addSRGates(b, '', 120, 10)
    link(b, 'S.out', 'n1.in0')
    link(b, 'R.out', 'n2.in1')
    putPin(b, 'Q', 'out', 'Q', 1, 300, 80)
    putPin(b, 'Qn', 'out', 'Qn', 1, 300, 20)
    link(b, 'n2.out', 'Q.in')
    link(b, 'n1.out', 'Qn.in')
    return b['circuit']

def buildDLatch(width=1):
    from zb_kit import newBuild, putPin, link
    b = newBuild('D latch')
    putPin(b, 'D', 'in', 'D', width, 0, 20)
    putPin(b, 'E', 'in', 'E', width, 0, 120)
    addDLatchGates(b, '', 80, 10, width)
    linkD(b, '', 'D.out')
    linkE(b, '', 'E.out')
    putPin(b, 'Q', 'out', 'Q', width, 400, 80)
    link(b, 'n2.out', 'Q.in')
    return b['circuit']

def addDffGates(b, p, x, y, width, clkSource):
    # Master (open while clk = 0) then slave (open while clk = 1): Q only
    # changes when clk rises. Q is p+'s_n2.out'; D goes in with linkD(b,
    # p + 'm_', ...).
    from zb_kit import put, link
    if width > 1:
        put(b, p + 'rep', 'EXTEND', x, y + 200, {'from': 1, 'to': width,
                                                 'mode': 'repeat'})
        link(b, clkSource, p + 'rep.in')
        clkSource = p + 'rep.out'
    put(b, p + 'nclk', 'NOT', x + 60, y + 200, {'width': width})
    link(b, clkSource, p + 'nclk.in')
    addDLatchGates(b, p + 'm_', x, y, width)
    addDLatchGates(b, p + 's_', x + 260, y, width)
    linkE(b, p + 'm_', p + 'nclk.out')
    linkE(b, p + 's_', clkSource)
    linkD(b, p + 's_', p + 'm_n2.out')

def buildDff(width=1):
    from zb_kit import newBuild, putPin, link
    b = newBuild('D flip-flop')
    putPin(b, 'D', 'in', 'D', width, 0, 20)
    putPin(b, 'clk', 'in', 'clk', 1, 0, 220)
    addDffGates(b, '', 80, 10, width, 'clk.out')
    linkD(b, 'm_', 'D.out')
    putPin(b, 'Q', 'out', 'Q', width, 700, 80)
    link(b, 's_n2.out', 'Q.in')
    return b['circuit']

def buildRegister8():
    # A flip-flop 8 wide, with q fed back through a MUX when we = 0
    from zb_kit import newBuild, put, putPin, link
    b = newBuild('register')
    putPin(b, 'd', 'in', 'd', 8, 0, 20)
    putPin(b, 'we', 'in', 'we', 1, 0, 120)
    putPin(b, 'clk', 'in', 'clk', 1, 0, 220)
    put(b, 'mux', 'MUX2', 60, 10, {'width': 8})
    link(b, 'd.out', 'mux.in1')
    link(b, 'we.out', 'mux.sel')
    addDffGates(b, '', 120, 10, 8, 'clk.out')
    linkD(b, 'm_', 'mux.out')
    putPin(b, 'q', 'out', 'q', 8, 760, 80)
    link(b, 's_n2.out', 'q.in')
    link(b, 's_n2.out', 'mux.in0')
    return b['circuit']

def latchNets(sim, circuit):
    # (Q net, Qn net) of buildSRLatch's circuit in a sim of it
    ids = {p['params']['name']: p['id'] for p in circuit['parts']
           if p['type'] == 'PIN_OUT'}
    return (sim['nodeNet'][('port', (ids['Q'],), 'in')],
            sim['nodeNet'][('port', (ids['Qn'],), 'in')])

def testGateLoopsFound():
    print('Testing that loops of gates are found...', end='')
    from zb_sim import loopInversions
    library = newLibrary()
    sim = flatten(library, buildSRLatch())
    assert(len(sim['loops']) == 1 and len(sim['loops'][0]) == 2)
    assert(loopInversions(sim, sim['loops'][0]) == 2)
    ring = makeCircuit()
    gates = [addPart(library, ring, 'NOT', 100 * i, 0) for i in range(3)]
    for i in range(3):
        addWire(ring, ['port', gates[i]['id'], 'out'],
                ['port', gates[(i + 1) % 3]['id'], 'in'])
    sim = flatten(library, ring)
    assert(len(sim['loops']) == 1 and len(sim['loops'][0]) == 3)
    assert(loopInversions(sim, sim['loops'][0]) == 3)
    # The loop is listed in cycle order
    loop = sim['loops'][0]
    for i in range(3):
        out = sim['prims'][loop[i]]['outNets']['out']
        assert(loop[(i + 1) % 3] in sim['nets'][out]['readers'])
    # A register feeding itself through a NOT is not a loop of gates
    circuit = makeCircuit()
    reg = addPart(library, circuit, 'REG', 0, 0, {'width': 1})
    inverter = addPart(library, circuit, 'NOT', 100, 0)
    addWire(circuit, ['port', reg['id'], 'q'], ['port', inverter['id'],
                                                 'in'])
    addWire(circuit, ['port', inverter['id'], 'out'], ['port', reg['id'],
                                                       'd'])
    assert(flatten(library, circuit)['loops'] == [])
    print('Passed!')

def testReferenceHasNoGateLoops():
    print('Testing that the lecture machine has no gate loops...', end='')
    library = newLibrary()
    assert(flatten(library, makeReferenceMachine())['loops'] == [])
    gates = expandToGates(library, makeReferenceMachine())
    assert(flatten(library, gates)['loops'] == [])
    print('Passed!')

def testLatchPowerOnIsX():
    print('Testing that a latch starts unknown...', end='')
    library = newLibrary()
    circuit = buildSRLatch()
    tester = makeTester(library, circuit)
    out = runTester(tester, {'S': 0, 'R': 0})
    assert(out == {'Q': X, 'Qn': X}), out
    assert(tester['sim']['loopError'] == None)
    print('Passed!')

def testLatchSetResetHold():
    print('Testing set, reset and hold on a NOR latch...', end='')
    library = newLibrary()
    tester = makeTester(library, buildSRLatch())
    assert(runTester(tester, {'S': 1, 'R': 0}) == {'Q': 1, 'Qn': 0})
    assert(runTester(tester, {'S': 0, 'R': 0}) == {'Q': 1, 'Qn': 0})
    assert(runTester(tester, {'S': 0, 'R': 1}) == {'Q': 0, 'Qn': 1})
    assert(runTester(tester, {'S': 0, 'R': 0}) == {'Q': 0, 'Qn': 1})
    assert(tester['sim']['loopError'] == None)
    print('Passed!')

def testRingOscillatorMessage():
    print('Testing the message for a ring that oscillates...', end='')
    library = newLibrary()
    # go AND (the ring) -> NOT -> NOT -> NOT -> back: three inversions
    ring = makeCircuit()
    pin = addPart(library, ring, 'PIN_IN', 0, 0, {'name': 'go'})
    gate = addPart(library, ring, 'AND', 100, 0)
    chain = [gate] + [addPart(library, ring, 'NOT', 200 + 60 * i, 0)
                      for i in range(3)]
    addWire(ring, ['port', pin['id'], 'out'], ['port', gate['id'], 'in0'])
    for i in range(3):
        addWire(ring, ['port', chain[i]['id'], 'out'],
                ['port', chain[i + 1]['id'], 'in'])
    addWire(ring, ['port', chain[3]['id'], 'out'], ['port', gate['id'],
                                                     'in1'])
    tester = makeTester(library, ring)
    runTester(tester, {'go': 0})                  # known values: 0 1 0 1
    assert(tester['sim']['loopError'] == None)
    start = time.time()
    runTester(tester, {'go': 1})
    assert(time.time() - start < 2)               # it returned
    sim = tester['sim']
    detail = sim['loopDetail']
    assert(detail['code'] == 'loopRing' and 'oscillates' in detail['text'])
    for name in ['AND1', 'NOT1', 'NOT2', 'NOT3']:
        assert(name in detail['text']), detail['text']
    assert(detail['text'].index('NOT1') < detail['text'].index('NOT2') <
           detail['text'].index('NOT3'))
    assert(detail['fix'] != '')
    for index in detail['loop']:
        out = sim['prims'][index]['outNets']['out']
        assert(sim['nets'][out]['value'] == X)
    # It stays settled: another settle changes nothing
    settle(sim)
    assert(sim['waveCount'] <= 1)
    print('Passed!')

def testLatchRaceGoesX():
    print('Testing a latch race...', end='')
    library = newLibrary()
    tester = makeTester(library, buildSRLatch())
    assert(runTester(tester, {'S': 1, 'R': 1}) == {'Q': 0, 'Qn': 0})
    out = runTester(tester, {'S': 0, 'R': 0})
    assert(out == {'Q': X, 'Qn': X})
    assert(tester['sim']['loopDetail']['code'] == 'loopRace')
    # Stable at X, and a set still works afterwards
    assert(runTester(tester, {'S': 0, 'R': 0}) == {'Q': X, 'Qn': X})
    assert(runTester(tester, {'S': 1, 'R': 0}) == {'Q': 1, 'Qn': 0})
    print('Passed!')

def testHistoryKeepsLatchState():
    print('Testing that Back keeps a latch\'s state...', end='')
    library = newLibrary()
    circuit = buildSRLatch()
    # A clock and a register (holding its value), so phases run
    addPart(library, circuit, 'CLOCK', 0, 300)
    reg = addPart(library, circuit, 'REG', 100, 300, {'width': 1})
    zero = addPart(library, circuit, 'CONST', 0, 400)
    addWire(circuit, ['port', zero['id'], 'out'], ['port', reg['id'], 'we'])
    addWire(circuit, ['port', zero['id'], 'out'], ['port', reg['id'], 'd'])
    sim = flatten(library, circuit)
    qNet, qnNet = latchNets(sim, circuit)
    pins = {prim['params']['name']: prim for prim in sim['prims']
            if prim['type'] == 'PIN_IN'}
    seen = [None]
    for s, r in [(1, 0), (0, 0), (0, 0), (0, 1), (0, 0), (0, 0)]:
        for name, value in [('S', s), ('R', r)]:
            if pins[name]['state'] != value:
                pins[name]['state'] = value
                sim['seeds'].add(pins[name]['index'])
        # (as zb_main.editState does when a pin is clicked)
        sim['history'][sim['halfCycles']] = snapshot(sim)
        stepPhase(sim)
        seen.append(sim['nets'][qNet]['value'])
    assert(seen[1:] == [1, 1, 1, 0, 0, 0]), seen
    for step in [3, 1, 6, 2, 5]:
        goToStep(sim, step)
        assert(sim['nets'][qNet]['value'] == seen[step]), (step, seen)
    print('Passed!')

def testContainsStateLoop():
    print('Testing that a part with a latch inside remembers...', end='')
    from zb_library import containsState
    library = newLibrary()
    circuit = buildSRLatch()
    assert(containsState(library, circuit))
    assert(not containsState(library, RECIPES['FULLADD']({})))
    definition = makeUserPart(library, 'latch', circuit)
    assert(definition['stateful'])
    result = verifyPart(library, definition, 'HALFADD')
    assert(not result['ok'] and 'remembers' in result['message'])
    # A part holding it remembers too, and can't run fast
    outer = makeCircuit('outer')
    addPart(library, outer, 'latch', 0, 0)
    assert(containsState(library, outer))
    from zb_sim import isFast
    part = outer['parts'][0]
    part['mode'] = 'fast'
    definition['verified'] = True
    definition['implements'] = 'HALFADD'
    assert(not isFast(library, part, definition))
    print('Passed!')

######################################################################
# Round 2, M4: truth tables
######################################################################

def buildBrokenAdder():
    # A full adder whose cout is wrongly just a AND b
    circuit = RECIPES['FULLADD']({})
    pins = {p['params']['name']: p['id'] for p in circuit['parts']
            if p['type'] == 'PIN_OUT'}
    ands = [p['id'] for p in circuit['parts'] if p['type'] == 'AND']
    for wire in circuit['wires']:
        if wire['b'] == ['port', pins['cout'], 'in']:
            wire['a'] = ['port', ands[0], 'out']
            wire['via'] = []
    return circuit

def testTruthTableFullAdder():
    print('Testing the truth table of a full adder...', end='')
    from zb_library import truthTable, builtInExpected
    library = newLibrary()
    table = truthTable(library, RECIPES['FULLADD']({}))
    assert(table['exhaustive'] and len(table['rows']) == 8)
    assert([c['name'] for c in table['inputs']] == ['a', 'b', 'cin'])
    for n in range(8):
        row = table['rows'][n]
        a, b, cin = n >> 2, (n >> 1) & 1, n & 1
        assert(row['in'] == {'a': a, 'b': b, 'cin': cin})
        assert(row['got'] == {'s': (a + b + cin) & 1,
                              'cout': (a + b + cin) >> 1})
    table = truthTable(library, RECIPES['FULLADD']({}),
                       builtInExpected('FULLADD'))
    assert(table['hasExpected'])
    assert(all(row['wrong'] == [] for row in table['rows']))
    print('Passed!')

def testTruthTableOrderAndWidths():
    print('Testing truth table column and row order...', end='')
    from zb_library import truthTable
    library = newLibrary()
    circuit = makeCircuit('order')
    cin = addPart(library, circuit, 'PIN_IN', 0, 0, {'name': 'cin'})
    a = addPart(library, circuit, 'PIN_IN', 0, 40, {'name': 'a'})
    gate = addPart(library, circuit, 'AND', 100, 0)
    out = addPart(library, circuit, 'PIN_OUT', 200, 0, {'name': 'y'})
    addWire(circuit, ['port', cin['id'], 'out'], ['port', gate['id'],
                                                  'in0'])
    addWire(circuit, ['port', a['id'], 'out'], ['port', gate['id'], 'in1'])
    addWire(circuit, ['port', gate['id'], 'out'], ['port', out['id'], 'in'])
    table = truthTable(library, circuit)
    assert([c['name'] for c in table['inputs']] == ['cin', 'a'])
    table = truthTable(library, circuit, portOrder=['a', 'cin'])
    assert([c['name'] for c in table['inputs']] == ['a', 'cin'])
    assert(table['rows'][1]['in'] == {'a': 0, 'cin': 1})
    # A 2-bit pin counts 0..3 within the row order
    wide = makeCircuit('wide')
    x = addPart(library, wide, 'PIN_IN', 0, 0, {'name': 'x', 'width': 2})
    y = addPart(library, wide, 'PIN_IN', 0, 40, {'name': 'y'})
    merge = addPart(library, wide, 'MERGE', 100, 0, {'widths': [2, 1]})
    out = addPart(library, wide, 'PIN_OUT', 200, 0, {'name': 'v',
                                                     'width': 3})
    addWire(wide, ['port', x['id'], 'out'], ['port', merge['id'], 'in0'])
    addWire(wide, ['port', y['id'], 'out'], ['port', merge['id'], 'in1'])
    addWire(wide, ['port', merge['id'], 'out'], ['port', out['id'], 'in'])
    table = truthTable(library, wide)
    assert(len(table['rows']) == 8)
    for k in range(8):
        assert(table['rows'][k]['in'] == {'x': k >> 1, 'y': k & 1})
        assert(table['rows'][k]['got'] == {'v': k})
    print('Passed!')

def testTruthTableSample():
    print('Testing the sampled table of an 8-bit adder...', end='')
    from zb_library import truthTable, makeVectors, tableTitle
    library = newLibrary()
    table = truthTable(library, buildAdder8())
    assert(not table['exhaustive'] and table['total'] == 131072)
    ports = [{'name': n, 'dir': 'in', 'width': w}
             for n, w in [('a', 8), ('b', 8), ('cin', 1)]]
    assert(len(table['rows']) == len(makeVectors(ports)[0]))
    assert('131,072' in tableTitle(table))
    print('Passed!')

def testTruthTableExpected():
    print('Testing the expected column on a broken adder...', end='')
    from zb_library import truthTable, builtInExpected
    library = newLibrary()
    table = truthTable(library, buildBrokenAdder(),
                       builtInExpected('FULLADD'))
    wrong = []
    for row in table['rows']:
        if row['wrong']:
            assert(row['wrong'] == ['cout'])
            wrong.append(''.join(str(row['in'][n]) for n in
                                 ['a', 'b', 'cin']))
    assert(wrong == ['011', '101']), wrong
    print('Passed!')

def testTruthTableStateful():
    print('Testing that a latch gets no truth table...', end='')
    from zb_library import truthTable
    table = truthTable(newLibrary(), buildSRLatch())
    assert(table['stateful'] and table['rows'] == [])
    assert('NOR1' in table['reason'] and 'NOR2' in table['reason'])
    print('Passed!')

def testMissionDetailFailedRow():
    print('Testing that a failed mission points at a wrong row...', end='')
    import zb_missions
    library = newLibrary()
    mission = zb_missions.getMission('fulladd')
    detail = zb_missions.checkMissionDetail(library, mission,
                                            buildBrokenAdder())
    assert(not detail['ok'] and detail['table'] != None)
    row = detail['table']['rows'][detail['failedRow']]
    assert('cout' in row['wrong'])
    ok, message = zb_missions.checkMission(library, mission,
                                           buildBrokenAdder())
    assert(not ok and type(message) == str)
    assert(library['user'] == dict())
    print('Passed!')

def testEditorTableRow():
    print('Testing a table row put on the pins...', end='')
    folder = os.path.join(HERE, 'table_test_tmp')
    app = makeFakeApp(folder, RECIPES['FULLADD']({}))
    try:
        data, message = zb_editor.tableForView(app)
        assert(message == None and len(data['rows']) == 8)
        row = data['rows'][6]
        assert(row['in'] == {'a': 1, 'b': 1, 'cin': 0})
        # Run mode, as zb_main.enterRun sets it up
        app.mode = 'run'
        app.sim = flatten(app.library, app.root)
        zb_editor.refreshView(app)
        assert(zb_editor.setRootPins(app, row['in']) == 2)
        pins = zb_editor.rootPins(app)
        assert(pins['a']['state'] == 1 and pins['cin']['state'] == 0)
        outs = {p['params']['name']: p for p in app.root['parts']
                if p['type'] == 'PIN_OUT'}
        for name in ['s', 'cout']:
            value = app.sim['nets'][app.sim['nodeNet'][
                ('port', (outs[name]['id'],), 'in')]]['value']
            assert(value == row['got'][name]), (name, value)
        # A latch has no table, and says why
        app2 = makeFakeApp(folder, buildSRLatch())
        data, message = zb_editor.tableForView(app2)
        assert(data == None and 'remembers' in message)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

######################################################################
# Round 2, M5: messages that say what, where, why and how to fix it
######################################################################

def netOfPort(sim, part, portName):
    return sim['nodeNet'][('port', (part['id'],), portName)]

def testExplainZ():
    print('Testing why a wire floats...', end='')
    from zb_explain import explainValue
    library = newLibrary()
    circuit = makeCircuit()
    gate = addPart(library, circuit, 'NOT', 100, 0)
    sim = flatten(library, circuit)
    settle(sim)
    steps = explainValue(sim, netOfPort(sim, gate, 'in'))
    assert('nothing is wired' in steps[-1]['text'])
    # A bus whose only TG is off
    circuit = makeCircuit()
    value = addPart(library, circuit, 'CONST', 0, 0, {'value': 1})
    en = addPart(library, circuit, 'PIN_IN', 0, 60, {'name': 'en'})
    tg = addPart(library, circuit, 'TG', 100, 0, {'width': 1})
    probe = addPart(library, circuit, 'PROBE', 200, 0, {'width': 1})
    addWire(circuit, ['port', value['id'], 'out'], ['port', tg['id'], 'in'])
    addWire(circuit, ['port', en['id'], 'out'], ['port', tg['id'], 'en'])
    addWire(circuit, ['port', tg['id'], 'out'], ['port', probe['id'], 'in'])
    sim = flatten(library, circuit)
    settle(sim)
    text = explainValue(sim, netOfPort(sim, probe, 'in'))[0]['text']
    assert('TG1' in text and 'en = 0' in text and 'pin en' in text), text
    print('Passed!')

def testExplainX():
    print('Testing where an x comes from...', end='')
    from zb_explain import explainValue
    library = newLibrary()
    circuit = makeCircuit()
    ram = addPart(library, circuit, 'RAM', 0, 0)
    addr = addPart(library, circuit, 'CONST', 300, 400, {'value': 5,
                                                        'width': 4})
    one = addPart(library, circuit, 'CONST', 0, 400, {'value': 1})
    reg = addPart(library, circuit, 'REG', 300, 0)
    addWire(circuit, ['port', addr['id'], 'out'], ['port', ram['id'],
                                                   'addr'])
    addWire(circuit, ['port', one['id'], 'out'], ['port', ram['id'], 're'])
    addWire(circuit, ['port', ram['id'], 'dout'], ['port', reg['id'], 'd'])
    sim = flatten(library, circuit)
    settle(sim)
    steps = explainValue(sim, netOfPort(sim, reg, 'd'))
    assert('M[5] was never set' in steps[-1]['text']), steps
    # A gate with one floating input
    circuit = makeCircuit()
    pin = addPart(library, circuit, 'PIN_IN', 0, 0, {'name': 'a'})
    gate = addPart(library, circuit, 'AND', 100, 0)
    addWire(circuit, ['port', pin['id'], 'out'], ['port', gate['id'],
                                                  'in0'])
    tester = makeTester(library, circuit)
    runTester(tester, {'a': 1})
    sim = tester['sim']
    steps = explainValue(sim, netOfPort(sim, gate, 'out'))
    assert('AND1.in1 is not connected' in steps[-1]['text']), steps
    print('Passed!')

def testExplainOutputCone():
    print('Testing the logic behind a wrong output...', end='')
    from zb_explain import explainOutput
    library = newLibrary()
    circuit = buildBrokenAdder()
    tester = makeTester(library, circuit)
    runTester(tester, {'a': 0, 'b': 1, 'cin': 1})
    sim = tester['sim']
    lines, cone = explainOutput(sim, tester['outputs']['cout'])
    assert(lines[0].startswith('cout = 0 comes from AND1')), lines
    assert(any('pin b' in line for line in lines))
    types = {sim['prims'][i]['type'] for i in cone['prims']}
    assert('AND' in types and 'XOR' not in types and 'OR' not in types)
    print('Passed!')

def problemWith(problems, code):
    found = [p for p in problems if p.get('code') == code]
    assert(len(found) > 0), (code, problems)
    return found[0]

def testMessageCatalog():
    print('Testing the message catalog...', end='')
    library = newLibrary()
    def joined(fromType, fromParams, toType, toParams, toPort='in'):
        circuit = makeCircuit()
        a = addPart(library, circuit, fromType, 0, 0, fromParams)
        b = addPart(library, circuit, toType, 100, 0, toParams)
        addWire(circuit, ['port', a['id'], 'out'], ['port', b['id'],
                                                    toPort])
        return circuit
    # width: the one part that fits
    problem = problemWith(validate(library, joined(
        'CONST', {'width': 4}, 'NOT', {'width': 8})), 'width')
    assert('4 bits' in problem['text'] and 'EXTEND' in problem['text'])
    assert(problem['fix'] != '')
    problem = problemWith(validate(library, joined(
        'CONST', {'width': 8}, 'NOT', {'width': 4})), 'width')
    assert('SPLIT' in problem['text'] and '3:0' in problem['text'])
    problem = problemWith(validate(library, joined(
        'CONST', {'width': 1}, 'NOT', {'width': 8})), 'width')
    assert('repeat' in problem['text'])
    # twoDrivers
    circuit = makeCircuit()
    c1 = addPart(library, circuit, 'CONST', 0, 0)
    c2 = addPart(library, circuit, 'CONST', 0, 60)
    addWire(circuit, ['port', c1['id'], 'out'], ['port', c2['id'], 'out'])
    problem = problemWith(validate(library, circuit), 'twoDrivers')
    assert('TG' in problem['fix'])
    # floating
    circuit = makeCircuit()
    addPart(library, circuit, 'AND', 0, 0, label='AND1')
    problem = problemWith(validate(library, circuit), 'floating')
    assert('AND1' in problem['text'] and 'another input is 0' in
           problem['why'][0] and 'CONST 0' in problem['fix'])
    # contention
    circuit = makeCircuit()
    tgs = []
    for i in range(2):
        value = addPart(library, circuit, 'CONST', 0, 100 * i,
                        {'value': i})
        on = addPart(library, circuit, 'CONST', 0, 100 * i + 40,
                     {'value': 1})
        tg = addPart(library, circuit, 'TG', 100, 100 * i, {'width': 1})
        addWire(circuit, ['port', value['id'], 'out'], ['port', tg['id'],
                                                        'in'])
        addWire(circuit, ['port', on['id'], 'out'], ['port', tg['id'], 'en'])
        tgs.append(tg)
    addWire(circuit, ['port', tgs[0]['id'], 'out'], ['port', tgs[1]['id'],
                                                      'out'])
    sim = flatten(library, circuit)
    beginPhase(sim)
    detail = sim['stopDetail']
    assert(detail['code'] == 'contention')
    assert('TG1' in detail['text'] and 'TG2' in detail['text'])
    assert(len(detail['why']) == 2 and 'en = 1' in detail['why'][0])
    assert(detail['fix'] != '')
    # loadsUnknown: a register loading a word that was never set
    circuit = makeCircuit()
    ram = addPart(library, circuit, 'RAM', 0, 0)
    addr = addPart(library, circuit, 'CONST', 300, 400, {'value': 5,
                                                        'width': 4})
    one = addPart(library, circuit, 'CONST', 0, 400, {'value': 1})
    zero = addPart(library, circuit, 'CONST', 0, 450, {'value': 0})
    reg = addPart(library, circuit, 'REG', 300, 0, label='R2')
    addWire(circuit, ['port', addr['id'], 'out'], ['port', ram['id'],
                                                   'addr'])
    addWire(circuit, ['port', one['id'], 'out'], ['port', ram['id'], 're'])
    addWire(circuit, ['port', zero['id'], 'out'], ['port', ram['id'], 'we'])
    addWire(circuit, ['port', one['id'], 'out'], ['port', reg['id'], 'we'])
    addWire(circuit, ['port', ram['id'], 'dout'], ['port', reg['id'], 'd'])
    sim = flatten(library, circuit)
    beginPhase(sim)
    detail = sim['stopDetail']
    assert(detail['code'] == 'loadsUnknown')
    assert('R2 would load xxxxxxxx' in detail['text'])
    assert('phase 1' in detail['text'])
    assert(any('M[5] was never set' in line for line in detail['why']))
    assert('M[5]' in detail['fix'])
    # loopRing and loopRace
    tester = makeTester(library, buildSRLatch())
    runTester(tester, {'S': 1, 'R': 1})
    runTester(tester, {'S': 0, 'R': 0})
    assert(tester['sim']['loopDetail']['code'] == 'loopRace')
    assert('one input at a time' in tester['sim']['loopDetail']['fix'])
    ring = makeCircuit()
    gates = [addPart(library, ring, 'NOT', 100 * i, 0) for i in range(3)]
    pin = addPart(library, ring, 'PIN_IN', 0, 100, {'name': 'go'})
    gate = addPart(library, ring, 'AND', 0, 0)
    addWire(ring, ['port', pin['id'], 'out'], ['port', gate['id'], 'in0'])
    addWire(ring, ['port', gate['id'], 'out'], ['port', gates[0]['id'],
                                                 'in'])
    addWire(ring, ['port', gates[0]['id'], 'out'], ['port', gate['id'],
                                                     'in1'])
    tester = makeTester(library, ring)
    runTester(tester, {'go': 0})
    runTester(tester, {'go': 1})
    assert(tester['sim']['loopDetail']['code'] == 'loopRing')
    # pins
    wrong = makeUserPart(library, 'wrong pins', buildSRLatch())
    wrong['stateful'] = False                # (only the pins are checked)
    result = verifyPart(library, wrong, 'FULLADD')
    assert(result['code'] == 'pins' and 'Missing' in result['message'])
    # notAllowed
    import zb_missions
    circuit = zb_missions.startCircuit(zb_missions.getMission('fulladd'))
    addPart(library, circuit, 'FULLADD', 200, 0, label='FA1')
    detail = zb_missions.checkMissionDetail(
        library, zb_missions.getMission('fulladd'), circuit)
    problem = detail['problem']
    assert(problem['code'] == 'notAllowed')
    assert('full adder' in problem['text'] and "'FA1'" in problem['text'])
    assert('Allowed here: NOT' in problem['text'] and problem['parts'])
    # unknownType
    circuit = makeCircuit()
    addPart(library, circuit, 'My ALU', 0, 0)
    problem = problemWith(validate(library, circuit), 'unknownType')
    assert("'My ALU'" in problem['text'] and 'parts/My_ALU.json' in
           problem['text'])
    # verifyStateful
    latch = makeUserPart(library, 'a latch', buildSRLatch())
    result = verifyPart(library, latch, 'HALFADD')
    assert(result['code'] == 'verifyStateful')
    assert('step table' in result['message'])
    # param
    circuit = makeCircuit()
    addPart(library, circuit, 'SPLIT', 0, 0, {'width': 4,
                                              'ranges': [[7, 4]]})
    problem = problemWith(validate(library, circuit), 'param')
    assert('[7:4]' in problem['text'])
    print('Passed!')

def testGoldenMessageNamesInstruction():
    print('Testing the lecture-check message...', end='')
    import zb_missions
    library = newLibrary()
    circuit = makeReferenceMachine()
    r2 = [p for p in circuit['parts'] if p['label'] == 'R2'][0]
    zero = addPart(library, circuit, 'CONST', 600, 160, {'value': 0})
    for wire in circuit['wires']:
        if wire['b'] == ['port', r2['id'], 'we']:
            wire['a'] = ['port', zero['id'], 'out']
            wire['via'] = []
    ok, message = zb_missions.checkMission(
        library, zb_missions.getMission('loads'), circuit)
    assert(not ok)
    assert('m_loads.z18' in message and 'execute' in message)
    assert('LOAD R2' in message and 'WE was 0' in message), message
    assert("lecture's" in message and 'decoder output 2' in message)
    print('Passed!')

def testPinDiffMessage():
    print('Testing the pin diff message...', end='')
    from zb_library import pinsDiff
    mine = [{'name': 'a', 'dir': 'in', 'width': 4},
            {'name': 'carry', 'dir': 'out', 'width': 1}]
    wanted = PRIMITIVES['FULLADD']['layout']({})[2]
    message = pinsDiff(mine, wanted)
    assert('Wrong width: IN a is 4 bits, should be 1' in message), message
    assert('OUT cout (1 bit)' in message.split('Extra')[0])
    assert('Extra: OUT carry (1 bit), did you mean cout?' in message)
    assert(pinsDiff(wanted, wanted) == None)
    print('Passed!')

######################################################################
# Round 2, M6: the Memory missions
######################################################################

def renamePin(circuit, old, new):
    for part in circuit['parts']:
        if part['type'] in ['PIN_IN', 'PIN_OUT'] and \
                part['params']['name'] == old:
            part['params']['name'] = new
    return circuit

def sequenceSolution(missionId):
    return {'srlatch': buildSRLatch,
            'dlatch': buildDLatch,
            'dff': buildDff,
            'register': buildRegister8}[missionId]()

def testDffMasterSlave():
    print('Testing the master-slave flip-flop step by step...', end='')
    import zb_missions
    library = newLibrary()
    mission = zb_missions.getMission('dff')
    table = zb_missions.stepTable(library, mission, buildDff())
    for row in table['rows']:
        assert(row['wrong'] == []), row
    held = [row for row in table['rows'] if 'while clk = 1' in row['note']]
    assert(len(held) == 1 and held[0]['got']['Q'] == 1)
    print('Passed!')

def testSequenceMissions():
    print('Testing the Memory missions...', end='')
    import zb_missions
    library = newLibrary()
    folder = os.path.join(HERE, 'memory_test_tmp')
    try:
        for mission in zb_missions.MISSIONS:
            if mission['kind'] != 'sequence':
                continue
            assert(mission['group'] == 'Memory')
            start = zb_missions.startCircuit(mission)
            ok, message = zb_missions.checkMission(library, mission, start)
            assert(not ok), mission['id']
            solution = sequenceSolution(mission['id'])
            detail = zb_missions.checkMissionDetail(library, mission,
                                                    solution)
            assert(detail['ok']), (mission['id'], detail['message'])
            assert(detail['table']['kind'] == 'steps')
            name = zb_missions.rewardPart(library, mission, solution,
                                          folder)
            definition = library['user'][name]
            assert(definition['verified'] and definition['stateful'])
            assert(definition['checkedBy'] == 'sequence')
            reloaded = newLibrary()
            assert(loadUserParts(reloaded, folder) == [])
            again = reloaded['user'][name]
            assert(again['verified'] and again['checkedBy'] == 'sequence')
            from zb_sim import isFast
            part = addPart(reloaded, makeCircuit(), name, 0, 0)
            part['mode'] = 'fast'
            assert(not isFast(reloaded, part, again))   # detailed only
        # The numbers: parts 1-5, memory 6-9, then the machine
        numbers = {m['id']: m['number'] for m in zb_missions.MISSIONS}
        assert(numbers['mux4'] == 5 and numbers['srlatch'] == 6)
        assert(numbers['register'] == 9 and numbers['fetch'] == 10)
        # A machine mission still works with its new number
        assert(zb_missions.getMission('jump')['number'] == 14)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testDLatchFailsDffMission():
    print('Testing that a D latch is not a flip-flop...', end='')
    import zb_missions
    library = newLibrary()
    latch = renamePin(buildDLatch(), 'E', 'clk')
    detail = zb_missions.checkMissionDetail(
        library, zb_missions.getMission('dff'), latch)
    assert(not detail['ok'])
    row = detail['table']['rows'][detail['failedStep']]
    assert('while clk = 1' in row['note'])
    assert('D changes while clk = 1' in detail['message'])
    assert('should stay 1 but is 0' in detail['message']), detail['message']
    print('Passed!')

######################################################################
# Round 2, M7: wires you can read
######################################################################

def buildFullAdder(layout='clean'):
    # A hand-wired full adder. 'clean' has crossings but nothing that
    # misleads; 'messy' (like the screenshot in PLAN.md §18.1) also runs
    # cin along b's wire and under the first XOR.
    from zb_kit import newBuild, put, putPin, link
    b = newBuild('Full adder')
    putPin(b, 'a', 'in', 'a', 1, 0, 20)
    putPin(b, 'b', 'in', 'b', 1, 0, 80)
    putPin(b, 'cin', 'in', 'cin', 1, 0, 260)
    put(b, 'x1', 'XOR', 200, 20)
    put(b, 'x2', 'XOR', 330, 40)
    put(b, 'a1', 'AND', 330, 140)
    put(b, 'a2', 'AND', 330, 220)
    put(b, 'or', 'OR', 450, 180)
    putPin(b, 's', 'out', 's', 1, 560, 50)
    putPin(b, 'cout', 'out', 'cout', 1, 560, 190)
    link(b, 'a.out', 'x1.in0')
    link(b, 'a.out', 'a1.in0', [(100, 30), (100, 150)])
    link(b, 'b.out', 'x1.in1', [(120, 90), (120, 50)])
    link(b, 'b.out', 'a1.in1', [(120, 90), (120, 170)])
    link(b, 'x1.out', 'x2.in0', [(290, 40), (290, 50)])
    link(b, 'x1.out', 'a2.in1', [(290, 40), (290, 250)])
    if layout == 'messy':
        link(b, 'cin.out', 'x2.in1', [(150, 270), (150, 50), (310, 50),
                                      (310, 70)])
    else:
        link(b, 'cin.out', 'x2.in1', [(310, 270), (310, 70)])
    link(b, 'cin.out', 'a2.in0', [(310, 270), (310, 230)])
    link(b, 'a1.out', 'or.in0', [(420, 160), (420, 190)])
    link(b, 'a2.out', 'or.in1', [(420, 240), (420, 210)])
    link(b, 'x2.out', 's.in')
    link(b, 'or.out', 'cout.in')
    return b['circuit']

def testWireGeometry():
    print('Testing crossings, overlaps and branch points...', end='')
    from zb_circuit import wireGeometry
    library = newLibrary()
    # A plus: two nets crossing
    circuit = makeCircuit()
    c1 = addPart(library, circuit, 'CONST', 0, 100)
    n1 = addPart(library, circuit, 'NOT', 200, 100)
    c2 = addPart(library, circuit, 'CONST', 90, 0)
    n2 = addPart(library, circuit, 'NOT', 200, 200)
    addWire(circuit, ['port', c1['id'], 'out'], ['port', n1['id'], 'in'])
    addWire(circuit, ['port', c2['id'], 'out'], ['port', n2['id'], 'in'],
            [(150, 10), (150, 210)])
    geom = wireGeometry(library, circuit)
    assert(len(geom['crossings']) == 1 and geom['overlaps'] == [])
    assert(geom['crossings'][0][:2] == (150, 110))
    # One net sharing a stretch, then splitting: a branch point
    circuit = makeCircuit()
    c1 = addPart(library, circuit, 'CONST', 0, 0)
    n1 = addPart(library, circuit, 'NOT', 200, 0)
    n2 = addPart(library, circuit, 'NOT', 200, 70)
    addWire(circuit, ['port', c1['id'], 'out'], ['port', n1['id'], 'in'])
    addWire(circuit, ['port', c1['id'], 'out'], ['port', n2['id'], 'in'],
            [(100, 10), (100, 80)])
    geom = wireGeometry(library, circuit)
    assert(geom['overlaps'] == [] and len(geom['branches']) == 1)
    assert(geom['branches'][0][:2] == (100, 10))
    # A corner of one net lying on another net's wire
    circuit = makeCircuit()
    c1 = addPart(library, circuit, 'CONST', 0, 100)
    n1 = addPart(library, circuit, 'NOT', 200, 100)
    c2 = addPart(library, circuit, 'CONST', 0, 0)
    n2 = addPart(library, circuit, 'NOT', 200, 200)
    addWire(circuit, ['port', c1['id'], 'out'], ['port', n1['id'], 'in'])
    addWire(circuit, ['port', c2['id'], 'out'], ['port', n2['id'], 'in'],
            [(80, 10), (80, 110), (120, 110), (120, 210)])
    geom = wireGeometry(library, circuit)
    assert(len(geom['overlaps']) >= 1)
    print('Passed!')

def testOverlapWarnings():
    print('Testing the warnings for misleading wires...', end='')
    library = newLibrary()
    from zb_circuit import wireGeometry, layoutProblems
    problems = layoutProblems(library, buildFullAdder('messy'),
                              wireGeometry(library,
                                           buildFullAdder('messy')))
    codes = [p['code'] for p in problems]
    assert('overlap' in codes and 'underPart' in codes), codes
    overlap = problemWith(problems, 'overlap')
    assert('pin b' in overlap['text'] and 'pin cin' in overlap['text'])
    assert(len(overlap['wires']) == 2)
    under = problemWith(problems, 'underPart')
    assert('XOR' in under['text'])
    clean = buildFullAdder('clean')
    assert(layoutProblems(library, clean, wireGeometry(library, clean))
           == [])
    # Both still work, and are warnings only
    from zb_library import truthTable, builtInExpected
    for circuit in [clean, buildFullAdder('messy')]:
        table = truthTable(library, circuit, builtInExpected('FULLADD'))
        assert(all(row['wrong'] == [] for row in table['rows']))
    print('Passed!')

def testGeometrySpeed():
    print('Testing how fast wire geometry is worked out...', end='')
    from zb_circuit import wireSegments, findCrossings, findOverlaps
    library = newLibrary()
    circuit = makeReferenceMachine()
    segments = wireSegments(library, circuit)
    start = time.perf_counter()
    crossings = findCrossings(segments)
    overlaps = findOverlaps(segments)
    elapsed = time.perf_counter() - start
    assert(elapsed < 0.05), elapsed
    print(f'Passed! ({1000 * elapsed:.1f} ms, {len(crossings)} crossings)')

######################################################################
# Round 2, M8: the router and Tidy wires
######################################################################

def routePoints(library, circuit, a, b, via):
    from zb_circuit import endPosition
    return ([endPosition(library, circuit, a)] + [tuple(p) for p in via] +
            [endPosition(library, circuit, b)])

def testRouterBasics():
    print('Testing the router on simple cases...', end='')
    from zb_route import routeWire
    library = newLibrary()
    circuit = makeCircuit()
    c1 = addPart(library, circuit, 'CONST', 0, 0)
    n1 = addPart(library, circuit, 'NOT', 200, 0)
    a, b = ['port', c1['id'], 'out'], ['port', n1['id'], 'in']
    assert(routeWire(library, circuit, a, b) == [])     # straight across
    n2 = addPart(library, circuit, 'NOT', 200, 130)
    b = ['port', n2['id'], 'in']
    via = routeWire(library, circuit, a, b)
    assert(via != None and len(via) in [1, 2])
    points = routePoints(library, circuit, a, b, via)
    for i in range(len(points) - 1):
        (x1, y1), (x2, y2) = points[i], points[i + 1]
        assert(x1 == x2 or y1 == y2), points
    assert(points[1][1] == points[0][1] and points[1][0] > points[0][0])
    assert(points[-2][1] == points[-1][1] and points[-2][0] < points[-1][0])
    assert(routeWire(library, circuit, a, b) == via)    # the same again
    print('Passed!')

def testRouterAvoidsParts():
    print('Testing that routes go around parts and other nets...', end='')
    from zb_route import routeWire
    from zb_circuit import wireGeometry
    library = newLibrary()
    circuit = makeCircuit()
    c1 = addPart(library, circuit, 'CONST', 0, 100)
    n1 = addPart(library, circuit, 'NOT', 400, 100)
    block = addPart(library, circuit, 'REG', 180, 80)     # in the way
    c2 = addPart(library, circuit, 'CONST', 0, 200)
    n2 = addPart(library, circuit, 'NOT', 400, 40)
    # another net running where a lazy route would go
    addWire(circuit, ['port', c2['id'], 'out'], ['port', n2['id'], 'in'],
            [(100, 210), (100, 50)])
    a, b = ['port', c1['id'], 'out'], ['port', n1['id'], 'in']
    via = routeWire(library, circuit, a, b)
    assert(via != None and len(via) > 0)
    addWire(circuit, a, b, via)
    geom = wireGeometry(library, circuit)
    assert(geom['under'] == []), geom['under']
    assert(geom['overlaps'] == []), geom['overlaps']
    print('Passed!')

def testTidyKeepsCircuit():
    print('Testing that Tidy wires changes only the geometry...', end='')
    from zb_route import tidyWires
    from zb_circuit import wireGeometry
    from zb_library import truthTable, builtInExpected
    library = newLibrary()
    circuit = buildFullAdder('messy')
    nets = computeNets(library, circuit)['nodeNet']
    before = wireGeometry(library, circuit)
    table = truthTable(library, circuit)['rows']
    rerouted, failed = tidyWires(library, circuit,
                                 [w['id'] for w in circuit['wires']])
    assert(rerouted > 0 and failed == 0)
    assert(computeNets(library, circuit)['nodeNet'] == nets)
    assert(truthTable(library, circuit)['rows'] == table)
    after = wireGeometry(library, circuit)
    assert(after['overlaps'] == [] and after['under'] == [])
    assert(len(after['crossings']) <= len(before['crossings']))
    print('Passed!')

def testScreenshotAdderTidy():
    print('Testing w w on the messy adder, and one undo...', end='')
    folder = os.path.join(HERE, 'tidy_test_tmp')
    app = makeFakeApp(folder, buildFullAdder('messy'))
    try:
        before = circuitToText(app.root)
        assert(any(p['code'] == 'overlap' for p in app.problems))
        zb_editor.tidy(app, 100.0)
        assert('again' in app.message)               # asks first
        assert(circuitToText(app.root) == before)
        zb_editor.tidy(app, 101.0)
        assert(app.message.startswith('Tidied'))
        assert(not any(p['code'] in ['overlap', 'underPart']
                       for p in app.problems))
        zb_editor.undo(app)
        assert(circuitToText(app.root) == before)
        # Too slow a second press only asks again
        zb_editor.tidy(app, 200.0)
        zb_editor.tidy(app, 205.0)
        assert('again' in app.message)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testReferenceLayoutClean():
    print('Testing that the lecture machine\'s wires are clean...', end='')
    from zb_circuit import wireGeometry, layoutProblems, loadCircuit
    library = newLibrary()
    circuit = makeReferenceMachine()
    problems = layoutProblems(library, circuit,
                              wireGeometry(library, circuit))
    assert(problems == []), [p['text'] for p in problems]
    shipped = loadCircuit(os.path.join(HERE, 'circuits',
                                       'z18100_reference.json'))
    assert(circuitToText(shipped) == circuitToText(circuit))
    print('Passed!')

def testEditorTidyUndo():
    print('Testing routed new wires and hand-bent wires...', end='')
    folder = os.path.join(HERE, 'tidy_test_tmp')
    app = makeFakeApp(folder)
    try:
        pin = placeFake(app, 'PIN_IN', 0, 0)
        block = placeFake(app, 'REG', 160, 0)
        out = placeFake(app, 'PIN_OUT', 340, 0)
        # A new wire without bends goes around the register
        wireFake(app, pin, 'out', out, 'in')
        wire = app.root['wires'][0]
        assert(len(wire['via']) > 0)
        from zb_circuit import wireGeometry
        assert(wireGeometry(app.library, app.root)['under'] == [])
        # A hand-bent wire keeps its bends when its part moves
        pin2 = placeFake(app, 'PIN_IN', 0, 200)
        out2 = placeFake(app, 'PIN_OUT', 340, 260)
        zb_editor.startWire(app, ['port', pin2['id'], 'out'])
        zb_editor.addBend(app, *screenOf(app, 200, 300))
        zb_editor.finishWire(app, portHit(out2, 'in'))
        bent = [w for w in app.root['wires']
                if w['a'] == ['port', pin2['id'], 'out']][0]
        bends = [list(p) for p in bent['via']]
        app.selection = {'parts': {pin2['id']}, 'wires': set(),
                         'junctions': set()}
        zb_editor.startMove(app, *screenOf(app, 10, 210))
        zb_editor.dragMove(app, *screenOf(app, 10, 190))
        zb_editor.endDrag(app)
        bent = [w for w in app.root['wires'] if w['id'] == bent['id']][0]
        assert(bent['via'][1:] == bends[1:])         # only the first moved
        # ... until w with the wire selected
        app.selection = {'parts': set(), 'wires': {bent['id']},
                         'junctions': set()}
        zb_editor.tidy(app, 0.0)
        bent = [w for w in app.root['wires'] if w['id'] == bent['id']][0]
        assert(bent['via'] != bends)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testRouterSpeed():
    print('Testing how fast the router is...', end='')
    from zb_route import routeWire, tidyWires
    library = newLibrary()
    circuit = makeReferenceMachine()
    times = []
    for wire in circuit['wires'][:20]:
        start = time.perf_counter()
        routeWire(library, circuit, wire['a'], wire['b'],
                  ignoreWires=[wire['id']])
        times.append(time.perf_counter() - start)
    start = time.perf_counter()
    tidyWires(library, circuit, [w['id'] for w in circuit['wires']])
    total = time.perf_counter() - start
    assert(max(times) < 0.5 and total < 10), (max(times), total)
    times.sort()
    print(f'Passed! (one wire: median {1000 * times[10]:.0f} ms, worst '
          f'{1000 * times[-1]:.0f} ms; every wire: {total:.1f} s)')

######################################################################
# Round 3
######################################################################

def testBusWiring():
    print('Testing bit-by-bit wiring through SPLIT and MERGE...', end='')
    folder = os.path.join(HERE, 'bus_test_tmp')
    app = makeFakeApp(folder)
    try:
        a = placeFake(app, 'PIN_IN', 0, 0)
        zb_editor.setParam(app, findPart(app.root, a['id']), 'width', '8')
        s = placeFake(app, 'PIN_OUT', 500, 0)
        zb_editor.setParam(app, findPart(app.root, s['id']), 'width', '8')
        gates = [placeFake(app, 'NOT', 250, 60 * i) for i in range(8)]
        # An 8-bit output dragged to a 1-bit input: a SPLIT appears
        zb_editor.startWire(app, ['port', a['id'], 'out'])
        zb_editor.finishWire(app, portHit(gates[0], 'in'))
        assert(app.tool == 'bus' and app.bus['kind'] == 'split')
        assert(app.bus['next'] == 1)
        splits = [p for p in app.root['parts'] if p['type'] == 'SPLIT']
        assert(len(splits) == 1)
        # Bits 1..7 one click each; a digit can pick the bit
        zb_editor.pickBusBit(app, 7)
        zb_editor.busConnect(app, ['port', gates[7]['id'], 'in'])
        assert(app.bus['next'] == 1)
        for gate in gates[1:7]:
            zb_editor.busConnect(app, ['port', gate['id'], 'in'])
        assert(app.tool == None and 'All 8 bits' in app.message)
        # A 1-bit output dragged to an 8-bit input: a MERGE, from the
        # 8-bit end this time
        s = findPart(app.root, s['id'])
        zb_editor.startWire(app, ['port', s['id'], 'in'])
        zb_editor.finishWire(app, portHit(gates[0], 'out'))
        assert(app.bus['kind'] == 'merge')
        for gate in gates[1:]:
            zb_editor.busConnect(app, ['port', gate['id'], 'out'])
        assert(app.tool == None)
        assert([p for p in app.problems if p['level'] == 'error'] == [])
        for value in [0x5A, 0x01, 0x80]:
            assert(settleRoot(app, {'in0': value}) == {'out0': 0xFF ^ value})
        # A wrong click doesn't wire anything; Esc-like cancel ends it
        zb_editor.startWire(app, ['port', a['id'], 'out'])
        extra = placeFake(app, 'NOT', 250, 600)
        wires = len(app.root['wires'])
        zb_editor.startWire(app, ['port', a['id'], 'out'])
        zb_editor.finishWire(app, portHit(findPart(app.root, extra['id']),
                                          'in'))
        assert('wired already' in app.message)       # every bit is used
        assert(len(app.root['wires']) == wires and app.tool == None)
        # One undo takes back one bit (after the extra NOT goes)
        count = len(app.root['wires'])
        zb_editor.undo(app)
        assert(len(app.root['wires']) == count)
        zb_editor.undo(app)
        assert(len(app.root['wires']) == count - 1)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testUserPartLayout():
    print('Testing the size and port sides of your parts...', end='')
    import zb_missions
    folder = os.path.join(HERE, 'layout_test_tmp')
    app = makeFakeApp(folder)
    try:
        zb_editor.PARTS_DIR = os.path.join(folder, 'parts')
        name = zb_missions.rewardPart(app.library,
                                      zb_missions.getMission('fulladd'),
                                      RECIPES['FULLADD']({}),
                                      zb_editor.PARTS_DIR)
        part = placeFake(app, name, 200, 200)
        definition = app.library['user'][name]
        # A box, not the built-in's 40 x 40
        width, height, ports = partLayout(app.library, part)
        assert(width >= 80 and height >= 80), (width, height)
        assert(definition['verified'])
        (now, smallest) = zb_editor.partBoxSize(app, definition)
        zb_editor.setPartSize(app, definition, 160, 120)
        assert(partLayout(app.library, part)[:2] == (160, 120))
        zb_editor.setPartSize(app, definition, 10, 10)   # never too small
        assert(partLayout(app.library, part)[:2] == smallest)
        zb_editor.growPart(app, definition, 20, 0)
        assert(partLayout(app.library, part)[0] == smallest[0] + 20)
        assert(zb_editor.parseSize('140 x 100') == (140, 100))
        assert(zb_editor.parseSize('auto') == (None, None))
        # cin to the top, then first on the left: a
        zb_editor.cyclePortSide(app, definition, 'cin')
        where = {p['name']: (p['dx'], p['dy'])
                 for p in partLayout(app.library, part)[2]}
        assert(where['cin'][1] == 0)                  # on the top edge
        zb_editor.movePortEarlier(app, definition, 'b')
        rows = zb_editor.userPortRows(app, definition)
        left = [r[0] for r in rows if r[1] == 'left']
        assert(left == ['b', 'a']), rows
        assert(definition['verified'])                # layout only
        # Saved and loaded with the part; undo puts the size back
        from zb_library import loadUserParts
        other = newLibrary()
        assert(loadUserParts(other, zb_editor.PARTS_DIR) == [])
        assert(other['user'][name]['size'] == definition['size'])
        before = list(definition['size'])
        zb_editor.growPart(app, definition, 0, 20)
        zb_editor.undo(app)
        assert(app.library['user'][name]['size'] == before)
        # Every port still works: it is the same full adder
        tester = makeTester(app.library, definition['circuit'])
        assert(runTester(tester, {'a': 1, 'b': 1, 'cin': 1}) ==
               {'s': 1, 'cout': 1})
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testRenamePort():
    print('Testing renaming a port of your part...', end='')
    import zb_missions
    folder = os.path.join(HERE, 'rename_test_tmp')
    app = makeFakeApp(folder)
    try:
        zb_editor.PARTS_DIR = os.path.join(folder, 'parts')
        name = zb_missions.rewardPart(app.library,
                                      zb_missions.getMission('fulladd'),
                                      RECIPES['FULLADD']({}),
                                      zb_editor.PARTS_DIR)
        adder = placeFake(app, name, 200, 200)
        pin = placeFake(app, 'PIN_IN', 0, 200)
        wireFake(app, pin, 'out', adder, 'a')
        definition = app.library['user'][name]
        zb_editor.renamePort(app, definition, 'a', ' x ')
        names = [p['name'] for p in partLayout(app.library, adder)[2]]
        assert('x' in names and 'a' not in names), names
        ends = [w['b'] if w['b'][1] == adder['id'] else w['a']
                for w in app.root['wires']]
        assert(ends == [['port', adder['id'], 'x']]), ends
        assert(not definition['verified'])
        # Bad names change nothing
        for bad in ['', 'b', 'two words', 'waytoolongname']:
            zb_editor.renamePort(app, definition, 'x', bad)
            assert(zb_editor.portPin(definition, 'x') != None), bad
        # Undo puts the old name and its wire back
        zb_editor.undo(app)
        definition = app.library['user'][name]
        assert(zb_editor.portPin(definition, 'a') != None)
        assert(any(end == ['port', adder['id'], 'a'] for w in
                   app.root['wires'] for end in [w['a'], w['b']]))
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testParamSteppers():
    print('Testing the - / + buttons and choices...', end='')
    folder = os.path.join(HERE, 'stepper_test_tmp')
    app = makeFakeApp(folder)
    try:
        gate = placeFake(app, 'AND', 0, 0)
        for i in range(10):
            zb_editor.stepParam(app, findPart(app.root, gate['id']),
                                'inputs', +1)
        gate = findPart(app.root, gate['id'])
        assert(gate['params']['inputs'] == 8)
        assert(zb_editor.stepParam(app, gate, 'inputs', +1) != None)
        zb_editor.stepParam(app, gate, 'inputs', -1)
        assert(findPart(app.root, gate['id'])['params']['inputs'] == 7)
        ext = placeFake(app, 'EXTEND', 0, 200)
        zb_editor.cycleParam(app, ext, 'mode')
        assert(findPart(app.root, ext['id'])['params']['mode'] == 'repeat')
        # A SPLIT made narrower keeps ranges that still fit
        split = placeFake(app, 'SPLIT', 0, 300)
        assert(zb_editor.setParam(app, split, 'width', '4') == None)
        split = findPart(app.root, split['id'])
        assert(split['params']['ranges'] == [[3, 0]])
        const = placeFake(app, 'CONST', 0, 400)
        zb_editor.stepParam(app, const, 'value', -1)    # wraps round
        assert(findPart(app.root, const['id'])['params']['value'] == 1)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testVerifyChoices():
    print('Testing the list of built-ins to verify against...', end='')
    from zb_library import makeUserPart
    folder = os.path.join(HERE, 'verify_test_tmp')
    app = makeFakeApp(folder)
    try:
        definition = makeUserPart(app.library, 'fa',
                                  RECIPES['FULLADD']({}))
        choices = zb_editor.verifyChoices(app, definition)
        names = [c[0] for c in choices]
        assert(choices[0][:2] == ('FULLADD', True))    # matching first
        assert([c[0] for c in choices if c[1]] == ['FULLADD'])
        for name in ['REG', 'RAM', 'CLOCK', 'PIN_IN', 'IR']:
            assert(name not in names)                  # can't be checked
        assert('ALU' in names and 'MUX4' in names)
        mux = [c for c in choices if c[0] == 'MUX4'][0]
        assert(mux[2].startswith('needs in0, in1, in2, in3, sel -> out'))
        # Picking one runs the check
        app.selection = {'parts': set(), 'wires': set(), 'junctions': set()}
        part = addPart(app.library, app.root, 'fa', 0, 0)
        app.selection['parts'] = {part['id']}
        zb_editor.verifyCurrent(app, 'FULLADD')
        assert(app.verifyResult['ok'] and definition['verified'])
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testRunInsidePart():
    print('Testing running a part on its own from inside it...', end='')
    from zb_library import makeUserPart
    folder = os.path.join(HERE, 'solo_test_tmp')
    app = makeFakeApp(folder)
    try:
        makeUserPart(app.library, 'fa', RECIPES['FULLADD']({}))
        part = placeFake(app, 'fa', 0, 0)
        zb_editor.drillIn(app, part['id'])
        inner = zb_editor.getCircuit(app)
        # What zb_main.enterRun does when the view is inside a part
        app.solo = {'path': list(app.path), 'names': list(app.pathNames),
                    'circuit': inner, 'readOnly': app.view['readOnly'],
                    'partName': app.view.get('partName')}
        app.mode = 'run'
        app.sim = flatten(app.library, inner)
        zb_editor.refreshView(app)
        assert(app.view['live'] and app.view['circuit'] is inner)
        assert(zb_editor.atRunTop(app) and zb_editor.runBase(app) == 1)
        assert(app.pathNames == ['fa'])
        # Its IN pins are switches now, and its table rows can be tried
        assert(set(zb_editor.rootPins(app)) == {'a', 'b', 'cin'})
        zb_editor.setRootPins(app, {'a': 1, 'b': 1, 'cin': 0})
        outs = {p['params']['name']: p for p in inner['parts']
                if p['type'] == 'PIN_OUT'}
        value = app.sim['nets'][app.sim['nodeNet'][
            ('port', (outs['cout']['id'],), 'in')]]['value']
        assert(value == 1)
        data, message = zb_editor.tableForView(app)
        assert(message == None and len(data['rows']) == 8)
        # Can't go above it while it runs on its own
        assert(not zb_editor.drillOut(app) and app.path == [part['id']])
        assert('on its own' in app.message)
        # Back in Build mode you are still inside it, and can go up
        app.mode, app.sim, app.solo = 'build', None, None
        zb_editor.refreshView(app)
        assert(zb_editor.editingPartName(app) == 'fa')
        assert(zb_editor.drillOut(app) and app.path == [])
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testPartNeighbors():
    print('Testing what a hovered part lights up...', end='')
    folder = os.path.join(HERE, 'neighbors_test_tmp')
    app = makeFakeApp(folder, RECIPES['FULLADD']({}))
    try:
        circuit = app.root
        byLabel = {p['label'] or p['params'].get('name', p['type']): p
                   for p in circuit['parts']}
        h = byLabel['h']                       # the first XOR: a ^ b
        found = zb_editor.partNeighbors(app, h['id'])
        names = lambda ids: sorted(
            findPart(circuit, i)['label'] or
            findPart(circuit, i)['params'].get('name', findPart(
                circuit, i)['type']) for i in ids)
        assert(names(found['feeders']) == ['a', 'b'])
        takers = [findPart(circuit, i)['type'] for i in found['takers']]
        assert(sorted(takers) == ['AND', 'XOR'])     # x2 and the cin AND
        assert(len(found['nets']) == 3)              # in0, in1, out
        # An output pin is fed by one gate and feeds nothing
        cout = byLabel['cout']
        found = zb_editor.partNeighbors(app, cout['id'])
        assert([findPart(circuit, i)['type'] for i in found['feeders']]
               == ['OR'] and found['takers'] == set())
        # A part with nothing wired lights nothing
        lone = placeFake(app, 'NOT', 900, 900)
        assert(zb_editor.partNeighbors(app, lone['id'])['nets'] == set())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testStashAndSave():
    print('Testing saving, and coming back after a mission...', end='')
    folder = os.path.join(HERE, 'stash_test_tmp')
    app = makeFakeApp(folder)
    try:
        placeFake(app, 'NOT', 0, 0)
        zb_editor.saveAs(app, 'mine')
        assert(app.fileName == 'mine' and not zb_editor.isUnsaved(app))
        placeFake(app, 'NOT', 0, 100)
        assert(zb_editor.isUnsaved(app))
        assert(zb_editor.listCircuitsByDate()[0] == 'mine')
        mine = app.root
        zb_editor.stashRoot(app)
        zb_editor.openCircuit(app, makeCircuit('mission'))
        assert(app.fileName == None)
        assert(zb_editor.restoreStash(app))
        assert(app.root is mine and app.fileName == 'mine')
        assert(zb_editor.isUnsaved(app))              # still not saved
        # A part opened from the Open list, and back again
        gate = placeFake(app, 'NOT', 200, 0)
        app.selection = {'parts': {gate['id']}, 'wires': set(),
                         'junctions': set()}
        zb_editor.packInto(app, 'Inv')
        zb_editor.openPartSheet(app, 'Inv')
        assert(zb_editor.editingPartName(app) == 'Inv')
        assert(zb_editor.restoreStash(app))
        assert(app.root is mine)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print('Passed!')

def testAll():
    testValues()
    testGates()
    testWiringParts()
    testBlocksMatchLecture()
    testStatefulParts()
    testNets()
    testSaveLoadAndEdit()
    testSettleAndWaves()
    testHistory()
    testLectureTrace()
    testAllProgramsLockstep()
    testCheckerFindsDifferences()
    testUnconditionalJump()
    testDeclaredCaptions()
    testRecipesVerify()
    testGateLevelMachine()
    testPacking()
    testInnerView()
    testPalette()
    testEditorActions()
    testWireBends()
    testPinSides()
    testMissions()
    testShippedReference()
    # Round 2
    testSpeedLevels()
    testRangeNotation()
    testRangePresets()
    testGateLoopsFound()
    testReferenceHasNoGateLoops()
    testLatchPowerOnIsX()
    testLatchSetResetHold()
    testRingOscillatorMessage()
    testLatchRaceGoesX()
    testHistoryKeepsLatchState()
    testContainsStateLoop()
    testTruthTableFullAdder()
    testTruthTableOrderAndWidths()
    testTruthTableSample()
    testTruthTableExpected()
    testTruthTableStateful()
    testMissionDetailFailedRow()
    testEditorTableRow()
    testExplainZ()
    testExplainX()
    testExplainOutputCone()
    testMessageCatalog()
    testGoldenMessageNamesInstruction()
    testPinDiffMessage()
    testDffMasterSlave()
    testSequenceMissions()
    testDLatchFailsDffMission()
    testWireGeometry()
    testOverlapWarnings()
    testGeometrySpeed()
    testRouterBasics()
    testRouterAvoidsParts()
    testTidyKeepsCircuit()
    testScreenshotAdderTidy()
    testReferenceLayoutClean()
    testEditorTidyUndo()
    testRouterSpeed()
    # Round 3
    testBusWiring()
    testUserPartLayout()
    testRenamePort()
    testParamSteppers()
    testStashAndSave()
    testVerifyChoices()
    testRunInsidePart()
    testPartNeighbors()
    print('All Z18 builder tests passed!')

if __name__ == '__main__':
    testAll()

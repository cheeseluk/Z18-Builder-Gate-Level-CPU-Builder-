# zb_kit.py
# The Z18 kit: the palette, the recipes that show what is inside each
# built-in part, the complete lecture machine built from kit parts, the
# run rules, and the side-by-side check against the golden model
# (../z18100/z18_cpu.py). No graphics here.

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(HERE)
for folder in [PROJECT_DIR, os.path.join(PROJECT_DIR, 'z18100')]:
    if folder not in sys.path:
        sys.path.append(folder)

import z18_cpu
from z18_assembler import isInstruction
from zb_values import Z, X, isKnown, formatValue
from zb_parts import PRIMITIVES
from zb_circuit import makeLibrary, makeCircuit, addPart, addWire, \
    addJunction, findPart
from zb_sim import findTagged, taggedValues, describePrim

# The palette, one tab per level
PALETTE = [('Gates', ['NOT', 'BUF', 'AND', 'OR', 'NAND', 'NOR', 'XOR', 'TG',
                      'CONST', 'SPLIT', 'MERGE', 'EXTEND', 'PIN_IN',
                      'PIN_OUT', 'PROBE']),
           ('Blocks', ['HALFADD', 'FULLADD', 'MUX2', 'MUX4', 'DEMUX',
                       'DECODER', 'REG', 'COUNTER']),
           ('Units', ['ALU', 'RAM', 'IR', 'PC', 'FLAGS', 'CLOCK'])]

# The tags that tie a part to the lecture machine (golden model fields)
TAGS = ['ir', 'pc', 'r0', 'r1', 'r2', 'r3', 'muxReg', 'a', 'b', 'out',
        'flags', 'n', 'z', 'o', 'mem']
# Which part types each tag fits
TAG_TYPES = {'ir': ['IR', 'REG'], 'pc': ['PC', 'COUNTER'],
             'flags': ['FLAGS'], 'mem': ['RAM']}
TAG_NAMES = {'ir': 'IR', 'pc': 'PC', 'r0': 'R0', 'r1': 'R1', 'r2': 'R2',
             'r3': 'R3', 'muxReg': 'MUX reg', 'a': 'A', 'b': 'B',
             'out': 'Output', 'flags': 'Flags', 'n': 'N', 'z': 'Z',
             'o': 'O', 'mem': 'RAM'}

KIT_LIBRARY = makeLibrary()           # only used to place primitives


def tagFits(tag, typeName):
    if tag in TAG_TYPES:
        return typeName in TAG_TYPES[tag]
    return typeName == 'REG'


######################################################################
# A small helper for building circuits in code
######################################################################

def newBuild(name):
    return {'circuit': makeCircuit(name), 'ids': dict()}

def put(build, key, typeName, x, y, params=None, label='', ref=None):
    part = addPart(KIT_LIBRARY, build['circuit'], typeName, x, y, params,
                   label, ref)
    build['ids'][key] = part['id']
    return part

def putPin(build, key, direction, name, width, x, y):
    typeName = 'PIN_IN' if direction == 'in' else 'PIN_OUT'
    return put(build, key, typeName, x, y, {'name': name, 'width': width})

def dot(build, key, x, y):
    build['ids'][key] = addJunction(build['circuit'], x, y)['id']

def endOf(build, spec):
    # 'key.port' names a port; '*key' names a junction
    if spec.startswith('*'):
        return ['junction', build['ids'][spec[1:]]]
    key, port = spec.split('.')
    return ['port', build['ids'][key], port]

def link(build, a, b, via=None, lamp=None, color=None):
    wire = addWire(build['circuit'], endOf(build, a), endOf(build, b), via)
    wire['lamp'] = lamp
    wire['color'] = color
    return wire


######################################################################
# Recipes: what is inside each built-in part (read-only)
######################################################################

def recipeHalfAdder(params):
    b = newBuild('Half adder')
    putPin(b, 'a', 'in', 'a', 1, 0, 20)
    putPin(b, 'b', 'in', 'b', 1, 0, 80)
    put(b, 'xor', 'XOR', 120, 10)
    put(b, 'and', 'AND', 120, 70)
    putPin(b, 's', 'out', 's', 1, 240, 20)
    putPin(b, 'c', 'out', 'c', 1, 240, 80)
    link(b, 'a.out', 'xor.in0')
    link(b, 'a.out', 'and.in0')
    link(b, 'b.out', 'xor.in1')
    link(b, 'b.out', 'and.in1')
    link(b, 'xor.out', 's.in')
    link(b, 'and.out', 'c.in')
    return b['circuit']

def recipeFullAdder(params):
    # As z18_cpu.fullAdder: h = a XOR b; s = h XOR cin;
    # cout = (a AND b) OR (cin AND h)
    b = newBuild('Full adder')
    putPin(b, 'a', 'in', 'a', 1, 0, 20)
    putPin(b, 'b', 'in', 'b', 1, 0, 70)
    putPin(b, 'cin', 'in', 'cin', 1, 0, 170)
    put(b, 'x1', 'XOR', 120, 20, label='h')
    put(b, 'x2', 'XOR', 240, 40)
    put(b, 'a1', 'AND', 240, 110)
    put(b, 'a2', 'AND', 240, 170)
    put(b, 'or', 'OR', 350, 130)
    putPin(b, 's', 'out', 's', 1, 460, 50)
    putPin(b, 'cout', 'out', 'cout', 1, 460, 140)
    link(b, 'a.out', 'x1.in0')
    link(b, 'b.out', 'x1.in1')
    link(b, 'a.out', 'a1.in0')
    link(b, 'b.out', 'a1.in1')
    link(b, 'x1.out', 'x2.in0')
    link(b, 'cin.out', 'x2.in1')
    link(b, 'cin.out', 'a2.in0')
    link(b, 'x1.out', 'a2.in1')
    link(b, 'a1.out', 'or.in0')
    link(b, 'a2.out', 'or.in1')
    link(b, 'x2.out', 's.in')
    link(b, 'or.out', 'cout.in')
    return b['circuit']

def recipeMux2(params):
    # out = (in0 AND NOT sel) OR (in1 AND sel), a whole word at a time
    width = params['width']
    b = newBuild('MUX 2:1')
    putPin(b, 'in0', 'in', 'in0', width, 0, 20)
    putPin(b, 'in1', 'in', 'in1', width, 0, 90)
    putPin(b, 'sel', 'in', 'sel', 1, 0, 170)
    put(b, 'not', 'NOT', 90, 130)
    put(b, 'r0', 'EXTEND', 170, 130, {'from': 1, 'to': width,
                                      'mode': 'repeat'})
    put(b, 'r1', 'EXTEND', 170, 190, {'from': 1, 'to': width,
                                      'mode': 'repeat'})
    put(b, 'g0', 'AND', 260, 20, {'width': width})
    put(b, 'g1', 'AND', 260, 100, {'width': width})
    put(b, 'or', 'OR', 360, 50, {'width': width})
    putPin(b, 'out', 'out', 'out', width, 460, 60)
    link(b, 'sel.out', 'not.in')
    link(b, 'not.out', 'r0.in')
    link(b, 'sel.out', 'r1.in')
    link(b, 'in0.out', 'g0.in0')
    link(b, 'r0.out', 'g0.in1')
    link(b, 'in1.out', 'g1.in0')
    link(b, 'r1.out', 'g1.in1')
    link(b, 'g0.out', 'or.in0')
    link(b, 'g1.out', 'or.in1')
    link(b, 'or.out', 'out.in')
    return b['circuit']

def recipeMux4(params):
    # As z18_cpu.runMux: four select lines from s1 s0, each ANDed with its
    # input, then one OR
    width = params['width']
    b = newBuild('MUX 4:1')
    for k in range(4):
        putPin(b, f'in{k}', 'in', f'in{k}', width, 0, 20 + 70 * k)
    putPin(b, 'sel', 'in', 'sel', 2, 0, 320)
    put(b, 'split', 'SPLIT', 70, 310, {'width': 2,
                                       'ranges': [[1, 1], [0, 0]]})
    put(b, 'n1', 'NOT', 130, 360, label='NOT s1')
    put(b, 'n0', 'NOT', 130, 400, label='NOT s0')
    for k in range(4):
        y = 20 + 70 * k
        put(b, f'sel{k}', 'AND', 220, 300 + 60 * k, label=f'sel={k}')
        put(b, f'rep{k}', 'EXTEND', 310, 310 + 60 * k,
            {'from': 1, 'to': width, 'mode': 'repeat'})
        put(b, f'g{k}', 'AND', 400, y, {'width': width})
        link(b, f'in{k}.out', f'g{k}.in0')
        link(b, f'sel{k}.out', f'rep{k}.in')
        link(b, f'rep{k}.out', f'g{k}.in1')
    lines = [('n1', 'n0'), ('n1', 'split'), ('split', 'n0'),
             ('split', 'split')]
    for k in range(4):
        high, low = lines[k]
        link(b, 'split.out0' if high == 'split' else high + '.out',
             f'sel{k}.in0')
        link(b, 'split.out1' if low == 'split' else low + '.out',
             f'sel{k}.in1')
    link(b, 'sel.out', 'split.in')
    link(b, 'split.out0', 'n1.in')
    link(b, 'split.out1', 'n0.in')
    put(b, 'or', 'OR', 520, 90, {'width': width, 'inputs': 4})
    for k in range(4):
        link(b, f'g{k}.out', f'or.in{k}')
    putPin(b, 'out', 'out', 'out', width, 620, 110)
    link(b, 'or.out', 'out.in')
    return b['circuit']

def recipeDemux(params):
    width = params['width']
    b = newBuild('DEMUX 1:2')
    putPin(b, 'in', 'in', 'in', width, 0, 20)
    putPin(b, 'sel', 'in', 'sel', 1, 0, 120)
    putPin(b, 'e', 'in', 'e', 1, 0, 180)
    put(b, 'not', 'NOT', 80, 110)
    put(b, 'a0', 'AND', 170, 100)
    put(b, 'a1', 'AND', 170, 170)
    put(b, 't0', 'TG', 300, 10, {'width': width})
    put(b, 't1', 'TG', 300, 210, {'width': width})
    putPin(b, 'f0', 'out', 'f0', width, 420, 20)
    putPin(b, 'en0', 'out', 'en0', 1, 420, 90)
    putPin(b, 'f1', 'out', 'f1', width, 420, 220)
    putPin(b, 'en1', 'out', 'en1', 1, 420, 160)
    link(b, 'sel.out', 'not.in')
    link(b, 'e.out', 'a0.in0')
    link(b, 'not.out', 'a0.in1')
    link(b, 'e.out', 'a1.in0')
    link(b, 'sel.out', 'a1.in1')
    link(b, 'in.out', 't0.in')
    link(b, 'in.out', 't1.in')
    link(b, 'a0.out', 't0.en')
    link(b, 'a1.out', 't1.en')
    link(b, 't0.out', 'f0.in')
    link(b, 't1.out', 'f1.in')
    link(b, 'a0.out', 'en0.in')
    link(b, 'a1.out', 'en1.in')
    return b['circuit']

def recipeDecoder(params):
    # As z18_cpu.decoderOutput: output k is an AND of en and each input bit
    # (or its NOT, where k has a 0)
    bits = params['bits']
    count = params['outputs']
    b = newBuild('Decoder')
    putPin(b, 'in', 'in', 'in', bits, 0, 20)
    putPin(b, 'en', 'in', 'en', 1, 0, 100)
    ranges = [[bits - 1 - i, bits - 1 - i] for i in range(bits)]
    put(b, 'split', 'SPLIT', 70, 10, {'width': bits, 'ranges': ranges})
    link(b, 'in.out', 'split.in')
    for j in range(bits):
        put(b, f'not{j}', 'NOT', 130, 80 + 30 * j)
        link(b, f'split.out{j}', f'not{j}.in')
    for k in range(count):
        gate = put(b, f'and{k}', 'AND', 260, 10 + 80 * k,
                   {'inputs': bits + 1}, label=f'= {k}')
        link(b, 'en.out', f'and{k}.in0')
        pattern = format(k, f'0{bits}b')
        for j in range(bits):
            if pattern[j] == '1':
                link(b, f'split.out{j}', f'and{k}.in{j + 1}')
            else:
                link(b, f'not{j}.out', f'and{k}.in{j + 1}')
        putPin(b, f'd{k}', 'out', f'd{k}', 1, 380, 20 + 80 * k)
        link(b, f'and{k}.out', f'd{k}.in')
    return b['circuit']

def recipeALU(params):
    # As z18_cpu.runAdder: 8 full adders in a ripple chain; to subtract,
    # B goes through XORs with minus and the first carry in is minus
    b = newBuild('ALU')
    putPin(b, 'a', 'in', 'a', 8, 0, 20)
    putPin(b, 'b', 'in', 'b', 8, 0, 120)
    putPin(b, 'plus', 'in', 'plus', 1, 0, 620)
    putPin(b, 'minus', 'in', 'minus', 1, 0, 240)
    ranges = [[7 - i, 7 - i] for i in range(8)]
    put(b, 'sa', 'SPLIT', 70, 10, {'width': 8, 'ranges': ranges})
    put(b, 'sb', 'SPLIT', 70, 110, {'width': 8, 'ranges': ranges})
    link(b, 'a.out', 'sa.in')
    link(b, 'b.out', 'sb.in')
    for i in range(8):
        y = 10 + 70 * i
        put(b, f'x{i}', 'XOR', 170, y + 10, label=f'b{i}^-')
        put(b, f'fa{i}', 'FULLADD', 290, y, label=f'bit {i}')
        link(b, f'sb.out{7 - i}', f'x{i}.in0')
        link(b, 'minus.out', f'x{i}.in1')
        link(b, f'sa.out{7 - i}', f'fa{i}.a')
        link(b, f'x{i}.out', f'fa{i}.b')
        if i == 0:
            link(b, 'minus.out', 'fa0.cin')
        else:
            link(b, f'fa{i - 1}.cout', f'fa{i}.cin')
    put(b, 'merge', 'MERGE', 400, 240, {'widths': [1] * 8})
    put(b, 'nor', 'NOR', 400, 380, {'inputs': 8}, label='Z')
    put(b, 'ov', 'XOR', 400, 510, label='O')
    put(b, 'gor', 'OR', 400, 600, label='go')
    for i in range(8):
        link(b, f'fa{i}.s', f'merge.in{7 - i}')
        link(b, f'fa{i}.s', f'nor.in{i}')
    link(b, 'fa6.cout', 'ov.in0')
    link(b, 'fa7.cout', 'ov.in1')
    link(b, 'plus.out', 'gor.in0')
    link(b, 'minus.out', 'gor.in1')
    putPin(b, 'n', 'out', 'n', 1, 520, 180)
    putPin(b, 'out', 'out', 'out', 8, 520, 240)
    putPin(b, 'z', 'out', 'z', 1, 520, 420)
    putPin(b, 'o', 'out', 'o', 1, 520, 520)
    putPin(b, 'go', 'out', 'go', 1, 520, 610)
    link(b, 'fa7.s', 'n.in')
    link(b, 'merge.out', 'out.in')
    link(b, 'nor.out', 'z.in')
    link(b, 'ov.out', 'o.in')
    link(b, 'gor.out', 'go.in')
    return b['circuit']

def recipeIR(params):
    b = newBuild('IR')
    putPin(b, 'd', 'in', 'd', 8, 0, 20)
    putPin(b, 'we', 'in', 'we', 1, 0, 90)
    put(b, 'reg', 'REG', 90, 10, {'width': 8, 'init': 'X'}, label='IR')
    put(b, 'split', 'SPLIT', 220, 60, {'width': 8,
                                       'ranges': [[7, 4], [3, 0]]})
    putPin(b, 'q', 'out', 'q', 8, 300, 10)
    putPin(b, 'opcode', 'out', 'opcode', 4, 300, 60)
    putPin(b, 'operand', 'out', 'operand', 4, 300, 100)
    link(b, 'd.out', 'reg.d')
    link(b, 'we.out', 'reg.we')
    link(b, 'reg.q', 'q.in')
    link(b, 'reg.q', 'split.in')
    link(b, 'split.out0', 'opcode.in', color='opcode')
    link(b, 'split.out1', 'operand.in', color='operand')
    return b['circuit']

def recipePC(params):
    b = newBuild('PC')
    putPin(b, 'd', 'in', 'd', 4, 0, 20)
    putPin(b, 'we', 'in', 'we', 1, 0, 90)
    putPin(b, 'inc', 'in', 'inc', 1, 0, 140)
    put(b, 'ext', 'EXTEND', 80, 20, {'from': 4, 'to': 8, 'mode': 'zero'})
    put(b, 'cnt', 'COUNTER', 170, 20, {'width': 8}, label='PC')
    put(b, 'split', 'SPLIT', 290, 30, {'width': 8, 'ranges': [[3, 0]]})
    putPin(b, 'q', 'out', 'q', 4, 360, 30)
    link(b, 'd.out', 'ext.in')
    link(b, 'ext.out', 'cnt.d')
    link(b, 'we.out', 'cnt.we')
    link(b, 'inc.out', 'cnt.inc')
    link(b, 'cnt.q', 'split.in')
    link(b, 'split.out0', 'q.in')
    return b['circuit']

def recipeFlags(params):
    b = newBuild('Flags')
    putPin(b, 'we', 'in', 'we', 1, 0, 200)
    for i in range(3):
        name = 'nzo'[i]
        y = 20 + 60 * i
        putPin(b, name, 'in', name, 1, 0, y)
        put(b, 'r' + name, 'REG', 100, y - 10, {'width': 1},
            label=name.upper())
        putPin(b, name + 'q', 'out', name + 'q', 1, 200, y)
        link(b, name + '.out', 'r' + name + '.d')
        link(b, 'we.out', 'r' + name + '.we')
        link(b, 'r' + name + '.q', name + 'q.in')
    return b['circuit']

RECIPES = {'HALFADD': recipeHalfAdder, 'FULLADD': recipeFullAdder,
           'MUX2': recipeMux2, 'MUX4': recipeMux4, 'DEMUX': recipeDemux,
           'DECODER': recipeDecoder, 'ALU': recipeALU, 'IR': recipeIR,
           'PC': recipePC, 'FLAGS': recipeFlags}

# How a stateful unit's state maps onto the registers in its recipe
# (found by label)
RECIPE_STATES = {'IR': lambda state: {'IR': state},
                 'PC': lambda state: {'PC': state},
                 'FLAGS': lambda state: {'N': state['n'], 'Z': state['z'],
                                         'O': state['o']}}

def attachRecipes(library):
    library['recipes'] = RECIPES
    library['recipeStates'] = RECIPE_STATES

# Where a unit's tag goes when it is opened up: {unit tag: {inner label:
# inner tag}}
INNER_TAGS = {'ir': {'IR': 'ir'}, 'pc': {'PC': 'pc'},
              'flags': {'N': 'n', 'Z': 'z', 'O': 'o'}}

def expandToGates(library, circuit):
    # A copy of the circuit where every built-in part that has a recipe
    # is replaced by a user part made from the recipe, all the way down
    # to gates and registers. Adds those parts to the library.
    import copy
    import json
    from zb_library import makeUserPart
    result = copy.deepcopy(circuit)
    for part in result['parts']:
        if part['type'] not in RECIPES:
            continue
        key = json.dumps(part['params'], sort_keys=True)
        name = f"gates {part['type']} {key}"
        if part['ref'] in INNER_TAGS:
            name += ' ' + part['ref']
        if name not in library['user']:
            inner = expandToGates(library, RECIPES[part['type']](
                part['params']))
            for innerPart in inner['parts']:
                tags = INNER_TAGS.get(part['ref'], dict())
                if innerPart['label'] in tags:
                    innerPart['ref'] = tags[innerPart['label']]
            made = makeUserPart(library, name, inner, 'box', part['type'])
            made['lookLike'] = True    # drawn like the built-in
            library['cache'] = dict()
        part['type'] = name
        part['params'] = dict()
        if part['ref'] in INNER_TAGS:
            part['ref'] = None
    return result


######################################################################
# The lecture machine, built from kit parts
######################################################################

DATA_BUS_Y = 30
ADDR_BUS_Y = 450

def placeReferenceParts(b):
    # Laid out like the lecture's schematic:
    # data bus on top, address bus below the RAM, decoder rails at the
    # bottom
    put(b, 'ram', 'RAM', 20, 60, ref='mem', label='RAM 16 x 8')
    put(b, 'ir', 'IR', 270, 80, ref='ir', label='IR')
    put(b, 'r1', 'REG', 500, 80, {'ports': 'top'}, 'R1', 'r1')
    put(b, 'r2', 'REG', 610, 80, {'ports': 'top'}, 'R2', 'r2')
    put(b, 'r3', 'REG', 720, 80, {'ports': 'top'}, 'R3', 'r3')
    put(b, 'zero', 'CONST', 810, 150, {'width': 8, 'value': 0},
        label='0 (D0)')
    put(b, 'mux', 'MUX4', 860, 150, {'width': 8}, 'MUX')
    put(b, 'muxreg', 'REG', 920, 170, {}, 'MUX reg', 'muxReg')
    put(b, 'demux', 'DEMUX', 1030, 150, {'width': 8}, 'DEMUX')
    put(b, 'a', 'REG', 1120, 100, {}, 'A', 'a')
    put(b, 'b', 'REG', 1120, 230, {}, 'B', 'b')
    put(b, 'alu', 'ALU', 1240, 90, label='ALU')
    put(b, 'flags', 'FLAGS', 1340, 90, ref='flags', label='Flags')
    put(b, 'out', 'REG', 1340, 150, {}, 'Output', 'out')
    put(b, 'r0', 'REG', 1340, 270, {'ports': 'top'}, 'R0', 'r0')
    put(b, 'r0buf', 'TG', 1450, 310, {'width': 8}, 'R0 RE')
    put(b, 'notn', 'NOT', 1440, 90, label='NOT N')
    put(b, 'andj', 'AND', 1500, 90, label='jump')
    put(b, 'pc', 'PC', 300, 290, ref='pc', label='PC (+1)')
    put(b, 'tgir', 'TG', 420, 180, {'width': 4}, 'TG CLK')
    put(b, 'tgpc', 'TG', 420, 290, {'width': 4}, 'TG /CLK')
    put(b, 'asplit', 'SPLIT', 820, 290, {'width': 4,
                                         'ranges': [[1, 0], [0, 0]]},
        'addr')
    put(b, 'reor', 'OR', 140, 460, {'inputs': 4}, 'RE')
    put(b, 'dec', 'DECODER', 20, 520, label='DEC 4>10')
    put(b, 'clock', 'CLOCK', -70, 560, label='Clock')
    put(b, 'fetch', 'BUF', 20, 640, label='"0" fetch')

def wireDataBus(b):
    y = DATA_BUS_Y
    dot(b, 'd1', 160, y)
    dot(b, 'd2', 255, y)
    dot(b, 'd3', 540, y)
    dot(b, 'd4', 650, y)
    dot(b, 'd5', 760, y)
    link(b, 'ram.din', '*d1', [(120, y)])
    link(b, 'ram.dout', '*d1')
    link(b, '*d1', '*d2')
    link(b, '*d2', 'ir.d', [(255, 100)])
    link(b, '*d2', '*d3')
    link(b, '*d3', 'r1.d')
    link(b, '*d3', '*d4')
    link(b, '*d4', 'r2.d')
    link(b, '*d4', '*d5')
    link(b, '*d5', 'r3.d')
    link(b, '*d5', 'r0buf.out', [(1560, y), (1560, 330)])

def wireAddressBus(b):
    y = ADDR_BUS_Y
    dot(b, 'a1', 280, y)
    dot(b, 'a2', 480, y)
    dot(b, 'a3', 490, y)
    link(b, 'ram.addr', '*a1', [(210, y)])
    link(b, '*a1', 'pc.d', [(280, 310)])
    link(b, '*a1', '*a2')
    link(b, 'tgpc.out', '*a2', [(480, 310)])
    link(b, '*a2', '*a3')
    link(b, 'tgir.out', '*a3', [(490, 200)])
    link(b, '*a3', 'asplit.in', [(800, y), (800, 300)])
    link(b, 'asplit.out0', 'mux.sel', [(870, 300)])
    link(b, 'asplit.out1', 'demux.sel', [(1040, 310)])
    link(b, 'pc.q', 'tgpc.in')
    link(b, 'ir.operand', 'tgir.in', [(360, 200)], color='operand')
    link(b, 'ir.opcode', 'dec.in', [(330, 160), (265, 160), (265, 455),
                                    (40, 455)], color='opcode')

def wireDatapath(b):
    link(b, 'r3.q', 'mux.in1', [(790, 180)])
    link(b, 'r2.q', 'mux.in2', [(680, 200)])
    link(b, 'r1.q', 'mux.in3', [(570, 220)])
    link(b, 'zero.out', 'mux.in0')
    link(b, 'mux.out', 'muxreg.d')
    link(b, 'muxreg.q', 'demux.in')
    link(b, 'demux.f0', 'a.d', [(1100, 160), (1100, 120)])
    link(b, 'demux.en0', 'a.we', [(1130, 170)])
    link(b, 'demux.f1', 'b.d', [(1100, 210), (1100, 250)])
    link(b, 'demux.en1', 'b.we', [(1080, 220), (1080, 290), (1130, 290)])
    link(b, 'a.q', 'alu.a')
    link(b, 'b.q', 'alu.b', [(1220, 250), (1220, 220)])
    link(b, 'alu.n', 'flags.n', [(1320, 120), (1320, 100)])
    link(b, 'alu.z', 'flags.z', [(1325, 130), (1325, 110)])
    link(b, 'alu.o', 'flags.o', [(1330, 140), (1330, 120)])
    link(b, 'alu.out', 'out.d')
    dot(b, 'go', 1350, 210)
    link(b, 'alu.go', '*go')
    link(b, '*go', 'out.we')
    link(b, '*go', 'flags.we', [(1430, 210), (1430, 140), (1380, 140)])
    link(b, 'out.q', 'r0.d', [(1440, 170), (1440, 250), (1380, 250)])
    link(b, 'r0.q', 'r0buf.in', [(1410, 330)])

def wireClock(b):
    # CLK: decoder enable, the IR's TG, the PC's +1. CLK-bar: the PC's TG
    # and the "0" fetch block (memory RE + IR WE)
    dot(b, 'clk', 0, 570)
    dot(b, 'clk2', 0, 670)
    link(b, 'clock.clk', '*clk', lamp='CLK')
    link(b, '*clk', 'dec.en')
    link(b, '*clk', '*clk2')
    link(b, '*clk2', 'pc.inc', [(330, 670)])
    link(b, '*clk2', 'tgir.en', [(405, 670), (405, 170), (440, 170)])
    dot(b, 'bar', -10, 590)
    link(b, 'clock.clkBar', '*bar', lamp='/CLK')
    link(b, '*bar', 'fetch.in', [(-10, 650)])
    link(b, '*bar', 'tgpc.en', [(-10, 680), (412, 680), (412, 280),
                                (440, 280)])
    dot(b, 'f', 80, 650)
    link(b, 'fetch.out', '*f', lamp='fetch')
    link(b, '*f', 'reor.in0', [(80, 470)])
    link(b, '*f', 'ir.we', [(398, 650), (398, 140), (290, 140)])
    link(b, 'reor.out', 'ram.re', [(200, 490), (200, 400), (60, 400)],
         lamp='RE')

def railY(k):
    return 530 + 10 * k

def wireDecoder(b):
    # Decoder output k runs along a rail at railY(k), then up to its part
    targets = ['r0.we', 'r1.we', 'r2.we', 'r3.we', 'muxreg.we', 'demux.e',
               'alu.plus', 'alu.minus', 'andj.in1', 'ram.we']
    tapX = [1350, 510, 620, 730, 930, 1060, 1260, 1280, None, None]
    names = ['R0 WE', 'R1 WE', 'R2 WE', 'R3 WE', 'MUX E', 'DMX E',
             'ALU +', 'ALU -', 'd8', 'WE, R0 RE']
    for k in range(10):
        y = railY(k)
        if k in [1, 2, 3]:
            # also into the OR that makes memory RE
            x = [None, 110, 120, 130][k]
            orY = [None, 480, 500, 510][k]
            dot(b, f'rail{k}', x, y)
            link(b, f'dec.d{k}', f'*rail{k}', lamp=names[k])
            link(b, f'*rail{k}', f'reor.in{k}', [(x, orY)])
            link(b, f'*rail{k}', targets[k], [(tapX[k], y)])
        elif k == 8:
            link(b, 'dec.d8', 'andj.in1', [(1495, y), (1495, 120)],
                 lamp=names[k])
        elif k == 9:
            dot(b, 'rail9', 100, y)
            link(b, 'dec.d9', '*rail9', lamp=names[k])
            link(b, '*rail9', 'ram.we')
            link(b, '*rail9', 'r0buf.en', [(1590, y), (1590, 300),
                                           (1470, 300)])
        else:
            link(b, f'dec.d{k}', targets[k], [(tapX[k], y)],
                 lamp=names[k])

def wireJump(b):
    # Jump-if-not-negative: PC WE = d8 AND NOT N, then the long trip back
    # to the PC
    link(b, 'flags.nq', 'notn.in', lamp='N')
    link(b, 'notn.out', 'andj.in0', lamp='NOT N')
    link(b, 'andj.out', 'pc.we', [(1575, 110), (1575, 440), (310, 440)],
         lamp='PC WE')

def makeReferenceMachine():
    b = newBuild('Z18100 (lecture machine)')
    placeReferenceParts(b)
    wireDataBus(b)
    wireAddressBus(b)
    wireDatapath(b)
    wireClock(b)
    wireDecoder(b)
    wireJump(b)
    return b['circuit']


######################################################################
# Run rules (the same stops as z18_cpu.findStop)
######################################################################

def z18Rule(sim):
    if sim['phase'] == 'fetch':
        pc = findTagged(sim, 'pc')
        if pc != None and isKnown(pc['state']) and pc['state'] >= 16:
            return ('halt', 'PC ran past address 15')
    else:
        ir = findTagged(sim, 'ir')
        if ir != None and not isKnown(ir['state']):
            return ('halt', 'IR holds xxxxxxxx (that word was never set), '
                            'so no decoder output turns on')
        # (a program can declare more op codes than the lecture's 0-9)
        if ir != None and not isInstruction(ir['state'], sim.get('isa')):
            return ('halt', f"op code {formatValue(ir['state'] >> 4, 4)} "
                            'is undefined: the decoder has no output for it')
    return None

def z18ProblemRule(sim):
    # A register loading an unknown value is an error, except the IR:
    # fetching xxxxxxxx is allowed (the next phase halts on it)
    from zb_sim import loadStop
    for index, problem in sim['problems']:
        prim = sim['prims'][index]
        if prim['ref'] == 'ir':
            continue                   # fetching xxxxxxxx halts next phase
        return loadStop(sim, index, problem)
    return None

def attachKit(sim):
    sim['rules'] = [z18Rule]
    sim['problemRule'] = z18ProblemRule

def kitWarnings(sim):
    # What the machine is missing to run a program like the lecture's
    warnings = []
    if len(sim['clocks']) == 0:
        warnings.append('No CLOCK: registers load at the end of each '
                        'phase, but nothing tells parts which phase it is')
    missing = []
    for tag in ['ir', 'pc', 'mem']:
        if findTagged(sim, tag) == None:
            missing.append(TAG_NAMES[tag])
    if len(missing) > 0:
        warnings.append('Not tagged: ' + ', '.join(missing) + '. Tag the '
                        'parts so the run rules and the lecture check '
                        'know them.')
    return warnings


######################################################################
# Side-by-side check against the golden model
######################################################################

def makeChecker(memory):
    cpu = z18_cpu.makeCPU(memory)
    return {'cpu': cpu, 'history': [z18_cpu.saveState(cpu)]}

def checkerGoTo(checker, step):
    # Puts the golden model at `step` phases (running it further if needed)
    history = checker['history']
    cpu = checker['cpu']
    while len(history) <= step and not cpu['halted']:
        z18_cpu.loadState(cpu, history[-1])
        z18_cpu.stepPhase(cpu)
        history.append(z18_cpu.saveState(cpu))
    step = min(step, len(history) - 1)
    z18_cpu.loadState(cpu, history[step])

def goldenValue(cpu, field):
    value = cpu[field]
    if value == None:
        return X
    return value

def compareWithGolden(sim, cpu):
    # The first difference between the user's machine and the lecture's,
    # as {'field', 'yours', 'lecture', 'message'}, or None
    values = taggedValues(sim)
    for field in ['ir', 'pc', 'r0', 'r1', 'r2', 'r3', 'muxReg', 'a', 'b',
                  'out', 'n', 'z', 'o']:
        if field not in values:
            continue
        mine = values[field]
        theirs = goldenValue(cpu, field)
        if mine != theirs:
            width = 1 if field in 'nzo' else 8
            return {'field': field, 'yours': formatValue(mine, width),
                    'lecture': formatValue(theirs, width),
                    'message': f'your {TAG_NAMES[field]} = '
                               f"{formatValue(mine, width)}, lecture's = "
                               f'{formatValue(theirs, width)}'}
    if 'mem' in values:
        for address in range(16):
            mine = values['mem'][address]
            theirs = cpu['mem'][address]
            theirs = X if theirs == None else theirs
            if mine != theirs:
                return {'field': 'mem', 'yours': formatValue(mine, 8),
                        'lecture': formatValue(theirs, 8),
                        'message': f'your M[{address}] = '
                                   f"{formatValue(mine, 8)}, lecture's = "
                                   f'{formatValue(theirs, 8)}'}
    if sim['halted'] != cpu['halted']:
        mine = sim['status'] if sim['halted'] else 'still running'
        theirs = cpu['status'] if cpu['halted'] else 'still running'
        return {'field': 'halted', 'yours': mine, 'lecture': theirs,
                'message': f'yours: {mine}; lecture: {theirs}'}
    if sim['halted'] and statusKind(sim['status']) != statusKind(
            cpu['status']):
        return {'field': 'halted', 'yours': sim['status'],
                'lecture': cpu['status'],
                'message': f"yours: {sim['status']}; lecture: "
                           f"{cpu['status']}"}
    return None

# When each lecture register loads, from ../z18100/z18100_cpu_spec.md
# (sections 2.3-2.10), checked against z18_cpu.computeControl
LOAD_RULES = {
    'ir': 'the fetch signal (every fetch phase, CLK = 0)',
    'pc': 'every execute phase (+1), or decoder output 8 AND NOT N for a '
          'jump',
    'r0': 'decoder output 0 (Move) during execute',
    'r1': 'decoder output 1 (Load R1) during execute',
    'r2': 'decoder output 2 (Load R2) during execute',
    'r3': 'decoder output 3 (Load R3) during execute',
    'muxReg': 'decoder output 4 (MUX) during execute',
    'a': 'decoder output 5 (DEMUX) with operand bit 0 = 0',
    'b': 'decoder output 5 (DEMUX) with operand bit 0 = 1',
    'out': 'decoder output 6 or 7 (Add, Sub) during execute',
    'n': 'decoder output 6 or 7 (Add, Sub): the flags load with Output',
    'z': 'decoder output 6 or 7 (Add, Sub): the flags load with Output',
    'o': 'decoder output 6 or 7 (Add, Sub): the flags load with Output',
    'mem': 'decoder output 9 (Store): memory WE',
}

def instructionText(word, isa=None):
    # 'LOAD R2,M5: R2 <- M[5]' (or 'IR = xxxxxxxx')
    from z18_assembler import shortDisassemble, explain
    if word == None or not isKnown(word):
        return 'IR = xxxxxxxx'
    return f"{shortDisassemble(word, 'code', isa)}: {explain(word, isa)}"

def phaseLabel(sim, cpu, phaseName):
    # 'phase 14 (execute, LOAD R2,M5: R2 <- M[5])' for the phase just run
    return (f"phase {sim['halfCycles']} ({phaseName}, "
            f"{instructionText(cpu['ir'])})")

def goldenWhy(sim, difference):
    # Why a tagged part differs from the lecture's: did it load at all
    # (its WE during the phase that just ran), and from what
    from zb_explain import show, sourceText
    field = difference['field']
    if field == 'halted':
        return []
    ref = 'flags' if field in 'nzo' and findTagged(sim, field) == None \
        else field
    prim = findTagged(sim, ref)
    if prim == None:
        return []
    name = TAG_NAMES[field]
    rule = LOAD_RULES.get(field, '')
    weNet = prim['inNets'].get('we')
    if weNet == None:
        return []
    we = sim['nets'][weNet]['value']
    lines = []
    if we == 0:
        lines.append(f'Your {name} did not load: its WE was 0 this phase '
                     f'(from {sourceText(sim, weNet)}).')
    elif we == 1:
        port = {'mem': 'din', 'flags': field}.get(ref, 'd')
        dNet = prim['inNets'].get(port)
        if dNet != None:
            lines.append(f'Your {name} loaded {show(sim, dNet)} from '
                         f'{sourceText(sim, dNet)} (its WE was 1).')
    else:
        lines.append(f'Your {name} WE was {show(sim, weNet)} this phase.')
    if rule != '':
        lines.append(f'In the lecture machine, {name} loads on {rule}.')
    return lines

def statusKind(status):
    return status.split(':')[0]

def checkerStep(checker, sim):
    # After the user's machine ran a phase: run the lecture's to the same
    # phase and compare. Returns a difference or None.
    checkerGoTo(checker, sim['halfCycles'])
    return compareWithGolden(sim, checker['cpu'])

def runAndCompare(sim, memory, maxPhases=20000):
    # Runs both machines from the start; returns (phase, difference) at the
    # first difference, or (phases run, None)
    from zb_sim import loadProgram, stepPhase
    loadProgram(sim, memory)
    checker = makeChecker(memory)
    count = 0
    while not sim['halted'] and count < maxPhases:
        stepPhase(sim)
        count += 1
        difference = checkerStep(checker, sim)
        if difference != None:
            return count, difference
    return count, None

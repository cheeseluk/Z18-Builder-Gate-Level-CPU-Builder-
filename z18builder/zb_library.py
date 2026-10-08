# zb_library.py
# Parts made of other parts (composites): making them, saving them,
# checking that one does the same job as a built-in part, and looking
# inside a part while the machine runs. No graphics here.
#
# A composite definition is
#   {'name', 'label', 'kind': 'composite', 'level': 3, 'shape',
#    'circuit', 'implements' (a built-in type or None), 'verified',
#    'stateful', 'help'}
# Its ports are the PIN_IN / PIN_OUT parts inside its circuit.

import os
import copy
import json
import random
from zb_values import Z, X, mask, formatValue
from zb_parts import PRIMITIVES, STATEFUL_TYPES
from zb_circuit import (getDefinition, definitionChanged, partLayout,
                        makeCircuit, addPart, addWire, findPart,
                        computeNets, getDrivers, nodeKey, circuitToText,
                        circuitFromText, compositeInfo, portsMatch,
                        partBounds, cleanUpJunctions, getPort)
from zb_sim import flatten, settle, netValueAt, primName

EXHAUSTIVE_BITS = 16
RANDOM_VECTORS = 2000
EDGE_VALUES = [0, 1, 0x7F, 0x80, 0xFF, 0x55, 0xAA]


######################################################################
# Making user parts
######################################################################

def containsState(library, circuit, depth=0):
    # True if anything inside holds state: a register, RAM, clock, ... or
    # a loop of gates (a latch remembers on its wires)
    if depth > 12:
        return False
    for part in circuit['parts']:
        if part['type'] in STATEFUL_TYPES:
            return True
        definition = getDefinition(library, part['type'])
        if (definition != None and definition['kind'] == 'composite' and
            containsState(library, definition['circuit'], depth + 1)):
            return True
    if depth == 0:
        return len(gateLoopsIn(library, circuit)) > 0
    return False

def gateLoopsIn(library, circuit):
    # The loops of gates in a circuit (flattened), as lists of prims
    sim = flatten(library, circuit)
    return [[sim['prims'][i] for i in loop] for loop in sim['loops']]

def remembersReason(library, circuit):
    # Why a circuit's outputs depend on what came before, or None
    sim = flatten(library, circuit)
    if len(sim['loops']) > 0:
        names = [primName(sim, sim['prims'][i]) for i in sim['loops'][0]]
        return ('it has a loop through ' + ' and '.join(names[:4]) +
                (' ...' if len(names) > 4 else ''))
    for part in circuit['parts']:
        if part['type'] in STATEFUL_TYPES:
            return f"it has a {PRIMITIVES[part['type']]['label']}"
    return None

def oneEditApart(a, b):
    # True if a and b differ by at most one letter (changed, added or cut)
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) <= 1
    if len(a) > len(b):
        a, b = b, a
    for i in range(len(b)):
        if b[:i] + b[i + 1:] == a:
            return True
    return False

def looksLike(name, other):
    return (name.lower() == other.lower() or oneEditApart(name.lower(),
                                                          other.lower()) or
            name[:1].lower() == other[:1].lower())

def pinsDiff(myPorts, wantedPorts):
    # A message listing what is missing, extra, the wrong width or the
    # wrong way round, or None if the pins match
    mine = {p['name']: p for p in myPorts}
    wanted = {p['name']: p for p in wantedPorts}
    def describe(port):
        bits = 'bit' if port['width'] == 1 else 'bits'
        kind = 'IN' if port['dir'] == 'in' else 'OUT'
        return f"{kind} {port['name']} ({port['width']} {bits})"
    missing = [p for name, p in wanted.items() if name not in mine]
    extra = [p for name, p in mine.items() if name not in wanted]
    pieces = []
    if len(missing) > 0:
        pieces.append('Missing: ' + ', '.join(describe(p) for p in missing)
                      + '.')
    for port in extra:
        text = f'Extra: {describe(port)}'
        for other in missing:
            if other['dir'] == port['dir'] and looksLike(port['name'],
                                                          other['name']):
                text += f", did you mean {other['name']}?"
                break
        pieces.append(text + ('' if text.endswith('?') else '.'))
    for name in mine:
        if name not in wanted:
            continue
        mineP, want = mine[name], wanted[name]
        if mineP['dir'] != want['dir']:
            kind = 'IN' if mineP['dir'] == 'in' else 'OUT'
            should = 'IN' if want['dir'] == 'in' else 'OUT'
            pieces.append(f'Wrong direction: {name} is an {kind} pin, '
                          f'should be {should}.')
        elif mineP['width'] != want['width']:
            pieces.append(f"Wrong width: {portKind(mineP)} {name} is "
                          f"{mineP['width']} bits, should be "
                          f"{want['width']}.")
    if len(pieces) == 0:
        return None
    return "The pins don't match yet. " + ' '.join(pieces)

def portKind(port):
    return 'IN' if port['dir'] == 'in' else 'OUT'

STATEFUL_MESSAGE = ('This part remembers (it has a register or a gate '
                    'loop), so it can\'t be checked with a truth table. The '
                    'Memory missions check parts like this with a step '
                    'table.')

def makeUserPart(library, name, circuit, shape='box', implements=None):
    definition = {'name': name, 'label': name, 'kind': 'composite',
                  'level': 3, 'shape': shape, 'circuit': circuit,
                  'implements': implements, 'verified': False,
                  'stateful': False, 'help': 'A part you built.'}
    library['user'][name] = definition
    updateUserPart(library, definition)
    return definition

def updateUserPart(library, definition):
    # Call after the part's circuit changes: it must be verified again
    definition['stateful'] = containsState(library, definition['circuit'])
    definitionChanged(library)

def partToText(definition):
    data = dict()
    for key in ['name', 'label', 'shape', 'implements', 'verified', 'help']:
        data[key] = definition[key]
    for key in ['checkedBy', 'size']:  # (optional: 'sequence', [w, h])
        if definition.get(key) != None:
            data[key] = definition[key]
    data['circuit'] = json.loads(circuitToText(definition['circuit']))
    return json.dumps(data, indent=1)

def saveUserPart(definition, folder):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, safeFileName(definition['name']) + '.json')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(partToText(definition))

def deleteUserPartFile(name, folder):
    path = os.path.join(folder, safeFileName(name) + '.json')
    if os.path.exists(path):
        os.remove(path)

def safeFileName(name):
    result = ''
    for c in name:
        if c.isalnum() or c in '-_':
            result += c
        else:
            result += '_'
    return result

def loadUserParts(library, folder):
    # Reads every part in folder; returns a list of error messages
    errors = []
    if not os.path.isdir(folder):
        return errors
    for fileName in sorted(os.listdir(folder)):
        if not fileName.endswith('.json') or fileName == 'progress.json':
            continue
        try:
            with open(os.path.join(folder, fileName), encoding='utf-8') as f:
                data = json.loads(f.read())
            circuit = circuitFromText(json.dumps(data['circuit']))
            definition = makeUserPart(library, data['name'], circuit,
                                      data.get('shape', 'box'),
                                      data.get('implements'))
            definition['label'] = data.get('label', data['name'])
            definition['verified'] = data.get('verified', False)
            definition['help'] = data.get('help', 'A part you built.')
            for key in ['checkedBy', 'size']:
                if data.get(key) != None:
                    definition[key] = data[key]
        except (OSError, ValueError, KeyError) as error:
            errors.append(f'{fileName}: {error}')
    for definition in library['user'].values():
        definition['stateful'] = containsState(library,
                                               definition['circuit'])
    definitionChanged(library)
    return errors

def getPorts(library, typeName):
    # The ports of a part type with its default parameters
    definition = getDefinition(library, typeName)
    if definition['kind'] == 'primitive':
        return definition['layout'](dict(definition['params']))[2]
    return compositeInfo(library, typeName)['layout'][2]


######################################################################
# Packing a selection into a part
######################################################################

def uniqueName(name, used):
    result = name
    n = 2
    while result in used:
        result = f'{name}{n}'
        n += 1
    used.add(result)
    return result

def packSelection(library, circuit, partIds, name):
    # Moves the chosen parts into a new user part, puts one instance of it
    # where they were, and keeps the connections through its pins.
    # Returns (definition, newPart), or (None, message).
    if name in library['user'] or name in PRIMITIVES:
        return None, f'There is already a part called {name}'
    ids = set(partIds)
    if len(ids) == 0:
        return None, 'Select some parts first'
    for partId in ids:
        if findPart(circuit, partId)['type'] in ['PIN_IN', 'PIN_OUT']:
            return None, 'Pins cannot be packed (they are a part\'s ports)'
    nets = computeNets(library, circuit)
    inner = makeCircuit(name)
    innerIds = dict()
    left, top = None, None
    for part in circuit['parts']:
        if part['id'] in ids:
            copied = copy.deepcopy(part)
            copied['id'] = 'p' + str(inner['nextId'])
            inner['nextId'] += 1
            innerIds[part['id']] = copied['id']
            inner['parts'].append(copied)
            x, y, w, h = partBounds(library, part)
            left = x if left == None else min(left, x)
            top = y if top == None else min(top, y)
    # Wires wholly inside the selection come along
    for wire in circuit['wires']:
        if (wire['a'][0] == 'port' and wire['a'][1] in ids and
            wire['b'][0] == 'port' and wire['b'][1] in ids):
            newWire = addWire(inner, ['port', innerIds[wire['a'][1]],
                                      wire['a'][2]],
                              ['port', innerIds[wire['b'][1]],
                               wire['b'][2]], wire['via'])
            newWire['color'] = wire['color']
    innerNets = computeNets(library, inner)
    used = set()
    crossing = []                  # (pinName, outer ports, inner ports)
    for net in nets['nets']:
        insidePorts = [p for p in net['ports'] if p[0] in ids]
        outsidePorts = [p for p in net['ports'] if p[0] not in ids]
        if len(insidePorts) == 0:
            continue
        # Join inside pieces the kept wires don't join (e.g. through a
        # junction outside the selection)
        groups = groupPorts(innerNets, innerIds, insidePorts)
        if len(outsidePorts) == 0:
            for group in groups[1:]:
                addWire(inner, portEnd(innerIds, groups[0][0]),
                        portEnd(innerIds, group[0]))
            continue
        pinName = uniqueName(insidePorts[0][1], used)
        crossing.append((pinName, net, groups))
    # Add a pin for every connection that crosses the edge
    pinY = {'in': 0, 'out': 0}
    pins = []
    for pinName, net, groups in crossing:
        drivers = getDrivers(library, circuit, net)
        insideDrives = any(d[0] in ids for d in drivers)
        direction = 'out' if insideDrives else 'in'
        width = getPort(library, findPart(circuit, net['ports'][0][0]),
                        net['ports'][0][1])['width']
        x = left - 80 if direction == 'in' else left + 400
        pin = addPart(library, inner, 'PIN_IN' if direction == 'in'
                      else 'PIN_OUT', x, top + pinY[direction],
                      {'name': pinName, 'width': width})
        pinY[direction] += 40
        pinPort = 'out' if direction == 'in' else 'in'
        for group in groups:
            addWire(inner, ['port', pin['id'], pinPort],
                    portEnd(innerIds, group[0]))
        pins.append((pinName, net))
    shape = 'box'
    definition = makeUserPart(library, name, inner, shape)
    # Replace the selection with one instance, wired to the same places
    for partId in ids:
        removeOnly(circuit, partId)
    newPart = addPart(library, circuit, name, left, top)
    for pinName, net in pins:
        outsideEnds = []
        for partId, portName in net['ports']:
            if partId not in ids:
                outsideEnds.append(['port', partId, portName])
        connected = set()
        for end in outsideEnds:
            key = nodeKey(end)
            if key in connected:
                continue
            addWire(circuit, ['port', newPart['id'], pinName], end)
            # Anything already joined to this end outside needs no wire
            after = computeNets(library, circuit)
            netIndex = after['nodeNet'][key]
            for other in outsideEnds:
                if after['nodeNet'].get(nodeKey(other)) == netIndex:
                    connected.add(nodeKey(other))
    cleanUpJunctions(circuit)
    return definition, newPart

def removeOnly(circuit, partId):
    # Removes a part and its wires but keeps junctions as they are
    part = findPart(circuit, partId)
    circuit['parts'].remove(part)
    for wire in list(circuit['wires']):
        if (wire['a'][0] == 'port' and wire['a'][1] == partId or
            wire['b'][0] == 'port' and wire['b'][1] == partId):
            circuit['wires'].remove(wire)

def portEnd(innerIds, port):
    return ['port', innerIds[port[0]], port[1]]

def groupPorts(innerNets, innerIds, ports):
    # The ports, grouped by which inner net they are on
    groups = dict()
    for partId, portName in ports:
        key = ('port', innerIds[partId], portName)
        index = innerNets['nodeNet'].get(key, key)
        groups.setdefault(index, []).append((partId, portName))
    return list(groups.values())


######################################################################
# Testing a circuit through its pins
######################################################################

def makeTester(library, circuit):
    # A simulator of the circuit where the input pins are switches
    sim = flatten(library, circuit)
    tester = {'sim': sim, 'inputs': dict(), 'outputs': dict()}
    for prim in sim['prims']:
        if prim['type'] == 'PIN_IN':
            tester['inputs'][prim['params']['name']] = prim['index']
        elif prim['type'] == 'PIN_OUT':
            tester['outputs'][prim['params']['name']] = prim['inNets']['in']
    return tester

def runTester(tester, inputs):
    # Sets the input pins, settles, returns {output name: value}
    sim = tester['sim']
    for name, value in inputs.items():
        index = tester['inputs'].get(name)
        if index != None and sim['prims'][index]['state'] != value:
            sim['prims'][index]['state'] = value
            sim['seeds'].add(index)
    settle(sim)
    outputs = dict()
    for name, netIndex in tester['outputs'].items():
        outputs[name] = sim['nets'][netIndex]['value']
    return outputs

def makeVectors(ports):
    # Every input combination if there are few, else edge cases + random
    inputs = [p for p in ports if p['dir'] == 'in']
    inputs.sort(key=lambda p: p['name'])
    totalBits = sum(p['width'] for p in inputs)
    vectors = []
    if totalBits <= EXHAUSTIVE_BITS:
        for n in range(1 << totalBits):
            vector = dict()
            for port in inputs:
                vector[port['name']] = n & mask(port['width'])
                n >>= port['width']
            vectors.append(vector)
        return vectors, True
    rng = random.Random(18100)
    for edge in EDGE_VALUES:
        vector = dict()
        for port in inputs:
            vector[port['name']] = edge & mask(port['width'])
        vectors.append(vector)
    for i in range(RANDOM_VECTORS):
        vector = dict()
        for port in inputs:
            if rng.random() < 0.2:
                value = rng.choice(EDGE_VALUES)
            else:
                value = rng.randrange(1 << port['width'])
            vector[port['name']] = value & mask(port['width'])
        vectors.append(vector)
    return vectors, False

def describeVector(vector, ports):
    widths = dict()
    for port in ports:
        widths[port['name']] = port['width']
    parts = []
    for name in sorted(vector):
        parts.append(f"{name}={formatValue(vector[name], widths[name])}")
    return '  '.join(parts)

######################################################################
# Truth tables
######################################################################

TABLE_BITS = 8                 # up to this many input bits: every row

def orderedPins(circuit):
    # (inputs, outputs): the IN and OUT pins in canvas order (top to
    # bottom, then left to right)
    from zb_circuit import getPins
    return getPins(circuit)

def pinColumns(pins, portOrder=None):
    # [{'name', 'width'}] for the pins; names in portOrder come first, in
    # that order
    columns = [{'name': p['params']['name'], 'width': p['params']['width']}
               for p in pins]
    if portOrder != None:
        rank = {name: i for i, name in enumerate(portOrder)}
        columns.sort(key=lambda c: rank.get(c['name'], len(rank)))
    return columns

def tableVectors(inputs, maxBits=TABLE_BITS):
    # (vectors, exhaustive). Textbook order: the first input is the most
    # significant, so a b cin count 000, 001, ..., 111. Too many bits: the
    # same sample makeVectors uses (edge cases + random).
    totalBits = sum(column['width'] for column in inputs)
    if totalBits > maxBits:
        ports = [{'name': c['name'], 'dir': 'in', 'width': c['width']}
                 for c in inputs]
        return makeVectors(ports)[0], False
    vectors = []
    for n in range(1 << totalBits):
        vector = dict()
        for column in reversed(inputs):
            vector[column['name']] = n & mask(column['width'])
            n >>= column['width']
        vectors.append(vector)
    return vectors, True

def truthTable(library, circuit, expected=None, portOrder=None,
               maxBits=TABLE_BITS):
    # What the circuit does for every input row (or a sample):
    #   {'inputs', 'outputs', 'rows': [{'in', 'got', 'expected', 'wrong'}],
    #    'exhaustive', 'total', 'stateful', 'reason', 'hasExpected'}
    # expected: a function {input: value} -> {output: value}, or None. A
    # fresh tester is used (never the running machine).
    pinsIn, pinsOut = orderedPins(circuit)
    inputs = pinColumns(pinsIn, portOrder)
    outputs = pinColumns(pinsOut, portOrder)
    totalBits = sum(column['width'] for column in inputs)
    table = {'kind': 'truth', 'name': circuit['name'],
             'inputs': inputs, 'outputs': outputs, 'rows': [],
             'exhaustive': True, 'total': 1 << totalBits,
             'stateful': False, 'reason': None,
             'hasExpected': expected != None}
    if containsState(library, circuit):
        table['stateful'] = True
        table['reason'] = remembersReason(library, circuit)
        return table
    if len(inputs) == 0 or len(outputs) == 0:
        table['reason'] = 'it needs IN and OUT pins'
        return table
    tester = makeTester(library, circuit)
    vectors, exhaustive = tableVectors(inputs, maxBits)
    table['exhaustive'] = exhaustive
    rows = []
    for vector in vectors:
        got = runTester(tester, vector)
        want = expected(vector) if expected != None else None
        wrong = []
        if want != None:
            for column in outputs:
                name = column['name']
                if name in want and want[name] != got.get(name):
                    wrong.append(name)
        rows.append({'in': dict(vector), 'got': got, 'expected': want,
                     'wrong': wrong})
    if not exhaustive:
        # wrong rows first, so they are seen
        rows.sort(key=lambda row: len(row['wrong']) == 0)
    table['rows'] = rows
    return table

def builtInExpected(typeName):
    # The expected-output function of a built-in part, for truthTable
    target = PRIMITIVES[typeName]
    params = dict(target['params'])
    return lambda vector: target['evaluate'](params, vector, None)

def tableSummary(table):
    # '8 rows · 7 right · 1 wrong' (or '8 rows' with nothing to compare)
    count = len(table['rows'])
    text = f"{count} {'steps' if table.get('kind') == 'steps' else 'rows'}"
    if table['hasExpected']:
        wrong = len([row for row in table['rows'] if row['wrong']])
        text += f' · {count - wrong} right · {wrong} wrong'
    return text

def tableTitle(table):
    if table.get('kind') == 'steps':
        return f"{len(table['rows'])} steps, from power-on"
    if table['exhaustive']:
        return f"Every input ({table['total']:,} rows)"
    return (f"A sample of {len(table['rows']):,} of {table['total']:,} "
            'inputs')


def verifyPart(library, definition, targetType):
    # Checks a user part against a built-in one. Returns
    # {'ok', 'tested', 'exhaustive', 'message', 'mismatch'}
    target = PRIMITIVES.get(targetType)
    if target == None:
        return {'ok': False, 'message': f'No built-in part {targetType}'}
    if definition['stateful'] or target['commit'] != None:
        return {'ok': False, 'code': 'verifyStateful',
                'message': STATEFUL_MESSAGE}
    targetPorts = target['layout'](dict(target['params']))[2]
    info = compositeInfo(library, definition['name'])
    myPorts = info['layout'][2]
    if not portsMatch(myPorts, targetPorts):
        return {'ok': False, 'code': 'pins',
                'message': pinsDiff(myPorts, targetPorts)}
    tester = makeTester(library, definition['circuit'])
    vectors, exhaustive = makeVectors(targetPorts)
    for count in range(len(vectors)):
        vector = vectors[count]
        expected = target['evaluate'](dict(target['params']), vector, None)
        got = runTester(tester, vector)
        for name in expected:
            if expected[name] != got.get(name):
                width = 1
                for port in targetPorts:
                    if port['name'] == name:
                        width = port['width']
                return {'ok': False, 'tested': count + 1,
                        'exhaustive': exhaustive,
                        'mismatch': {'inputs': describeVector(vector,
                                                              targetPorts),
                                     'output': name,
                                     'expected': formatValue(expected[name],
                                                             width),
                                     'got': formatValue(got.get(name, X),
                                                        width)},
                        'message': f'{name} is wrong for '
                                   f'{describeVector(vector, targetPorts)}'}
    definition['implements'] = targetType
    definition['verified'] = True
    definitionChanged(library)
    kind = 'every' if exhaustive else 'edge case and random'
    return {'ok': True, 'tested': len(vectors), 'exhaustive': exhaustive,
            'mismatch': None,
            'message': f'Matches {targetType} on {kind} input '
                       f'({len(vectors)} tested)'}


######################################################################
# Looking inside a part while the machine runs
######################################################################

# A view is what the canvas shows at one level:
#   {'circuit', 'sim', 'prefix', 'live', 'readOnly'}
# prefix is the path of the level in sim; live means the sim is the real
# running machine (so the animation waves apply).

def topView(circuit, sim):
    return {'circuit': circuit, 'sim': sim, 'prefix': (), 'live': True,
            'readOnly': False}

def getInnerCircuit(library, part):
    # (circuit, readOnly) inside a part, or (None, None) if it is atomic
    definition = getDefinition(library, part['type'])
    if definition == None:
        return None, None
    if definition['kind'] == 'composite':
        return definition['circuit'], False
    recipe = library['recipes'].get(part['type'])
    if recipe == None:
        return None, None
    return recipe(part['params']), True

def innerView(library, view, part):
    # The view inside a part, or None if the part can't be opened
    circuit, readOnly = getInnerCircuit(library, part)
    if circuit == None:
        return None
    sim = view['sim']
    path = view['prefix'] + (part['id'],)
    if sim == None:
        return {'circuit': circuit, 'sim': None, 'prefix': (),
                'live': False, 'readOnly': readOnly}
    if path in sim['composites']:
        return {'circuit': circuit, 'sim': sim, 'prefix': path,
                'live': view['live'], 'readOnly': readOnly}
    # A primitive (or a fast part): simulate its inside once, with the
    # values its ports have right now
    tester = makeTester(library, circuit)
    inputs = dict()
    for port in partLayout(library, part)[2]:
        if port['dir'] == 'in':
            value = netValueAt(sim, ('port', path, port['name']))
            inputs[port['name']] = Z if value == None else value
    index = sim['primByPath'].get(path)
    stateRecipe = library.get('recipeStates', dict()).get(part['type'])
    if index != None and stateRecipe != None:
        # The recipe's registers (found by label) get the part's state
        states = stateRecipe(sim['prims'][index]['state'])
        for prim in tester['sim']['prims']:
            if prim['label'] in states:
                prim['state'] = states[prim['label']]
    tester['sim']['seeds'] = set(range(len(tester['sim']['prims'])))
    runTester(tester, inputs)
    return {'circuit': circuit, 'sim': tester['sim'], 'prefix': (),
            'live': False, 'readOnly': readOnly}

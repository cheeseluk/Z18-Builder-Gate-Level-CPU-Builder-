# zb_explain.py
# Why a wire carries what it carries: traces an unknown (x) or floating
# (Z) value back to where it starts, explains a wrong output gate by gate,
# and builds the detailed messages for the run's stops (bus contention,
# a register loading x). No graphics here.
#
# A problem (from validate, a stop, or a mission check) is a dict:
#   {'level': 'error' | 'warning', 'code', 'text' (one line: what),
#    'why': [lines] (the cause), 'fix' (one line), 'parts', 'wires',
#    'nets', 'prims'}

from zb_values import Z, X, isKnown, formatValue
from z18_assembler import shortDisassemble
from z18_isa import LECTURE_ISA, OPCODE_SLOTS

MAX_STEPS = 6


######################################################################
# Names, in the user's words
######################################################################

def primName(sim, prim):
    from zb_sim import primName as simPrimName
    return simPrimName(sim, prim)

def portText(sim, index, port):
    # 'AND1.in1', or 'pin cin' for a pin
    prim = sim['prims'][index]
    if prim['type'] in ['PIN_IN', 'PIN_OUT']:
        return f"pin {prim['params']['name']}"
    return f'{primName(sim, prim)}.{port}'

def netWidth(sim, netIndex):
    return sim['nets'][netIndex]['width']

def show(sim, netIndex, value=None):
    if value == None:
        value = sim['nets'][netIndex]['value']
    return formatValue(value, netWidth(sim, netIndex))

def netName(sim, netIndex):
    # 'the data bus', 'the address bus', or 'the wire into AND1.in0'
    net = sim['nets'][netIndex]
    for index, port in net['drivers']:
        if sim['prims'][index]['type'] == 'RAM' and port == 'dout':
            return 'the data bus'
    for index in net['readers']:
        prim = sim['prims'][index]
        if prim['type'] == 'RAM' and prim['inNets'].get('addr') == netIndex \
                and len(net['drivers']) >= 2:
            return 'the address bus'
    for index in net['readers']:
        prim = sim['prims'][index]
        for port, other in prim['inNets'].items():
            if other == netIndex:
                return f'the wire into {portText(sim, index, port)}'
    if len(net['drivers']) > 0:
        index, port = net['drivers'][0]
        return f'the wire from {portText(sim, index, port)}'
    return 'a wire'

def activeDrivers(net):
    return [key for key, value in net['driverValues'].items() if value != Z]

def sourceText(sim, netIndex):
    # Where a net's value comes from: 'decoder output 9 (STORE)', 'pin a',
    # or 'AND1.out'
    net = sim['nets'][netIndex]
    drivers = activeDrivers(net) or net['drivers']
    if len(drivers) == 0:
        return 'nothing'
    index, port = drivers[0]
    prim = sim['prims'][index]
    if prim['type'] == 'DECODER' and port.startswith('d'):
        k = int(port[1:])
        name = ''
        instruction = (sim.get('isa') or LECTURE_ISA)['byOpcode'][k]             if k < OPCODE_SLOTS else None
        if prim['params'].get('bits') == 4 and instruction != None:
            name = f" ({instruction['name']})"
        return f'decoder output {k}{name}'
    return portText(sim, index, port)

def phaseText(sim):
    # 'phase 14 (execute, LOAD R2,M5)' for the phase being settled
    text = f"phase {sim['halfCycles'] + 1} ({sim['phase']}"
    for prim in sim['prims']:
        if prim['ref'] == 'ir':
            if isKnown(prim['state']) and sim['phase'] == 'execute':
                text += ', ' + shortDisassemble(prim['state'], 'code',
                                                sim.get('isa'))
            break
    return text + ')'


######################################################################
# Tracing x and Z back to where they start
######################################################################

def step(sim, netIndex, text, prim=None, port=None):
    return {'prim': prim, 'port': port, 'net': netIndex,
            'value': sim['nets'][netIndex]['value'], 'text': text}

def offReason(sim, index, port):
    # Why a tri-state output is off (floats)
    prim = sim['prims'][index]
    name = portText(sim, index, port)
    def value(inPort):
        netIndex = prim['inNets'].get(inPort)
        return '?' if netIndex == None else show(sim, netIndex)
    if prim['type'] == 'TG':
        enNet = prim['inNets']['en']
        return (f"{name} is off: en = {value('en')} (from "
                f'{sourceText(sim, enNet)})')
    if prim['type'] == 'RAM':
        return f"{name} is off: RE = {value('re')}"
    if prim['type'] == 'DEMUX':
        return f"{name} is off: e = {value('e')}, sel = {value('sel')}"
    return f'{name} is off'

def unknownInput(sim, prim):
    # The input port that makes a part's output unknown, or None. Selects
    # and enables come first: with those unknown, nothing else matters.
    nets = sim['nets']
    ordered = sorted(prim['inNets'], key=lambda port:
                     port not in ['sel', 'en', 'e', 're', 'addr'])
    if prim['type'] in ['MUX2', 'MUX4']:
        sel = nets[prim['inNets']['sel']]['value']
        if isKnown(sel):
            ordered = ['in' + str(sel)]
    for port in ordered:
        value = nets[prim['inNets'][port]]['value']
        if not isKnown(value):
            return port
    return None

def loopLabel(sim, loopIndex):
    names = [primName(sim, sim['prims'][i]) for i in sim['loops'][loopIndex]]
    return '/'.join(names)

def explainUnknownDriver(sim, index, port, netIndex):
    # (step text, the next net to follow or None) for a driver putting x
    # on a net
    prim = sim['prims'][index]
    name = portText(sim, index, port)
    state = prim['state']
    typeName = prim['type']
    if typeName == 'RAM' and port == 'dout':
        address = sim['nets'][prim['inNets']['addr']]['value']
        re = sim['nets'][prim['inNets']['re']]['value']
        if not isKnown(re):
            return f'{name} is x because its RE is x', prim['inNets']['re']
        if not isKnown(address):
            return (f'{name} is x because its address is x',
                    prim['inNets']['addr'])
        if not isKnown(state[address]):
            return (f'{name} is x: M[{address}] was never set (the program '
                    "doesn't write it)"), None
    held = state[port[0]] if typeName == 'FLAGS' else state
    if prim['defn']['commit'] != None and typeName != 'RAM' and \
            not isKnown(held):
        if prim['ref'] == 'ir' or typeName == 'IR':
            return f"{name} is x: the IR hasn't loaded anything yet", None
        return (f'{name} is x: {primName(sim, prim)} holds xxxxxxxx (it '
                'never loaded a known value)'), None
    loopIndex = sim.get('loopOf', dict()).get(index)
    if loopIndex != None:
        if index in sim.get('loopParts', []) and sim.get('loopDetail'):
            return sim['loopDetail']['text'], None
        return (f'{name} is x: the latch {loopLabel(sim, loopIndex)} has '
                'never been set or reset since power-on (pulse S or R)'), None
    inPort = unknownInput(sim, prim)
    if inPort == None:
        return f'{name} is x', None
    inNet = prim['inNets'][inPort]
    inValue = sim['nets'][inNet]['value']
    if inValue == Z and len(sim['nets'][inNet]['drivers']) == 0:
        return (f'{name} is x because {portText(sim, index, inPort)} is not '
                'connected (it floats)'), None
    word = 'floats (Z)' if inValue == Z else 'is x'
    return (f'{name} is x because {portText(sim, index, inPort)} {word}',
            inNet)

def explainValue(sim, netIndex, depth=MAX_STEPS):
    # [{'prim', 'port', 'net', 'value', 'text'}]: why a net is x or Z,
    # step by step back to a source (empty if its value is known)
    steps = []
    visited = set()
    while netIndex != None:
        if netIndex in visited:
            break
        if len(steps) >= depth:
            steps.append(step(sim, netIndex, '... and more steps'))
            break
        visited.add(netIndex)
        net = sim['nets'][netIndex]
        value = net['value']
        if value == Z:
            if len(net['drivers']) == 0:
                steps.append(step(sim, netIndex, f'{netName(sim, netIndex)}'
                                  ' floats: nothing is wired to drive it'))
                break
            reasons = [offReason(sim, i, p) for i, p in net['drivers']]
            steps.append(step(sim, netIndex, f'{netName(sim, netIndex)} '
                              'floats: ' + '; '.join(reasons[:3])))
            break
        if value != X:
            break
        active = activeDrivers(net)
        if len(active) >= 2:
            pieces = [f'{portText(sim, i, p)} drives '
                      f'{show(sim, netIndex, net["driverValues"][(i, p)])}'
                      for i, p in active[:3]]
            steps.append(step(sim, netIndex, f'{netName(sim, netIndex)} is '
                              'x: two parts drive it at once (' +
                              ', '.join(pieces) + ')'))
            break
        if len(active) == 0:
            # driven, but every driver says Z, and yet it is X: a reader
            # sees floating as x
            steps.append(step(sim, netIndex, f'{netName(sim, netIndex)} is '
                              'x'))
            break
        index, port = active[0]
        text, following = explainUnknownDriver(sim, index, port, netIndex)
        steps.append(step(sim, netIndex, text, index, port))
        netIndex = following
    return steps

def explainLines(steps):
    return [s['text'] for s in steps]


######################################################################
# Explaining a known but wrong output (truth-table rows)
######################################################################

def explainOutput(sim, netIndex, depth=3):
    # (lines, cone): the logic that produced a net's value, one level per
    # line, with input values; cone = {'prims', 'nets'} is everything it
    # depends on (to highlight)
    lines = []
    cone = {'prims': set(), 'nets': set()}
    def walk(netIndex, label, level):
        cone['nets'].add(netIndex)
        net = sim['nets'][netIndex]
        value = show(sim, netIndex)
        drivers = activeDrivers(net) or net['drivers']
        if len(drivers) == 0:
            if level <= depth:
                lines.append('  ' * level + f'{label} = {value}: nothing '
                             'drives it')
            return
        index, port = drivers[0]
        prim = sim['prims'][index]
        if index in cone['prims']:
            return
        cone['prims'].add(index)
        if prim['type'] == 'PIN_IN':
            if level <= depth:
                lines.append('  ' * level + f'{label} = {value} comes from '
                             f"pin {prim['params']['name']}")
            return
        inputs = ', '.join(f'{p} = {show(sim, n)}' for p, n in
                           prim['inNets'].items())
        if level <= depth:
            lines.append('  ' * level + f'{label} = {value} comes from '
                         f'{primName(sim, prim)} ({inputs})')
        if prim['defn']['commit'] != None:
            return                     # a register: its value is its state
        for inPort, inNet in prim['inNets'].items():
            walk(inNet, f'{primName(sim, prim)}.{inPort}', level + 1)
    netLabel = None
    for index in sim['nets'][netIndex]['readers']:
        prim = sim['prims'][index]
        if prim['type'] == 'PIN_OUT':
            netLabel = prim['params']['name']
    walk(netIndex, netLabel or netName(sim, netIndex), 0)
    return lines, cone


######################################################################
# Details for the run's stops
######################################################################

def contentionDetail(sim, netIndex, drivers):
    net = sim['nets'][netIndex]
    where = netName(sim, netIndex)
    pieces = []
    why = []
    for index in drivers:
        for (i, port), value in net['driverValues'].items():
            if i == index and value != Z:
                pieces.append(f'{portText(sim, i, port)} drives '
                              f'{show(sim, netIndex, value)}')
                why.append(onReason(sim, i, port))
    names = [primName(sim, sim['prims'][i]) for i in drivers]
    text = (f"Two parts drive {where} at once: " + ' and '.join(pieces[:3])
            + '.')
    second = names[-1]
    return {'level': 'error', 'code': 'contention', 'text': text,
            'why': why,
            'fix': f"Only one driver may be on per phase. Check what turns "
                   f"on {second}'s enable.",
            'prims': list(drivers), 'nets': [netIndex], 'parts': [],
            'wires': []}

def onReason(sim, index, port):
    # Why a tri-state output is driving
    prim = sim['prims'][index]
    name = primName(sim, prim)
    def value(inPort):
        return show(sim, prim['inNets'][inPort])
    if prim['type'] == 'TG':
        return (f"{name} is open because en = {value('en')}, from "
                f"{sourceText(sim, prim['inNets']['en'])}.")
    if prim['type'] == 'RAM':
        return (f"{name} drives dout because RE = {value('re')}, from "
                f"{sourceText(sim, prim['inNets']['re'])}.")
    if prim['type'] == 'DEMUX':
        return f"{name} drives {port} because e = {value('e')}."
    return f'{name} drives it.'

def loadProblemDetail(sim, index, problem):
    # A register that would load x (or whose WE is x), with the cause
    prim = sim['prims'][index]
    name = primName(sim, prim)
    what = problem
    if what.startswith('its '):
        what = f"'s {what[4:]}"            # R2's WE is unknown
    else:
        what = ' ' + what
    text = f'{name}{what} in {phaseText(sim)}.'
    why = []
    fix = f'Check what drives {name}.d.'
    if 'WE is unknown' in problem or 'its WE' in problem:
        netIndex = prim['inNets'].get('we')
        if netIndex != None:
            why = explainLines(explainValue(sim, netIndex))
        fix = f'Wire {name}.we to a control line (or a CONST 0).'
    else:
        port = 'din' if prim['type'] == 'RAM' else 'd'
        if 'address' in problem:
            port = 'addr'
        netIndex = prim['inNets'].get(port)
        if netIndex != None:
            steps = explainValue(sim, netIndex)
            why = [f'{name}.{port} comes from {netName(sim, netIndex)}'] + \
                explainLines(steps)
            for s in steps:
                if 'was never set' in s['text'] and 'M[' in s['text']:
                    address = s['text'].split('M[')[1].split(']')[0]
                    fix = (f'Set M[{address}] in the program, or check what '
                           f'drives {name}.{port}.')
    return {'level': 'error', 'code': 'loadsUnknown', 'text': text,
            'why': why, 'fix': fix, 'prims': [index], 'parts': [],
            'wires': [], 'nets': []}

def partsOnLevel(sim, prims, prefix):
    # The ids of the parts at the level with this path prefix that hold
    # (or are) the given prims
    parts = set()
    for index in prims:
        path = sim['prims'][index]['path']
        if path[:len(prefix)] == prefix and len(path) > len(prefix):
            parts.add(path[len(prefix)])
    return parts

# zb_sim.py
# Runs a circuit. No graphics here.
#
# flatten() turns a circuit (with parts inside parts) into a flat list of
# primitives joined by nets. Each clock phase then works in two steps,
# like the golden model (../z18100/z18_cpu.py):
#   beginPhase: set the clock, settle the logic in waves, work out what
#               every register would load, and check the run rules
#   endPhase:   the clock edge: every register loads at once (or the
#               machine halts)
# stepPhase does both. Settling is incremental: each phase starts from the
# last settled values, so only what changes moves. The wave numbers of
# the changes are what the animation plays.

from zb_values import Z, X
from zb_parts import PRIMITIVES, copyState
from zb_circuit import getDefinition, partLayout

MAX_PHASES = 20000
MAX_DEPTH = 12                 # parts inside parts inside ...
PHASES = ['fetch', 'execute']


######################################################################
# Flattening
######################################################################

def isFast(library, part, definition):
    # A user part runs as its built-in twin if it has been verified
    return (part['mode'] == 'fast' and definition.get('verified') and
            definition.get('implements') in PRIMITIVES and
            not definition.get('stateful'))

def addPrimitive(sim, path, part, definition, portNodes):
    # portNodes: {port name the primitive uses: node key}
    index = len(sim['prims'])
    prim = {'index': index, 'path': path, 'type': definition['name'],
            'defn': definition, 'params': part['params'],
            'ref': part.get('ref'), 'label': part.get('label', ''),
            'state': None, 'inNets': dict(), 'outNets': dict(),
            'portNodes': portNodes}
    if definition['initState'] != None:
        prim['state'] = definition['initState'](part['params'])
    sim['prims'].append(prim)
    sim['primByPath'][path] = index
    return prim

def addLevel(sim, library, circuit, prefix, parents):
    # Adds one circuit's parts (going inside composites) and its wires
    if len(prefix) > MAX_DEPTH:
        sim['buildErrors'].append('Parts are nested too deeply (a part '
                                  'that contains itself?)')
        return
    for part in circuit['parts']:
        path = prefix + (part['id'],)
        definition = getDefinition(library, part['type'])
        if definition == None:
            sim['buildErrors'].append(f"Unknown part type {part['type']}")
            continue
        ports = partLayout(library, part)[2]
        if part['type'] in ['PIN_IN', 'PIN_OUT'] and len(prefix) > 0:
            # A pin inside a composite joins the composite's port
            portName = ports[0]['name']
            inner = ('port', path, portName)
            outer = ('port', prefix, part['params']['name'])
            addNode(parents, inner)
            addNode(parents, outer)
            unionNodes(parents, inner, outer)
            continue
        if definition['kind'] == 'primitive':
            nodes = dict()
            for port in ports:
                nodes[port['name']] = ('port', path, port['name'])
            addPrimitive(sim, path, part, definition, nodes)
        elif isFast(library, part, definition):
            # The composite's port names match the built-in's
            builtIn = PRIMITIVES[definition['implements']]
            nodes = dict()
            for port in ports:
                nodes[port['name']] = ('port', path, port['name'])
            addPrimitive(sim, path, {'params': dict(builtIn['params']),
                                     'ref': part.get('ref'),
                                     'label': part.get('label', '')},
                         builtIn, nodes)
        else:
            sim['composites'][path] = part['type']
            addLevel(sim, library, definition['circuit'], path, parents)
        for port in ports:
            addNode(parents, ('port', path, port['name']))
    for junction in circuit['junctions']:
        addNode(parents, ('junction', prefix + (junction['id'],)))
    for wire in circuit['wires']:
        a = fullKey(prefix, wire['a'])
        b = fullKey(prefix, wire['b'])
        addNode(parents, a)
        addNode(parents, b)
        unionNodes(parents, a, b)

def fullKey(prefix, end):
    # The node key of a wire end, at the level given by prefix
    if end[0] == 'port':
        return ('port', prefix + (end[1],), end[2])
    return ('junction', prefix + (end[1],))

def addNode(parents, key):
    if key not in parents:
        parents[key] = key

def findRoot(parents, key):
    root = key
    while parents[root] != root:
        root = parents[root]
    while parents[key] != root:
        parents[key], key = root, parents[key]
    return root

def unionNodes(parents, a, b):
    rootA, rootB = findRoot(parents, a), findRoot(parents, b)
    if rootA != rootB:
        parents[rootA] = rootB

def buildNets(sim, parents):
    rootIndex = dict()
    for key in parents:
        root = findRoot(parents, key)
        if root not in rootIndex:
            rootIndex[root] = len(sim['nets'])
            sim['nets'].append({'index': len(sim['nets']), 'width': 1,
                                'drivers': [], 'readers': [], 'value': Z,
                                'driverValues': dict()})
        sim['nodeNet'][key] = rootIndex[root]
    for prim in sim['prims']:
        layout = prim['defn']['layout'](prim['params'])
        for port in layout[2]:
            netIndex = sim['nodeNet'][prim['portNodes'][port['name']]]
            net = sim['nets'][netIndex]
            net['width'] = port['width']
            if port['dir'] == 'out':
                prim['outNets'][port['name']] = netIndex
                net['drivers'].append((prim['index'], port['name']))
                net['driverValues'][(prim['index'], port['name'])] = Z
            else:
                prim['inNets'][port['name']] = netIndex
                if prim['index'] not in net['readers']:
                    net['readers'].append(prim['index'])

def flatten(library, circuit):
    sim = {'prims': [], 'nets': [], 'nodeNet': dict(), 'primByPath': dict(),
           'composites': dict(), 'buildErrors': [], 'rules': [],
           'problemRule': genericRule, 'program': None}
    parents = dict()
    addLevel(sim, library, circuit, (), parents)
    buildNets(sim, parents)
    sim['stateful'] = []
    sim['clocks'] = []
    for prim in sim['prims']:
        if prim['type'] == 'CLOCK':
            sim['clocks'].append(prim['index'])
        elif prim['defn']['commit'] != None:
            sim['stateful'].append(prim['index'])
    sim['sharedNets'] = []
    for net in sim['nets']:
        if len(net['drivers']) >= 2:
            sim['sharedNets'].append(net['index'])
    findGateLoops(sim)
    resetSim(sim)
    return sim


######################################################################
# Gate loops (latches, and rings that never settle)
######################################################################

def breaksLoops(prim):
    # A register's (or the clock's) outputs depend only on its state, so
    # a path through one is not a loop of logic
    return prim['defn']['commit'] != None or prim['type'] == 'CLOCK'

def gateGraph(sim):
    # {prim: [prims reading its outputs]}, without edges out of registers
    nets = sim['nets']
    graph = dict()
    for prim in sim['prims']:
        following = []
        if not breaksLoops(prim):
            for netIndex in prim['outNets'].values():
                for reader in nets[netIndex]['readers']:
                    if reader not in following:
                        following.append(reader)
        graph[prim['index']] = following
    return graph

def strongComponents(graph):
    # Tarjan's algorithm without recursion: lists of nodes that can all
    # reach each other
    index = dict()
    low = dict()
    onStack = set()
    stack = []
    components = []
    counter = 0
    for start in graph:
        if start in index:
            continue
        work = [(start, 0)]
        while len(work) > 0:
            node, i = work.pop()
            if i == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                onStack.add(node)
            following = graph[node]
            if i < len(following):
                work.append((node, i + 1))
                other = following[i]
                if other not in index:
                    work.append((other, 0))
                elif other in onStack:
                    low[node] = min(low[node], index[other])
                continue
            # every neighbour is done: pass the low link up, maybe pop
            if len(work) > 0:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    other = stack.pop()
                    onStack.discard(other)
                    component.append(other)
                    if other == node:
                        break
                components.append(component)
    return components

def cycleThrough(graph, members, start):
    # The shortest path start -> ... -> start inside members (cycle order)
    parent = {start: None}
    queue = [start]
    while len(queue) > 0:
        node = queue.pop(0)
        for other in graph[node]:
            if other not in members:
                continue
            if other == start:
                cycle = [node]
                while parent[cycle[-1]] != None:
                    cycle.append(parent[cycle[-1]])
                return list(reversed(cycle))
            if other not in parent:
                parent[other] = node
                queue.append(other)
    return [start]

def findGateLoops(sim):
    # sim['loops']: one cycle (prim indices in order) per loop of gates;
    # sim['loopMembers']: every prim of each loop; sim['loopNets']: the
    # nets those prims drive or read (their values are the loop's memory)
    graph = gateGraph(sim)
    sim['loops'] = []
    sim['loopMembers'] = []
    sim['loopOf'] = dict()
    sim['loopNets'] = set()
    for component in strongComponents(graph):
        if len(component) == 1 and component[0] not in graph[component[0]]:
            continue
        members = set(component)
        cycle = cycleThrough(graph, members, min(component))
        sim['loops'].append(cycle)
        sim['loopMembers'].append(members)
        for index in members:
            sim['loopOf'][index] = len(sim['loops']) - 1
            prim = sim['prims'][index]
            sim['loopNets'].update(prim['outNets'].values())
            sim['loopNets'].update(prim['inNets'].values())

INVERTING = {'NOT': 1, 'NAND': 1, 'NOR': 1, 'AND': 0, 'OR': 0, 'BUF': 0,
             'TG': 0}

def loopInversions(sim, loop):
    # How many inverting gates the cycle passes: odd is a ring (it
    # oscillates), even a latch (it holds a value). None if it can't be
    # told (an XOR, or a bigger part in the loop).
    count = 0
    for index in loop:
        typeName = sim['prims'][index]['type']
        if typeName not in INVERTING:
            return None
        count += INVERTING[typeName]
    return count

def primName(sim, prim):
    # A name for messages: the label, else the type and a number (NOR2)
    if prim['label'] != '':
        return prim['label']
    if prim['ref'] != None:
        return prim['ref'].upper()
    number = 0
    for other in sim['prims']:
        if other['type'] == prim['type']:
            number += 1
        if other is prim:
            break
    return f"{prim['defn']['label']}{number}"

def describeLoop(sim, loopIndex):
    # {'code', 'text', 'why', 'fix', 'loop', 'prims'} for a loop of gates
    # that never settled
    loop = sim['loops'][loopIndex]
    names = [primName(sim, sim['prims'][i]) for i in loop]
    inversions = loopInversions(sim, loop)
    detail = {'level': 'error', 'loop': list(loop),
              'prims': sorted(sim['loopMembers'][loopIndex]),
              'parts': [], 'wires': [], 'nets': []}
    if inversions != None and inversions % 2 == 0:
        detail.update({
            'code': 'loopRace',
            'text': f"The latch {'/'.join(names)} never settles: its gates "
                    'flip back and forth on every wave (a race, as when S '
                    'and R go from 1, 1 to 0, 0 at the same time). Real '
                    'hardware would end up in an unpredictable state, so '
                    'its outputs are now x.',
            'why': ['Both gates changed in the same wave, so each one '
                    'undoes the other on the next wave.'],
            'fix': 'Never release S and R together. Change one input at a '
                   'time.'})
    else:
        ring = ' -> '.join(names + [names[0]])
        if inversions == None:
            text = (f'{ring} is a loop of logic that never settles: it '
                    'oscillates.')
        else:
            text = (f'{ring} is a ring with an odd number of inverting '
                    f'gates ({inversions}), so it can never settle: it '
                    'oscillates.')
        detail.update({
            'code': 'loopRing', 'text': text,
            'why': ['Each gate flips the next one, and the last flips the '
                    'first, so the values go round forever. Its outputs '
                    'are now x.'],
            'fix': 'Break the loop with a register, or use an even number '
                   'of inverting gates to make a latch.'})
    return detail


######################################################################
# Starting over
######################################################################

def findProgramRAM(sim):
    # The RAM a program goes into: the one tagged 'mem', else the first
    first = None
    for prim in sim['prims']:
        if prim['type'] == 'RAM':
            if prim['ref'] == 'mem':
                return prim
            if first == None:
                first = prim
    return first

def loadProgram(sim, memory):
    # memory: 16 entries, each 0-255 or None (uninitialized)
    sim['program'] = list(memory)
    resetSim(sim)

def resetSim(sim):
    for prim in sim['prims']:
        definition = prim['defn']
        if definition['initState'] != None:
            if prim['type'] == 'PIN_IN' and prim['state'] != None:
                continue                   # switches keep their setting
            prim['state'] = definition['initState'](prim['params'])
    ram = findProgramRAM(sim)
    if ram != None and sim['program'] != None:
        memory = []
        for word in sim['program']:
            memory.append(X if word == None else word)
        ram['state'] = memory
    clearNets(sim)
    sim['phase'] = 'fetch'
    sim['halted'] = False
    sim['status'] = 'Ready'
    if len(sim['buildErrors']) > 0:
        halt(sim, 'Error: ' + sim['buildErrors'][0])
    sim['halfCycles'] = 0
    sim['instrCount'] = 0
    sim['changes'] = []
    sim['pending'] = []
    sim['stop'] = None
    sim['stopDetail'] = None
    sim['begun'] = False
    sim['history'] = [snapshot(sim)]

def clearNets(sim):
    # Forget every settled value: the next settle evaluates everything
    for net in sim['nets']:
        net['value'] = Z
        for key in net['driverValues']:
            net['driverValues'][key] = Z
    sim['netWave'] = dict()
    sim['primWave'] = dict()
    sim['waveCount'] = 0
    sim['seeds'] = set(range(len(sim['prims'])))
    sim['settled'] = False
    sim['loopError'] = None
    sim['loopDetail'] = None
    sim['loopParts'] = []
    sim['contention'] = []

def halt(sim, status):
    sim['halted'] = True
    sim['status'] = status


######################################################################
# Settling (combinational logic, wave by wave)
######################################################################

def getInputs(sim, prim):
    inputs = dict()
    nets = sim['nets']
    for port, netIndex in prim['inNets'].items():
        inputs[port] = nets[netIndex]['value']
    return inputs

def resolveNet(net):
    # Floating drivers don't count; two real drivers conflict (X)
    value = Z
    count = 0
    for driverValue in net['driverValues'].values():
        if driverValue != Z:
            value = driverValue
            count += 1
    if count >= 2:
        return X
    return value

def settle(sim):
    # Evaluates the seed parts, then whatever reads a net that changed,
    # wave by wave, until nothing changes
    prims = sim['prims']
    nets = sim['nets']
    current = sorted(sim['seeds'])
    sim['seeds'] = set()
    netWave = dict()
    primWave = dict()
    wave = 0
    limit = 4 * len(prims) + 10
    sim['loopError'] = None
    sim['loopDetail'] = None
    sim['loopParts'] = []
    frozen = set()                 # loops that never settled: now X
    sinceFreeze = 0
    while len(current) > 0:
        touched = set()
        if sinceFreeze > limit:
            # A loop keeps flipping: its outputs become X (stable), and
            # what reads them settles once more
            stuck = stuckLoops(sim, current)
            for index in stuck:
                prim = prims[index]
                for port, netIndex in prim['outNets'].items():
                    nets[netIndex]['driverValues'][(index, port)] = X
                    touched.add(netIndex)
            frozen.update(stuck)
            sinceFreeze = 0
        else:
            for index in current:
                prim = prims[index]
                primWave[index] = wave
                outputs = prim['defn']['evaluate'](prim['params'],
                                                   getInputs(sim, prim),
                                                   prim['state'])
                for port, value in outputs.items():
                    netIndex = prim['outNets'][port]
                    key = (index, port)
                    if nets[netIndex]['driverValues'][key] != value:
                        nets[netIndex]['driverValues'][key] = value
                        touched.add(netIndex)
        following = set()
        for netIndex in touched:
            net = nets[netIndex]
            value = resolveNet(net)
            if value != net['value']:
                net['value'] = value
                netWave[netIndex] = wave
                following.update(net['readers'])
        current = sorted(following - frozen)
        wave += 1
        sinceFreeze += 1
    sim['netWave'] = netWave
    sim['primWave'] = primWave
    sim['waveCount'] = wave
    sim['settled'] = True
    findContention(sim)

def stuckLoops(sim, current):
    # The prims of every gate loop that is still changing (and says so in
    # sim['loopError'] / sim['loopDetail'], for the first one)
    stuck = set()
    hit = []
    for index in current:
        loopIndex = sim['loopOf'].get(index)
        if loopIndex != None and loopIndex not in hit:
            hit.append(loopIndex)
            stuck.update(sim['loopMembers'][loopIndex])
    if len(hit) == 0:
        stuck = set(current)           # (can't happen: a change needs a loop)
    if sim['loopDetail'] == None:
        if len(hit) > 0:
            sim['loopDetail'] = describeLoop(sim, hit[0])
        else:
            names = [primName(sim, sim['prims'][i]) for i in current[:4]]
            sim['loopDetail'] = {
                'level': 'error', 'code': 'loopRing',
                'text': f"Logic through {', '.join(names)} never settles",
                'why': [], 'fix': '', 'loop': list(current), 'parts': [],
                'prims': list(current), 'wires': [], 'nets': []}
        sim['loopError'] = sim['loopDetail']['text']
    sim['loopParts'] = sorted(set(sim['loopParts']) | stuck)
    return stuck

def findContention(sim):
    # Nets that two drivers are really driving at once
    sim['contention'] = []
    for netIndex in sim['sharedNets']:
        net = sim['nets'][netIndex]
        drivers = []
        for key, value in net['driverValues'].items():
            if value != Z:
                drivers.append(key[0])
        if len(drivers) >= 2:
            sim['contention'].append((netIndex, drivers))

def describePrim(prim):
    if prim['label'] != '':
        return prim['label']
    if prim['ref'] != None:
        return prim['ref'].upper()
    return prim['defn']['label']


######################################################################
# One clock phase
######################################################################

def setClocks(sim):
    value = 1 if sim['phase'] == 'execute' else 0
    for index in sim['clocks']:
        prim = sim['prims'][index]
        if prim['state'] != value:
            prim['state'] = value
            sim['seeds'].add(index)

def computePending(sim):
    # What each register would load, and any it can't load safely
    pending = []
    problems = []
    for index in sim['stateful']:
        prim = sim['prims'][index]
        definition = prim['defn']
        inputs = getInputs(sim, prim)
        newState = definition['commit'](prim['params'], inputs,
                                        prim['state'])
        if newState != prim['state']:
            pending.append((index, newState))
        if definition['problem'] != None:
            problem = definition['problem'](prim['params'], inputs,
                                            prim['state'])
            if problem != None:
                problems.append((index, problem))
    sim['pending'] = pending
    sim['problems'] = problems

def genericRule(sim):
    # Without a kit: any register loading an unknown value is an error
    for index, problem in sim['problems']:
        return loadStop(sim, index, problem)
    return None

def loadStop(sim, index, problem):
    # ('error', message) for a register that can't load safely; the
    # details (why, how to fix it) go in sim['stopDetail']
    from zb_explain import loadProblemDetail
    sim['stopDetail'] = loadProblemDetail(sim, index, problem)
    return ('error', sim['stopDetail']['text'])

def findStop(sim):
    # ('halt' or 'error', message) if this phase stops the machine. Halts
    # come first, as in the golden model: a machine that fetched
    # xxxxxxxx stops before its unknown control lines matter. The details
    # of the stop are in sim['stopDetail'].
    sim['stopDetail'] = None
    if sim['loopError'] != None:
        sim['stopDetail'] = sim['loopDetail']
        return ('error', sim['loopError'])
    for rule in sim['rules']:
        stop = rule(sim)
        if stop != None:
            if sim['stopDetail'] == None:
                sim['stopDetail'] = {'level': 'warning', 'code': stop[0],
                                     'text': stop[1], 'why': [], 'fix': '',
                                     'prims': [], 'parts': [], 'wires': [],
                                     'nets': []}
            return stop
    if len(sim['contention']) > 0:
        from zb_explain import contentionDetail
        netIndex, drivers = sim['contention'][0]
        sim['stopDetail'] = contentionDetail(sim, netIndex, drivers)
        return ('error', sim['stopDetail']['text'])
    stop = sim['problemRule'](sim)
    return stop

def beginPhase(sim):
    # Settles the next phase without committing it. Returns False if the
    # machine has halted.
    if sim['halted']:
        return False
    setClocks(sim)
    settle(sim)
    computePending(sim)
    sim['stop'] = findStop(sim)
    sim['begun'] = True
    return True

def endPhase(sim):
    # The clock edge: every register loads at once
    if not sim['begun']:
        return
    sim['begun'] = False
    sim['changes'] = []
    sim['halfCycles'] += 1
    stop = sim['stop']
    if stop != None:
        kind, message = stop
        halt(sim, kind.capitalize() + 'ed: ' + message
             if kind == 'halt' else 'Error: ' + message)
    else:
        for index, newState in sim['pending']:
            prim = sim['prims'][index]
            sim['changes'].append((index, prim['state'], newState))
            prim['state'] = newState
            sim['seeds'].add(index)
        if sim['phase'] == 'fetch':
            sim['phase'] = 'execute'
        else:
            sim['phase'] = 'fetch'
            sim['instrCount'] += 1
        if sim['halfCycles'] >= MAX_PHASES:
            halt(sim, 'Error: phase limit reached (infinite loop?)')
    recordHistory(sim)

def stepPhase(sim):
    if beginPhase(sim):
        endPhase(sim)

def stepInstruction(sim):
    stepPhase(sim)
    while sim['phase'] == 'execute' and not sim['halted']:
        stepPhase(sim)

def runToEnd(sim, maxPhases=MAX_PHASES):
    count = 0
    while not sim['halted'] and count < maxPhases:
        stepPhase(sim)
        count += 1
    return sim


######################################################################
# History (Back and the timeline)
######################################################################

def snapshot(sim):
    states = []
    for prim in sim['prims']:
        states.append(copyState(prim['state']))
    snap = {'states': states, 'phase': sim['phase'],
            'halted': sim['halted'], 'status': sim['status'],
            'halfCycles': sim['halfCycles'],
            'instrCount': sim['instrCount'],
            'changes': list(sim['changes'])}
    if len(sim.get('loopNets', ())) > 0:
        # A latch made of gates remembers on its wires, so wire values are
        # state too. All of them are kept (not only the loop's): the gates
        # feeding a latch must see their old inputs when it is settled
        # again, or they would pass it a passing x. A net with one driver
        # carries that driver's value, so only shared nets need more.
        shared = dict()
        for netIndex in sim['sharedNets']:
            shared[netIndex] = dict(sim['nets'][netIndex]['driverValues'])
        snap['netValues'] = ([net['value'] for net in sim['nets']], shared)
    return snap

def restoreNetValues(sim, snap):
    # Puts the remembered wire values back (after clearNets), for circuits
    # with gate loops
    if 'netValues' not in snap:
        return
    values, shared = snap['netValues']
    for net in sim['nets']:
        net['value'] = values[net['index']]
        if net['index'] in shared:
            net['driverValues'] = dict(shared[net['index']])
        else:
            for key in net['driverValues']:
                net['driverValues'][key] = net['value']

def recordHistory(sim):
    history = sim['history']
    step = sim['halfCycles']
    if step == len(history):
        history.append(snapshot(sim))
    elif step < len(history):
        history[step] = snapshot(sim)

def restore(sim, snap):
    for i in range(len(sim['prims'])):
        sim['prims'][i]['state'] = copyState(snap['states'][i])
    for key in ['phase', 'halted', 'status', 'halfCycles', 'instrCount']:
        sim[key] = snap[key]
    sim['changes'] = list(snap['changes'])
    sim['begun'] = False
    sim['stop'] = None
    if not sim['halted']:
        sim['stopDetail'] = None

def goToStep(sim, step):
    # Shows the machine after `step` phases: the wires carry what they
    # carried during that phase, the registers what they loaded after it
    history = sim['history']
    step = max(0, min(len(history) - 1, step))
    clearNets(sim)
    if step > 0:
        restore(sim, history[step - 1])
        restoreNetValues(sim, history[step - 1])
        setClocks(sim)
        sim['seeds'] = set(range(len(sim['prims'])))
        settle(sim)
    restore(sim, history[step])
    for index, old, new in sim['changes']:
        sim['seeds'].add(index)
    sim['netWave'] = dict()
    if step == 0:
        sim['seeds'] = set(range(len(sim['prims'])))


######################################################################
# Reading values (for the view, the checker and tests)
######################################################################

def netValueAt(sim, key):
    # The value on the net holding this node key, or None if unknown key
    index = sim['nodeNet'].get(key)
    if index == None:
        return None
    return sim['nets'][index]['value']

def findTagged(sim, ref):
    for prim in sim['prims']:
        if prim['ref'] == ref:
            return prim
    return None

def taggedValues(sim):
    # {golden model field: value} for every tagged part. Flags give n z o.
    values = dict()
    for prim in sim['prims']:
        ref = prim['ref']
        if ref == None:
            continue
        state = prim['state']
        if ref == 'flags':
            for name in 'nzo':
                values[name] = state[name]
        elif ref == 'mem':
            values['mem'] = list(state)
        else:
            values[ref] = state
    return values

def changedPaths(sim):
    # The paths of the parts that loaded a new value at the last edge
    paths = set()
    for index, old, new in sim['changes']:
        paths.add(sim['prims'][index]['path'])
    return paths

# zb_circuit.py
# A circuit is plain data: parts, wires and junctions. This file creates
# and edits circuits, works out which wires are joined (nets), checks the
# wiring, and saves circuits as JSON. No graphics here.
#
#   circuit  = {'name', 'parts': [...], 'wires': [...], 'junctions': [...],
#               'nextId'}
#   part     = {'id', 'type', 'x', 'y', 'params', 'label', 'ref', 'mode'}
#   wire     = {'id', 'a': end, 'b': end, 'via': [[x, y], ...], 'color',
#               'lamp'}   (via = [] means "route it automatically")
#   end      = ['port', partId, portName] or ['junction', junctionId]
#   junction = {'id', 'x', 'y'}  (a dot where three or more wires meet)
#
# A library says what each part type is:
#   library = {'user': {name: composite definition}, 'recipes': {...},
#              'version': n, 'cache': {...}}
# Primitive types come from zb_parts.PRIMITIVES; the rest are composites
# (a part built from a circuit of other parts, see zb_library.py).

import json
import copy
import math
from zb_parts import PRIMITIVES, GRID, checkParams

JSON_VERSION = 1


######################################################################
# Definitions and layouts
######################################################################

def makeLibrary():
    return {'user': dict(), 'recipes': dict(), 'version': 0,
            'cache': dict()}

def getDefinition(library, typeName):
    if typeName in PRIMITIVES:
        return PRIMITIVES[typeName]
    return library['user'].get(typeName)

def isPrimitive(typeName):
    return typeName in PRIMITIVES

def definitionChanged(library):
    # Call after editing a user part, so cached layouts are rebuilt
    library['version'] += 1
    library['cache'] = dict()

def partLayout(library, part):
    # (width, height, ports) for a placed part
    definition = getDefinition(library, part['type'])
    if definition == None:
        return 60, 40, []
    if definition['kind'] == 'primitive':
        key = (part['type'], json.dumps(part['params'], sort_keys=True))
        cache = library['cache']
        if key not in cache:
            cache[key] = definition['layout'](part['params'])
        return cache[key]
    return compositeInfo(library, part['type'])['layout']

def compositeInfo(library, name):
    # Ports, layout and which outputs can float, for a user part. Cached
    # until the library changes.
    key = ('composite', name)
    cache = library['cache']
    if key not in cache:
        cache[key] = None              # guards a part that contains itself
        cache[key] = makeCompositeInfo(library, library['user'][name])
    if cache[key] == None:
        return {'layout': (60, 40, []), 'tristate': set(), 'pins': []}
    return cache[key]

def getPins(circuit):
    # (inputs, outputs): the PIN_IN and PIN_OUT parts, top to bottom
    inputs = []
    outputs = []
    for part in circuit['parts']:
        if part['type'] == 'PIN_IN':
            inputs.append(part)
        elif part['type'] == 'PIN_OUT':
            outputs.append(part)
    inputs.sort(key=lambda p: (p['y'], p['x']))
    outputs.sort(key=lambda p: (p['y'], p['x']))
    return inputs, outputs

def pinSide(pin):
    # Which side of the box a pin's port goes on. 'auto': inputs on the
    # left, outputs on the right.
    side = pin['params'].get('side', 'auto')
    if side == 'auto':
        return 'left' if pin['type'] == 'PIN_IN' else 'right'
    return side

SIDES = ['left', 'top', 'right', 'bottom']

def pinsBySide(inputs, outputs):
    # {side: [pins in order]}: a pin's 'order' param comes first, then
    # where it is inside the part (top to bottom, left to right)
    sides = {'left': [], 'right': [], 'top': [], 'bottom': []}
    for pin in inputs + outputs:
        sides[pinSide(pin)].append(pin)
    for side in sides:
        ranked = list(enumerate(sides[side]))
        ranked.sort(key=lambda item: (
            item[1]['params'].get('order') if
            item[1]['params'].get('order') != None else 1000 + item[0],
            item[0]))
        sides[side] = [pin for i, pin in ranked]
    return sides

def boxMinimum(sides):
    # The smallest box the pins fit on: 20 apart, room for the names
    rows = max(len(sides['left']), len(sides['right']), 1)
    columns = max(len(sides['top']), len(sides['bottom']))
    longest = 0
    for pin in sides['left'] + sides['right']:
        longest = max(longest, len(pin['params']['name']))
    width = max(80, ((longest * 12 + 30) // 20) * 20, 20 * columns + 20)
    return width, 20 * rows + 20

def spread(length, count, i):
    # Where the i-th of count ports goes along a side this long: evenly
    # spaced, on the 10-unit grid
    return int(round(length * (i + 1) / (count + 1) / GRID)) * GRID

def boxLayout(inputs, outputs, size=None):
    # A box with the ports spread evenly down the left and right sides
    # (and along the top and bottom, for pins that ask for those sides).
    # size = [width, height] makes it bigger (never smaller than the
    # ports need); None is the smallest that fits.
    sides = pinsBySide(inputs, outputs)
    width, height = boxMinimum(sides)
    if size != None:
        width = max(width, int(size[0]) // GRID * GRID)
        height = max(height, int(size[1]) // GRID * GRID)
    ports = []
    for side, pins in sides.items():
        for i in range(len(pins)):
            params = pins[i]['params']
            along = spread(height if side in ['left', 'right'] else width,
                           len(pins), i)
            dx, dy = {'left': (0, along), 'right': (width, along),
                      'top': (along, 0), 'bottom': (along, height)}[side]
            ports.append({'name': params['name'],
                          'dir': 'in' if pins[i]['type'] == 'PIN_IN'
                          else 'out', 'width': params['width'],
                          'dx': dx, 'dy': dy})
    return width, height, ports

def portsMatch(ports, otherPorts):
    # Same names, directions and widths (in any order)
    if len(ports) != len(otherPorts):
        return False
    table = dict()
    for port in otherPorts:
        table[port['name']] = (port['dir'], port['width'])
    for port in ports:
        if table.get(port['name']) != (port['dir'], port['width']):
            return False
    return True

def makeCompositeInfo(library, definition):
    inputs, outputs = getPins(definition['circuit'])
    layout = boxLayout(inputs, outputs, definition.get('size'))
    target = definition.get('implements')
    if target in PRIMITIVES and definition.get('lookLike'):
        # The hidden gate-level copies of built-ins (zb_kit.expandToGates)
        # look like the built-in, so the lecture machine still lines up.
        # Your own parts are always boxes.
        builtIn = PRIMITIVES[target]
        builtInLayout = builtIn['layout'](dict(builtIn['params']))
        if portsMatch(layout[2], builtInLayout[2]):
            layout = builtInLayout
    # An output can float if everything driving it inside can float
    nets = computeNets(library, definition['circuit'])
    tristate = set()
    for pin in outputs:
        net = nets['nets'][nets['nodeNet'][nodeKey(['port', pin['id'],
                                                    'in'])]]
        drivers = getDrivers(library, definition['circuit'], net)
        if len(drivers) > 0 and all(d[2] for d in drivers):
            tristate.add(pin['params']['name'])
    return {'layout': layout, 'tristate': tristate,
            'pins': inputs + outputs}

def getPort(library, part, portName):
    for port in partLayout(library, part)[2]:
        if port['name'] == portName:
            return port
    return None

def isTristate(library, part, portName):
    definition = getDefinition(library, part['type'])
    if definition == None:
        return False
    if definition['kind'] == 'primitive':
        return portName in definition['tristate']
    return portName in compositeInfo(library, part['type'])['tristate']

def portPosition(library, part, portName):
    port = getPort(library, part, portName)
    if port == None:
        return (part['x'], part['y'])
    return (part['x'] + port['dx'], part['y'] + port['dy'])

def portSide(library, part, port):
    width, height, ports = partLayout(library, part)
    if port['dx'] == 0:
        return 'left'
    if port['dx'] == width:
        return 'right'
    if port['dy'] == 0:
        return 'top'
    return 'bottom'

def partBounds(library, part):
    width, height, ports = partLayout(library, part)
    return (part['x'], part['y'], width, height)


######################################################################
# Building circuits
######################################################################

def makeCircuit(name='untitled'):
    return {'name': name, 'parts': [], 'wires': [], 'junctions': [],
            'nextId': 1}

def newId(circuit, prefix):
    number = circuit['nextId']
    circuit['nextId'] += 1
    return prefix + str(number)

def addPart(library, circuit, typeName, x, y, params=None, label='',
            ref=None):
    definition = getDefinition(library, typeName)
    allParams = dict()
    if definition != None and definition['kind'] == 'primitive':
        allParams = copy.deepcopy(definition['params'])
    if params != None:
        allParams.update(copy.deepcopy(params))
    part = {'id': newId(circuit, 'p'), 'type': typeName, 'x': x, 'y': y,
            'params': allParams, 'label': label, 'ref': ref,
            'mode': 'detailed'}
    circuit['parts'].append(part)
    return part

def findPart(circuit, partId):
    for part in circuit['parts']:
        if part['id'] == partId:
            return part
    return None

def findWire(circuit, wireId):
    for wire in circuit['wires']:
        if wire['id'] == wireId:
            return wire
    return None

def findJunction(circuit, junctionId):
    for junction in circuit['junctions']:
        if junction['id'] == junctionId:
            return junction
    return None

def addJunction(circuit, x, y):
    junction = {'id': newId(circuit, 'j'), 'x': x, 'y': y}
    circuit['junctions'].append(junction)
    return junction

def addWire(circuit, a, b, via=None):
    if via == None:
        via = []
    wire = {'id': newId(circuit, 'w'), 'a': list(a), 'b': list(b),
            'via': [list(point) for point in via], 'color': None,
            'lamp': None}
    circuit['wires'].append(wire)
    return wire

def wiresAt(circuit, end):
    # The wires with an end at this port or junction
    result = []
    for wire in circuit['wires']:
        if wire['a'] == list(end) or wire['b'] == list(end):
            result.append(wire)
    return result

def removeWire(circuit, wireId):
    wire = findWire(circuit, wireId)
    if wire != None:
        circuit['wires'].remove(wire)
    cleanUpJunctions(circuit)

def removePart(circuit, partId):
    part = findPart(circuit, partId)
    if part == None:
        return
    circuit['parts'].remove(part)
    for wire in list(circuit['wires']):
        if (wire['a'][0] == 'port' and wire['a'][1] == partId or
            wire['b'][0] == 'port' and wire['b'][1] == partId):
            circuit['wires'].remove(wire)
    cleanUpJunctions(circuit)

def removeJunction(circuit, junctionId):
    end = ['junction', junctionId]
    for wire in wiresAt(circuit, end):
        circuit['wires'].remove(wire)
    junction = findJunction(circuit, junctionId)
    if junction != None:
        circuit['junctions'].remove(junction)
    cleanUpJunctions(circuit)

def otherEnd(wire, end):
    if wire['a'] == list(end):
        return wire['b']
    return wire['a']

def pointsFromEnd(wire, end):
    # The wire's bend points, starting from the given end
    if wire['a'] == list(end):
        return [list(p) for p in wire['via']]
    return [list(p) for p in reversed(wire['via'])]

def cleanUpJunctions(circuit):
    # A junction with no wires goes; one with one wire goes with its wire;
    # one joining exactly two wires becomes a bend in a single wire
    changed = True
    while changed:
        changed = False
        for junction in list(circuit['junctions']):
            end = ['junction', junction['id']]
            wires = wiresAt(circuit, end)
            if len(wires) >= 3:
                continue
            circuit['junctions'].remove(junction)
            for wire in wires:
                circuit['wires'].remove(wire)
            if len(wires) == 2:
                first, second = wires
                via = (list(reversed(pointsFromEnd(first, end))) +
                       [[junction['x'], junction['y']]] +
                       pointsFromEnd(second, end))
                joined = addWire(circuit, otherEnd(first, end),
                                 otherEnd(second, end), via)
                joined['color'] = first['color'] or second['color']
                joined['lamp'] = first['lamp'] or second['lamp']
            changed = True
            break

def splitWire(library, circuit, wireId, x, y):
    # Puts a junction on the wire at the point nearest (x, y) and returns
    # it; the wire becomes two wires meeting there
    wire = findWire(circuit, wireId)
    points = wirePoints(library, circuit, wire)
    bestIndex, bestPoint, bestDistance = 0, points[0], None
    for i in range(len(points) - 1):
        point = closestPoint(points[i], points[i + 1], x, y)
        distance = abs(point[0] - x) + abs(point[1] - y)
        if bestDistance == None or distance < bestDistance:
            bestIndex, bestPoint, bestDistance = i, point, distance
    junction = addJunction(circuit, bestPoint[0], bestPoint[1])
    end = ['junction', junction['id']]
    # points[1:-1] are the bends, including automatic ones, which are kept
    # so both halves follow the old path
    bends = points[1:-1]
    circuit['wires'].remove(wire)
    first = addWire(circuit, wire['a'], end, bends[:bestIndex])
    second = addWire(circuit, end, wire['b'], bends[bestIndex:])
    for piece in [first, second]:
        piece['color'] = wire['color']
        piece['lamp'] = wire['lamp']
    return junction

def closestPoint(p, q, x, y):
    # The point on segment p-q nearest (x, y), snapped to the grid if the
    # segment is on the grid
    (x1, y1), (x2, y2) = p, q
    if x1 == x2:
        return (x1, snapBetween(y, y1, y2))
    if y1 == y2:
        return (snapBetween(x, x1, x2), y1)
    dx, dy = x2 - x1, y2 - y1
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    t = max(0, min(1, t))
    return (x1 + t * dx, y1 + t * dy)

def snapBetween(value, a, b):
    low, high = min(a, b), max(a, b)
    snapped = round(value / GRID) * GRID
    if low <= snapped <= high:
        return snapped
    return max(low, min(high, value))


######################################################################
# Wire geometry
######################################################################

def endPosition(library, circuit, end):
    if end[0] == 'port':
        part = findPart(circuit, end[1])
        if part == None:
            return (0, 0)
        return portPosition(library, part, end[2])
    junction = findJunction(circuit, end[1])
    if junction == None:
        return (0, 0)
    return (junction['x'], junction['y'])

def endSide(library, circuit, end):
    if end[0] != 'port':
        return None
    part = findPart(circuit, end[1])
    port = None
    if part != None:
        port = getPort(library, part, end[2])
    if port == None:
        return None
    return portSide(library, part, port)

def isHorizontal(side):
    return side == 'left' or side == 'right'

def autoRoute(p, q, sideP, sideQ):
    # Bend points for a wire with no bends of its own: a Z shape leaving
    # each port the way it faces, or an L shape between the two
    (x1, y1), (x2, y2) = p, q
    if x1 == x2 or y1 == y2:
        return []
    if isHorizontal(sideP) and isHorizontal(sideQ):
        middle = round((x1 + x2) / 2 / GRID) * GRID
        if middle == x1 or middle == x2:
            middle = (x1 + x2) / 2
        return [(middle, y1), (middle, y2)]
    if sideP in ['top', 'bottom'] and sideQ in ['top', 'bottom']:
        middle = round((y1 + y2) / 2 / GRID) * GRID
        if middle == y1 or middle == y2:
            middle = (y1 + y2) / 2
        return [(x1, middle), (x2, middle)]
    if isHorizontal(sideP) or sideQ in ['top', 'bottom']:
        return [(x2, y1)]
    return [(x1, y2)]

def wirePoints(library, circuit, wire):
    # The full polyline: end a, bend points, end b
    p = endPosition(library, circuit, wire['a'])
    q = endPosition(library, circuit, wire['b'])
    if len(wire['via']) > 0:
        via = [tuple(point) for point in wire['via']]
    else:
        via = autoRoute(p, q, endSide(library, circuit, wire['a']),
                        endSide(library, circuit, wire['b']))
    return [p] + via + [q]

def movePart(library, circuit, part, dx, dy):
    # Moves a part; each attached wire's nearest bend moves along with it,
    # so its first (or last) segment stays straight
    for wire in circuit['wires']:
        for endName, index in [('a', 0), ('b', -1)]:
            end = wire[endName]
            if (end[0] != 'port' or end[1] != part['id'] or
                len(wire['via']) == 0):
                continue
            x, y = portPosition(library, part, end[2])
            bend = wire['via'][index]
            if bend[1] == y:
                bend[1] += dy
            elif bend[0] == x:
                bend[0] += dx
    part['x'] += dx
    part['y'] += dy


######################################################################
# Wire geometry: crossings, overlaps, branches, wires under parts
######################################################################

def wireSegments(library, circuit, wireNet=None):
    # One dict per straight stretch of every wire: {'wire', 'net', 'x1',
    # 'y1', 'x2', 'y2', 'horizontal'} with x1 <= x2 and y1 <= y2.
    # horizontal is None for a slanted stretch (those are left out of
    # the checks below).
    if wireNet == None:
        wireNet = computeNets(library, circuit)['wireNet']
    segments = []
    for wire in circuit['wires']:
        points = wirePoints(library, circuit, wire)
        for i in range(len(points) - 1):
            (x1, y1), (x2, y2) = points[i], points[i + 1]
            if (x1, y1) == (x2, y2):
                continue
            horizontal = True if y1 == y2 else (False if x1 == x2 else None)
            segments.append({'wire': wire['id'], 'net': wireNet[wire['id']],
                             'x1': min(x1, x2), 'y1': min(y1, y2),
                             'x2': max(x1, x2), 'y2': max(y1, y2),
                             'horizontal': horizontal})
    return segments

def splitByDirection(segments):
    horizontal = [s for s in segments if s['horizontal'] == True]
    vertical = [s for s in segments if s['horizontal'] == False]
    return horizontal, vertical

def findCrossings(segments):
    # [(x, y, verticalWireId, horizontalWireId)]: a horizontal and a
    # vertical stretch of different nets crossing strictly inside both
    import bisect
    horizontal, vertical = splitByDirection(segments)
    vertical.sort(key=lambda s: s['x1'])
    xs = [s['x1'] for s in vertical]
    crossings = []
    for h in horizontal:
        start = bisect.bisect_right(xs, h['x1'])
        end = bisect.bisect_left(xs, h['x2'])
        y = h['y1']
        for v in vertical[start:end]:
            if v['net'] != h['net'] and v['y1'] < y < v['y2']:
                crossings.append((v['x1'], y, v['wire'], h['wire']))
    return crossings

def groupByLine(segments, horizontal):
    # {the line's y (or x): [segments on it]}
    groups = dict()
    for s in segments:
        key = s['y1'] if horizontal else s['x1']
        groups.setdefault(key, []).append(s)
    return groups

def findOverlaps(segments, points=None):
    # Stretches where two different nets run on top of each other:
    # [{'nets', 'wires', 'from', 'to', 'kind'}], kind 'along' for two
    # collinear stretches sharing a length, 'falseT' for an end or bend of
    # one net lying inside a stretch of another (it looks joined).
    # points: [(x, y, wireId, net)], the wires' ends and bends.
    overlaps = []
    for horizontal, group in zip([True, False],
                                 splitByDirection(segments)):
        lo, hi = ('x1', 'x2') if horizontal else ('y1', 'y2')
        for line, items in groupByLine(group, horizontal).items():
            items.sort(key=lambda s: s[lo])
            for i in range(len(items)):
                a = items[i]
                for j in range(i + 1, len(items)):
                    b = items[j]
                    if b[lo] >= a[hi]:
                        break
                    if a['net'] == b['net']:
                        continue
                    start, end = b[lo], min(a[hi], b[hi])
                    if end > start:
                        ends = [(start, line), (end, line)] if horizontal \
                            else [(line, start), (line, end)]
                        overlaps.append({'nets': (a['net'], b['net']),
                                         'wires': (a['wire'], b['wire']),
                                         'from': ends[0], 'to': ends[1],
                                         'kind': 'along'})
    if points != None:
        # (a pair already running along each other is reported once)
        along = {frozenset(o['wires']) for o in overlaps}
        horizontal, vertical = splitByDirection(segments)
        byY = groupByLine(horizontal, True)
        byX = groupByLine(vertical, False)
        seen = set()
        for x, y, wireId, net in points:
            for s in byY.get(y, []) + byX.get(x, []):
                inside = (s['x1'] < x < s['x2'] if s['horizontal'] else
                          s['y1'] < y < s['y2'])
                key = (x, y, s['wire'])
                if inside and s['net'] != net and key not in seen and \
                        frozenset((wireId, s['wire'])) not in along:
                    seen.add(key)
                    overlaps.append({'nets': (net, s['net']),
                                     'wires': (wireId, s['wire']),
                                     'from': (x, y), 'to': (x, y),
                                     'kind': 'falseT'})
    return overlaps

def wireCorners(library, circuit, wireNet):
    # [(x, y, wireId, net)]: every wire's two ends and its bends
    points = []
    for wire in circuit['wires']:
        for x, y in wirePoints(library, circuit, wire):
            points.append((x, y, wire['id'], wireNet[wire['id']]))
    return points

def directionsAt(segments, x, y):
    # The directions ('l', 'r', 'u', 'd') wire stretches leave (x, y) in
    directions = set()
    for s in segments:
        if s['horizontal'] == True and s['y1'] == y and \
                s['x1'] <= x <= s['x2']:
            if s['x1'] < x:
                directions.add('l')
            if x < s['x2']:
                directions.add('r')
        elif s['horizontal'] == False and s['x1'] == x and \
                s['y1'] <= y <= s['y2']:
            if s['y1'] < y:
                directions.add('u')
            if y < s['y2']:
                directions.add('d')
    return directions

def findBranchPoints(segments, points, taken=()):
    # [(x, y, net)]: where wires of one net split three or more ways
    # without a dot (taken: the junctions and ports, which already show)
    byNet = dict()
    for s in segments:
        byNet.setdefault(s['net'], []).append(s)
    taken = set(taken)
    branches = []
    seen = set()
    for x, y, wireId, net in points:
        if (x, y) in taken or (x, y, net) in seen:
            continue
        seen.add((x, y, net))
        if len(directionsAt(byNet.get(net, []), x, y)) >= 3:
            branches.append((x, y, net))
    return branches

def findUnderParts(library, circuit, segments):
    # [(wireId, partId)]: a stretch passing through a part's box (shrunk
    # by 1 unit) that is not one of the wire's own ends
    ends = dict()
    for wire in circuit['wires']:
        ends[wire['id']] = {end[1] for end in [wire['a'], wire['b']]
                            if end[0] == 'port'}
    boxes = [(part['id'],) + partBounds(library, part)
             for part in circuit['parts']]
    found = []
    seen = set()
    for s in segments:
        if s['horizontal'] == None:
            continue
        for partId, x, y, w, h in boxes:
            if partId in ends[s['wire']] or (s['wire'], partId) in seen:
                continue
            left, top, right, bottom = x + 1, y + 1, x + w - 1, y + h - 1
            if s['horizontal']:
                hit = (top < s['y1'] < bottom and
                       min(s['x2'], right) - max(s['x1'], left) > 0)
            else:
                hit = (left < s['x1'] < right and
                       min(s['y2'], bottom) - max(s['y1'], top) > 0)
            if hit:
                seen.add((s['wire'], partId))
                found.append((s['wire'], partId))
    return found

def hopPath(points, hops, radius):
    # The polyline with a half-circle hop over each crossing point (hops)
    # that lies on one of its vertical stretches
    if len(hops) == 0:
        return points
    result = [points[0]]
    for i in range(len(points) - 1):
        (x1, y1), (x2, y2) = points[i], points[i + 1]
        if x1 == x2 and y1 != y2:
            step = 1 if y2 > y1 else -1
            here = sorted([hy for hx, hy in hops if hx == x1 and
                           min(y1, y2) + radius < hy < max(y1, y2) - radius],
                          reverse=step < 0)
            for hy in here:
                for k in range(7):
                    angle = math.pi * k / 6
                    result.append((x1 + radius * math.sin(angle),
                                   hy - step * radius * math.cos(angle)))
        result.append((x2, y2))
    return result

def wireGeometry(library, circuit, hopRadius=4):
    # Everything the view and the warnings need about where wires go,
    # worked out once per edit:
    #   {'crossings', 'overlaps', 'branches', 'under', 'hopPaths'}
    nets = computeNets(library, circuit)
    segments = wireSegments(library, circuit, nets['wireNet'])
    points = wireCorners(library, circuit, nets['wireNet'])
    crossings = findCrossings(segments)
    taken = {(j['x'], j['y']) for j in circuit['junctions']}
    for part in circuit['parts']:
        for port in partLayout(library, part)[2]:
            taken.add((part['x'] + port['dx'], part['y'] + port['dy']))
    hops = dict()
    for x, y, verticalWire, horizontalWire in crossings:
        hops.setdefault(verticalWire, []).append((x, y))
    hopPaths = dict()
    for wire in circuit['wires']:
        if wire['id'] in hops:
            hopPaths[wire['id']] = hopPath(
                wirePoints(library, circuit, wire), hops[wire['id']],
                hopRadius)
    return {'crossings': crossings,
            'overlaps': findOverlaps(segments, points),
            'branches': findBranchPoints(segments, points, taken),
            'under': findUnderParts(library, circuit, segments),
            'hopPaths': hopPaths, 'nets': nets}

def describeWire(circuit, wire):
    # 'pin b -> XOR1.in1'
    def endText(end):
        if end[0] == 'port':
            return describePort(circuit, end[1], end[2])
        return 'a junction'
    return f"{endText(wire['a'])} -> {endText(wire['b'])}"

def layoutProblems(library, circuit, geometry):
    # Warnings for wires that mislead: different nets on top of each other,
    # and wires passing under parts
    problems = []
    for overlap in geometry['overlaps'][:20]:
        a, b = [findWire(circuit, w) for w in overlap['wires']]
        if a == None or b == None:
            continue
        (x1, y1), (x2, y2) = overlap['from'], overlap['to']
        if overlap['kind'] == 'along':
            text = (f'Wires of two different nets run on top of each other '
                    f'from ({x1:g}, {y1:g}) to ({x2:g}, {y2:g}): '
                    f'{describeWire(circuit, a)} and '
                    f'{describeWire(circuit, b)}. They look connected but '
                    "aren't. Select them and press w to tidy.")
        else:
            text = (f'A corner of {describeWire(circuit, a)} touches '
                    f'{describeWire(circuit, b)} at ({x1:g}, {y1:g}): it '
                    "looks joined but isn't. Select them and press w to "
                    'tidy.')
        problems.append({'level': 'warning', 'code': 'overlap',
                         'text': text, 'parts': [],
                         'wires': list(overlap['wires']),
                         'fix': 'Press w with the wires selected, or move '
                                'one of them.',
                         'from': overlap['from'], 'to': overlap['to']})
    for wireId, partId in geometry['under'][:20]:
        wire = findWire(circuit, wireId)
        part = findPart(circuit, partId)
        name = part['label'] or part['type']
        problems.append({'level': 'warning', 'code': 'underPart',
                         'text': f'The wire {describeWire(circuit, wire)} '
                                 f'passes under {name}. Press w to tidy.',
                         'parts': [partId], 'wires': [wireId],
                         'fix': 'Press w with the wire selected, or move '
                                f'{name}.'})
    return problems


######################################################################
# Nets: which ports and junctions are joined
######################################################################

def nodeKey(end):
    # A hashable name for a port or junction
    if end[0] == 'port':
        return ('port', end[1], end[2])
    return ('junction', end[1])

def findRoot(parents, key):
    root = key
    while parents[root] != root:
        root = parents[root]
    while parents[key] != root:            # path compression
        parents[key], key = root, parents[key]
    return root

def union(parents, a, b):
    rootA = findRoot(parents, a)
    rootB = findRoot(parents, b)
    if rootA != rootB:
        parents[rootA] = rootB

def computeNets(library, circuit):
    # Returns {'nets': [...], 'nodeNet': {nodeKey: index},
    #          'wireNet': {wireId: index}}. Every port gets a net, even an
    # unconnected one. A net is {'ports': [(partId, portName)],
    # 'junctions': [ids], 'wires': [ids]}.
    parents = dict()
    for part in circuit['parts']:
        for port in partLayout(library, part)[2]:
            key = ('port', part['id'], port['name'])
            parents[key] = key
    for junction in circuit['junctions']:
        key = ('junction', junction['id'])
        parents[key] = key
    for wire in circuit['wires']:
        a, b = nodeKey(wire['a']), nodeKey(wire['b'])
        parents.setdefault(a, a)
        parents.setdefault(b, b)
        union(parents, a, b)
    rootIndex = dict()
    nets = []
    nodeNet = dict()
    for key in parents:
        root = findRoot(parents, key)
        if root not in rootIndex:
            rootIndex[root] = len(nets)
            nets.append({'ports': [], 'junctions': [], 'wires': []})
        index = rootIndex[root]
        nodeNet[key] = index
        if key[0] == 'port':
            nets[index]['ports'].append((key[1], key[2]))
        else:
            nets[index]['junctions'].append(key[1])
    wireNet = dict()
    for wire in circuit['wires']:
        index = nodeNet[nodeKey(wire['a'])]
        wireNet[wire['id']] = index
        nets[index]['wires'].append(wire['id'])
    return {'nets': nets, 'nodeNet': nodeNet, 'wireNet': wireNet}

def getDrivers(library, circuit, net):
    # [(partId, portName, canFloat)] for the outputs on a net
    drivers = []
    for partId, portName in net['ports']:
        part = findPart(circuit, partId)
        if part == None:
            continue
        port = getPort(library, part, portName)
        if port != None and port['dir'] == 'out':
            drivers.append((partId, portName,
                            isTristate(library, part, portName)))
    return drivers

def getNetWidth(library, circuit, net):
    # The width of the first port found (None if the net has no ports)
    for partId, portName in net['ports']:
        port = getPort(library, findPart(circuit, partId), portName)
        if port != None:
            return port['width']
    return None


######################################################################
# Checking the wiring
######################################################################

def describePort(circuit, partId, portName):
    part = findPart(circuit, partId)
    name = part['type']
    if part['label'] != '':
        name = part['label']
    elif part['type'] in ['PIN_IN', 'PIN_OUT']:
        # a pin is known by its name ("the pin cout")
        return f"pin {part['params']['name']}"
    return f'{name}.{portName}'

def widthFix(fromWidth, toWidth):
    # The one part that joins a wire this wide to a port that wide
    if fromWidth < toWidth:
        if fromWidth == 1:
            return (f'use an EXTEND with repeat (copies the bit into all '
                    f'{toWidth}), or a MERGE 1x{toWidth} to join {toWidth} '
                    'one-bit wires')
        return f'use an EXTEND (zero-extend {fromWidth} to {toWidth})'
    if toWidth == 1:
        return (f'use a SPLIT with range 0 (or {fromWidth - 1}), or "bits" '
                'for one output per bit')
    return (f'use a SPLIT with range {toWidth - 1}:0 (or {fromWidth - 1}:'
            f'{fromWidth - toWidth})')

def checkNet(library, circuit, net):
    # A message if the net's ports cannot be joined, else None
    detail = checkNetDetail(library, circuit, net)
    return None if detail == None else detail['text']

def checkNetDetail(library, circuit, net):
    # {'code', 'text', 'fix'} if the net's ports cannot be joined
    width = None
    drivers = getDrivers(library, circuit, net)
    for partId, portName in net['ports']:
        port = getPort(library, findPart(circuit, partId), portName)
        if port == None:
            continue
        if width == None:
            width = port['width']
            first = describePort(circuit, partId, portName)
        elif port['width'] != width:
            here = describePort(circuit, partId, portName)
            fromWidth, toWidth = width, port['width']
            if (partId, portName) in [(d[0], d[1]) for d in drivers]:
                fromWidth, toWidth = port['width'], width
            fix = widthFix(fromWidth, toWidth)
            return {'code': 'width', 'fix': fix[0].upper() + fix[1:] + '.',
                    'text': f'{first} is {width} bits but {here} is '
                            f"{port['width']} bits: {fix}"}
    always = [d for d in drivers if not d[2]]
    if len(always) >= 2 or (len(always) == 1 and len(drivers) >= 2):
        names = []
        for partId, portName, canFloat in drivers[:3]:
            names.append(describePort(circuit, partId, portName))
        return {'code': 'twoDrivers',
                'text': f"{' and '.join(names)} would both drive one wire. "
                        'Only outputs that can float (TG, RAM dout, DEMUX '
                        'f0/f1) can share a bus.',
                'fix': 'Put a TG in front of one of them (driven by a '
                       'select line), or combine them with an OR gate if '
                       'you meant "either".'}
    return None

def floatingWhy(circuit, partId):
    part = findPart(circuit, partId)
    name = part['label'] or part['type']
    if part['type'] in ['AND', 'NAND']:
        return (f'In Run mode it reads Z, so {name} outputs x unless '
                'another input is 0.')
    if part['type'] in ['OR', 'NOR']:
        return (f'In Run mode it reads Z, so {name} outputs x unless '
                'another input is 1.')
    return f'In Run mode it reads Z, so {name} sees x (unknown).'

def checkNewWire(library, circuit, a, b):
    # A message saying why wiring a to b is not allowed, else None
    if list(a) == list(b):
        return 'A wire needs two different ends'
    trial = copy.deepcopy(circuit)
    addWire(trial, a, b)
    nets = computeNets(library, trial)
    net = nets['nets'][nets['nodeNet'][nodeKey(a)]]
    return checkNet(library, trial, net)

def validate(library, circuit):
    # Every problem with the circuit: [{'level', 'text', 'parts'}] where
    # level is 'error' (can't run) or 'warning'
    # (each also has a 'code', and may have 'why', 'fix' and 'wires')
    problems = []
    for part in circuit['parts']:
        if getDefinition(library, part['type']) == None:
            fileName = ''.join(c if c.isalnum() or c in '-_' else '_'
                               for c in part['type'])
            problems.append({
                'level': 'error', 'parts': [part['id']],
                'code': 'unknownType',
                'text': f"This circuit uses a part called '{part['type']}' "
                        "that isn't in My parts. Its file would be "
                        f'parts/{fileName}.json.',
                'fix': 'Put that file back in parts/, or delete the part.'})
            continue
        if isPrimitive(part['type']):
            message = checkParams(part['type'], part['params'])
            if message != None:
                problems.append({'level': 'error', 'parts': [part['id']],
                                 'code': 'param',
                                 'text': f"{part['label'] or part['type']}: "
                                         f'{message}'})
    nets = computeNets(library, circuit)
    for net in nets['nets']:
        detail = checkNetDetail(library, circuit, net)
        partIds = [partId for partId, portName in net['ports']]
        if detail != None:
            problem = {'level': 'error', 'parts': partIds,
                       'wires': list(net['wires'])}
            problem.update(detail)
            problems.append(problem)
            continue
        drivers = getDrivers(library, circuit, net)
        if len(drivers) == 0:
            for partId, portName in net['ports']:
                part = findPart(circuit, partId)
                port = getPort(library, part, portName)
                if port != None and port['dir'] == 'in':
                    problems.append({
                        'level': 'warning', 'parts': [partId],
                        'code': 'floating',
                        'text': f'{describePort(circuit, partId, portName)}'
                                ' is not connected to anything that drives '
                                'it (it floats: Z)',
                        'why': [floatingWhy(circuit, partId)],
                        'fix': 'Wire it to an output, or to a CONST 0.'})
    return problems


######################################################################
# Copy and paste
######################################################################

def copyParts(circuit, partIds):
    # The chosen parts and the wires between them, as plain data
    ids = set(partIds)
    parts = [copy.deepcopy(p) for p in circuit['parts'] if p['id'] in ids]
    wires = []
    for wire in circuit['wires']:
        if (wire['a'][0] == 'port' and wire['a'][1] in ids and
            wire['b'][0] == 'port' and wire['b'][1] in ids):
            wires.append(copy.deepcopy(wire))
    return {'parts': parts, 'wires': wires}

def pasteParts(circuit, data, dx, dy):
    # Adds copies (moved by dx, dy); returns the new part ids
    newIds = dict()
    for part in data['parts']:
        newPart = copy.deepcopy(part)
        newPart['id'] = newId(circuit, 'p')
        newPart['x'] += dx
        newPart['y'] += dy
        newIds[part['id']] = newPart['id']
        circuit['parts'].append(newPart)
    for wire in data['wires']:
        a = ['port', newIds[wire['a'][1]], wire['a'][2]]
        b = ['port', newIds[wire['b'][1]], wire['b'][2]]
        via = [[x + dx, y + dy] for x, y in wire['via']]
        newWire = addWire(circuit, a, b, via)
        newWire['color'] = wire['color']
    return list(newIds.values())


######################################################################
# Saving and loading
######################################################################

def circuitToText(circuit):
    data = copy.deepcopy(circuit)
    data['version'] = JSON_VERSION
    return json.dumps(data, indent=1)

def circuitFromText(text):
    data = json.loads(text)
    data.pop('version', None)
    for key, default in [('parts', []), ('wires', []), ('junctions', []),
                         ('nextId', 1), ('name', 'untitled')]:
        data.setdefault(key, default)
    for part in data['parts']:
        part.setdefault('label', '')
        part.setdefault('ref', None)
        part.setdefault('mode', 'detailed')
        part.setdefault('params', dict())
    for wire in data['wires']:
        wire.setdefault('via', [])
        wire.setdefault('color', None)
        wire.setdefault('lamp', None)
    return data

def saveCircuit(circuit, path):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(circuitToText(circuit))

def loadCircuit(path):
    with open(path, encoding='utf-8') as f:
        return circuitFromText(f.read())

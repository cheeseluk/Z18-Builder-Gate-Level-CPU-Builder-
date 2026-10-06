# zb_route.py
# Finds a path for a wire on the 10-unit grid that goes around parts,
# never runs along (or turns on) a wire of another net, and crosses
# other nets as little as it can. Used for new wires drawn without bends
# and for Tidy wires (w). It only changes where wires go, never what they
# join. No graphics here.
#
# A* over states (x, y, direction), in grid cells. Costs: 1 per cell
# (0.5 along a wire of the same net, so wires share trunks), BEND per
# turn, CROSS per crossing of another net, NEAR_PART next to a part.

import heapq
from zb_parts import GRID
from zb_circuit import (computeNets, wirePoints, partBounds, partLayout,
                        endPosition, endSide, findWire, findPart, nodeKey)

BEND = 4
CROSS = 6
NEAR_PART = 1
SAME_NET = 0.5
MARGIN = 15                    # cells around the two ends
WIDE_MARGIN = 5                # cells around the whole circuit (2nd try)
MAX_STATES = 60000             # per search, so a hopeless one gives up
DIRECTIONS = [(1, 0), (0, 1), (-1, 0), (0, -1)]     # right down left up
FACING = {'right': 0, 'bottom': 1, 'left': 2, 'top': 3}


######################################################################
# What is in the way (kept up to date as wires are rerouted)
######################################################################

def onGrid(x, y):
    return x % GRID == 0 and y % GRID == 0

def cell(x, y):
    return (int(round(x / GRID)), int(round(y / GRID)))

def makeContext(library, circuit):
    # Everything a route has to avoid, in grid cells
    nets = computeNets(library, circuit)
    context = {'library': library, 'circuit': circuit, 'nets': nets,
               'blocked': set(), 'near': set(), 'edges': dict(),
               'innerH': dict(), 'innerV': dict(), 'corners': dict(),
               'wires': dict()}
    for part in circuit['parts']:
        x, y, w, h = partBounds(library, part)
        x1, y1 = -((-x) // GRID), -((-y) // GRID)           # ceil
        x2, y2 = (x + w) // GRID, (y + h) // GRID           # floor
        for cx in range(int(x1), int(x2) + 1):
            for cy in range(int(y1), int(y2) + 1):
                context['blocked'].add((cx, cy))
        for cx in range(int(x1) - 1, int(x2) + 2):
            for cy in range(int(y1) - 1, int(y2) + 2):
                context['near'].add((cx, cy))
    for junction in circuit['junctions']:
        if onGrid(junction['x'], junction['y']):
            net = nets['nodeNet'][('junction', junction['id'])]
            addTo(context['corners'], cell(junction['x'], junction['y']), net)
    for wire in circuit['wires']:
        addWire(context, wire)
    return context

def addTo(table, key, net):
    table.setdefault(key, dict())
    table[key][net] = table[key].get(net, 0) + 1

def takeFrom(table, key, net):
    counts = table.get(key)
    if counts == None or net not in counts:
        return
    counts[net] -= 1
    if counts[net] == 0:
        del counts[net]
    if len(counts) == 0:
        del table[key]

def wireCells(context, wire):
    # [(table name, key)] a wire occupies: its unit edges, the cells
    # inside its straight stretches, and its ends and bends
    # (a stretch on a grid line whose ends are off the grid, like the
    # data bus's junction at x = 255, still covers the cells it passes)
    points = wirePoints(context['library'], context['circuit'], wire)
    items = []
    for x, y in points:
        if onGrid(x, y):
            items.append(('corners', cell(x, y)))
    for i in range(len(points) - 1):
        (x1, y1), (x2, y2) = points[i], points[i + 1]
        if y1 == y2 and x1 != x2 and y1 % GRID == 0:
            row = int(y1 // GRID)
            lo, hi = cellsBetween(x1, x2)
            for k in range(lo, hi):
                items.append(('edges', ((k, row), (k + 1, row))))
            for k in range(lo, hi + 1):
                if min(x1, x2) < k * GRID < max(x1, x2):
                    items.append(('innerH', (k, row)))
        elif x1 == x2 and y1 != y2 and x1 % GRID == 0:
            column = int(x1 // GRID)
            lo, hi = cellsBetween(y1, y2)
            for k in range(lo, hi):
                items.append(('edges', ((column, k), (column, k + 1))))
            for k in range(lo, hi + 1):
                if min(y1, y2) < k * GRID < max(y1, y2):
                    items.append(('innerV', (column, k)))
    return items

def cellsBetween(a, b):
    # The first and last grid cell from a to b (world units)
    low, high = min(a, b), max(a, b)
    return int(-((-low) // GRID)), int(high // GRID)

def addWire(context, wire):
    net = context['nets']['wireNet'][wire['id']]
    items = wireCells(context, wire)
    context['wires'][wire['id']] = (net, items)
    for table, key in items:
        addTo(context[table], key, net)

def removeWire(context, wireId):
    if wireId not in context['wires']:
        return
    net, items = context['wires'].pop(wireId)
    for table, key in items:
        takeFrom(context[table], key, net)

def others(table, key, net):
    # True if a net other than this one has something at key
    counts = table.get(key)
    return counts != None and any(n != net for n in counts)

def mine(table, key, net):
    counts = table.get(key)
    return counts != None and net in counts


######################################################################
# The search
######################################################################

def edgeKey(p, q):
    return (p, q) if p <= q else (q, p)

def endInfo(context, end):
    # (cell, directions it may be left in / arrived through) of a wire end,
    # or None if it is off the grid
    x, y = endPosition(context['library'], context['circuit'], end)
    if not onGrid(x, y):
        return None
    side = endSide(context['library'], context['circuit'], end)
    if side == None:
        return cell(x, y), [0, 1, 2, 3]
    return cell(x, y), [FACING[side]]

def searchBox(context, start, goal, margin, wide):
    if not wide:
        (x1, y1), (x2, y2) = start, goal
        return (min(x1, x2) - margin, min(y1, y2) - margin,
                max(x1, x2) + margin, max(y1, y2) + margin)
    xs, ys = [start[0], goal[0]], [start[1], goal[1]]
    for cx, cy in context['blocked']:
        xs.append(cx)
        ys.append(cy)
    return (min(xs) - margin, min(ys) - margin, max(xs) + margin,
            max(ys) + margin)

def heuristic(p, d, goal):
    # Manhattan distance, plus a bend unless the goal is straight ahead
    dx, dy = goal[0] - p[0], goal[1] - p[1]
    if dx == 0 and dy == 0:
        return 0
    ux, uy = DIRECTIONS[d]
    ahead = (dy == 0 and dx * ux > 0) or (dx == 0 and dy * uy > 0)
    return abs(dx) + abs(dy) + (0 if ahead else BEND)

def search(context, start, starts, goal, arrive, net, box):
    # A* from start (leaving in one of starts' directions) to goal
    # (arriving moving in one of arrive's directions). Returns the cells.
    left, top, right, bottom = box
    blocked = context['blocked']
    near = context['near']
    edges = context['edges']
    innerH, innerV = context['innerH'], context['innerV']
    corners = context['corners']
    heap = []
    counter = 0
    best = dict()
    parent = dict()
    for d in starts:
        state = (start, d)
        best[state] = 0
        parent[state] = None
        heapq.heappush(heap, (heuristic(start, d, goal), counter, 0, state))
        counter += 1
    expanded = 0
    while len(heap) > 0:
        f, _, g, state = heapq.heappop(heap)
        if g > best.get(state, float('inf')):
            continue
        p, d = state
        if p == goal:
            return walkBack(parent, state)
        expanded += 1
        if expanded > MAX_STATES:
            return None
        turnable = not (others(innerH, p, net) or others(innerV, p, net))
        for nd in range(4):
            if nd == (d + 2) % 4:
                continue                       # no going back
            if nd != d and (not turnable or p == start and
                            nd not in starts):
                continue
            ux, uy = DIRECTIONS[nd]
            q = (p[0] + ux, p[1] + uy)
            if not (left <= q[0] <= right and top <= q[1] <= bottom):
                continue
            if q == goal:
                if nd not in arrive:
                    continue
            else:
                if q in blocked or others(corners, q, net):
                    continue
            key = edgeKey(p, q)
            if others(edges, key, net):
                continue                       # along another net's wire
            cost = SAME_NET if mine(edges, key, net) else 1
            if nd != d:
                cost += BEND
            if q != goal and (others(innerH if uy != 0 else innerV, q, net)):
                cost += CROSS
            if q in near:
                cost += NEAR_PART
            newState = (q, nd)
            newG = g + cost
            if newG < best.get(newState, float('inf')):
                best[newState] = newG
                parent[newState] = state
                heapq.heappush(heap, (newG + heuristic(q, nd, goal),
                                      counter, newG, newState))
                counter += 1
    return None

def walkBack(parent, state):
    cells = []
    while state != None:
        cells.append(state[0])
        state = parent[state]
    return list(reversed(cells))

def corners(cells):
    # The bend points of a path of cells (its two ends left out), in world
    # units
    via = []
    for i in range(1, len(cells) - 1):
        (x0, y0), (x1, y1), (x2, y2) = cells[i - 1], cells[i], cells[i + 1]
        if (x1 - x0, y1 - y0) != (x2 - x1, y2 - y1):
            via.append([x1 * GRID, y1 * GRID])
    return via


######################################################################
# Routing one wire, and tidying many
######################################################################

def routeWire(library, circuit, endA, endB, ignoreWires=(), context=None,
              net=None):
    # Bend points (a list of [x, y], [] for a straight wire) for a wire
    # from endA to endB, or None if no route was found
    if context == None:
        context = makeContext(library, circuit)
        for wireId in ignoreWires:
            removeWire(context, wireId)
    a = endInfo(context, endA)
    b = endInfo(context, endB)
    if a == None or b == None:
        return None
    if net == None:
        net = context['nets']['nodeNet'].get(nodeKey(endA))
    start, starts = a
    goal, facing = b
    arrive = [(d + 2) % 4 for d in facing]     # moving into the port
    for wide, margin in [(False, MARGIN), (True, WIDE_MARGIN)]:
        box = searchBox(context, start, goal, margin, wide)
        cells = search(context, start, starts, goal, arrive, net, box)
        if cells != None:
            return corners(cells)
    return None

def wireLength(library, circuit, wire):
    points = wirePoints(library, circuit, wire)
    return sum(abs(points[i + 1][0] - points[i][0]) +
               abs(points[i + 1][1] - points[i][1])
               for i in range(len(points) - 1))

def tidyWires(library, circuit, wireIds):
    # Reroutes the chosen wires, one at a time against all the others:
    # the nets with the biggest reach first, and in a net the longest wire
    # first. A wire that can't be routed keeps its old shape. If some
    # fail, a second try routes those first (so the others go round
    # them), and the better try is kept. Returns (rerouted, failed).
    from zb_circuit import wireGeometry
    wires = [findWire(circuit, w) for w in wireIds]
    wires = [w for w in wires if w != None]
    original = {w['id']: [list(p) for p in w['via']] for w in wires}
    context = makeContext(library, circuit)
    # wires with an end off the grid can't be routed: they go first and
    # stay as they are
    stuck = [w['id'] for w in wires if endInfo(context, w['a']) == None or
             endInfo(context, w['b']) == None]
    tries = []
    first = stuck
    for attempt in range(2):
        for wire in wires:
            wire['via'] = [list(p) for p in original[wire['id']]]
        rerouted, failed = tidyOnce(library, circuit, wires, first)
        geom = wireGeometry(library, circuit)
        score = (len(failed), len(geom['overlaps']), len(geom['under']),
                 len(geom['crossings']))
        tries.append((score, rerouted, failed,
                      {w['id']: [list(p) for p in w['via']] for w in wires}))
        if len(failed) == len(stuck):
            break
        first = stuck + [w for w in failed if w not in stuck]
    score, rerouted, failed, vias = min(tries, key=lambda t: t[0])
    for wire in wires:
        wire['via'] = vias[wire['id']]
    return rerouted, len(failed)

def tidyOnce(library, circuit, wires, first):
    # One pass of tidyWires; first: wire ids to route before the others.
    # Returns (rerouted count, failed wire ids).
    context = makeContext(library, circuit)
    wireNet = context['nets']['wireNet']
    reach = dict()
    for wire in wires:
        for x, y in wirePoints(library, circuit, wire):
            box = reach.setdefault(wireNet[wire['id']], [x, y, x, y])
            box[0], box[1] = min(box[0], x), min(box[1], y)
            box[2], box[3] = max(box[2], x), max(box[3], y)
    def size(net):
        box = reach[net]
        return (box[2] - box[0]) + (box[3] - box[1])
    rank = {wireId: i for i, wireId in enumerate(first)}
    wires = sorted(wires, key=lambda w: (
        rank.get(w['id'], len(rank)), -size(wireNet[w['id']]),
        wireNet[w['id']], -wireLength(library, circuit, w), w['id']))
    for wire in wires:
        removeWire(context, wire['id'])
    rerouted = 0
    failed = []
    for wire in wires:
        old = [list(p) for p in wire['via']]
        via = routeWire(library, circuit, wire['a'], wire['b'],
                        context=context, net=wireNet[wire['id']])
        if via == None:
            failed.append(wire['id'])
        else:
            wire['via'] = via
            rerouted += 1 if via != old else 0
        addWire(context, wire)
    return rerouted, failed

# zb_editor.py
# Build-mode actions: the camera, finding what is under the mouse, placing,
# moving, wiring, deleting, copying, undo, saving and opening. These
# functions change app (and its circuits) but never draw.

import os
import copy
import json
from zb_parts import (PRIMITIVES, GRID, STATEFUL_TYPES, checkParams,
                      parseRanges, parseWidths)
from zb_circuit import (getDefinition, partLayout, partBounds, addPart,
                        addWire, findPart, findWire, findJunction, removePart,
                        removeJunction, splitWire, wirePoints, movePart,
                        checkNewWire, copyParts, pasteParts, circuitToText,
                        circuitFromText, saveCircuit, loadCircuit, makeCircuit,
                        getPort, validate, cleanUpJunctions, wireGeometry,
                        layoutProblems, definitionChanged)
from zb_library import (updateUserPart, saveUserPart, packSelection,
                        getInnerCircuit, verifyPart)
from zb_kit import TAGS, tagFits
from zb_helpers import distanceToPath

HERE = os.path.dirname(os.path.abspath(__file__))
CIRCUIT_DIR = os.path.join(HERE, 'circuits')
PARTS_DIR = os.path.join(HERE, 'parts')
AUTOSAVE = 'autosave'
ZOOMS = [0.3, 0.4, 0.5, 0.65, 0.75, 0.9, 1, 1.25, 1.5, 2]
MIN_ZOOM, MAX_ZOOM = 0.25, 2.5
PORT_HIT = 6                    # screen distance to grab a port
WIRE_HIT = 5
MAX_UNDO = 100
USER_SHAPES = ['box']                 # your parts are boxes (Round 3)

# The speed dial of the Run-mode animation. 1x is 14 frames per wave;
# the slowest steps (0.15x down to 0.05x, about 1.6-4.7 s per wave) are
# for following a wave by eye or recording one.
# (Kept here, not in zb_view, so the tests can read it without
# cmu_graphics; zb_view and zb_main import it from here.)
SPEEDS = [0.05, 0.1, 0.15, 0.25, 0.5, 0.75, 1, 1.5, 2, 4, 7]
BASE_FRAMES_PER_WAVE = 14
FRAMES_PER_WAVE = [BASE_FRAMES_PER_WAVE / s for s in SPEEDS]
START_ANIM_LEVEL = SPEEDS.index(1)


def speedLabel(speed):
    # 0.25 -> '0.25×', 1 -> '1×', 1.5 -> '1.5×' (no trailing .0)
    text = f'{speed:g}'
    return text + '×'

def changeAnimLevel(app, amount):
    # + / -: one step faster or slower, clamped at both ends
    lastLevel = len(SPEEDS) - 1
    app.animLevel = max(0, min(lastLevel, app.animLevel + amount))
    say(app, f'Speed {speedLabel(SPEEDS[app.animLevel])}')

def advanceWave(waveT, frames, animLevel):
    # How far through a wave (0..1) the animation is after `frames` more
    # frames at this speed
    waveT = min(1, waveT + frames / FRAMES_PER_WAVE[animLevel])
    if waveT > 0.999:                  # (adding 1/n n times can miss 1)
        waveT = 1
    return waveT


######################################################################
# The app fields
######################################################################

def initAppFields(app, layout, library, root):
    # Every field the editor and the view read, with starting values.
    # zb_main.onAppStart calls this, and so do the tests (on a fake app).
    app.mode = 'build'
    app.layout = layout
    app.library = library
    app.root = root
    app.sim = None
    app.view = None
    app.path = []                      # part ids from the top to the view
    app.pathNames = []
    app.cams = dict()                  # {tuple(path): camera}
    app.selection = emptySelection()
    app.tool = None                    # None, 'place' or 'wire'
    app.placeType = None
    app.lastParams = dict()
    app.lastPlaced = None
    app.wireStart = None
    app.wireVia = []
    app.bus = None                     # bus wiring (tool 'bus')
    app.drag = None
    app.clipboard = None
    app.undo = []
    app.redo = []
    app.editVersion = 0
    app.viewVersion = 0
    app.simVersion = 0
    app.levelCache = dict()
    app.flowCache = dict()
    app.problems = []
    app.problemParts = set()
    app.problemKey = None
    app.differencePart = None
    app.message = None
    app.messageColor = None
    app.messageFrames = 0
    app.hoverWire = None
    app.hoverPort = None
    app.hoverNet = None                # the net under the mouse (lit up)
    app.hoverPart = None               # the part under the mouse (its
                                       # wires and neighbours light up)
    app.paletteHover = None            # (type name, row) under the mouse
    app.fileName = None                # the circuits/ file it came from
    app.savedVersion = 0               # editVersion when last saved
    app.stash = None                   # the circuit a mission (or a part
                                       # opened from Open) replaced
    app.tidyArmed = None               # when w was pressed with nothing
                                       # selected (press again: tidy all)
    app.wireGeom = None
    app.mouseX = 0
    app.mouseY = 0
    app.mouseInCanvas = False
    app.lastClick = None
    app.showGrid = {'build': True, 'run': False}   # one setting per mode
    app.netHighlight = True            # hovering lights up a whole net (i)
    app.showHelp = False
    app.showVerify = False
    app.bitLanes = False
    app.numFormat = 'bin'
    app.animLevel = START_ANIM_LEVEL
    app.stage = 0                      # zb_view.IDLE
    app.wave = 0
    app.waveT = 0
    app.waveCount = 1
    app.goal = None
    app.running = False
    app.settling = False
    app.flashFrames = 0
    app.breakpoints = set()
    app.programRam = None
    app.programName = ''
    app.programPath = None
    app.programMemory = [None] * 16
    app.rows = [None] * 16
    app.picker = None
    app.paletteTab = 0
    app.mission = None
    app.checkOn = False
    app.difference = None
    app.checker = None
    app.kitWarnings = []
    app.narration = []
    app.verifyResult = None
    app.table = None                   # the truth / step table (u)
    app.logicMode = False              # Run mode without a CLOCK
    app.frozen = False                 # paused mid-animation (Pause)
    app.solo = None                    # a part running on its own:
                                       # {'path', 'names', 'circuit',
                                       #  'readOnly', 'partName'}
    app.explain = None                 # a problem shown under "Why"
    app.explainParts = set()           # the parts it is about
    refreshView(app)
    syncProblems(app)

def syncProblems(app):
    # The wiring problems of the level on screen (and which parts to
    # outline in red), worked out again only after an edit or a new view
    key = (app.editVersion, app.viewVersion)
    if app.problemKey == key:
        return
    app.problemKey = key
    circuit = getCircuit(app)
    app.problems = validate(app.library, circuit)
    # Where the wires go (crossings, overlaps, ...), for the view and for
    # the layout warnings. Worked out per edit, never per frame.
    app.wireGeom = wireGeometry(app.library, circuit)
    app.wireGeom['key'] = key
    if not app.view['readOnly']:       # (a recipe can't be tidied)
        app.problems += layoutProblems(app.library, circuit, app.wireGeom)
    app.problemParts = set()
    for problem in app.problems:
        if problem['level'] == 'error':
            app.problemParts.update(problem['parts'])


######################################################################
# The camera (world units <-> design units on the canvas)
######################################################################

def getCanvas(app):
    # (left, top, width, height) of the canvas in design units
    if app.mode == 'build':
        return app.layout['buildCanvas']
    return app.layout['runCanvas']

def getCam(app):
    key = tuple(app.path)
    if key not in app.cams:
        app.cams[key] = {'x': -40, 'y': -20, 'zoom': 0.6}
        fitView(app)
    return app.cams[key]

def toScreen(app, x, y):
    cam = getCam(app)
    left, top, width, height = getCanvas(app)
    return (left + (x - cam['x']) * cam['zoom'],
            top + (y - cam['y']) * cam['zoom'])

def toWorld(app, x, y):
    cam = getCam(app)
    left, top, width, height = getCanvas(app)
    return (cam['x'] + (x - left) / cam['zoom'],
            cam['y'] + (y - top) / cam['zoom'])

def inCanvas(app, x, y):
    left, top, width, height = getCanvas(app)
    return left <= x <= left + width and top <= y <= top + height

def circuitBounds(app, circuit):
    # (left, top, right, bottom) around every part and wire
    library = app.library
    xs, ys = [], []
    for part in circuit['parts']:
        x, y, w, h = partBounds(library, part)
        xs += [x, x + w]
        ys += [y - 14, y + h]
    for wire in circuit['wires']:
        for x, y in wirePoints(library, circuit, wire):
            xs.append(x)
            ys.append(y)
    if len(xs) == 0:
        return (0, 0, 400, 300)
    return (min(xs), min(ys), max(xs), max(ys))

def fitView(app):
    # Zooms and pans so the whole level fits on the canvas
    cam = app.cams[tuple(app.path)]
    left, top, right, bottom = circuitBounds(app, getCircuit(app))
    canvasLeft, canvasTop, width, height = getCanvas(app)
    margin = 30
    zoom = min((width - 2 * margin) / max(1, right - left),
               (height - 2 * margin) / max(1, bottom - top))
    zoom = max(MIN_ZOOM, min(1.5, zoom))
    cam['zoom'] = zoom
    cam['x'] = (left + right) / 2 - width / 2 / zoom
    cam['y'] = (top + bottom) / 2 - height / 2 / zoom

def zoomStep(app, direction, screenX=None, screenY=None):
    # To the next zoom level in/out, keeping the point under (screenX,
    # screenY) (default: the canvas middle) where it is
    cam = getCam(app)
    left, top, width, height = getCanvas(app)
    if screenX == None:
        screenX, screenY = left + width / 2, top + height / 2
    worldX, worldY = toWorld(app, screenX, screenY)
    zoom = cam['zoom']
    if direction > 0:
        bigger = [z for z in ZOOMS if z > zoom + 0.01]
        zoom = bigger[0] if len(bigger) > 0 else zoom
    else:
        smaller = [z for z in ZOOMS if z < zoom - 0.01]
        zoom = smaller[-1] if len(smaller) > 0 else zoom
    cam['zoom'] = zoom
    cam['x'] = worldX - (screenX - left) / zoom
    cam['y'] = worldY - (screenY - top) / zoom

def panBy(app, dx, dy):
    # dx, dy in design units on screen
    cam = getCam(app)
    cam['x'] -= dx / cam['zoom']
    cam['y'] -= dy / cam['zoom']

def snap(value):
    return round(value / GRID) * GRID


######################################################################
# Which circuit is on screen
######################################################################

def getView(app):
    # The view dict of the level on screen (see zb_library.innerView)
    return app.view

def getCircuit(app):
    return app.view['circuit']

def isEditable(app):
    return app.mode == 'build' and not app.view['readOnly']

def editingPartName(app):
    # The user part whose inside is on screen, or None at the top
    return app.view.get('partName')

def readOnlyMessage(app):
    if app.mode != 'build':
        return 'Press Tab to go back to Build mode to edit'
    return ('This is a built-in part\'s recipe (read-only). Press c to '
            'copy it to My parts and edit that.')


######################################################################
# What is under the mouse
######################################################################

def hitTest(app, screenX, screenY, wantWires=True):
    # {'kind': 'port'|'junction'|'part'|'wire'|None, ...} at a screen point
    circuit = getCircuit(app)
    library = app.library
    zoom = getCam(app)['zoom']
    x, y = toWorld(app, screenX, screenY)
    reach = PORT_HIT / zoom
    best = None
    for part in circuit['parts']:
        for port in partLayout(library, part)[2]:
            px, py = part['x'] + port['dx'], part['y'] + port['dy']
            distance = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
            if distance <= reach and (best == None or distance < best[0]):
                best = (distance, {'kind': 'port', 'part': part['id'],
                                   'port': port['name'],
                                   'end': ['port', part['id'],
                                           port['name']]})
    if best != None:
        return best[1]
    for junction in circuit['junctions']:
        if (abs(junction['x'] - x) <= reach and
            abs(junction['y'] - y) <= reach):
            return {'kind': 'junction', 'junction': junction['id'],
                    'end': ['junction', junction['id']]}
    for part in reversed(circuit['parts']):
        left, top, width, height = partBounds(library, part)
        if left <= x <= left + width and top <= y <= top + height:
            return {'kind': 'part', 'part': part['id']}
    if wantWires:
        for wire in reversed(circuit['wires']):
            points = wirePoints(library, circuit, wire)
            if distanceToPath(points, x, y) <= WIRE_HIT / zoom:
                return {'kind': 'wire', 'wire': wire['id'], 'x': x, 'y': y}
    return {'kind': None, 'x': x, 'y': y}


######################################################################
# Undo and the "something changed" bookkeeping
######################################################################

def snapshotEdits(app):
    data = {'root': circuitToText(app.root), 'user': dict(),
            'sizes': dict()}
    for name, definition in app.library['user'].items():
        data['user'][name] = circuitToText(definition['circuit'])
        data['sizes'][name] = copy.deepcopy(definition.get('size'))
    return data

def pushUndo(app):
    app.undo.append(snapshotEdits(app))
    if len(app.undo) > MAX_UNDO:
        app.undo.pop(0)
    app.redo = []

def restoreEdits(app, data):
    app.root = circuitFromText(data['root'])
    for name, text in data['user'].items():
        if name in app.library['user']:
            definition = app.library['user'][name]
            definition['circuit'] = circuitFromText(text)
            if name in data.get('sizes', dict()):
                definition['size'] = copy.deepcopy(data['sizes'][name])
            updateUserPart(app.library, definition)
    app.selection = emptySelection()
    app.path = []
    refreshView(app)
    afterEdit(app, saveUndo=False)

def undo(app):
    if len(app.undo) == 0:
        return say(app, 'Nothing to undo')
    app.redo.append(snapshotEdits(app))
    restoreEdits(app, app.undo.pop())
    say(app, 'Undone')

def redo(app):
    if len(app.redo) == 0:
        return say(app, 'Nothing to redo')
    app.undo.append(snapshotEdits(app))
    restoreEdits(app, app.redo.pop())
    say(app, 'Redone')

def afterEdit(app, saveUndo=True):
    # Call after every change to a circuit
    app.editVersion += 1
    app.hoverNet = None                # net numbers change with the circuit
    name = editingPartName(app)
    if name != None and name in app.library['user']:
        definition = app.library['user'][name]
        wasVerified = definition['verified']
        definition['verified'] = False
        updateUserPart(app.library, definition)
        saveUserPart(definition, PARTS_DIR)
        if wasVerified:
            say(app, f'{name} changed, so it must be verified again')
    else:
        app.library['cache'] = dict()
    app.explain = None
    app.explainParts = set()
    syncProblems(app)
    autosave(app)

def showExplanation(app, problem, parts=()):
    # Puts a problem's why and fix in the side panel and marks its parts
    app.explain = problem
    app.explainParts = set(parts) | set(problem.get('parts', []))

def explainRow(app, row):
    # For a truth-table row with a wrong output: the logic that made it,
    # traced on a fresh tester of the circuit on screen
    from zb_library import makeTester, runTester
    from zb_explain import explainOutput, partsOnLevel
    from zb_values import formatValue
    if not row.get('wrong'):
        app.explain = None
        app.explainParts = set()
        return
    circuit = getCircuit(app)
    tester = makeTester(app.library, circuit)
    runTester(tester, row['in'])
    name = row['wrong'][0]
    netIndex = tester['outputs'][name]
    sim = tester['sim']
    lines, cone = explainOutput(sim, netIndex)
    width = sim['nets'][netIndex]['width']
    got = formatValue(row['got'][name], width)
    want = formatValue(row['expected'][name], width)
    showExplanation(app, {'level': 'error', 'code': 'wrongOutput',
                          'text': f'{name} is {got} but should be {want}.',
                          'why': lines,
                          'fix': 'Follow the lit parts back from ' + name +
                                 ' to find the gate that is wired wrong.'},
                    partsOnLevel(sim, cone['prims'], ()))

def autosave(app):
    try:
        os.makedirs(CIRCUIT_DIR, exist_ok=True)
        saveCircuit(app.root, os.path.join(CIRCUIT_DIR, AUTOSAVE + '.json'))
    except OSError:
        pass

def say(app, text, color=None):
    app.message = text
    app.messageColor = color
    app.messageFrames = 60 * 6

def emptySelection():
    return {'parts': set(), 'wires': set(), 'junctions': set()}


######################################################################
# Moving between levels
######################################################################

def refreshView(app):
    # Rebuilds app.view for app.path (in Build mode there is no sim).
    # When a part runs on its own (app.solo), the running view starts at
    # that part, app.solo['path'] down from the top.
    from zb_library import innerView, topView
    sim = app.sim if app.mode == 'run' else None
    solo = app.solo if app.mode == 'run' else None
    if solo != None:
        view = topView(solo['circuit'], sim)
        view['readOnly'] = solo['readOnly']
        view['partName'] = solo['partName']
        names = list(solo['names'])
        kept = list(solo['path'])
        below = app.path[len(kept):]
    else:
        view = topView(app.root, sim)
        view['partName'] = None
        names = []
        kept = []
        below = app.path
    for partId in below:
        part = findPart(view['circuit'], partId)
        if part == None:
            break
        inner = innerView(app.library, view, part)
        if inner == None:
            break
        definition = getDefinition(app.library, part['type'])
        inner['partName'] = (part['type'] if definition['kind'] ==
                             'composite' else None)
        names.append(part['label'] or definition['label'])
        kept.append(partId)
        view = inner
    app.path = kept
    app.pathNames = names
    app.view = view
    app.viewVersion += 1

def noInsideMessage(app, part):
    # Why a part has no inside to open. Parts that remember are made of
    # smaller parts, but the builder simulates them as one block.
    label = getDefinition(app.library, part['type'])['label']
    if part['type'] == 'DFF':
        return (f'{label} is simulated as one block. Missions 6-8 build one '
                'from gates: an SR latch, a D latch, then two D latches in '
                'a row')
    if part['type'] in STATEFUL_TYPES:
        return (f'{label} is simulated as one block, so there is no inside '
                'to show')
    return (f'{label} is one of the smallest parts in the builder: there '
            'is nothing inside it to show')

def drillIn(app, partId):
    part = findPart(getCircuit(app), partId)
    circuit, readOnly = getInnerCircuit(app.library, part)
    if circuit == None:
        return say(app, noInsideMessage(app, part))
    app.path.append(partId)
    app.selection = emptySelection()
    cancelTool(app)
    refreshView(app)
    getCam(app)

def levelNets(app):
    # The nets of the level on screen (from the per-edit geometry cache,
    # so this is cheap enough to ask every frame)
    from zb_circuit import computeNets
    geom = app.wireGeom
    if geom != None and geom.get('key') == (app.editVersion,
                                            app.viewVersion):
        return geom['nets']
    return computeNets(app.library, getCircuit(app))

def partNeighbors(app, partId):
    # What a part is wired to: {'nets': the nets on its ports, 'feeders':
    # parts driving its inputs, 'takers': parts reading its outputs}.
    # (A part that does both counts as a feeder.)
    circuit = getCircuit(app)
    part = findPart(circuit, partId)
    result = {'nets': set(), 'feeders': set(), 'takers': set()}
    if part == None:
        return result
    nets = levelNets(app)
    for port in partLayout(app.library, part)[2]:
        netIndex = nets['nodeNet'].get(('port', partId, port['name']))
        if netIndex == None:
            continue
        net = nets['nets'][netIndex]
        if len(net['wires']) == 0:
            continue                   # nothing wired to this port
        result['nets'].add(netIndex)
        for otherId, otherPort in net['ports']:
            if otherId == partId:
                continue
            other = findPart(circuit, otherId)
            info = getPort(app.library, other, otherPort)
            if info == None:
                continue
            if port['dir'] == 'in' and info['dir'] == 'out':
                result['feeders'].add(otherId)
            elif port['dir'] == 'out' and info['dir'] == 'in':
                result['takers'].add(otherId)
    result['takers'] -= result['feeders']
    return result

def runBase(app):
    # How deep the top of what is running is: 0 for the whole circuit,
    # more when a part runs on its own (and always 0 in Build mode)
    if app.mode == 'run' and app.solo != None:
        return len(app.solo['path'])
    return 0

def atRunTop(app):
    # True at the top of what is running (where its IN pins are switches)
    return len(app.path) == runBase(app)

def soloMessage(app):
    return (f"{app.solo['names'][-1]} is running on its own. To run the "
            'whole circuit, press Tab, go up (Esc), and press Tab again.')

def drillOut(app):
    if len(app.path) == 0:
        return False
    if app.mode == 'run' and app.solo != None and atRunTop(app):
        say(app, soloMessage(app))
        return False
    app.path.pop()
    app.selection = emptySelection()
    cancelTool(app)
    refreshView(app)
    return True

def cancelTool(app):
    app.tool = None
    app.wireStart = None
    app.wireVia = []
    app.bus = None


######################################################################
# Placing, wiring, moving, deleting
######################################################################

def startPlacing(app, typeName):
    if not isEditable(app):
        return say(app, readOnlyMessage(app))
    app.tool = 'place'
    app.placeType = typeName
    app.selection = emptySelection()

def placeAt(app, screenX, screenY, keepPlacing=False):
    # Drops a new part with its middle at the mouse. keepPlacing (a
    # shift-click) leaves the tool on, to place another.
    if app.tool != 'place' or not isEditable(app):
        return
    typeName = app.placeType
    definition = getDefinition(app.library, typeName)
    if definition == None:
        return
    x, y = toWorld(app, screenX, screenY)
    pushUndo(app)
    circuit = getCircuit(app)
    params = app.lastParams.get(typeName)
    part = addPart(app.library, circuit, typeName, 0, 0, params)
    width, height, ports = partLayout(app.library, part)
    part['x'] = snap(x - width / 2)
    part['y'] = snap(y - height / 2)
    if typeName in ['PIN_IN', 'PIN_OUT']:
        part['params']['name'] = uniquePinName(circuit, part)
    app.selection = {'parts': {part['id']}, 'wires': set(),
                     'junctions': set()}
    app.lastPlaced = typeName
    app.tool = 'place' if keepPlacing else None
    afterEdit(app)
    if keepPlacing:
        say(app, f'Placed a {typeName}. Shift-click to place another, '
                 'Esc to stop.')

def uniquePinName(circuit, newPart):
    used = set()
    for part in circuit['parts']:
        if part is not newPart and part['type'] in ['PIN_IN', 'PIN_OUT']:
            used.add(part['params']['name'])
    base = 'in' if newPart['type'] == 'PIN_IN' else 'out'
    n = 0
    while f'{base}{n}' in used:
        n += 1
    return f'{base}{n}'

def startWire(app, end):
    if not isEditable(app):
        return say(app, readOnlyMessage(app))
    app.tool = 'wire'
    app.wireStart = end
    app.wireVia = []

def lastWirePoint(app):
    from zb_circuit import endPosition
    if len(app.wireVia) > 0:
        return tuple(app.wireVia[-1])
    return endPosition(app.library, getCircuit(app), app.wireStart)

def addBend(app, screenX, screenY):
    # A right-angle step to the point, as the wire in progress is drawn
    x, y = toWorld(app, screenX, screenY)
    x, y = snap(x), snap(y)
    lastX, lastY = lastWirePoint(app)
    if x != lastX and y != lastY:
        app.wireVia.append([x, lastY])
    if (x, y) != (lastX, lastY):
        app.wireVia.append([x, y])

def finishBends(app, end):
    # The wire's last stretch goes straight into the end it finishes on
    from zb_circuit import endPosition, endSide
    if len(app.wireVia) == 0:
        return []
    circuit = getCircuit(app)
    endX, endY = endPosition(app.library, circuit, end)
    lastX, lastY = app.wireVia[-1]
    via = [list(point) for point in app.wireVia]
    if lastX != endX and lastY != endY:
        if endSide(app.library, circuit, end) in ['top', 'bottom']:
            via.append([endX, lastY])
        else:
            via.append([lastX, endY])
    return via

def finishWire(app, hit):
    # Ends the wire being drawn on a port, junction or another wire
    circuit = getCircuit(app)
    if hit['kind'] == 'wire':
        end = None                        # made below, after the checks
    elif hit['kind'] in ['port', 'junction']:
        end = hit['end']
    else:
        return
    start = app.wireStart
    trial = None
    if end != None and busKind(app, start, end) != None:
        # an N-bit port to a 1-bit port: wire it bit by bit through a
        # SPLIT or MERGE
        return startBus(app, start, end)
    if end == None:
        # Check against any port on that wire's net
        wire = findWire(circuit, hit['wire'])
        trial = wire['a']
        message = checkNewWire(app.library, circuit, start, trial)
    else:
        message = checkNewWire(app.library, circuit, start, end)
    if message != None:
        return say(app, message, 'error')
    pushUndo(app)
    if end == None:
        junction = splitWire(app.library, circuit, hit['wire'], hit['x'],
                             hit['y'])
        end = ['junction', junction['id']]
    via = finishBends(app, end)
    if len(app.wireVia) == 0:
        # no bends of its own: the router finds a way around parts and
        # other wires ([] if it can't: then it is drawn as an L or Z)
        from zb_route import routeWire
        via = routeWire(app.library, circuit, start, end) or []
    addWire(circuit, start, end, via)
    cancelTool(app)
    afterEdit(app)

######################################################################
# Bus wiring: an N-bit port to 1-bit ports, one bit per click, through a
# SPLIT "bits" (from an N-bit output) or a MERGE 1xN (into an N-bit
# input). app.bus = {'kind': 'split' | 'merge', 'part', 'width', 'wide',
# 'next'} while the tool is 'bus'.
######################################################################

def portInfo(app, end):
    # (width, 'in' | 'out') of a port end, or None
    if end[0] != 'port':
        return None
    part = findPart(getCircuit(app), end[1])
    port = getPort(app.library, part, end[2]) if part != None else None
    if port == None:
        return None
    return port['width'], port['dir']

def busKind(app, a, b):
    # (kind, wide end, narrow end) if a and b are an N-bit and a 1-bit
    # port that a SPLIT or MERGE can join, else None
    infoA, infoB = portInfo(app, a), portInfo(app, b)
    if infoA == None or infoB == None:
        return None
    if infoA[0] == 1 and infoB[0] > 1:
        a, b, infoA, infoB = b, a, infoB, infoA
    if not (infoA[0] > 1 and infoB[0] == 1):
        return None
    if infoA[1] == 'out' and infoB[1] == 'in':
        return ('split', list(a), list(b))
    if infoA[1] == 'in' and infoB[1] == 'out':
        return ('merge', list(a), list(b))
    return None

def busPortName(bus, bit):
    # SPLIT "bits" has bit 7 on out0; MERGE 1x8 has bit 7 on in0
    index = bus['width'] - 1 - bit
    return ('out' if bus['kind'] == 'split' else 'in') + str(index)

def busEnd(bus, bit):
    return ['port', bus['part'], busPortName(bus, bit)]

def freeBits(app, bus):
    from zb_circuit import wiresAt
    circuit = getCircuit(app)
    return [bit for bit in range(bus['width'])
            if len(wiresAt(circuit, busEnd(bus, bit))) == 0]

def findBusPart(app, kind, wide, width):
    # A SPLIT "bits" / MERGE 1xN already on the wide port's net, or None
    from zb_parts import bitsRanges
    from zb_circuit import computeNets, nodeKey
    circuit = getCircuit(app)
    nets = computeNets(app.library, circuit)
    netIndex = nets['nodeNet'][nodeKey(wide)]
    for partId, portName in nets['nets'][netIndex]['ports']:
        part = findPart(circuit, partId)
        if kind == 'split' and part['type'] == 'SPLIT' and \
                portName == 'in' and part['params']['ranges'] == \
                bitsRanges(width):
            return part
        if kind == 'merge' and part['type'] == 'MERGE' and \
                portName == 'out' and part['params']['widths'] == \
                [1] * width:
            return part
    return None

def overlapsAny(app, circuit, box, ignore=None):
    x, y, w, h = box
    for part in circuit['parts']:
        if part is ignore:
            continue
        px, py, pw, ph = partBounds(app.library, part)
        if x < px + pw + GRID and px < x + w + GRID and \
                y < py + ph + GRID and py < y + h + GRID:
            return True
    return False

def placeBusPart(app, kind, wide, width):
    # A new SPLIT / MERGE next to the wide port, clear of other parts
    from zb_parts import bitsRanges
    from zb_circuit import endPosition, endSide
    circuit = getCircuit(app)
    px, py = endPosition(app.library, circuit, wide)
    side = endSide(app.library, circuit, wide)
    if kind == 'split':
        part = addPart(app.library, circuit, 'SPLIT', 0, 0,
                       {'width': width, 'ranges': bitsRanges(width)})
    else:
        part = addPart(app.library, circuit, 'MERGE', 0, 0,
                       {'widths': [1] * width})
    w, h = partLayout(app.library, part)[:2]
    # (its wide port is 10 below its top: the SPLIT's in, the MERGE's out)
    near = {'right': (px + 40, py - 10, 1), 'left': (px - w - 40, py - 10, 1),
            'bottom': (px + 30, py + 30, 1),
            'top': (px + 30, py - h - 30, -1)}
    x, y, direction = near.get(side, near['right'])
    for attempt in range(40):
        if not overlapsAny(app, circuit, (x, y, w, h), part):
            break
        y += 2 * GRID * direction
    part['x'], part['y'] = snap(x), snap(y)
    part['label'] = 'bits'
    return part

def routedWire(app, a, b):
    from zb_route import routeWire
    circuit = getCircuit(app)
    return addWire(circuit, a, b, routeWire(app.library, circuit, a, b)
                   or [])

def startBus(app, a, b):
    # The first bit: find or place the SPLIT / MERGE, wire the wide port
    # to it, and wire bit 0 to the 1-bit port
    kind, wide, narrow = busKind(app, a, b)
    width = portInfo(app, wide)[0]
    pushUndo(app)
    part = findBusPart(app, kind, wide, width)
    made = part == None
    if made:
        part = placeBusPart(app, kind, wide, width)
        if kind == 'split':
            routedWire(app, wide, ['port', part['id'], 'in'])
        else:
            routedWire(app, ['port', part['id'], 'out'], wide)
    app.tool = 'bus'
    app.wireVia = []
    app.bus = {'kind': kind, 'part': part['id'], 'width': width,
               'wide': wide, 'next': 0}
    free = freeBits(app, app.bus)
    if len(free) == 0:
        app.undo.pop()
        cancelTool(app)
        return say(app, f'Every bit of that {kind.upper()} is wired already',
                   'error')
    app.bus['next'] = free[0]
    app.wireStart = busEnd(app.bus, app.bus['next'])
    message = busConnect(app, narrow, pushed=True)
    if message != None and made:
        say(app, message, 'error')

def busConnect(app, narrow, pushed=False):
    # Wires the next bit to a 1-bit port. Returns an error message, or
    # None.
    from zb_circuit import describePort
    bus = app.bus
    bit = bus['next']
    circuit = getCircuit(app)
    end = busEnd(bus, bit)
    info = portInfo(app, narrow)
    wanted = 'in' if bus['kind'] == 'split' else 'out'
    message = None
    if info == None or info[0] != 1 or info[1] != wanted:
        message = (f"Click a 1-bit {'input' if wanted == 'in' else 'output'}"
                   f' for bit {bit} (Esc stops)')
    else:
        a, b = (end, narrow) if bus['kind'] == 'split' else (narrow, end)
        message = checkNewWire(app.library, circuit, a, b)
    if message != None:
        if pushed:
            afterEdit(app)             # (the SPLIT / MERGE stays)
        say(app, message, 'error')
        return message
    if not pushed:
        pushUndo(app)
    if bus['kind'] == 'split':
        routedWire(app, end, narrow)
    else:
        routedWire(app, narrow, end)
    afterEdit(app)
    free = freeBits(app, bus)
    target = describePort(circuit, narrow[1], narrow[2])
    wideName = describePort(circuit, bus['wide'][1], bus['wide'][2])
    if len(free) == 0:
        cancelTool(app)
        say(app, f'Bit {bit} -> {target}. All {bus["width"]} bits of '
                 f'{wideName} are wired.', 'good')
        return None
    later = [b for b in free if b > bit]
    bus['next'] = later[0] if len(later) > 0 else free[0]
    app.wireStart = busEnd(bus, bus['next'])
    say(app, f'Bit {bit} -> {target}. Now click the port for bit '
             f"{bus['next']} of {wideName} (0-{bus['width'] - 1}: pick "
             'another bit, Esc: stop)')
    return None

def pickBusBit(app, bit):
    # A digit while bus wiring: wire that bit next
    bus = app.bus
    if bit not in freeBits(app, bus):
        return say(app, f'Bit {bit} is ' + ('wired already' if
                   bit < bus['width'] else f"not on a {bus['width']}-bit "
                   'wire'), 'error')
    bus['next'] = bit
    app.wireStart = busEnd(bus, bit)
    say(app, f'Click the port for bit {bit}')

TIDY_CONFIRM_SECONDS = 2

def tidy(app, now):
    # w (or the Tidy button): reroutes the selected wires, or every wire
    # touching the selected parts, or (pressed twice) every wire on this
    # level. One undo step.
    from zb_route import tidyWires
    if not isEditable(app):
        return say(app, readOnlyMessage(app))
    circuit = getCircuit(app)
    ids = set(app.selection['wires'])
    parts = app.selection['parts']
    for wire in circuit['wires']:
        for end in [wire['a'], wire['b']]:
            if end[0] == 'port' and end[1] in parts:
                ids.add(wire['id'])
    if len(ids) == 0:
        count = len(circuit['wires'])
        if count == 0:
            return say(app, 'There are no wires here to tidy')
        armed = app.tidyArmed
        if armed == None or now - armed > TIDY_CONFIRM_SECONDS:
            app.tidyArmed = now
            return say(app, f'Press w again to tidy all {count} wires on '
                            'this level')
        ids = {wire['id'] for wire in circuit['wires']}
    app.tidyArmed = None
    pushUndo(app)
    order = [wire['id'] for wire in circuit['wires'] if wire['id'] in ids]
    rerouted, failed = tidyWires(app.library, circuit, order)
    if rerouted == 0:
        app.undo.pop()
        if failed > 0:
            return say(app, f'{failed} wire(s) could not be routed and kept '
                            'their shape')
        return say(app, 'Those wires are already as tidy as the router can '
                        'make them')
    afterEdit(app)
    message = f'Tidied {rerouted} wire(s)'
    if failed > 0:
        message += (f' ({failed} could not be routed and kept their '
                    'shape)')
    say(app, message, 'good')

def selectionPartIds(app):
    return set(app.selection['parts'])

def startMove(app, screenX, screenY):
    app.drag = {'kind': 'move', 'last': toWorld(app, screenX, screenY),
                'total': (0, 0), 'moved': False}

def dragMove(app, screenX, screenY):
    # Moves the selection by whole grid steps as the mouse moves
    drag = app.drag
    x, y = toWorld(app, screenX, screenY)
    lastX, lastY = drag['last']
    dx, dy = snap(x - lastX), snap(y - lastY)
    if dx == 0 and dy == 0:
        return
    if not drag['moved']:
        pushUndo(app)
        drag['moved'] = True
    drag['last'] = (lastX + dx, lastY + dy)
    moveSelection(app, dx, dy)

def moveSelection(app, dx, dy):
    circuit = getCircuit(app)
    ids = selectionPartIds(app)
    # Wires between two moved parts move whole
    for wire in circuit['wires']:
        aMoves = endMoves(wire['a'], ids, app.selection)
        bMoves = endMoves(wire['b'], ids, app.selection)
        if aMoves and bMoves:
            for point in wire['via']:
                point[0] += dx
                point[1] += dy
    for partId in ids:
        part = findPart(circuit, partId)
        if part != None:
            movePart(app.library, circuit, part, dx, dy)
    for junctionId in app.selection['junctions']:
        junction = findJunction(circuit, junctionId)
        if junction != None:
            junction['x'] += dx
            junction['y'] += dy

def endMoves(end, ids, selection):
    if end[0] == 'port':
        return end[1] in ids
    return end[1] in selection['junctions']

def endDrag(app):
    if app.drag != None and app.drag['kind'] == 'move' and \
       app.drag['moved']:
        afterEdit(app)
    app.drag = None

def selectBox(app, x1, y1, x2, y2, add):
    # Selects every part and junction inside the world rectangle
    circuit = getCircuit(app)
    left, right = min(x1, x2), max(x1, x2)
    top, bottom = min(y1, y2), max(y1, y2)
    if not add:
        app.selection = emptySelection()
    for part in circuit['parts']:
        x, y, w, h = partBounds(app.library, part)
        if left <= x and x + w <= right and top <= y and y + h <= bottom:
            app.selection['parts'].add(part['id'])
    for junction in circuit['junctions']:
        if left <= junction['x'] <= right and top <= junction['y'] <= bottom:
            app.selection['junctions'].add(junction['id'])

def deleteSelection(app):
    if not isEditable(app):
        return say(app, readOnlyMessage(app))
    selection = app.selection
    if (len(selection['parts']) + len(selection['wires']) +
        len(selection['junctions']) == 0):
        return
    pushUndo(app)
    circuit = getCircuit(app)
    for wireId in selection['wires']:
        wire = findWire(circuit, wireId)
        if wire != None:
            circuit['wires'].remove(wire)
    for partId in selection['parts']:
        removePart(circuit, partId)
    for junctionId in selection['junctions']:
        removeJunction(circuit, junctionId)
    cleanUpJunctions(circuit)
    app.selection = emptySelection()
    afterEdit(app)


######################################################################
# Copy, paste, properties
######################################################################

def copySelection(app):
    ids = selectionPartIds(app)
    if len(ids) == 0:
        return say(app, 'Select some parts to copy')
    app.clipboard = copyParts(getCircuit(app), ids)
    say(app, f'Copied {len(ids)} part(s)')

def paste(app, offset=40):
    if not isEditable(app):
        return say(app, readOnlyMessage(app))
    if app.clipboard == None:
        return say(app, 'Nothing copied yet (ctrl+c)')
    pushUndo(app)
    newIds = pasteParts(getCircuit(app), app.clipboard, offset, offset)
    app.selection = {'parts': set(newIds), 'wires': set(),
                     'junctions': set()}
    afterEdit(app)

def duplicate(app):
    copySelection(app)
    if app.clipboard != None:
        paste(app)

def getSelectedPart(app):
    if len(app.selection['parts']) != 1:
        return None
    return findPart(getCircuit(app), list(app.selection['parts'])[0])

def getSelectedWire(app):
    if len(app.selection['wires']) != 1:
        return None
    return findWire(getCircuit(app), list(app.selection['wires'])[0])

class ParamError(ValueError):
    # A typed value that can't be used, with a message saying why
    pass

def parseParamValue(old, text, typeName=None, key=None, params=None):
    # Turns typed text into the same kind of value as old. SPLIT ranges
    # and MERGE widths are typed in bus notation ('7:4 3:0', '4 4').
    text = text.strip()
    if typeName == 'SPLIT' and key == 'ranges':
        width = params['width'] if params != None else 8
        value, message = parseRanges(text, width)
        if message != None:
            raise ParamError(message)
        return value
    if typeName == 'MERGE' and key == 'widths':
        value, message = parseWidths(text)
        if message != None:
            raise ParamError(message)
        return value
    if type(old) == int:
        if text.lower().startswith('0b'):
            return int(text[2:], 2)
        if text.lower().startswith('0x'):
            return int(text[2:], 16)
        return int(text)
    if type(old) == list:
        value = json.loads(text)
        if type(value) != list:
            raise ValueError('expected a list')
        return value
    return text

def setParam(app, part, key, text):
    # Returns an error message, or None
    if not isEditable(app):
        return readOnlyMessage(app)
    old = part['params'][key]
    try:
        value = parseParamValue(old, text, part['type'], key,
                                part['params'])
    except ParamError as error:
        return f'{key}: {error}'
    except (ValueError, json.JSONDecodeError):
        return f"'{text}' is not a valid {key}"
    params = copy.deepcopy(part['params'])
    params[key] = value
    fitDependentParams(part['type'], params, key)
    if key == 'name' and part['type'] in ['PIN_IN', 'PIN_OUT']:
        for other in getCircuit(app)['parts']:
            if (other is not part and other['type'] in ['PIN_IN', 'PIN_OUT']
                and other['params']['name'] == value):
                return f'Another pin is already called {value}'
    message = checkParams(part['type'], params)
    if message != None:
        return message
    pushUndo(app)
    part['params'] = params
    app.lastParams[part['type']] = copy.deepcopy(params)
    if (key == 'name' and part['type'] in ['PIN_IN', 'PIN_OUT'] and
            editingPartName(app) != None and value != old):
        # the pin is a port of this part: its copies keep their wires
        renamePortWires(app, editingPartName(app), old, value)
    dropBadWires(app, part)
    afterEdit(app)
    return None

PARAM_LIMITS = {'inputs': (2, 8), 'width': (1, 8), 'outputs': (1, 16),
                'bits': (1, 4), 'from': (1, 8), 'to': (1, 8)}
PARAM_CHOICES = {'mode': ['zero', 'repeat'], 'init': ['0', 'X'],
                 'ports': ['side', 'top'],
                 'side': ['auto', 'left', 'top', 'right', 'bottom']}

def stepParam(app, part, key, amount):
    # The - / + buttons (and [ ]): one more or one less, kept in range.
    # Returns an error message, or None.
    value = part['params'][key] + amount
    if key == 'value':
        value %= 1 << part['params'].get('width', 1)
    elif key in PARAM_LIMITS:
        low, high = PARAM_LIMITS[key]
        if not low <= value <= high:
            return f'{key} goes from {low} to {high}'
    message = setParam(app, part, key, str(value))
    if message == None:
        say(app, f"{part['label'] or part['type']}: {key} = {value}")
    return message

def cycleParam(app, part, key):
    # A click on a setting with a few choices moves to the next one
    choices = PARAM_CHOICES[key]
    now = part['params'][key]
    value = choices[(choices.index(now) + 1) % len(choices)] if now in \
        choices else choices[0]
    message = setParam(app, part, key, value)
    if message == None:
        say(app, f"{part['label'] or part['type']}: {key} = {value}")
    return message

def fitDependentParams(typeName, params, key):
    # A SPLIT that gets narrower keeps ranges that still fit (or splits
    # into nibbles); a DECODER with fewer bits keeps outputs it can have
    from zb_parts import nibbleRanges
    if typeName == 'SPLIT' and key == 'width':
        width = params['width']
        ranges = [r for r in params['ranges'] if r[0] < width]
        params['ranges'] = ranges if len(ranges) > 0 else \
            nibbleRanges(width)
    if typeName == 'DECODER' and key == 'bits':
        params['outputs'] = min(params['outputs'], 1 << params['bits'])
    if typeName == 'EXTEND' and key in ['from', 'to']:
        if params['from'] > params['to']:
            other = 'to' if key == 'from' else 'from'
            params[other] = params[key]

def dropBadWires(app, part):
    # After a part changes size, wires to ports it no longer has (or of a
    # different width) are removed
    circuit = getCircuit(app)
    names = dict()
    for port in partLayout(app.library, part)[2]:
        names[port['name']] = port
    removed = 0
    for wire in list(circuit['wires']):
        for end in [wire['a'], wire['b']]:
            if (end[0] == 'port' and end[1] == part['id'] and
                end[2] not in names):
                circuit['wires'].remove(wire)
                removed += 1
                break
    for problem in validate(app.library, circuit):
        if problem['level'] == 'error' and part['id'] in problem['parts']:
            for wire in list(circuit['wires']):
                if (wire['a'][:2] == ['port', part['id']] or
                    wire['b'][:2] == ['port', part['id']]):
                    circuit['wires'].remove(wire)
                    removed += 1
            break
    cleanUpJunctions(circuit)
    if removed > 0:
        say(app, f'Removed {removed} wire(s) that no longer fit')

def setLabel(app, part, text):
    if not isEditable(app):
        return readOnlyMessage(app)
    pushUndo(app)
    part['label'] = text.strip()
    afterEdit(app)
    return None

def cycleTag(app, part):
    # Steps through the tags this part can carry (and none)
    if not isEditable(app):
        return say(app, readOnlyMessage(app))
    circuit = getCircuit(app)
    used = set()
    for other in circuit['parts']:
        if other is not part and other['ref'] != None:
            used.add(other['ref'])
    choices = [None]
    for tag in TAGS:
        if tagFits(tag, part['type']) and tag not in used:
            choices.append(tag)
    if len(choices) == 1:
        return say(app, 'Only registers, IR, PC, Flags and RAM can be '
                        'tagged')
    index = choices.index(part['ref']) if part['ref'] in choices else 0
    pushUndo(app)
    part['ref'] = choices[(index + 1) % len(choices)]
    afterEdit(app)

def cycleWireColor(app, wire):
    colors = [None, 'data', 'addr', 'control', 'opcode', 'operand']
    index = colors.index(wire['color']) if wire['color'] in colors else 0
    pushUndo(app)
    wire['color'] = colors[(index + 1) % len(colors)]
    afterEdit(app)

def setLamp(app, wire, text):
    pushUndo(app)
    text = text.strip()
    wire['lamp'] = text if text != '' else None
    afterEdit(app)

def toggleMode(app, part):
    # Fast or detailed simulation for a user part
    definition = getDefinition(app.library, part['type'])
    if definition['kind'] != 'composite':
        return say(app, 'Built-in parts always run fast')
    if part['mode'] == 'fast':
        pushUndo(app)
        part['mode'] = 'detailed'
        afterEdit(app)
        return say(app, 'Detailed: its inside is simulated gate by gate')
    if definition['stateful']:
        return say(app, 'Parts that hold state always run detailed')
    if not definition['verified']:
        return say(app, 'Verify it first: only a verified part can run as '
                        'its built-in twin')
    pushUndo(app)
    part['mode'] = 'fast'
    afterEdit(app)
    say(app, f"Fast: runs as the built-in {definition['implements']}")


######################################################################
# User parts
######################################################################

def packInto(app, name):
    if not isEditable(app):
        return say(app, readOnlyMessage(app))
    name = name.strip()
    if name == '':
        return
    pushUndo(app)
    definition, result = packSelection(app.library, getCircuit(app),
                                       selectionPartIds(app), name)
    if definition == None:
        app.undo.pop()
        return say(app, result, 'error')
    saveUserPart(definition, PARTS_DIR)
    app.selection = {'parts': {result['id']}, 'wires': set(),
                     'junctions': set()}
    afterEdit(app)
    say(app, f'Made the part "{name}". Enter opens it; it is in My parts.')

def newUserPart(app, name):
    # A blank part with one input and one output pin: places it in the
    # middle of the view and opens it, ready to build inside
    from zb_library import makeUserPart
    if not isEditable(app):
        return say(app, readOnlyMessage(app))
    name = name.strip()
    if name == '':
        return
    if name in app.library['user'] or name in PRIMITIVES:
        return say(app, f'There is already a part called {name}', 'error')
    inner = makeCircuit(name)
    addPart(app.library, inner, 'PIN_IN', 0, 40, {'name': 'in0'})
    addPart(app.library, inner, 'PIN_OUT', 300, 40, {'name': 'out0'})
    definition = makeUserPart(app.library, name, inner)
    saveUserPart(definition, PARTS_DIR)
    pushUndo(app)
    left, top, width, height = getCanvas(app)
    x, y = toWorld(app, left + width / 2, top + height / 2)
    part = addPart(app.library, getCircuit(app), name, snap(x), snap(y))
    afterEdit(app)
    drillIn(app, part['id'])
    say(app, f'Building "{name}": its pins are its ports. Esc goes back up.')

######################################################################
# How your part looks from outside: its size, and which side each port
# is on. Layout only, so a verified part stays verified.
######################################################################

SIZE_STEP = 10

def partBoxSize(app, definition):
    # (width, height) the part is drawn at now, and the smallest it can be
    from zb_circuit import compositeInfo, getPins, pinsBySide, boxMinimum
    width, height, ports = compositeInfo(app.library,
                                         definition['name'])['layout']
    inputs, outputs = getPins(definition['circuit'])
    return (width, height), boxMinimum(pinsBySide(inputs, outputs))

def afterLayoutEdit(app, definition, message):
    # The part's ports moved: save it, and straighten the wires on its
    # copies here (their bends were made for the old port positions)
    from zb_route import tidyWires
    updateUserPart(app.library, definition)
    saveUserPart(definition, PARTS_DIR)
    if isEditable(app):
        circuit = getCircuit(app)
        ids = {part['id'] for part in circuit['parts']
               if part['type'] == definition['name']}
        wires = [wire['id'] for wire in circuit['wires']
                 if len(wire['via']) > 0 and any(
                     end[0] == 'port' and end[1] in ids
                     for end in [wire['a'], wire['b']])]
        if len(wires) > 0:
            tidyWires(app.library, circuit, wires)
    app.editVersion += 1
    syncProblems(app)
    autosave(app)
    say(app, message)

def setPartSize(app, definition, width, height):
    # width, height in world units (None, None: automatic, the smallest)
    pushUndo(app)
    if width == None:
        definition['size'] = None
    else:
        (now, smallest) = partBoxSize(app, definition)
        width = max(smallest[0], snap(width))
        height = max(smallest[1], snap(height))
        definition['size'] = [width, height]
    definitionChanged(app.library)
    size = partBoxSize(app, definition)[0]
    afterLayoutEdit(app, definition, f"{definition['name']} is "
                                     f'{size[0]} x {size[1]}' +
                    ('' if width != None else ' (automatic size)'))

def growPart(app, definition, dWidth, dHeight):
    (width, height), smallest = partBoxSize(app, definition)
    setPartSize(app, definition, width + dWidth, height + dHeight)

def parseSize(text):
    # '120 x 80', '120,80', '120 80' -> (120, 80); 'auto' -> (None, None);
    # anything else -> None
    text = text.strip().lower()
    if text in ['auto', 'automatic', '']:
        return (None, None)
    for sign in ['x', '*', ',']:
        text = text.replace(sign, ' ')
    pieces = text.split()
    if len(pieces) == 2 and all(p.isdigit() for p in pieces):
        return (int(pieces[0]), int(pieces[1]))
    return None

def portPin(definition, portName):
    # The IN / OUT pin inside a part that is its port portName
    for part in definition['circuit']['parts']:
        if part['type'] in ['PIN_IN', 'PIN_OUT'] and \
                part['params']['name'] == portName:
            return part
    return None

def cyclePortSide(app, definition, portName):
    # left -> top -> right -> bottom -> left (from the side it is on now)
    from zb_circuit import pinSide, SIDES
    pin = portPin(definition, portName)
    if pin == None:
        return
    pushUndo(app)
    side = SIDES[(SIDES.index(pinSide(pin)) + 1) % len(SIDES)]
    pin['params']['side'] = side
    pin['params'].pop('order', None)       # last on its new side
    definitionChanged(app.library)
    afterLayoutEdit(app, definition, f'{portName} is on the {side} now')

def movePortEarlier(app, definition, portName):
    # Moves a port one place up (or left) on its side
    from zb_circuit import getPins, pinsBySide, pinSide
    pin = portPin(definition, portName)
    if pin == None:
        return
    inputs, outputs = getPins(definition['circuit'])
    pins = pinsBySide(inputs, outputs)[pinSide(pin)]
    index = pins.index(pin)
    if index == 0:
        return say(app, f'{portName} is already first on its side')
    pushUndo(app)
    pins[index - 1], pins[index] = pins[index], pins[index - 1]
    for order, other in enumerate(pins):
        other['params']['order'] = order
    definitionChanged(app.library)
    afterLayoutEdit(app, definition, f'{portName} moved up')

MAX_PORT_NAME = 10

def portNameProblem(circuit, pin, name):
    # Why name can't be this pin's (port's) name, or None if it can
    if name == '':
        return 'A port needs a name'
    if len(name) > MAX_PORT_NAME:
        return f'Port names are at most {MAX_PORT_NAME} characters'
    if not all(c.isalnum() or c == '_' for c in name):
        return 'Port names use letters, digits and _ only'
    for other in circuit['parts']:
        if (other is not pin and other['type'] in ['PIN_IN', 'PIN_OUT']
                and other['params']['name'] == name):
            return f'Another port is already called {name}'
    return None

def renamePortWires(app, partName, oldName, newName):
    # Wires on the copies of user part partName that end at its port
    # oldName now end at newName (in your circuit and in your other parts)
    circuits = [(app.root, None)]
    if app.stash != None:
        circuits.append((app.stash['root'], None))
    for definition in app.library['user'].values():
        circuits.append((definition['circuit'], definition))
    for circuit, owner in circuits:
        ids = {part['id'] for part in circuit['parts']
               if part['type'] == partName}
        if len(ids) == 0:
            continue
        for wire in circuit['wires']:
            for end in [wire['a'], wire['b']]:
                if (end[0] == 'port' and end[1] in ids and
                        end[2] == oldName):
                    end[2] = newName
        if owner != None:
            saveUserPart(owner, PARTS_DIR)

def renamePort(app, definition, oldName, text):
    # Gives one of your part's ports a new name: the IN / OUT pin inside
    # it is renamed, and the wires on its copies stay connected
    pin = portPin(definition, oldName)
    if pin == None or text == None:
        return
    newName = text.strip()
    if newName == oldName:
        return
    problem = portNameProblem(definition['circuit'], pin, newName)
    if problem != None:
        return say(app, problem, 'error')
    pushUndo(app)
    pin['params']['name'] = newName
    renamePortWires(app, definition['name'], oldName, newName)
    definition['verified'] = False     # (its ports changed)
    definitionChanged(app.library)
    afterLayoutEdit(app, definition, f'Port {oldName} is now called '
                                     f'{newName}')

def userPortRows(app, definition):
    # [(port name, side, direction, width)] in the order they are drawn
    from zb_circuit import getPins, pinsBySide, SIDES
    inputs, outputs = getPins(definition['circuit'])
    sides = pinsBySide(inputs, outputs)
    rows = []
    for side in SIDES:
        for pin in sides[side]:
            rows.append((pin['params']['name'], side,
                         'in' if pin['type'] == 'PIN_IN' else 'out',
                         pin['params']['width']))
    return rows

def currentUserPart(app):
    # The selected user part's definition, else the one being edited
    part = getSelectedPart(app)
    if part != None:
        definition = getDefinition(app.library, part['type'])
        if definition != None and definition['kind'] == 'composite':
            return definition
        return None
    name = editingPartName(app)
    if name != None:
        return app.library['user'].get(name)
    return None

def copyRecipe(app, name):
    # Copies the built-in recipe on screen into a new editable user part
    from zb_library import makeUserPart
    name = name.strip()
    if name == '' or name in app.library['user'] or name in PRIMITIVES:
        return say(app, 'Pick a new name', 'error')
    definition = makeUserPart(app.library, name,
                              copy.deepcopy(getCircuit(app)))
    saveUserPart(definition, PARTS_DIR)
    say(app, f'"{name}" is in My parts: place it, then Enter to edit it')

def partToVerify(app):
    # The user part selected (or on screen), or None
    part = getSelectedPart(app)
    definition = None
    if part != None:
        definition = getDefinition(app.library, part['type'])
    elif editingPartName(app) != None:
        definition = app.library['user'][editingPartName(app)]
    if definition == None or definition['kind'] != 'composite':
        return None
    return definition

# Built-ins a part can't be checked against (they hold state, or are
# only pins)
NOT_VERIFIABLE = {'PIN_IN', 'PIN_OUT', 'PROBE', 'CLOCK'}

def verifyChoices(app, definition):
    # [(type name, matches, note)] of every built-in the part could be
    # checked against: the ones whose ports match the part's pins first,
    # then the rest with what is different
    from zb_circuit import compositeInfo, portsMatch
    from zb_library import getPorts
    mine = compositeInfo(app.library, definition['name'])['layout'][2]
    matching, others = [], []
    for typeName, builtIn in PRIMITIVES.items():
        if typeName in NOT_VERIFIABLE or builtIn['commit'] != None:
            continue
        ports = getPorts(app.library, typeName)
        inputs = ', '.join(p['name'] for p in ports if p['dir'] == 'in')
        outputs = ', '.join(p['name'] for p in ports if p['dir'] == 'out')
        signature = f"{inputs or '-'} -> {outputs}"
        if portsMatch(mine, ports):
            matching.append((typeName, True, signature))
        else:
            # how many of its ports your part lacks (or has differently)
            have = {(p['name'], p['dir'], p['width']) for p in mine}
            differ = sum(1 for p in ports
                         if (p['name'], p['dir'], p['width']) not in have)
            extra = len(mine) - (len(ports) - differ)
            note = f'{differ} of its ports missing or different'
            if extra > 0:
                note += f', {extra} extra pin(s)'
            others.append((differ + max(0, extra), typeName,
                           f'needs {signature}  ({note})'))
    # the closest ones (fewest pins to fix) first
    others.sort(key=lambda item: item[0])
    return matching + [(name, False, note) for n, name, note in others]

def verifyCurrent(app, target):
    # Verifies the user part on screen (or selected) against a built-in
    definition = partToVerify(app)
    if definition == None:
        return say(app, 'Select one of your parts (or open it) to verify')
    target = target.strip().upper()
    if target not in PRIMITIVES:
        return say(app, f'{target} is not a built-in part', 'error')
    result = verifyPart(app.library, definition, target)
    app.verifyResult = result
    saveUserPart(definition, PARTS_DIR)
    if result['ok']:
        say(app, result['message'], 'good')
    else:
        say(app, result['message'], 'error')


######################################################################
# Truth tables (u), and setting IN pins in Run mode
######################################################################

def tableForView(app):
    # (table data, None) for the level on screen, or (None, a message
    # saying why there is no table)
    from zb_library import truthTable, builtInExpected, getPorts
    import zb_missions
    circuit = getCircuit(app)
    mission = app.mission
    top = len(app.path) == 0           # (missions are about the top level)
    if mission != None and top and mission['kind'] == 'sequence':
        return zb_missions.stepTable(app.library, mission, circuit), None
    if mission != None and top and mission['kind'] == 'part':
        data = zb_missions.missionTable(app.library, mission, circuit)
    else:
        expected, order = None, None
        name = editingPartName(app)
        definition = app.library['user'].get(name) if name else None
        target = definition.get('implements') if definition else None
        if target in PRIMITIVES and PRIMITIVES[target]['commit'] == None:
            expected = builtInExpected(target)
            order = [p['name'] for p in getPorts(app.library, target)]
        data = truthTable(app.library, circuit, expected, order)
    if data['stateful']:
        return None, (f"This circuit remembers ({data['reason']}), so its "
                      'outputs depend on what came before, not only on the '
                      'inputs. Click its IN pins in Run mode to try it.')
    if data['reason'] != None:
        return None, f"No truth table: {data['reason']}"
    return data, None

def openTableData(app, data, selected=None):
    app.table = {'data': data, 'scroll': 0, 'onlyWrong': False,
                 'selected': selected, 'playing': False, 'docked': False,
                 'hover': None, 'colScroll': 0, 'hiddenCols': (0, 0)}
    if selected != None:
        app.table['scroll'] = max(0, selected - 5)

def tableRows(app):
    # The rows the table shows (all, or only the wrong ones), as
    # (index, row)
    table = app.table
    rows = table['data'].get('rows', [])
    if table['onlyWrong']:
        return [(i, row) for i, row in enumerate(rows) if row['wrong']]
    return list(enumerate(rows))

def editSimState(sim, prim, newState):
    # Gives a part a new state now. The future (history after this phase)
    # no longer holds, so it is cut.
    prim['state'] = newState
    step = sim['halfCycles']
    del sim['history'][step + 1:]
    from zb_sim import snapshot
    sim['history'][step] = snapshot(sim)
    sim['seeds'].add(prim['index'])

def rootPins(app):
    # {name: prim} of the top level's IN pins in the running machine
    pins = dict()
    if app.sim == None:
        return pins
    for prim in app.sim['prims']:
        if prim['type'] == 'PIN_IN' and len(prim['path']) == 1:
            pins[prim['params']['name']] = prim
    return pins

def setRootPins(app, values):
    # Sets the top level's IN pins ({name: value}) and settles once.
    # Returns the number of pins changed.
    from zb_sim import settle
    pins = rootPins(app)
    changed = 0
    for name, value in values.items():
        prim = pins.get(name)
        if prim != None and prim['state'] != value:
            editSimState(app.sim, prim, value)
            changed += 1
    settle(app.sim)
    return changed


######################################################################
# Files
######################################################################

def listCircuits():
    try:
        names = os.listdir(CIRCUIT_DIR)
    except OSError:
        return []
    result = []
    for name in sorted(names):
        if name.endswith('.json'):
            result.append(name[:-5])
    return result

def listCircuitsByDate():
    # The saved circuits, newest first (autosave left out)
    names = [name for name in listCircuits() if name != AUTOSAVE]
    def modified(name):
        try:
            return os.path.getmtime(os.path.join(CIRCUIT_DIR, name +
                                                 '.json'))
        except OSError:
            return 0
    return sorted(names, key=lambda name: -modified(name))

def saveAs(app, name):
    name = name.strip()
    if name == '':
        return
    os.makedirs(CIRCUIT_DIR, exist_ok=True)
    app.root['name'] = name
    saveCircuit(app.root, os.path.join(CIRCUIT_DIR, name + '.json'))
    app.fileName = name
    app.savedVersion = app.editVersion
    say(app, f'Saved circuits/{name}.json', 'good')

def isUnsaved(app):
    return app.editVersion != app.savedVersion

def openCircuit(app, circuit, fileName=None):
    pushUndo(app)
    app.root = circuit
    app.path = []
    app.cams = dict()
    app.selection = emptySelection()
    cancelTool(app)
    refreshView(app)
    afterEdit(app)
    app.fileName = fileName
    app.savedVersion = app.editVersion

def openFile(app, name):
    try:
        circuit = loadCircuit(os.path.join(CIRCUIT_DIR, name + '.json'))
    except (OSError, ValueError) as error:
        return say(app, f'Could not open {name}: {error}', 'error')
    openCircuit(app, circuit, name)
    say(app, f'Opened {name}')

def stashRoot(app):
    # Remembers the circuit on screen before a mission (or a part sheet)
    # replaces it, so it can come back. A second replacement keeps the
    # first one remembered.
    if app.stash == None:
        app.stash = {'root': app.root, 'fileName': app.fileName,
                     'unsaved': isUnsaved(app),
                     'name': app.root.get('name', 'untitled')}

def restoreStash(app):
    # Brings back the remembered circuit. Returns True if there was one.
    stash = app.stash
    if stash == None:
        return False
    app.stash = None
    openCircuit(app, stash['root'], stash['fileName'])
    if stash['unsaved']:
        app.savedVersion = -1          # (it still has unsaved changes)
    say(app, f"Back to {stash['name']}")
    return True

def openPartSheet(app, name):
    # Opens one of your parts for editing: a sheet holding one copy of it,
    # opened up. Esc shows the copy; Open > Back returns to your circuit.
    definition = app.library['user'].get(name)
    if definition == None:
        return say(app, f'There is no part called {name}', 'error')
    stashRoot(app)
    sheet = makeCircuit(f'Part: {name}')
    part = addPart(app.library, sheet, name, 0, 0)
    openCircuit(app, sheet)
    drillIn(app, part['id'])
    say(app, f'Editing {name}. Esc shows it from outside; Open > Back to '
             'returns to your circuit.')

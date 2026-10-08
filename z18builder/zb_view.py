# zb_view.py
# Draws the builder: the canvas (parts, wires, values moving along wires),
# the palette, the properties / inspector panel, the control strip, the
# timeline and the pop-up lists. Every draw function only reads app.
# The small read-only helpers here (panel rectangles, property rows) are
# also used by zb_main.py to know what was clicked.
#
# Each shape takes a part dict (and the camera), so any part can be drawn
# anywhere on the canvas.

import math
from types import SimpleNamespace
from cmu_graphics import rgb
# All drawing goes through zb_paint (see there): nothing here calls the
# graphics library directly
from zb_paint import (onePixel, scaledRect, scaledLine, scaledCircle,
                      scaledPolygon, scaledLabel, DESIGN_WIDTH,
                      DESIGN_HEIGHT, clipTo, unclip)
from zb_helpers import pointAlongPath, pathUpTo, pathLength, offsetPolyline
from zb_values import (Z, X, isKnown, formatValue, formatAll, getBit,
                       bitString, toSignedWidth)
from zb_parts import PRIMITIVES, RAM_WORDS, formatRanges, formatWidths
from zb_circuit import (getDefinition, partLayout, wirePoints, findPart,
                        computeNets, nodeKey, portSide, getPort)
from zb_editor import (toWorld, getCam, getCircuit, getSelectedPart,
                       getSelectedWire, editingPartName, snap)
from zb_editor import toScreen as editorToScreen
from zb_editor import getCanvas as editorGetCanvas
from zb_kit import PALETTE as KIT_PALETTE, TAG_NAMES
from z18_assembler import shortDisassemble, disassemble, isInstruction

FONT = 'monospace'
WINDOW_WIDTH = DESIGN_WIDTH            # the layout's size in design units
WINDOW_HEIGHT = DESIGN_HEIGHT          # (zb_paint scales it to the window)

# Colors
BG_COLOR = rgb(24, 26, 32)
CANVAS_COLOR = rgb(28, 30, 37)
GRID_COLOR = rgb(44, 48, 59)
TEXT_COLOR = rgb(225, 228, 235)
DIM_TEXT_COLOR = rgb(140, 146, 160)
TITLE_COLOR = rgb(120, 190, 255)
PANEL_COLOR = rgb(38, 41, 51)
BORDER_COLOR = rgb(80, 86, 104)
COMPONENT_FILL = rgb(46, 50, 63)
COMPONENT_BORDER = rgb(120, 128, 150)
DIM_WIRE_COLOR = rgb(66, 70, 86)
DATA_COLOR = rgb(90, 180, 255)
ADDR_COLOR = rgb(190, 140, 255)
CONTROL_COLOR = rgb(255, 165, 60)
MID_COLOR = rgb(80, 210, 200)
OPCODE_COLOR = rgb(110, 220, 130)
OPERAND_COLOR = rgb(240, 110, 110)
UNKNOWN_COLOR = rgb(200, 80, 80)
LANE_OFF_COLOR = rgb(55, 58, 70)
FLASH_COLOR = rgb(255, 230, 80)
GOOD_COLOR = rgb(110, 220, 130)
ERROR_COLOR = rgb(255, 110, 110)
WARN_COLOR = rgb(255, 190, 90)
LABEL_BG_COLOR = rgb(24, 26, 32)
READ_COLOR = rgb(40, 70, 110)
WRITE_COLOR = rgb(30, 100, 70)
BIT_ON_FILL = rgb(95, 85, 30)
BIT_OFF_FILL = rgb(32, 34, 42)
BREAKPOINT_COLOR = rgb(230, 60, 60)
LIT_GATE_FILL = rgb(90, 64, 30)
TG_ON_FILL = rgb(70, 50, 100)
WAVE_FILL = rgb(60, 66, 44)
BUTTON_COLOR = rgb(55, 90, 150)
DISABLED_COLOR = rgb(70, 72, 80)
ON_COLOR = rgb(190, 110, 40)
TRACK_COLOR = rgb(58, 63, 78)
SELECT_COLOR = TITLE_COLOR

NAMED_COLORS = {'data': DATA_COLOR, 'addr': ADDR_COLOR,
                'control': CONTROL_COLOR, 'opcode': OPCODE_COLOR,
                'operand': OPERAND_COLOR}

# Screen regions (design units)
TITLE_HEIGHT = 40
TOOLBAR_TOP = 44
# (a 1440 x 810 layout, 16:9; the canvas takes all the room the panels
# leave)
PALETTE_RECT = (4, 82, 150, 596)
BUILD_CANVAS = (158, 82, 1030, 596)
RUN_CANVAS = (4, 82, 1184, 596)
SIDE = (1192, 82, 244, 596)
BOTTOM = (4, 682, 1432, 82)
TIMELINE = (4, 768, 1432, 38)
TRACK_LEFT = 130
TRACK_RIGHT = 1140
PALETTE_TAB_HEIGHT = 26
PALETTE_ROW_HEIGHT = 25
SIDE_ROW_HEIGHT = 20
LAYOUT = {'buildCanvas': BUILD_CANVAS, 'runCanvas': RUN_CANVAS}

IDLE, WAVES, EDGE = 0, 1, 2
from zb_editor import SPEEDS, FRAMES_PER_WAVE, speedLabel
MIN_PACKET_PATH = 40
MIN_TEXT = 5.5                 # smallest canvas text, in design units
RAM_ROW_TOP = 26
RAM_ROW_HEIGHT = 18
RAM_TEXT = 8


######################################################################
# Drawing in world units (through the camera)
######################################################################

# While a frame is drawn, the camera and canvas are read from app once (in
# drawApp) and kept here. Reading app.anything goes through cmu_graphics's
# attribute translation, which was a large part of each frame.
FRAME = {'active': False}

def startFrame(app):
    cam = getCam(app)
    FRAME.clear()
    FRAME.update({'active': True, 'canvas': editorGetCanvas(app),
                  'camX': cam['x'], 'camY': cam['y'], 'zoom': cam['zoom'],
                  'levelInfo': None})

def endFrameCache():
    FRAME.clear()
    FRAME['active'] = False

def getCanvas(app):
    if FRAME['active']:
        return FRAME['canvas']
    return editorGetCanvas(app)

def toScreen(app, x, y):
    if FRAME['active']:
        left, top = FRAME['canvas'][0], FRAME['canvas'][1]
        zoom = FRAME['zoom']
        return (left + (x - FRAME['camX']) * zoom,
                top + (y - FRAME['camY']) * zoom)
    return editorToScreen(app, x, y)

def zoomOf(app):
    if FRAME['active']:
        return FRAME['zoom']
    return getCam(app)['zoom']

def wLine(app, x1, y1, x2, y2, color, width=1.5, opacity=100):
    sx1, sy1 = toScreen(app, x1, y1)
    sx2, sy2 = toScreen(app, x2, y2)
    scaledLine(sx1, sy1, sx2, sy2, fill=color,
               lineWidth=max(onePixel(), width * zoomOf(app)),
               opacity=opacity)

def wPolyline(app, points, color, width, opacity=100):
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        if x1 != x2 or y1 != y2:
            wLine(app, x1, y1, x2, y2, color, width, opacity)
    if width * zoomOf(app) >= 3:
        # fill the gaps at the corners of thick lines
        for x, y in points[1:-1]:
            wRect(app, x - width / 2, y - width / 2, width, width, color,
                  opacity=opacity)

def wRect(app, left, top, width, height, fill, border=None, borderWidth=1,
          opacity=100):
    sx, sy = toScreen(app, left, top)
    zoom = zoomOf(app)
    scaledRect(sx, sy, width * zoom, height * zoom, fill=fill, border=border,
               borderWidth=max(onePixel(), borderWidth * min(1, zoom)),
               opacity=opacity)

def wPolygon(app, points, fill, border=None, borderWidth=1):
    screen = []
    for i in range(0, len(points), 2):
        sx, sy = toScreen(app, points[i], points[i + 1])
        screen += [sx, sy]
    scaledPolygon(screen, fill=fill, border=border,
                  borderWidth=max(onePixel(), borderWidth * min(1, zoomOf(app))))

def wCircle(app, x, y, radius, fill):
    sx, sy = toScreen(app, x, y)
    scaledCircle(sx, sy, max(1, radius * zoomOf(app)), fill=fill)

def wText(app, text, x, y, size=9, color=TEXT_COLOR, align='center',
          bold=False):
    # Small text is drawn at a readable minimum size (the whole lecture
    # machine only fits at about 0.55 zoom); tiny text is skipped
    # Small decorative text (port names, gate types: size < 8) is skipped
    # when it would be tiny, which also keeps the shape count down
    scaled = size * zoomOf(app)
    if text == '' or scaled < MIN_TEXT * 0.6 or (size < 8 and scaled < 5):
        return
    size = max(MIN_TEXT, scaled)
    sx, sy = toScreen(app, x, y)
    scaledLabel(text, sx, sy, size=size, fill=color, font=FONT, align=align,
                bold=bold)

def drawText(text, x, y, size=10, color=TEXT_COLOR, align='center',
             bold=False):
    # In design units (panels)
    scaledLabel(text, x, y, size=size, fill=color, font=FONT, align=align,
                bold=bold)

def arcPoints(cx, cy, rx, ry, startDegrees, endDegrees, count):
    points = []
    for i in range(count + 1):
        angle = math.radians(startDegrees +
                             (endDegrees - startDegrees) * i / count)
        points += [cx + rx * math.cos(angle), cy - ry * math.sin(angle)]
    return points

def fitText(text, maxChars):
    if len(text) <= maxChars:
        return text
    return text[:max(1, maxChars - 1)] + '.'

def wrapText(text, maxChars):
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for word in paragraph.split(' '):
            if line == '':
                line = word
            elif len(line) + 1 + len(word) <= maxChars:
                line += ' ' + word
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


######################################################################
# Values at the level on screen (read-only)
######################################################################

def getLevelInfo(app):
    # The level's nets, and which sim net each one is. Cached until the
    # circuit or the view changes (and looked up once per frame)
    if FRAME['active'] and FRAME['levelInfo'] != None:
        return FRAME['levelInfo']
    info = findLevelInfo(app)
    if FRAME['active']:
        FRAME['levelInfo'] = info
    return info

def findLevelInfo(app):
    key = (app.editVersion, app.viewVersion, app.mode)
    if app.levelCache.get('key') == key:
        return app.levelCache['info']
    view = app.view
    circuit = view['circuit']
    nets = computeNets(app.library, circuit)
    simNets = []
    sim = view['sim']
    for net in nets['nets']:
        index = None
        if sim != None:
            keys = []
            for partId, portName in net['ports']:
                keys.append(('port', view['prefix'] + (partId,), portName))
            for junctionId in net['junctions']:
                keys.append(('junction', view['prefix'] + (junctionId,)))
            for key2 in keys:
                if key2 in sim['nodeNet']:
                    index = sim['nodeNet'][key2]
                    break
        simNets.append(index)
    info = {'nets': nets, 'simNets': simNets, 'widths': dict()}
    for i in range(len(nets['nets'])):
        info['widths'][i] = netWidth(app, circuit, nets['nets'][i])
    # (changed in place: cmu_graphics forbids setting app fields while
    # drawing)
    app.levelCache.clear()
    app.levelCache.update({'key': key, 'info': info})
    app.flowCache.clear()
    return info

def netWidth(app, circuit, net):
    for partId, portName in net['ports']:
        port = getPort(app.library, findPart(circuit, partId), portName)
        if port != None:
            return port['width']
    return 1

def simNetOf(app, netIndex):
    return getLevelInfo(app)['simNets'][netIndex]

def netValue(app, netIndex):
    # The value on a level net, or None when nothing is running
    sim = app.view['sim']
    simIndex = simNetOf(app, netIndex)
    if sim == None or simIndex == None:
        return None
    return sim['nets'][simIndex]['value']

def portNet(app, part, portName):
    info = getLevelInfo(app)
    return info['nets']['nodeNet'].get(('port', part['id'], portName))

def portValue(app, part, portName):
    netIndex = portNet(app, part, portName)
    if netIndex == None:
        return None
    return netValue(app, netIndex)

def getPrim(app, part):
    # The simulated primitive for a part at this level, or None
    view = app.view
    sim = view['sim']
    if sim == None:
        return None
    index = sim['primByPath'].get(view['prefix'] + (part['id'],))
    if index == None:
        return None
    return sim['prims'][index]

def partState(app, part):
    prim = getPrim(app, part)
    if prim == None:
        return None
    return prim['state']

def isLive(app):
    return app.mode == 'run' and app.view['sim'] != None and \
        app.view['live']

def isAnimating(app):
    return app.mode == 'run' and app.stage == WAVES

def netWave(app, netIndex):
    # The wave in which this net changed during the phase on screen
    if not isLive(app):
        return None
    simIndex = simNetOf(app, netIndex)
    if simIndex == None:
        return None
    return app.sim['netWave'].get(simIndex)

def waveReached(app, wave):
    # True if the animation has shown wave (or is not animating)
    if not isAnimating(app):
        return True
    return wave == None or wave < app.wave or (wave == app.wave and
                                              app.waveT >= 1)


######################################################################
# Wire colors and flows
######################################################################

def widthColor(width):
    if width == 1:
        return CONTROL_COLOR
    if width == 4:
        return ADDR_COLOR
    if width == 8:
        return DATA_COLOR
    return MID_COLOR

def wireColor(app, wire, width):
    if wire['color'] in NAMED_COLORS:
        return NAMED_COLORS[wire['color']]
    return widthColor(width)

def wireThickness(width):
    if width == 1:
        return 1.5
    if width <= 4:
        return 3
    return 4.5

def getWireState(app, wire, netIndex):
    # 'dim', 'lit', 'moving' or 'unknown'
    if app.mode != 'run':
        return 'dim'
    value = netValue(app, netIndex)
    wave = netWave(app, netIndex)
    if isAnimating(app) and wave != None:
        if wave > app.wave:
            return 'dim'
        if wave == app.wave and app.waveT < 1:
            return 'moving'
    if value == None or value == Z:
        return 'dim'
    if value == X:
        return 'unknown'
    if getLevelInfo(app)['widths'][netIndex] == 1 and value == 0:
        return 'dim'
    return 'lit'

def getFlow(app, netIndex):
    # For each wire of the net: (start distance, length, reversed), so a
    # value spreads out from the part driving the net at a steady speed
    key = (app.simVersion, netIndex)
    if key in app.flowCache:
        return app.flowCache[key]
    circuit = getCircuit(app)
    info = getLevelInfo(app)
    net = info['nets']['nets'][netIndex]
    edges = dict()
    lengths = dict()
    wires = [w for w in circuit['wires'] if w['id'] in set(net['wires'])]
    for wire in wires:
        a, b = nodeKey(wire['a']), nodeKey(wire['b'])
        length = pathLength(wirePoints(app.library, circuit, wire))
        lengths[wire['id']] = length
        edges.setdefault(a, []).append((b, length))
        edges.setdefault(b, []).append((a, length))
    sources = findSources(app, circuit, net)
    distance = dict()
    frontier = [(0, source) for source in sources]
    while len(frontier) > 0:
        frontier.sort()
        d, node = frontier.pop(0)
        if node in distance:
            continue
        distance[node] = d
        for other, length in edges.get(node, []):
            if other not in distance:
                frontier.append((d + length, other))
    flow = dict()
    total = 0
    for wire in wires:
        a, b = nodeKey(wire['a']), nodeKey(wire['b'])
        da, db = distance.get(a, 0), distance.get(b, 0)
        start = min(da, db)
        flow[wire['id']] = (start, lengths[wire['id']], db < da)
        total = max(total, start + lengths[wire['id']])
    result = {'wires': flow, 'total': max(1, total)}
    app.flowCache[key] = result
    return result

def findSources(app, circuit, net):
    # The output ports driving the net (the ones really driving, if known)
    sources = []
    active = []
    for partId, portName in net['ports']:
        part = findPart(circuit, partId)
        port = getPort(app.library, part, portName)
        if port == None or port['dir'] != 'out':
            continue
        key = ('port', partId, portName)
        sources.append(key)
        prim = getPrim(app, part)
        if prim != None:
            netIndex = prim['outNets'].get(portName)
            value = app.view['sim']['nets'][netIndex]['driverValues'].get(
                (prim['index'], portName))
            if value != Z:
                active.append(key)
    if len(active) > 0:
        return active
    if len(sources) > 0:
        return sources
    return [('port', net['ports'][0][0], net['ports'][0][1])] if \
        len(net['ports']) > 0 else []

def wireProgress(app, wire, netIndex):
    flow = getFlow(app, netIndex)
    start, length, backwards = flow['wires'][wire['id']]
    t = app.waveT * flow['total']
    if length <= 0:
        return 1, backwards
    return max(0, min(1, (t - start) / length)), backwards


######################################################################
# Wires
######################################################################

def drawBitLanes(app, points, width, value, color, progress=None):
    lanes = width
    spacing = 2 * onePixel() / zoomOf(app)
    for lane in range(lanes):
        offset = (lane - (lanes - 1) / 2) * spacing
        lanePoints = offsetPolyline(points, offset)
        bit = 0
        if isKnown(value):
            bit = getBit(value, lanes - 1 - lane)
        laneColor = color if bit == 1 else LANE_OFF_COLOR
        if progress != None:
            if bit == 1:
                wPolyline(app, pathUpTo(lanePoints, progress), color,
                          1 / zoomOf(app))
        else:
            wPolyline(app, lanePoints, laneColor, 1 / zoomOf(app))

HOP_RADIUS = 4                 # world units (zb_circuit.wireGeometry)
DIM_OPACITY = 40               # other nets, while one net is lit up

def currentGeometry(app):
    # The wire geometry of the level on screen, if it is up to date
    geom = app.wireGeom
    if geom == None or geom.get('key') != (app.editVersion,
                                           app.viewVersion):
        return None
    return geom

def wirePath(app, wire):
    # The wire's polyline, with hops where it crosses another net (when
    # they would be big enough to see)
    geom = currentGeometry(app)
    if geom != None and wire['id'] in geom['hopPaths'] and \
            HOP_RADIUS * zoomOf(app) >= 2 * onePixel():
        return geom['hopPaths'][wire['id']]
    return wirePoints(app.library, getCircuit(app), wire)

FEEDER_COLOR = rgb(110, 220, 130)     # parts that feed the focus part
TAKER_COLOR = rgb(240, 120, 220)      # parts the focus part feeds

def focusPart(app):
    # The part whose connections light up: the one under the mouse, else
    # a single selected part (only with the highlight on, i)
    if not app.netHighlight:
        return None
    if app.hoverPart != None:
        return app.hoverPart
    if len(app.selection['parts']) == 1 and len(app.selection['wires']) == 0:
        return list(app.selection['parts'])[0]
    return None

def getFocus(app):
    # {'nets', 'feeders', 'takers', 'part'} to light up this frame
    # (worked out once per frame)
    if FRAME['active'] and FRAME.get('focus') != None:
        return FRAME['focus']
    from zb_editor import partNeighbors
    focus = {'nets': set(), 'feeders': set(), 'takers': set(),
             'part': None}
    netCount = len(getLevelInfo(app)['nets']['nets'])
    if app.hoverNet != None and app.hoverNet >= netCount:
        app.hoverNet = None            # left over from before an edit
    if app.hoverNet != None and app.netHighlight:
        focus['nets'] = {app.hoverNet}
    elif focusPart(app) != None:
        focus.update(partNeighbors(app, focusPart(app)))
        focus['part'] = focusPart(app)
    elif len(app.selection['wires']) == 1:
        wireId = list(app.selection['wires'])[0]
        netIndex = getLevelInfo(app)['nets']['wireNet'].get(wireId)
        if netIndex != None:
            focus['nets'] = {netIndex}
    if FRAME['active']:
        FRAME['focus'] = focus
    return focus

def litNets(app):
    # The nets to light up (others step back)
    return getFocus(app)['nets']

def drawWire(app, wire, netIndex, state, selected, opacity=100):
    points = wirePath(app, wire)
    width = getLevelInfo(app)['widths'][netIndex]
    color = wireColor(app, wire, width)
    thickness = wireThickness(width)
    if opacity < 100:
        # another net is lit up: this one steps back
        wPolyline(app, points, DIM_WIRE_COLOR if state == 'dim' else color,
                  thickness, opacity)
        return
    if selected:
        wPolyline(app, points, SELECT_COLOR, thickness + 3)
    value = netValue(app, netIndex)
    if app.bitLanes and width > 1 and app.mode == 'run':
        if state == 'moving':
            drawBitLanes(app, points, width, Z, color)
            progress, backwards = wireProgress(app, wire, netIndex)
            lanePoints = list(reversed(points)) if backwards else points
            drawBitLanes(app, lanePoints, width, value, color, progress)
        else:
            drawBitLanes(app, points, width,
                         value if state == 'lit' else Z, color)
        return
    if state == 'lit':
        wPolyline(app, points, color, thickness)
    elif state == 'unknown':
        wPolyline(app, points, UNKNOWN_COLOR, thickness)
    elif state == 'moving':
        wPolyline(app, points, DIM_WIRE_COLOR, thickness)
        progress, backwards = wireProgress(app, wire, netIndex)
        path = list(reversed(points)) if backwards else points
        lit = UNKNOWN_COLOR if value == X else color
        wPolyline(app, pathUpTo(path, progress), lit, thickness)
    else:
        wPolyline(app, points, DIM_WIRE_COLOR, thickness)

def drawPacket(app, wire, netIndex):
    # The value riding along a moving wire
    circuit = getCircuit(app)
    points = wirePoints(app.library, circuit, wire)
    if pathLength(points) < MIN_PACKET_PATH:
        return
    progress, backwards = wireProgress(app, wire, netIndex)
    if not 0 < progress < 1:
        return
    if backwards:
        points = list(reversed(points))
    x, y = pointAlongPath(points, progress)
    width = getLevelInfo(app)['widths'][netIndex]
    value = netValue(app, netIndex)
    color = wireColor(app, wire, width)
    if value == X:
        color = UNKNOWN_COLOR
    if width == 1:
        wCircle(app, x, y, 5, color)
        return
    text = formatValue(value, width, app.numFormat)
    textWidth = len(text) * 6 + 6
    wRect(app, x - textWidth / 2, y - 7, textWidth, 14, color)
    wCircle(app, x - textWidth / 2, y, 7, color)
    wCircle(app, x + textWidth / 2, y, 7, color)
    wText(app, text, x, y, size=9, color=LABEL_BG_COLOR, bold=True)

def isWireOnScreen(app, circuit, wire):
    points = wirePoints(app.library, circuit, wire)
    xs = [x for x, y in points]
    ys = [y for x, y in points]
    sx1, sy1 = toScreen(app, min(xs), min(ys))
    sx2, sy2 = toScreen(app, max(xs), max(ys))
    left, top, width, height = getCanvas(app)
    return not (sx2 < left or sx1 > left + width or sy2 < top or
                sy1 > top + height)

def drawWires(app):
    circuit = getCircuit(app)
    info = getLevelInfo(app)
    wireNet = info['nets']['wireNet']
    states = dict()
    for wire in circuit['wires']:
        if isWireOnScreen(app, circuit, wire):
            states[wire['id']] = getWireState(app, wire,
                                              wireNet[wire['id']])
        else:
            states[wire['id']] = 'offscreen'
    lit = litNets(app)
    # dim ones first, so lit wires sharing a stretch stay on top
    for order in ['dim', 'unknown', 'moving', 'lit']:
        for wire in circuit['wires']:
            if states[wire['id']] == order:
                netIndex = wireNet[wire['id']]
                faded = len(lit) > 0 and netIndex not in lit
                drawWire(app, wire, netIndex, order,
                         wire['id'] in app.selection['wires'],
                         DIM_OPACITY if faded else 100)
    if len(lit) > 0:
        # the lit nets on top, with a glow under them
        for wire in circuit['wires']:
            netIndex = wireNet[wire['id']]
            if netIndex in lit and states[wire['id']] != 'offscreen':
                width = info['widths'][netIndex]
                wPolyline(app, wirePath(app, wire), SELECT_COLOR,
                          wireThickness(width) + 4, 45)
                drawWire(app, wire, netIndex, states[wire['id']], False)
    for junction in circuit['junctions']:
        color = TEXT_COLOR
        if junction['id'] in app.selection['junctions']:
            color = SELECT_COLOR
        wCircle(app, junction['x'], junction['y'], 3.5, color)
    geom = currentGeometry(app)
    if geom != None:
        # a dot where one net splits without a junction
        for x, y, netIndex in geom['branches']:
            wCircle(app, x, y, 3, widthColor(info['widths'][netIndex]))
        if app.mode == 'build':
            for overlap in geom['overlaps']:
                drawDashes(app, overlap['from'], overlap['to'], ERROR_COLOR)
    if isAnimating(app):
        for wire in circuit['wires']:
            if states[wire['id']] == 'moving':
                drawPacket(app, wire, wireNet[wire['id']])

def drawDashes(app, start, end, color):
    # A red dashed line over a stretch where two nets overlap (a ring for
    # a single point)
    (x1, y1), (x2, y2) = start, end
    length = abs(x2 - x1) + abs(y2 - y1)
    if length == 0:
        wCircle(app, x1, y1, 5, color)
        wCircle(app, x1, y1, 3, CANVAS_COLOR)
        return
    count = max(1, int(length // 8))
    for i in range(count):
        a, b = i / count, (i + 0.5) / count
        wLine(app, x1 + (x2 - x1) * a, y1 + (y2 - y1) * a,
              x1 + (x2 - x1) * b, y1 + (y2 - y1) * b, color, 2)

def drawNetPortRings(app):
    # A ring around every port on the lit nets (drawn over the parts)
    circuit = getCircuit(app)
    nets = getLevelInfo(app)['nets']['nets']
    for netIndex in litNets(app):
        for partId, portName in nets[netIndex]['ports']:
            part = findPart(circuit, partId)
            port = getPort(app.library, part, portName)
            if port != None:
                x, y = part['x'] + port['dx'], part['y'] + port['dy']
                wCircle(app, x, y, 5.5, SELECT_COLOR)
                wCircle(app, x, y, 3, widthColor(port['width']))

def drawWireInProgress(app):
    # The wire being drawn, from its start through its bends to the mouse
    if app.tool not in ['wire', 'bus'] or app.wireStart == None:
        return
    from zb_circuit import endPosition
    start = endPosition(app.library, getCircuit(app), app.wireStart)
    points = [start] + [tuple(p) for p in app.wireVia]
    mouse = toWorld(app, app.mouseX, app.mouseY)
    last = points[-1]
    # A right-angle step to the mouse
    points.append((mouse[0], last[1]))
    points.append(mouse)
    wPolyline(app, points, SELECT_COLOR, 2)


######################################################################
# Parts
######################################################################

def partBox(app, part):
    width, height, ports = partLayout(app.library, part)
    return part['x'], part['y'], width, height

def isFlashing(app, part):
    if app.mode != 'run' or app.stage != EDGE or not app.view['live']:
        return False
    prim = getPrim(app, part)
    path = app.view['prefix'] + (part['id'],)
    for index, old, new in app.sim['changes']:
        primPath = app.sim['prims'][index]['path']
        if primPath[:len(path)] == path:
            return True
    return False

def isInWave(app, part):
    # The part is being evaluated in the wave now showing
    if not isAnimating(app) or not app.view['live']:
        return False
    path = app.view['prefix'] + (part['id'],)
    for index, wave in app.sim['primWave'].items():
        if wave == app.wave:
            primPath = app.sim['prims'][index]['path']
            if primPath[:len(path)] == path:
                return True
    return False

def getBorder(app, part):
    if isFlashing(app, part):
        return FLASH_COLOR, 3
    if part['id'] in app.problemParts:
        return ERROR_COLOR, 2
    if part['id'] in app.selection['parts']:
        return SELECT_COLOR, 2.5
    if part['id'] == app.differencePart:
        return ERROR_COLOR, 3
    if part['id'] in app.explainParts:
        return FLASH_COLOR, 2.5
    focus = getFocus(app)
    if part['id'] == focus['part']:
        return SELECT_COLOR, 2.5           # (the part under the mouse)
    if part['id'] in focus['feeders']:
        return FEEDER_COLOR, 2.5           # feeds its inputs
    if part['id'] in focus['takers']:
        return TAKER_COLOR, 2.5            # reads its outputs
    return COMPONENT_BORDER, 1

def partFill(app, part):
    if isInWave(app, part):
        return WAVE_FILL
    return COMPONENT_FILL

def partTitle(app, part, definition):
    if part['label'] != '':
        return part['label']
    return definition['label']

def drawPorts(app, part):
    zoom = zoomOf(app)
    hover = app.hoverPort
    for port in partLayout(app.library, part)[2]:
        x, y = part['x'] + port['dx'], part['y'] + port['dy']
        color = widthColor(port['width'])
        radius = 2.2
        if hover != None and hover == (part['id'], port['name']):
            radius = 4
            color = SELECT_COLOR
        if app.mode == 'build' or radius > 3:
            wCircle(app, x, y, radius, color)

def drawPortNames(app, part, skip=()):
    # Small names next to each port, inside the part
    width, height, ports = partLayout(app.library, part)
    for port in ports:
        if port['name'] in skip:
            continue
        x, y = part['x'] + port['dx'], part['y'] + port['dy']
        side = portSide(app.library, part, port)
        if side == 'left':
            wText(app, port['name'], x + 3, y, 7, DIM_TEXT_COLOR, 'left')
        elif side == 'right':
            wText(app, port['name'], x - 3, y, 7, DIM_TEXT_COLOR, 'right')
        elif side == 'top':
            wText(app, port['name'], x, y + 7, 7, DIM_TEXT_COLOR)
        else:
            wText(app, port['name'], x, y - 7, 7, DIM_TEXT_COLOR)

def drawLabelAbove(app, part, text, color=DIM_TEXT_COLOR):
    wText(app, text, part['x'], part['y'] - 7, 9, color, 'left', True)

def gateOutputOn(app, part):
    return portValue(app, part, 'out') == 1 and app.mode == 'run'

def drawGate(app, part, definition, color, borderWidth):
    shape = definition['shape']
    l, t, w, h = partBox(app, part)
    fill = LIT_GATE_FILL if gateOutputOn(app, part) else partFill(app, part)
    bubble = shape in ['nand', 'nor', 'not']
    bodyW = w - 8 if bubble else w
    if shape in ['and', 'nand']:
        points = ([l, t, l + bodyW - h / 2, t] +
                  arcPoints(l + bodyW - h / 2, t + h / 2, min(h / 2, bodyW),
                            h / 2, 90, -90, 14) + [l, t + h])
        if h / 2 > bodyW:
            points = [l, t] + arcPoints(l, t + h / 2, bodyW, h / 2, 90, -90,
                                        14) + [l, t + h]
    elif shape in ['or', 'nor', 'xor']:
        back = l + (6 if shape == 'xor' else 0)
        points = [back, t, back + bodyW * 0.45, t + h * 0.02,
                  back + bodyW * 0.78, t + h * 0.2, l + bodyW, t + h / 2,
                  back + bodyW * 0.78, t + h * 0.8,
                  back + bodyW * 0.45, t + h * 0.98, back, t + h,
                  back + 7, t + h * 0.75, back + 9, t + h / 2,
                  back + 7, t + h * 0.25]
    else:
        points = [l, t, l + bodyW, t + h / 2, l, t + h]
    wPolygon(app, points, fill, color, borderWidth)
    if shape == 'xor':
        wPolyline(app, [(l, t), (l + 7, t + h * 0.25), (l + 9, t + h / 2),
                        (l + 7, t + h * 0.75), (l, t + h)], color,
                  borderWidth)
    if bubble:
        wCircle(app, l + w - 4, t + h / 2, 4, color)
        wCircle(app, l + w - 4, t + h / 2, 2.5, fill)
    if shape in ['not', 'buf']:
        text = part['label'] or ''
    else:
        text = definition['label']
    if part['label'] != '' and shape not in ['not', 'buf']:
        drawLabelAbove(app, part, part['label'])
    elif shape in ['not', 'buf'] and text != '':
        drawLabelAbove(app, part, text)
    if shape not in ['not', 'buf']:
        wText(app, definition['label'], l + bodyW * 0.42, t + h / 2, 7,
              DIM_TEXT_COLOR)
    width = part['params'].get('width', 1)
    if width > 1:
        wText(app, f'x{width}', l + 4, t + h - 5, 6, DIM_TEXT_COLOR, 'left')

def drawTG(app, part, color, borderWidth):
    l, t, w, h = partBox(app, part)
    fill = TG_ON_FILL if portValue(app, part, 'en') == 1 else \
        partFill(app, part)
    wLine(app, l, t + h / 2, l + 6, t + h / 2, color)
    wLine(app, l + w - 6, t + h / 2, l + w, t + h / 2, color)
    wLine(app, l + w / 2, t, l + w / 2, t + h / 2 - 6, color)
    wPolygon(app, [l + 6, t + 8, l + 6, t + h - 8, l + w / 2, t + h / 2],
             fill, color, borderWidth)
    wPolygon(app, [l + w - 6, t + 8, l + w - 6, t + h - 8, l + w / 2,
                   t + h / 2], fill, color, borderWidth)
    drawLabelAbove(app, part, part['label'] or 'TG')

def drawConst(app, part, color, borderWidth):
    l, t, w, h = partBox(app, part)
    wRect(app, l, t, w, h, partFill(app, part), color, borderWidth)
    params = part['params']
    wText(app, formatValue(params['value'] & ((1 << params['width']) - 1),
                           params['width'], 'dec'), l + w / 2, t + h / 2,
          9, TEXT_COLOR, bold=True)
    if part['label'] != '':
        drawLabelAbove(app, part, part['label'])

def drawSplitMerge(app, part, color, borderWidth):
    l, t, w, h = partBox(app, part)
    params = part['params']
    barX = l + w / 2
    wRect(app, barX - 2, t + 4, 4, h - 8, color)
    for port in partLayout(app.library, part)[2]:
        x, y = part['x'] + port['dx'], part['y'] + port['dy']
        wLine(app, x, y, barX, y, color, 1.5)
    if part['type'] == 'SPLIT':
        for i in range(len(params['ranges'])):
            high, low = params['ranges'][i]
            text = f'[{high}:{low}]' if high != low else f'[{high}]'
            wText(app, text, l + w + 2, t + 10 * (i + 1) - 6, 7,
                  DIM_TEXT_COLOR, 'left')
    else:
        for i in range(len(params['widths'])):
            wText(app, str(params['widths'][i]), l - 2, t + 10 * (i + 1) - 6,
                  7, DIM_TEXT_COLOR, 'right')
    if part['label'] != '':
        wText(app, part['label'], l, t - 7, 8, DIM_TEXT_COLOR, 'left')

def drawExtend(app, part, color, borderWidth):
    l, t, w, h = partBox(app, part)
    wPolygon(app, [l, t + 5, l + w, t, l + w, t + h, l, t + h - 5],
             partFill(app, part), color, borderWidth)
    params = part['params']
    text = f"{params['from']}>{params['to']}"
    if params['mode'] == 'repeat':
        text = f"x{params['to']}"
    wText(app, text, l + w / 2, t + h / 2, 7, DIM_TEXT_COLOR)

def drawPin(app, part, color, borderWidth):
    l, t, w, h = partBox(app, part)
    params = part['params']
    if part['type'] == 'PIN_IN':
        points = [l, t, l + w - 8, t, l + w, t + h / 2, l + w - 8, t + h,
                  l, t + h]
        value = partState(app, part) if app.mode == 'run' else None
        if value == None and app.mode == 'run':
            value = portValue(app, part, 'out')
    else:
        points = [l + 8, t, l + w, t, l + w, t + h, l + 8, t + h, l,
                  t + h / 2]
        value = portValue(app, part, 'in')
    fill = partFill(app, part)
    if value == 1 and params['width'] == 1:
        fill = LIT_GATE_FILL
    wPolygon(app, points, fill, color, borderWidth)
    text = params['name']
    if value != None:
        text = f"{params['name']}={formatValue(value, params['width'], 'dec' if params['width'] > 1 else 'bin')}"
    wText(app, fitText(text, 9), l + w / 2 + (-2 if part['type'] ==
                                              'PIN_IN' else 3),
          t + h / 2, 7, TEXT_COLOR, bold=True)
    if params['width'] > 1:
        wText(app, f"{params['width']} bits", l + w / 2, t + h + 7, 6,
              DIM_TEXT_COLOR)

def drawProbe(app, part, color, borderWidth):
    l, t, w, h = partBox(app, part)
    wRect(app, l, t, w, h, LABEL_BG_COLOR, color, borderWidth)
    value = portValue(app, part, 'in')
    width = part['params']['width']
    text = 'probe' if value == None else formatValue(value, width,
                                                     app.numFormat)
    wText(app, fitText(text, 10), l + w / 2 + 2, t + h / 2, 8,
          widthColor(width), bold=True)
    if part['label'] != '':
        drawLabelAbove(app, part, part['label'])

def drawBox(app, part, definition, color, borderWidth):
    l, t, w, h = partBox(app, part)
    wRect(app, l, t, w, h, partFill(app, part), color, borderWidth)
    title = partTitle(app, part, definition)
    if len(title) * 5.5 > w - 8:
        # a name too long for the box goes above it, whole
        drawLabelAbove(app, part, title, TEXT_COLOR)
    else:
        wText(app, title, l + w / 2, t + h / 2, 9, TEXT_COLOR, bold=True)
    if definition['kind'] == 'composite':
        badge = ''
        if definition.get('verified'):
            badge = 'ok ' + (definition.get('implements') or '')
        if part['mode'] == 'fast':
            badge += ' fast'
        wText(app, badge.strip(), l + w / 2, t + h - 6, 6, GOOD_COLOR)
    drawPortNames(app, part)

def drawMux(app, part, definition, color, borderWidth):
    l, t, w, h = partBox(app, part)
    slant = w / 2 + 2
    if definition['shape'] == 'mux':
        points = [l, t, l + w, t + slant, l + w, t + h - slant, l, t + h]
    else:
        points = [l, t + slant, l + w, t, l + w, t + h, l, t + h - slant]
    wPolygon(app, points, partFill(app, part), color, borderWidth)
    drawLabelAbove(app, part, partTitle(app, part, definition))
    if app.mode != 'run':
        drawPortNames(app, part)
        return
    ports = dict()
    for port in partLayout(app.library, part)[2]:
        ports[port['name']] = (part['x'] + port['dx'], part['y'] + port['dy'])
    for name, (x, y) in ports.items():
        if name.startswith('in') and definition['shape'] == 'mux':
            wText(app, name[2:], x + 5, y, 7, DIM_TEXT_COLOR)
    if definition['shape'] == 'mux':
        sel = portValue(app, part, 'sel')
        if isKnown(sel) and ('in' + str(sel)) in ports:
            x1, y1 = ports['in' + str(sel)]
            x2, y2 = ports['out']
            wLine(app, x1 + 9, y1, x2 - 3, y2, FLASH_COLOR, 1.5)
    else:
        for index in [0, 1]:
            if portValue(app, part, 'en' + str(index)) == 1:
                x1, y1 = ports['in']
                x2, y2 = ports['f' + str(index)]
                wLine(app, x1 + 3, y1, x2 - 8, y2, FLASH_COLOR, 1.5)
        wText(app, 'f0', ports['f0'][0] - 8, ports['f0'][1], 6,
              DIM_TEXT_COLOR)
        wText(app, 'f1', ports['f1'][0] - 8, ports['f1'][1], 6,
              DIM_TEXT_COLOR)

def drawDecoder(app, part, definition, color, borderWidth):
    l, t, w, h = partBox(app, part)
    wRect(app, l, t, w, h, partFill(app, part), color, borderWidth)
    wText(app, 'DEC', l + 14, t + 10, 7, TEXT_COLOR, bold=True)
    params = part['params'] if definition['kind'] == 'primitive' else \
        PRIMITIVES['DECODER']['params']
    wText(app, f"{params['bits']}>{params['outputs']}", l + 14, t + 20, 6,
          DIM_TEXT_COLOR)
    value = portValue(app, part, 'in')
    if value != None and isKnown(value):
        wText(app, formatValue(value, params['bits']), l + 14, t + 32, 7,
              OPCODE_COLOR, bold=True)
    for k in range(params['outputs']):
        x, y = l + w, t + 10 * (k + 1)
        on = portValue(app, part, 'd' + str(k)) == 1
        wCircle(app, x - 7, y, 2.5, CONTROL_COLOR if on else LANE_OFF_COLOR)
        wText(app, str(k), x - 15, y, 6, DIM_TEXT_COLOR)
    if part['label'] != '':
        drawLabelAbove(app, part, part['label'])

def drawBitCell(app, bit, left, top, width, height, color, offDrawn=False):
    # offDrawn: the caller already drew the dark background of the cells
    if offDrawn and bit == 0 and zoomOf(app) < 0.9:
        return
    fill = BIT_OFF_FILL
    text = '0'
    textColor = DIM_TEXT_COLOR
    if bit == 1:
        fill = BIT_ON_FILL
        text = '1'
        textColor = color
    elif bit == None:
        text = 'x'
    if not (offDrawn and bit == 0):
        wRect(app, left, top, width, height, fill)
    if bit != 0 or zoomOf(app) >= 0.9:
        # (a dark cell reads as 0; its text is left out when zoomed out,
        # to keep the number of shapes per frame down)
        wText(app, text, left + width / 2, top + height / 2, 8, textColor,
              bold=True)

def registerBits(part):
    if part['type'] in ['IR', 'PC']:
        return 8
    return part['params'].get('width', 8)

def pendingValue(app, part):
    # What the register will load at the coming clock edge (shown near the
    # end of the phase), or None
    if not isAnimating(app) or app.wave < app.waveCount - 1:
        return None
    prim = getPrim(app, part)
    if prim == None or not app.view['live']:
        return None
    for index, newState in app.sim['pending']:
        if index == prim['index']:
            return newState
    return None

def programIsa(app):
    # The running program's instruction set (None: the lecture machine's)
    return app.sim.get('isa') if app.sim != None else None

def registerCaption(app, part, value, bits):
    if not isKnown(value):
        return 'x' * bits
    ref = part['ref']
    if part['type'] == 'IR' or ref == 'ir':
        isa = programIsa(app)
        text = disassemble(value, isa)
        if len(text) > 16 or not isInstruction(value, isa):
            text = shortDisassemble(value, 'code', isa)  # not the bits
        return text
    if part['type'] == 'PC' or ref == 'pc':
        return f'= {value}'
    if bits == 8:
        return f'= {toSignedWidth(value, 8)}'
    return f'= {value}'

def drawRegister(app, part, definition, color, borderWidth):
    l, t, w, h = partBox(app, part)
    wRect(app, l, t, w, h, partFill(app, part), color, borderWidth)
    title = partTitle(app, part, definition)
    tagName = TAG_NAMES.get(part['ref'], part['ref'])
    if part['ref'] != None and tagName != title:
        title += f'  [{tagName}]'
    drawLabelAbove(app, part, title, TEXT_COLOR)
    bits = registerBits(part)
    value = partState(app, part)
    if app.mode != 'run' or value == None and getPrim(app, part) == None:
        wText(app, f'{bits}-bit', l + w / 2, t + 13, 7, DIM_TEXT_COLOR)
        drawPortNames(app, part)
        return
    cells = [None] * bits
    if isKnown(value):
        cells = [getBit(value, bits - 1 - i) for i in range(bits)]
    cellWidth = (w - 8) / bits
    wRect(app, l + 4, t + 4, w - 8 - 1, 14, BIT_OFF_FILL)
    for i in range(bits):
        cellColor = TEXT_COLOR
        if part['type'] == 'IR' or part['ref'] == 'ir':
            cellColor = OPCODE_COLOR if i < 4 else OPERAND_COLOR
        drawBitCell(app, cells[i], l + 4 + i * cellWidth, t + 4,
                    cellWidth - 1, 14, cellColor, offDrawn=True)
    if part['type'] == 'PC':
        # its high 4 bits never leave it (only [3:0] reach the bus)
        wRect(app, l + 4, t + 4, 4 * cellWidth - 1, 14, COMPONENT_FILL,
              opacity=60)
    caption = registerCaption(app, part, value, bits)
    captionColor = DIM_TEXT_COLOR
    incoming = pendingValue(app, part)
    if incoming != None and isKnown(incoming):
        caption = '<- ' + bitString(incoming, bits)
        captionColor = FLASH_COLOR
    wText(app, fitText(caption, int(w / 5)), l + w / 2, t + 28, 8,
          captionColor)

def drawFlags(app, part, definition, color, borderWidth):
    l, t, w, h = partBox(app, part)
    wRect(app, l, t, w, h, partFill(app, part), color, borderWidth)
    title = partTitle(app, part, definition)
    if part['ref'] != None:
        title += '  [NZO]'
    drawLabelAbove(app, part, title, TEXT_COLOR)
    state = partState(app, part)
    for i in range(3):
        name = 'nzo'[i]
        bit = 0
        if state != None:
            bit = state[name] if isKnown(state[name]) else None
        cellLeft = l + 8 + i * 22
        if app.mode == 'run':
            drawBitCell(app, bit, cellLeft, t + 5, 18, 14, TEXT_COLOR)
        wText(app, name.upper(), cellLeft + 9, t + 29, 7, DIM_TEXT_COLOR)

def drawALU(app, part, definition, color, borderWidth):
    l, t, w, h = partBox(app, part)
    points = [l, t, l + w, t + 20, l + w, t + h - 20, l, t + h,
              l, t + h * 0.6, l + w * 0.3, t + h / 2, l, t + h * 0.4]
    wPolygon(app, points, partFill(app, part), color, borderWidth)
    wText(app, partTitle(app, part, definition), l + w / 2 + 6, t + 45, 10,
          TEXT_COLOR, bold=True)
    wText(app, '+', l + 20, t + h - 14, 9, CONTROL_COLOR, bold=True)
    wText(app, '-', l + 40, t + h - 18, 9, CONTROL_COLOR, bold=True)
    for name, dy in [('N', 30), ('Z', 40), ('O', 50), ('out', 80),
                     ('go', 120)]:
        wText(app, name, l + w - 4, t + dy, 6, DIM_TEXT_COLOR, 'right')
    if app.mode != 'run':
        return
    a = portValue(app, part, 'a')
    b = portValue(app, part, 'b')
    out = portValue(app, part, 'out')
    minus = portValue(app, part, 'minus')
    if not (isKnown(a) and isKnown(b) and isKnown(out)):
        return
    symbol = '-' if minus == 1 else '+'
    color = TITLE_COLOR if portValue(app, part, 'go') == 1 else \
        DIM_TEXT_COLOR
    lines = [str(toSignedWidth(a, 8)), symbol + str(toSignedWidth(b, 8)),
             '----', str(toSignedWidth(out, 8))]
    for i in range(len(lines)):
        wText(app, lines[i], l + w / 2 + 6, t + 70 + i * 12, 9, color)

def drawClock(app, part, color, borderWidth):
    l, t, w, h = partBox(app, part)
    wRect(app, l, t, w, h, partFill(app, part), color, borderWidth)
    points = [(l + 6, t + 26), (l + 16, t + 26), (l + 16, t + 12),
              (l + 28, t + 12), (l + 28, t + 26), (l + 40, t + 26)]
    wPolyline(app, points, DIM_TEXT_COLOR, 1.5)
    wText(app, 'CLK', l + w - 4, t + 10, 6, DIM_TEXT_COLOR, 'right')
    wText(app, '/CLK', l + w - 4, t + 30, 6, DIM_TEXT_COLOR, 'right')
    drawLabelAbove(app, part, partTitle(app, part,
                                        PRIMITIVES['CLOCK']))
    state = partState(app, part)
    if state != None and app.mode == 'run':
        phase = 'execute' if state == 1 else 'fetch'
        wText(app, phase, l + w / 2, t + h + 8, 7, FLASH_COLOR, bold=True)

def ramRowTop(part, address):
    return part['y'] + RAM_ROW_TOP + address * RAM_ROW_HEIGHT

def textSize(app, size):
    # The size wText really draws at (in design units)
    return max(MIN_TEXT, size * zoomOf(app))

def ramBitX(app, part, bit):
    # The world x where bit (0 = leftmost) of a RAM word starts. A
    # monospace character is 0.6 of the font size wide; the two halves of
    # the word have a space between them.
    charWidth = 0.6 * textSize(app, RAM_TEXT) / zoomOf(app)
    return part['x'] + 66 + (bit + (1 if bit >= 4 else 0)) * charWidth

def ramBitAt(app, part, x):
    # Which bit of a RAM word is at world x, or None
    for bit in range(8):
        if ramBitX(app, part, bit) <= x < ramBitX(app, part, bit + 1) or \
                (bit == 3 and ramBitX(app, part, 3) <= x <
                 ramBitX(app, part, 4)):
            return bit
    return None

def ramRowAt(app, part, x, y):
    # The address of the RAM row at world (x, y), or None
    if not part['x'] <= x <= part['x'] + 220:
        return None
    for address in range(RAM_WORDS):
        top = ramRowTop(part, address)
        if top <= y < top + RAM_ROW_HEIGHT:
            return address
    return None

def getProgramPC(app):
    # The PC value (for the RAM's PC marker), or None
    if app.mode != 'run':
        return None
    for prim in app.sim['prims']:
        if prim['ref'] == 'pc' and isKnown(prim['state']):
            return prim['state']
    return None

def drawRAM(app, part, definition, color, borderWidth):
    l, t, w, h = partBox(app, part)
    wRect(app, l, t, w, h, partFill(app, part), color, borderWidth)
    title = partTitle(app, part, definition)
    if part['ref'] != None:
        title += '  [RAM]'
    wText(app, title, l + 8, t + 11, 9, TEXT_COLOR, 'left', True)
    memory = partState(app, part)
    if app.mode != 'run' or memory == None:
        wText(app, '16 words x 8 bits', l + w / 2, t + h / 2 - 8, 9,
              DIM_TEXT_COLOR)
        wText(app, '(program loaded in Run mode)', l + w / 2, t + h / 2 + 8,
              8, DIM_TEXT_COLOR)
        drawPortNames(app, part)
        return
    wText(app, 'addr  word    click bit: flip  shift: break', l + 34, t + 21,
          6, DIM_TEXT_COLOR, 'left')
    address = portValue(app, part, 'addr')
    re = portValue(app, part, 're')
    we = portValue(app, part, 'we')
    pc = getProgramPC(app)
    isProgramRAM = part['ref'] == 'mem' or app.programRam == part['id']
    for row in range(RAM_WORDS):
        top = ramRowTop(part, row)
        midY = top + RAM_ROW_HEIGHT / 2
        if address == row and re == 1:
            wRect(app, l + 2, top, w - 4, RAM_ROW_HEIGHT - 1, READ_COLOR)
        elif address == row and we == 1:
            wRect(app, l + 2, top, w - 4, RAM_ROW_HEIGHT - 1, WRITE_COLOR)
        if isProgramRAM and row in app.breakpoints:
            wCircle(app, l + 8, midY, 4, BREAKPOINT_COLOR)
        if isProgramRAM and pc == row:
            wText(app, 'PC', l + 19, midY, 6, FLASH_COLOR, bold=True)
        wText(app, bitString(row, 4), l + 34, midY, 8, DIM_TEXT_COLOR,
              'left')
        word = memory[row]
        kind = 'code'
        if isProgramRAM and app.rows[row] != None:
            kind = app.rows[row]['kind']
        # One label per half word (not per bit), to keep the shape count
        # down; ramBitX says where each bit lands, for clicks
        bits = bitString(word, 8)
        for half in [0, 1]:
            bitColor = TEXT_COLOR
            if kind == 'code' and isKnown(word):
                bitColor = OPCODE_COLOR if half == 0 else OPERAND_COLOR
            if not isKnown(word):
                bitColor = DIM_TEXT_COLOR
            wText(app, bits[4 * half:4 * half + 4],
                  ramBitX(app, part, 4 * half), midY, RAM_TEXT, bitColor,
                  'left', isKnown(word))
        if isKnown(word):
            wText(app, shortDisassemble(word, kind, programIsa(app)),
                  max(l + 122, ramBitX(app, part, 8) + 4), midY, 7,
                  DIM_TEXT_COLOR, 'left')
    if isKnown(address):
        midY = ramRowTop(part, address) + RAM_ROW_HEIGHT / 2
        x = l + 32
        wPolygon(app, [x, midY, x - 7, midY - 5, x - 7, midY + 5],
                 ADDR_COLOR)
    drawPortNames(app, part, skip=())

def drawPart(app, part):
    definition = getDefinition(app.library, part['type'])
    color, borderWidth = getBorder(app, part)
    if definition == None:
        l, t, w, h = partBox(app, part)
        wRect(app, l, t, w, h, COMPONENT_FILL, ERROR_COLOR, 2)
        wText(app, '? ' + part['type'], l + w / 2, t + h / 2, 8,
              ERROR_COLOR)
        return
    shape = definition['shape']
    if definition['kind'] == 'composite':
        # your parts are boxes; only the hidden gate-level copies of
        # built-ins (zb_kit.expandToGates) are drawn like the built-in
        shape = 'box'
        builtIn = PRIMITIVES.get(definition.get('implements'))
        if definition.get('lookLike') and builtIn != None and \
                partLayout(app.library, part) == builtIn['layout'](
                    dict(builtIn['params'])) and builtIn['commit'] == None:
            shape = builtIn['shape']
    if shape in ['and', 'or', 'nand', 'nor', 'xor', 'not', 'buf']:
        drawGate(app, part, definition, color, borderWidth)
    elif shape == 'tg':
        drawTG(app, part, color, borderWidth)
    elif shape == 'const':
        drawConst(app, part, color, borderWidth)
    elif shape in ['split', 'merge']:
        drawSplitMerge(app, part, color, borderWidth)
    elif shape == 'extend':
        drawExtend(app, part, color, borderWidth)
    elif shape in ['pinIn', 'pinOut']:
        drawPin(app, part, color, borderWidth)
    elif shape == 'probe':
        drawProbe(app, part, color, borderWidth)
    elif shape in ['mux', 'demux']:
        drawMux(app, part, definition, color, borderWidth)
    elif shape == 'decoder':
        drawDecoder(app, part, definition, color, borderWidth)
    elif shape == 'register' and definition['kind'] == 'primitive':
        drawRegister(app, part, definition, color, borderWidth)
    elif shape == 'flags' and definition['kind'] == 'primitive':
        drawFlags(app, part, definition, color, borderWidth)
    elif shape == 'alu':
        drawALU(app, part, definition, color, borderWidth)
    elif shape == 'ram':
        drawRAM(app, part, definition, color, borderWidth)
    elif shape == 'clock':
        drawClock(app, part, color, borderWidth)
    else:
        drawBox(app, part, definition, color, borderWidth)
    drawPorts(app, part)

def isOnScreen(app, part):
    l, t, w, h = partBox(app, part)
    sx1, sy1 = toScreen(app, l, t - 16)
    sx2, sy2 = toScreen(app, l + w, t + h)
    left, top, width, height = getCanvas(app)
    return not (sx2 < left or sx1 > left + width or sy2 < top or
                sy1 > top + height)

def drawGrid(app):
    left, top, width, height = getCanvas(app)
    zoom = zoomOf(app)
    step = 20 if zoom >= 0.8 else 40
    if step * zoom < 8:
        return
    x0, y0 = toWorld(app, left, top)
    x1, y1 = toWorld(app, left + width, top + height)
    x = math.floor(x0 / step) * step
    while x <= x1:
        sx, sy = toScreen(app, x, y0)
        scaledLine(sx, top, sx, top + height, fill=GRID_COLOR, lineWidth=1)
        x += step
    y = math.floor(y0 / step) * step
    while y <= y1:
        sx, sy = toScreen(app, x0, y)
        scaledLine(left, sy, left + width, sy, fill=GRID_COLOR, lineWidth=1)
        y += step

def drawCanvas(app):
    left, top, width, height = getCanvas(app)
    scaledRect(left, top, width, height, fill=CANVAS_COLOR)
    # Parts half off the canvas are cut at its edge
    clipTo(left, top, width, height)
    try:
        if app.showGrid[app.mode]:
            drawGrid(app)
        drawWires(app)
        for part in getCircuit(app)['parts']:
            if isOnScreen(app, part):
                drawPart(app, part)
        drawNetPortRings(app)
        drawWireInProgress(app)
        drawBoxSelect(app)
        drawPlacingGhost(app)
    finally:
        unclip()

def drawBoxSelect(app):
    drag = app.drag
    if drag == None or drag['kind'] != 'box':
        return
    (x1, y1), (x2, y2) = drag['start'], drag['end']
    wRect(app, min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1),
          SELECT_COLOR, SELECT_COLOR, 1, opacity=15)

def drawPlacingGhost(app):
    if app.tool != 'place' or not app.mouseInCanvas:
        return
    definition = getDefinition(app.library, app.placeType)
    if definition == None:
        return
    fake = {'type': app.placeType, 'params': dict(definition.get('params',
                                                                 {})),
            'x': 0, 'y': 0}
    fake['params'].update(app.lastParams.get(app.placeType, {}))
    width, height, ports = partLayout(app.library, fake)
    x, y = toWorld(app, app.mouseX, app.mouseY)
    wRect(app, snap(x - width / 2),
          snap(y - height / 2), width, height, SELECT_COLOR,
          SELECT_COLOR, 1, opacity=25)


######################################################################
# Title, toolbar, palette
######################################################################

def drawTitle(app):
    drawText('Z18 Builder', 10, 21, size=19, align='left', bold=True)
    rects = crumbRects(app)
    for i, (crumb, (cl, ct, cw, ch)) in enumerate(rects):
        last = i == len(rects) - 1
        hover = not last and pointInRectView(app.mouseX, app.mouseY, cl, ct,
                                             cw, ch)
        if hover:
            scaledRect(cl - 3, ct, cw + 6, ch, fill=TRACK_COLOR)
        drawText(crumb, cl, ct + ch / 2, size=12,
                 color=TEXT_COLOR if last else TITLE_COLOR, align='left',
                 bold=last)
        if not last:
            drawText('>', cl + cw + 8, ct + ch / 2, size=12,
                     color=DIM_TEXT_COLOR, align='left')
    if len(rects) > 0:
        cl, ct, cw, ch = rects[-1][1]
        note = ''
        if app.mode == 'run' and app.solo != None and \
                len(app.path) == len(app.solo['path']):
            note = '(running on its own)'
        elif app.view['readOnly']:
            note = '(built-in recipe, read-only)'
        elif editingPartName(app) != None and app.mode == 'build':
            note = '(editing your part)'
        drawText(note, cl + cw + 14, ct + ch / 2, size=10,
                 color=DIM_TEXT_COLOR, align='left')
    modeText = 'BUILD' if app.mode == 'build' else (
        'LOGIC' if app.logicMode else 'RUN')
    color = GOOD_COLOR if app.mode == 'run' else WARN_COLOR
    scaledRect(820, 8, 64, 26, fill=PANEL_COLOR, border=color)
    drawText(modeText, 852, 21, size=12, color=color, bold=True)
    if app.mode == 'run' and not app.logicMode:
        left, top, width, height = app.layout['programName']
        scaledRect(left, top, width, height, fill=PANEL_COLOR,
                   border=TITLE_COLOR if app.picker != None else BORDER_COLOR)
        drawText('program: ' + fitText(app.programName, 26), left + 8,
                 top + height / 2, size=12, color=TITLE_COLOR, align='left',
                 bold=True)
    else:
        # where it is saved, and * for changes not saved yet (ctrl+S)
        unsaved = app.editVersion != app.savedVersion
        name = (f'circuits/{app.fileName}.json' if app.fileName else
                app.root['name'] + ' (not saved)')
        drawText(fitText(name, 36) + (' *' if unsaved and app.fileName
                                       else ''), 1430, 21, size=11,
                 color=WARN_COLOR if unsaved and app.fileName else
                 DIM_TEXT_COLOR, align='right')

CRUMB_LEFT = 150
CRUMB_RIGHT = 800
CRUMB_CHAR = 7.2               # a 12-point monospace character

def crumbRects(app):
    # [(name, (left, top, width, height))] of the breadcrumb in the title:
    # Computer > ALU > bit 3. Clicking one goes up to that level. Long
    # paths drop the middle names.
    names = [fitText(name, 18) for name in app.pathNames]
    crumbs = ['Computer'] + names
    if len(names) > 3:
        crumbs = ['Computer', '...'] + names[-2:]
    rects = []
    x = CRUMB_LEFT
    for crumb in crumbs:
        width = len(crumb) * CRUMB_CHAR
        rects.append((crumb, (x, 9, width, 24)))
        x += width + 28
    return rects

def crumbLevel(app, k):
    # The path length the k-th breadcrumb stands for
    # ('...' stands for the level just before the two shown after it)
    shown = len(crumbRects(app))
    return 0 if k == 0 else len(app.pathNames) - (shown - 1 - k)

def drawButtons(app, buttons, isEnabled, isOn, getLabel):
    for button in buttons:
        enabled = isEnabled(button['action'])
        color = BUTTON_COLOR
        textColor = 'white'
        if not enabled:
            color = DISABLED_COLOR
            textColor = DIM_TEXT_COLOR
        elif isOn(button['action']):
            color = ON_COLOR
        scaledRect(button['left'], button['top'], button['width'],
                   button['height'], fill=color, border=BORDER_COLOR)
        drawText(getLabel(button), button['left'] + button['width'] / 2,
                 button['top'] + button['height'] / 2, size=12,
                 color=textColor, bold=True)

def paletteItems(app):
    # The rows of the palette's current tab: (type name, label, allowed)
    tab = app.paletteTab
    allowed = None
    if app.mission != None and app.mission.get('allowed') != None:
        allowed = set(app.mission['allowed'])
    items = []
    if tab < len(KIT_PALETTE):
        for typeName in KIT_PALETTE[tab][1]:
            items.append((typeName, PRIMITIVES[typeName]['label'],
                          allowed == None or typeName in allowed))
    else:
        for name in sorted(app.library['user']):
            if name.startswith('gates '):
                continue
            definition = app.library['user'][name]
            label = name
            if definition['verified']:
                label += ' (ok)'
            items.append((name, label, allowed == None or name in allowed))
    return items

def paletteRowRect(i):
    left, top, width, height = PALETTE_RECT
    return (left + 4, top + PALETTE_TAB_HEIGHT + 8 + i * PALETTE_ROW_HEIGHT,
            width - 8, PALETTE_ROW_HEIGHT - 3)

def paletteTabRect(i):
    left, top, width, height = PALETTE_RECT
    tabWidth = (width - 8) / 4
    return (left + 4 + i * tabWidth, top + 4, tabWidth - 2,
            PALETTE_TAB_HEIGHT - 4)

def drawPalette(app):
    left, top, width, height = PALETTE_RECT
    scaledRect(left, top, width, height, fill=PANEL_COLOR,
               border=BORDER_COLOR)
    names = [group for group, types in KIT_PALETTE] + ['Mine']
    for i in range(4):
        tl, tt, tw, th = paletteTabRect(i)
        fill = BUTTON_COLOR if i == app.paletteTab else BG_COLOR
        scaledRect(tl, tt, tw, th, fill=fill, border=BORDER_COLOR)
        drawText(names[i], tl + tw / 2, tt + th / 2, size=9, color='white',
                 bold=(i == app.paletteTab))
    items = paletteItems(app)
    for i in range(len(items)):
        typeName, label, allowed = items[i]
        rl, rt, rw, rh = paletteRowRect(i)
        if rt + rh > top + height - 40:
            break
        chosen = app.tool == 'place' and app.placeType == typeName
        fill = ON_COLOR if chosen else BG_COLOR
        scaledRect(rl, rt, rw, rh, fill=fill, border=BORDER_COLOR)
        color = TEXT_COLOR if allowed else DISABLED_COLOR
        drawText(fitText(label, 21), rl + 6, rt + rh / 2, size=10,
                 color=color, align='left', bold=True)
    if len(items) == 0:
        drawText('No parts yet.', left + 10, top + 50, size=10,
                 color=DIM_TEXT_COLOR, align='left')
        drawText('Select parts, then', left + 10, top + 68, size=10,
                 color=DIM_TEXT_COLOR, align='left')
        drawText('press P to pack them.', left + 10, top + 86, size=10,
                 color=DIM_TEXT_COLOR, align='left')
    drawText('click, then click the', left + 8, top + height - 28, size=9,
             color=DIM_TEXT_COLOR, align='left')
    drawText('canvas to place it', left + 8, top + height - 14, size=9,
             color=DIM_TEXT_COLOR, align='left')


######################################################################
# The side panel: properties (Build) or inspector (Run)
######################################################################

def sideRowRect(i):
    left, top, width, height = SIDE
    return (left + 6, top + 8 + i * SIDE_ROW_HEIGHT, width - 12,
            SIDE_ROW_HEIGHT - 2)

def sideButtonRects(i, buttons):
    # The small buttons at the right end of side-panel row i, as
    # [(left, top, width, height)] in the same order as buttons
    rl, rt, rw, rh = sideRowRect(i)
    rects = []
    right = rl + rw
    for label, action in reversed(buttons):
        width = max(24, len(label) * 7 + 12)
        right -= width
        rects.insert(0, (right, rt, width - 3, rh))
        right -= 1
    return rects

# Parameters that count (steppers) and ones with a few choices (cycle)
STEP_PARAMS = ['inputs', 'width', 'outputs', 'bits', 'from', 'to', 'value']
PARAM_CHOICES = {'mode': ['zero', 'repeat'], 'init': ['0', 'X'],
                 'ports': ['side', 'top'],
                 'side': ['auto', 'left', 'top', 'right', 'bottom']}
HIDDEN_PARAMS = ['order']

def paramText(value, typeName=None, key=None):
    # SPLIT ranges and MERGE widths read in bus notation ('7:4 3:0')
    if typeName == 'SPLIT' and key == 'ranges':
        return formatRanges(value)
    if typeName == 'MERGE' and key == 'widths':
        return formatWidths(value)
    if type(value) == list:
        return str(value).replace(' ', '')
    return str(value)

def getPropertyRows(app):
    # [{'text', 'action', 'color', 'bold'}] for the side panel. action is
    # what a click does (handled in zb_main.clickSide), or None.
    # buttons: [(label, action)] drawn small at the row's right end
    rows = []
    def add(text, action=None, color=TEXT_COLOR, bold=False, buttons=()):
        rows.append({'text': text, 'action': action, 'color': color,
                     'bold': bold, 'buttons': list(buttons)})
    mission = app.mission
    if mission != None and app.mode == 'build':
        add('Mission ' + mission['title'], None, TITLE_COLOR, True)
        for line in wrapText(mission['goal'], 38)[:7]:
            add(line, None, DIM_TEXT_COLOR)
        add('[ Check my work ]', ('missionCheck',), GOOD_COLOR, True)
        if mission['kind'] == 'part':
            add('u: its truth table, with what it should be', None,
                DIM_TEXT_COLOR)
        elif mission['kind'] == 'sequence':
            add('u: the step table (Tab, then click pins)', None,
                DIM_TEXT_COLOR)
        add('')
    if app.explain != None:
        addExplainRows(app, add)
    part = getSelectedPart(app)
    wire = getSelectedWire(app)
    if app.mode == 'run':
        addRunRows(app, add, part)
        return rows
    if part != None:
        addPartRows(app, add, part)
    elif wire != None:
        addWireRows(app, add, wire)
    elif editingPartName(app) != None:
        definition = app.library['user'][editingPartName(app)]
        add('Inside your part', None, TITLE_COLOR, True)
        add(definition['name'], None, TEXT_COLOR, True)
        verified = 'yes' if definition['verified'] else 'no'
        add(f"verified: {verified}  implements: "
            f"{definition['implements'] or '-'}")
        add('[ Verify against a built-in ]', ('verify',), GOOD_COLOR)
        addLayoutRows(app, add, definition)
        add('Pins (IN / OUT) are its ports. Esc goes', None,
            DIM_TEXT_COLOR)
        add('back up.', None, DIM_TEXT_COLOR)
    elif app.view['readOnly']:
        add('Built-in recipe', None, TITLE_COLOR, True)
        for line in wrapText('This is how the built-in part is made. It '
                             'is read-only. Press c to copy it to My parts '
                             'and edit it there. Esc goes back up.', 38):
            add(line, None, DIM_TEXT_COLOR)
    else:
        addCircuitRows(app, add)
    return rows

def explainLines(problem, chars):
    # [(text, kind)] for a problem: what, why (the cause), how to fix it
    lines = []
    for line in wrapText(problem['text'], chars):
        lines.append((line, 'text'))
    for reason in problem.get('why', []):
        indent = len(reason) - len(reason.lstrip(' '))
        for line in wrapText(reason.strip(), chars - indent):
            lines.append((' ' * indent + line, 'why'))
    if problem.get('fix'):
        for line in wrapText('Fix: ' + problem['fix'], chars):
            lines.append((line, 'fix'))
    return lines

EXPLAIN_COLORS = {'text': None, 'why': TEXT_COLOR, 'fix': GOOD_COLOR}

def addExplainRows(app, add):
    problem = app.explain
    add('Why  (click or Esc to close)', ('closeExplain',), TITLE_COLOR,
        True)
    textColor = ERROR_COLOR if problem.get('level') == 'error' else \
        WARN_COLOR
    for line, kind in explainLines(problem, 38)[:16]:
        add(line, None, EXPLAIN_COLORS[kind] or textColor)
    add('')

def addLayoutRows(app, add, definition):
    # The size of your part's box, and which side each port is on
    from zb_editor import partBoxSize, userPortRows
    name = definition['name']
    (width, height), smallest = partBoxSize(app, definition)
    auto = definition.get('size') == None
    add(f"box: {width} x {height}{'  (auto)' if auto else ''}",
        ('size', name), buttons=[('auto', ('autoSize', name))])
    add(f'  width  {width}', None, TEXT_COLOR,
        buttons=[('-', ('grow', name, -10, 0)), ('+', ('grow', name, 10, 0))])
    add(f'  height {height}', None, TEXT_COLOR,
        buttons=[('-', ('grow', name, 0, -10)), ('+', ('grow', name, 0, 10))])
    add('ports (click: next side, name: rename)', None, DIM_TEXT_COLOR)
    for portName, side, direction, bits in userPortRows(app,
                                                        definition)[:12]:
        kind = 'IN ' if direction == 'in' else 'OUT'
        add(f'  {kind} {portName:7} {bits}b  {side}',
            ('portSide', name, portName),
            buttons=[('name', ('portName', name, portName)),
                     ('up', ('portUp', name, portName))])

def addPartRows(app, add, part):
    definition = getDefinition(app.library, part['type'])
    add(definition['label'] if definition else part['type'], None,
        TITLE_COLOR, True)
    add(f"label: {part['label'] or '-'}", ('label', part['id']))
    if definition == None:
        return
    if definition['kind'] == 'primitive':
        for key, value in part['params'].items():
            if key in HIDDEN_PARAMS:
                continue
            text = f"{key}: {paramText(value, part['type'], key)}"
            if key in STEP_PARAMS and type(value) == int:
                add(text, ('param', part['id'], key),
                    buttons=[('-', ('step', part['id'], key, -1)),
                             ('+', ('step', part['id'], key, +1))])
            elif key in PARAM_CHOICES:
                add(text + '  (click)', ('cycle', part['id'], key))
            elif (part['type'], key) in [('SPLIT', 'ranges'),
                                         ('MERGE', 'widths')]:
                add(text + '  (click)', ('param', part['id'], key))
            else:
                add(text, ('param', part['id'], key))
    from zb_kit import TAGS, tagFits
    if any(tagFits(tag, part['type']) for tag in TAGS):
        tag = part['ref']
        text = TAG_NAMES.get(tag, '-') if tag else '-'
        add(f'lecture tag: {text}  (click)', ('tag', part['id']))
    if definition['kind'] == 'composite':
        add(f"mode: {part['mode']}  (click)", ('mode', part['id']))
        verified = 'yes' if definition['verified'] else 'no'
        add(f"verified: {verified}  implements: "
            f"{definition['implements'] or '-'}")
        add('[ Verify against a built-in ]', ('verify',), GOOD_COLOR)
        addLayoutRows(app, add, definition)
    if definition['kind'] == 'composite' or part['type'] in \
            app.library['recipes']:
        add('Enter / double-click: look inside', None, DIM_TEXT_COLOR)
    add('')
    for line in wrapText(definition['help'], 38)[:6]:
        add(line, None, DIM_TEXT_COLOR)

def addWireRows(app, add, wire):
    info = getLevelInfo(app)
    netIndex = info['nets']['wireNet'][wire['id']]
    width = info['widths'][netIndex]
    add('Wire', None, TITLE_COLOR, True)
    add(f'width: {width} bit(s)')
    add(f"color: {wire['color'] or 'by width'}  (click)",
        ('wireColor', wire['id']))
    add(f"lamp: {wire['lamp'] or '-'}  (click)", ('wireLamp', wire['id']))
    add('')
    for line in wrapText('A lamp puts this wire in the control strip '
                         'in Run mode. Delete removes the wire.', 38):
        add(line, None, DIM_TEXT_COLOR)

def addCircuitRows(app, add):
    circuit = getCircuit(app)
    add(circuit['name'], None, TITLE_COLOR, True)
    add(f"{len(circuit['parts'])} parts, {len(circuit['wires'])} wires")
    errors = [p for p in app.problems if p['level'] == 'error']
    warnings = [p for p in app.problems if p['level'] == 'warning']
    add(f'{len(errors)} errors, {len(warnings)} warnings',
        None, ERROR_COLOR if errors else DIM_TEXT_COLOR)
    add('')
    tips = ['Click a part in the palette, then the canvas.',
            'Drag from a port to another port to wire them. Click empty '
            'space to bend the wire.',
            'Drop a wire on another wire to join them.',
            'Wire an 8-bit port to a 1-bit one: a SPLIT (or MERGE) '
            'appears, then click the ports for bits 1, 2, ...',
            'Shift-click places a part and keeps placing.',
            'Tab runs the machine.', '? shows every key.']
    for tip in tips:
        for line in wrapText(tip, 38):
            add(line, None, DIM_TEXT_COLOR)

def addRunRows(app, add, part):
    sim = app.sim
    if app.logicMode:
        add('Logic mode (no CLOCK)', None, GOOD_COLOR, True)
        for line in wrapText('Click an IN pin to flip it; the wires '
                             'settle at once. u shows the truth table.',
                             38):
            add(line, None, DIM_TEXT_COLOR)
    else:
        for line in wrapText(sim['status'], 38)[:3]:
            add(line, None, statusColor(sim['status']), True)
        add(f"phase {sim['halfCycles']}  next: {sim['phase']}  "
            f"instr {sim['instrCount']}")
    if app.logicMode:
        pass
    elif app.checkOn and programIsa(app) != None and             not programIsa(app)['standard']:
        add('Lecture check: off (the program declares instructions)',
            None, DIM_TEXT_COLOR)
    elif app.checkOn:
        if app.difference != None:
            add('Lecture check: DIFFERENT  (w: why)', None, ERROR_COLOR,
                True)
            for line in wrapText(app.difference['message'], 38):
                add(line, None, ERROR_COLOR)
        else:
            add('Lecture check: matches so far', None, GOOD_COLOR)
    else:
        add('Lecture check: off (k)', None, DIM_TEXT_COLOR)
    for warning in app.kitWarnings[:2]:
        for line in wrapText(warning, 38)[:3]:
            add(line, None, WARN_COLOR)
    add('')
    if part == None:
        for line in wrapText('Click a part to see how it works. Enter '
                             'looks inside it. Hover a wire for its '
                             'value.', 38):
            add(line, None, DIM_TEXT_COLOR)
        return
    definition = getDefinition(app.library, part['type'])
    add(partTitle(app, part, definition), None, TITLE_COLOR, True)
    shape = definition['shape']
    if part['type'] == 'ALU' or definition.get('implements') == 'ALU':
        addAdderRows(app, add, part)
    elif part['type'] == 'DECODER':
        addDecoderRows(app, add, part)
    elif part['type'] in ['MUX4', 'MUX2']:
        addMuxRows(app, add, part)
    else:
        addPortRows(app, add, part)
    add('')
    for line in wrapText(definition['help'], 38)[:5]:
        add(line, None, DIM_TEXT_COLOR)

def addPortRows(app, add, part):
    state = partState(app, part)
    if state != None and type(state) == int or state in [X]:
        bits = registerBits(part) if part['type'] != 'CLOCK' else 1
        add(f'holds {formatValue(state, bits)}', None, TEXT_COLOR, True)
    incoming = pendingValue(app, part)
    if incoming != None and type(incoming) == int:
        add(f'loads {formatValue(incoming, registerBits(part))} at the edge',
            None, FLASH_COLOR)
    for port in partLayout(app.library, part)[2][:12]:
        value = portValue(app, part, port['name'])
        text = '-' if value == None else formatValue(value, port['width'],
                                                     app.numFormat)
        arrow = '<-' if port['dir'] == 'in' else '->'
        add(f"{arrow} {port['name']:8} {text}")

def addAdderRows(app, add, part):
    # The carry table of the 8 full adders (as the lecture's inspector)
    import z18_cpu
    a = portValue(app, part, 'a')
    b = portValue(app, part, 'b')
    minus = portValue(app, part, 'minus')
    if not (isKnown(a) and isKnown(b) and isKnown(minus)):
        add('inputs unknown')
        return
    alu = z18_cpu.runAdder(a, b, minus)
    add('bit  a  b^-  cin  sum  cout', None, DIM_TEXT_COLOR)
    for i in range(7, -1, -1):
        c = alu['columns'][i]
        add(f"  {i}  {c['a']}   {c['b']}    {c['carryIn']}    {c['sum']}"
            f"     {c['carryOut']}")
    add(f"result {formatValue(alu['result'], 8)}  N{alu['n']} Z{alu['z']} "
        f"O{alu['o']}", None, TITLE_COLOR)
    if minus == 1:
        add('minus: B inverted, carry in 1', None, DIM_TEXT_COLOR)

def addDecoderRows(app, add, part):
    value = portValue(app, part, 'in')
    en = portValue(app, part, 'en')
    add(f"in {formatValue(value, part['params']['bits'])}  en {en}")
    for k in range(part['params']['outputs']):
        on = portValue(app, part, 'd' + str(k))
        pattern = format(k, f"0{part['params']['bits']}b")
        add(f'  d{k}: AND(en, {pattern}) = {on}', None,
            CONTROL_COLOR if on == 1 else TEXT_COLOR)

def addMuxRows(app, add, part):
    sel = portValue(app, part, 'sel')
    count = 4 if part['type'] == 'MUX4' else 2
    add(f"sel = {formatValue(sel, 2 if count == 4 else 1)}")
    for k in range(count):
        value = portValue(app, part, 'in' + str(k))
        chosen = isKnown(sel) and sel == k
        add(f"{'>' if chosen else ' '} in{k} {formatValue(value, part['params']['width'], app.numFormat)}",
            None, FLASH_COLOR if chosen else TEXT_COLOR)
    add(f"out {formatValue(portValue(app, part, 'out'), part['params']['width'], app.numFormat)}")

def statusColor(status):
    if status.startswith('Error'):
        return ERROR_COLOR
    if status.startswith('Halted'):
        return WARN_COLOR
    return GOOD_COLOR

def drawSide(app):
    left, top, width, height = SIDE
    scaledRect(left, top, width, height, fill=PANEL_COLOR,
               border=BORDER_COLOR)
    rows = getPropertyRows(app)
    maxRows = int((height - 16) // SIDE_ROW_HEIGHT)
    for i in range(min(len(rows), maxRows)):
        row = rows[i]
        rl, rt, rw, rh = sideRowRect(i)
        buttons = row.get('buttons', [])
        rects = sideButtonRects(i, buttons)
        textRoom = rw if len(rects) == 0 else rects[0][0] - rl - 4
        if row['action'] != None:
            scaledRect(rl - 2, rt, textRoom + 4, rh, fill=BG_COLOR,
                       border=BORDER_COLOR)
        drawText(fitText(row['text'], int(textRoom / 5.7)), rl + 2,
                 rt + rh / 2, size=9.5, color=row['color'], align='left',
                 bold=row['bold'])
        for (label, action), (bl, bt, bw, bh) in zip(buttons, rects):
            hover = pointInRectView(app.mouseX, app.mouseY, bl, bt, bw, bh)
            scaledRect(bl, bt, bw, bh, fill=ON_COLOR if hover else
                       BUTTON_COLOR, border=BORDER_COLOR)
            drawText(label, bl + bw / 2, bt + bh / 2, size=10,
                     color='white', bold=True)


######################################################################
# Bottom: messages (Build), control strip + narration (Run)
######################################################################

def getLamps(app):
    # [(label, value)] for every wire with a lamp at this level
    lamps = []
    seen = set()
    info = getLevelInfo(app)
    for wire in getCircuit(app)['wires']:
        if wire['lamp'] == None:
            continue
        netIndex = info['nets']['wireNet'][wire['id']]
        if netIndex in seen:
            continue
        seen.add(netIndex)
        value = netValue(app, netIndex)
        wave = netWave(app, netIndex)
        if not waveReached(app, wave):
            value = None
        lamps.append((wire['lamp'], value))
    return lamps

def drawLamps(app, left, top, width):
    lamps = getLamps(app)
    x = left
    y = top
    for label, value in lamps:
        textWidth = len(label) * 6 + 18
        if x + textWidth > left + width:
            x = left
            y += 18
        color = LANE_OFF_COLOR
        if value == 1:
            color = CONTROL_COLOR
        elif value == X:
            color = UNKNOWN_COLOR
        scaledCircle(x + 5, y, 4.5, fill=color)
        drawText(label, x + 13, y, size=9,
                 color=TEXT_COLOR if value == 1 else DIM_TEXT_COLOR,
                 align='left')
        x += textWidth

def drawBottom(app):
    left, top, width, height = BOTTOM
    scaledRect(left, top, width, height, fill=PANEL_COLOR,
               border=BORDER_COLOR)
    if app.mode == 'run':
        drawLamps(app, left + 10, top + 12, width - 20)
        lines = app.narration[:2]
        for i in range(len(lines)):
            drawText(fitText(lines[i], 170), left + 10,
                     top + 38 + i * 16, size=11,
                     color=FLASH_COLOR if i == 0 else TEXT_COLOR,
                     align='left')
    else:
        problems = app.problems
        y = top + 14
        shown = 0
        for problem in problems:
            if shown == 3:
                break
            color = ERROR_COLOR if problem['level'] == 'error' else \
                WARN_COLOR
            drawText(fitText(problem['level'] + ': ' + problem['text'],
                             170), left + 10, y, size=10, color=color,
                     align='left')
            y += 16
            shown += 1
        if len(problems) == 0:
            drawText('No wiring problems.', left + 10, y, size=10,
                     color=GOOD_COLOR, align='left')
    if app.message != None:
        color = TITLE_COLOR
        if app.messageColor == 'error':
            color = ERROR_COLOR
        elif app.messageColor == 'good':
            color = GOOD_COLOR
        drawText(fitText(app.message, 170), left + 10, top + height - 10,
                 size=11, color=color, align='left', bold=True)

def drawTimeline(app):
    left, top, width, height = TIMELINE
    scaledRect(left, top, width, height, fill=PANEL_COLOR,
               border=BORDER_COLOR)
    y = top + height / 2
    if app.mode != 'run':
        drawText('Tab: run it   Enter: look inside   Esc: back up   '
                 'P: pack into a part   Del: delete   ctrl+Z: undo   '
                 'right-drag: pan   ctrl +/-: zoom   F: fit   ?: help',
                 left + 10, y, size=10, color=DIM_TEXT_COLOR, align='left')
        return
    if app.logicMode:
        drawText('Logic mode (no CLOCK): click IN pins to flip them, or a '
                 'row of the truth table (u).   0 / Reset: every pin to 0.'
                 '   Add a CLOCK to step through phases.', left + 10, y,
                 size=10.5, color=DIM_TEXT_COLOR, align='left')
        return
    scaledRect(12, top + 6, 104, 26, fill=BUTTON_COLOR, border=BORDER_COLOR)
    drawText('Go to phase', 64, y, size=11, color='white', bold=True)
    current = app.sim['halfCycles']
    maxStep = len(app.sim['history']) - 1
    fraction = current / maxStep if maxStep > 0 else 0
    knobX = TRACK_LEFT + fraction * (TRACK_RIGHT - TRACK_LEFT)
    scaledLine(TRACK_LEFT, y, TRACK_RIGHT, y, fill=TRACK_COLOR, lineWidth=6)
    if knobX > TRACK_LEFT:
        scaledLine(TRACK_LEFT, y, knobX, y, fill=BUTTON_COLOR, lineWidth=6)
    scaledCircle(knobX, y, 8, fill=TITLE_COLOR)
    wave = ''
    if isAnimating(app):
        wave = f'  wave {app.wave + 1}/{app.waveCount}'
    drawText(f'phase {current}/{maxStep}  instr {app.sim["instrCount"]}'
             f'{wave}  speed {speedLabel(SPEEDS[app.animLevel])}',
             left + width - 10, y, size=11, color=DIM_TEXT_COLOR,
             align='right')


######################################################################
# Tooltips, pop-up lists, help
######################################################################

def drawTooltip(app):
    if app.hoverWire == None or app.picker != None:
        return
    circuit = getCircuit(app)
    info = getLevelInfo(app)
    netIndex = info['nets']['wireNet'].get(app.hoverWire)
    if netIndex == None:
        return
    width = info['widths'][netIndex]
    lines = [f'{width}-bit wire']
    value = netValue(app, netIndex)
    if value == None:
        # Build mode: the whole net, from its driver to what it reaches
        from zb_circuit import describePort
        net = info['nets']['nets'][netIndex]
        drivers, readers = [], []
        for partId, portName in net['ports']:
            port = getPort(app.library, findPart(circuit, partId), portName)
            text = describePort(circuit, partId, portName)
            if port != None and port['dir'] == 'out':
                drivers.append(text)
            else:
                readers.append(text)
        bits = 'bit' if width == 1 else 'bits'
        lines = [f"Net ({width} {bits}): {', '.join(drivers) or 'no driver'}"
                 + ' ->']
        for line in wrapText(', '.join(readers) or 'nothing', 60)[:3]:
            lines.append('  ' + line)
    if value != None:
        lines.append(formatAll(value, width))
        drivers = []
        simIndex = simNetOf(app, netIndex)
        for index, port in app.view['sim']['nets'][simIndex]['drivers']:
            prim = app.view['sim']['prims'][index]
            driven = app.view['sim']['nets'][simIndex]['driverValues'][
                (index, port)]
            if driven != Z:
                name = prim['label'] or prim['defn']['label']
                drivers.append(f'{name}.{port}')
        if len(drivers) > 0:
            lines.append('driven by ' + ', '.join(drivers[:3]))
        else:
            lines.append('nothing drives it now')
        if not isKnown(value) and app.mode == 'run':
            # where the x (or Z) comes from
            from zb_explain import explainValue
            steps = explainValue(app.view['sim'], simIndex, depth=6)
            if len(steps) > 0:
                source = steps[-1]['text'] if len(steps) > 1 else \
                    steps[0]['text']
                for line in wrapText(source, 70)[:3]:
                    lines.append(line)
    x, y = app.mouseX + 14, app.mouseY + 12
    boxWidth = max(len(line) for line in lines) * 6.6 + 16
    x = min(x, WINDOW_WIDTH - boxWidth - 4)
    scaledRect(x, y, boxWidth, len(lines) * 16 + 8, fill=LABEL_BG_COLOR,
               border=TITLE_COLOR)
    for i in range(len(lines)):
        drawText(lines[i], x + 8, y + 12 + i * 16, size=11, align='left')

def pickerBox(app):
    # (left, top, width, height) of the pop-up list; a list with
    # 'perColumn' (the missions) has two columns
    picker = app.picker
    rows = len(picker['items'])
    if picker.get('perColumn'):
        rows = picker['perColumn']
        return 170, 70, 1100, 50 + rows * 40 + 36
    return 350, 70, 740, 50 + rows * 40 + 36

def drawPartTip(app):
    # Over a part: a legend for its lit neighbours
    focus = getFocus(app)
    if app.hoverPart == None or focus['part'] != app.hoverPart or \
            app.picker != None or app.tool != None:
        return
    part = findPart(getCircuit(app), app.hoverPart)
    if part == None:
        return
    definition = getDefinition(app.library, part['type'])
    name = partTitle(app, part, definition) if definition else part['type']
    feeders, takers = len(focus['feeders']), len(focus['takers'])
    pieces = [(name + ':', TITLE_COLOR),
              (f"fed by {feeders} part{'s' if feeders != 1 else ''}",
               FEEDER_COLOR),
              (f"feeds {takers} part{'s' if takers != 1 else ''}",
               TAKER_COLOR)]
    text = '  '.join(p for p, c in pieces)
    x, y = app.mouseX + 14, app.mouseY + 14
    boxWidth = len(text) * 6.6 + 16
    x = min(x, WINDOW_WIDTH - boxWidth - 4)
    scaledRect(x, y, boxWidth, 24, fill=LABEL_BG_COLOR, border=BORDER_COLOR)
    left = x + 8
    for piece, color in pieces:
        drawText(piece, left, y + 12, size=11, color=color, align='left',
                 bold=color != TITLE_COLOR)
        left += (len(piece) + 2) * 6.6

def drawPaletteTip(app):
    # What the palette item under the mouse does
    if app.paletteHover == None or app.mode != 'build' or \
            app.picker != None:
        return
    typeName, i = app.paletteHover
    definition = getDefinition(app.library, typeName)
    if definition == None:
        return
    lines = [definition['label'] if definition['kind'] == 'primitive'
             else typeName]
    lines += wrapText(definition['help'], 48)[:5]
    if definition['kind'] == 'composite' and definition.get('verified'):
        lines.append('verified' + (f" ({definition['implements']})" if
                                   definition.get('implements') else ''))
    rl, rt, rw, rh = paletteRowRect(i)
    x, y = rl + rw + 10, rt
    boxWidth = max(len(line) for line in lines) * 6.6 + 16
    scaledRect(x, y, boxWidth, len(lines) * 16 + 8, fill=LABEL_BG_COLOR,
               border=TITLE_COLOR)
    for k in range(len(lines)):
        drawText(lines[k], x + 8, y + 12 + k * 16, size=11, align='left',
                 color=TITLE_COLOR if k == 0 else TEXT_COLOR, bold=k == 0)

def pickerRowRect(app, i):
    left, top, width, height = pickerBox(app)
    per = app.picker.get('perColumn')
    if per:
        columnWidth = (width - 42) / 2
        column, row = i // per, i % per
        return (left + 14 + column * (columnWidth + 14), top + 50 + row * 40,
                columnWidth, 34)
    return (left + 14, top + 50 + i * 40, width - 28, 34)

def drawPicker(app):
    picker = app.picker
    if picker == None:
        return
    left, top, width, height = pickerBox(app)
    items = picker['items']
    scaledRect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT, fill='black', opacity=50)
    scaledRect(left, top, width, height, fill=PANEL_COLOR,
               border=TITLE_COLOR, borderWidth=2)
    drawText(picker['title'], left + 20, top + 26, size=17,
             color=TITLE_COLOR, align='left', bold=True)
    for i in range(len(items)):
        label, description, value = items[i]
        rl, rt, rw, rh = pickerRowRect(app, i)
        if value == ('heading',):
            drawText(label, rl + 4, rt + rh - 10, size=13, color=WARN_COLOR,
                     align='left', bold=True)
            continue
        hover = rl <= app.mouseX <= rl + rw and rt <= app.mouseY <= rt + rh
        scaledRect(rl, rt, rw, rh, fill=TRACK_COLOR if hover else BG_COLOR,
                   border=BORDER_COLOR)
        drawText(fitText(label, int((rw - 16) / 7.2)), rl + 10, rt + 11,
                 size=12, color=TITLE_COLOR, align='left', bold=True)
        drawText(fitText(description, int((rw - 16) / 6)), rl + 10,
                 rt + 25, size=10, color=DIM_TEXT_COLOR, align='left')
    drawText('Click one.  Esc closes.', left + width / 2, top + height - 18,
             size=11, color=DIM_TEXT_COLOR)

def drawVerify(app):
    # The result of checking a user part against a built-in: the first
    # input where they differ, as a table
    result = app.verifyResult
    if result == None:
        return
    left, top, width, height = 350, 160, 740, 300
    scaledRect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT, fill='black', opacity=50)
    scaledRect(left, top, width, height, fill=PANEL_COLOR,
               border=ERROR_COLOR if not result['ok'] else GOOD_COLOR,
               borderWidth=2)
    title = 'It matches' if result['ok'] else 'Not the same yet'
    drawText(title, left + 20, top + 26, size=17,
             color=GOOD_COLOR if result['ok'] else ERROR_COLOR,
             align='left', bold=True)
    tested = result.get('tested')
    if tested != None:
        how = 'every input' if result.get('exhaustive') else \
            'edge cases, then random inputs'
        drawText(f'Tried {tested} input(s) ({how})', left + 20, top + 50,
                 size=11, color=DIM_TEXT_COLOR, align='left')
    mismatch = result.get('mismatch')
    if mismatch != None:
        columns = [('inputs', 20, 390), ('output', 410, 90),
                   ('expected', 500, 110), ('got', 610, 110)]
        for name, dx, w in columns:
            scaledRect(left + dx, top + 72, w, 26, fill=BG_COLOR,
                       border=BORDER_COLOR)
            drawText(name, left + dx + 8, top + 85, size=11,
                     color=TITLE_COLOR, align='left', bold=True)
            color = ERROR_COLOR if name == 'got' else TEXT_COLOR
            if name == 'expected':
                color = GOOD_COLOR
            scaledRect(left + dx, top + 98, w, 30, fill=PANEL_COLOR,
                       border=BORDER_COLOR)
            drawText(fitText(mismatch[name], int(w / 7)), left + dx + 8,
                     top + 113, size=11, color=color, align='left',
                     bold=name != 'inputs')
        lines = wrapText(f"With these inputs the built-in part gives "
                         f"{mismatch['output']} = {mismatch['expected']}, "
                         f"but yours gives {mismatch['got']}. Set the same "
                         'inputs on IN pins (at the top level, click them '
                         'in Run mode) to watch where it goes wrong.', 96)
        for i in range(len(lines)):
            drawText(lines[i], left + 20, top + 150 + i * 18, size=11,
                     align='left')
    else:
        for i, line in enumerate(wrapText(result['message'], 96)):
            drawText(line, left + 20, top + 80 + i * 18, size=11,
                     align='left')
    drawText('Click or press any key to close', left + width / 2,
             top + height - 18, size=11, color=DIM_TEXT_COLOR)

######################################################################
# The truth table (u) and the step table
######################################################################

TABLE_RECT = (220, 86, 1000, 592)
TABLE_ROW_HEIGHT = 18
TABLE_HEAD = 92                # from the box top to the first row
TABLE_TEXT = 11
DOCK_ROW_HEIGHT = 16
DOCK_HEAD = 66
DOCK_TEXT = 9

DOCK_EXPLAIN_LINES = 14
DOCK_LINE_HEIGHT = 13

def tableVisibleCount(app):
    if app.table['docked']:
        room = SIDE[3] - DOCK_HEAD - 40
        if sum(app.table.get('hiddenCols', (0, 0))) > 0:
            room -= 16                 # the "more columns" line
        if app.explain != None:
            room -= DOCK_EXPLAIN_LINES * DOCK_LINE_HEIGHT + 16
        return max(1, int(room // DOCK_ROW_HEIGHT))
    return int((TABLE_RECT[3] - TABLE_HEAD - 56) // TABLE_ROW_HEIGHT)

def tableRowRect(app, k):
    # The k-th row on screen (after scrolling), in design units
    if app.table['docked']:
        left, top, width, height = SIDE
        return (left + 4, top + DOCK_HEAD + k * DOCK_ROW_HEIGHT, width - 8,
                DOCK_ROW_HEIGHT)
    left, top, width, height = TABLE_RECT
    return (left + 12, top + TABLE_HEAD + k * TABLE_ROW_HEIGHT, width - 24,
            TABLE_ROW_HEIGHT)

def tableRowAt(app, x, y):
    # The index (into the data's rows) of the row at (x, y), or None
    from zb_editor import tableRows
    visible = tableRows(app)[app.table['scroll']:]
    for k in range(min(len(visible), tableVisibleCount(app))):
        if pointInRectView(x, y, *tableRowRect(app, k)):
            return visible[k][0]
    return None

def pointInRectView(x, y, left, top, width, height):
    return left <= x <= left + width and top <= y <= top + height

def valueChars(width, fmt):
    # How many characters a value of this width takes in this format
    if width == 1 or fmt == 'bin':
        return width + (1 if width == 8 else 0)
    if fmt == 'hex':
        return 2 + (width + 3) // 4
    return len(str(1 << width)) + 1

def cellText(value, width, fmt):
    # (text, dim): unknown and floating values are one dim letter
    if value == None:
        return '-', True
    if value == X:
        return 'x', True
    if value == Z:
        return 'Z', True
    return formatValue(value, width, fmt if width > 1 else 'bin'), False

def tableColumns(app, data, charWidth, compact, fmt=None):
    # [(group, column, x offset in chars)] and the total width in chars
    if fmt == None:
        fmt = app.numFormat
    groups = [('in', data['inputs']), ('out', data['outputs'])]
    if data['hasExpected'] and not compact:
        groups.append(('expected', data['outputs']))
    columns = []
    x = 0
    for group, cols in groups:
        for column in cols:
            chars = max(len(column['name']),
                        valueChars(column['width'], fmt))
            columns.append((group, column, x, chars))
            x += chars + 2
        x += 2                         # room for the divider
    return columns, x

MIN_TABLE_TEXT = 7

def tableRoom(app):
    # How wide (design units) the table's columns may be
    if app.table['docked']:
        return SIDE[2] - 24
    return TABLE_RECT[2] - 48

def fitTableColumns(app, data, compact, size):
    # Makes a wide table fit: binary -> hex, then smaller text, and if it
    # still doesn't fit, only the columns from table['colScroll'] on that
    # fit (left / right scroll the rest). Returns
    # {'fmt', 'size', 'columns', 'total' (chars), 'hidden': (left, right)}
    table = app.table
    room = tableRoom(app)
    markChars = 0
    if data['hasExpected']:
        markChars = 3 if compact else 24
    formats = [app.numFormat]
    if app.numFormat == 'bin':
        formats.append('hex')
    sizes = []
    s = size
    while s >= MIN_TABLE_TEXT:
        sizes.append(s)
        s -= 0.5
    for fmt in formats:
        for s in sizes:
            columns, total = tableColumns(app, data, 0.6 * s, compact, fmt)
            if (total + markChars) * 0.6 * s <= room:
                return {'fmt': fmt, 'size': s, 'columns': columns,
                        'total': total, 'hidden': (0, 0)}
    # still too wide: scroll the columns sideways
    fmt, s = formats[-1], MIN_TABLE_TEXT
    columns, total = tableColumns(app, data, 0.6 * s, compact, fmt)
    start = max(0, min(len(columns) - 1, table.get('colScroll', 0)))
    table['colScroll'] = start
    offset = columns[start][2]
    shown = []
    end = start
    for group, column, x, chars in columns[start:]:
        if (x - offset + chars + markChars) * 0.6 * s > room and \
                len(shown) > 0:
            break
        shown.append((group, column, x - offset, chars))
        end += 1
    last = shown[-1]
    return {'fmt': fmt, 'size': s, 'columns': shown,
            'total': last[2] + last[3] + 2,
            'hidden': (start, len(columns) - end)}

def drawTableRows(app, left, top, rowHeight, size, compact):
    from zb_editor import tableRows
    table = app.table
    data = table['data']
    fit = fitTableColumns(app, data, compact, size)
    # (kept on the table, so the keys know there are columns to scroll)
    table['hiddenCols'] = fit['hidden']
    fmt, size = fit['fmt'], fit['size']
    charWidth = 0.6 * size
    columns, totalChars = fit['columns'], fit['total']
    # group labels and column names
    if not compact:
        shown = set()
        for group, column, x, chars in columns:
            if group not in shown:
                shown.add(group)
                drawText(group, left + x * charWidth, top - 36, size=size - 1,
                         color=DIM_TEXT_COLOR, align='left')
    for group, column, x, chars in columns:
        color = GOOD_COLOR if group == 'expected' else TITLE_COLOR
        drawText(column['name'], left + (x + chars) * charWidth, top - 16,
                 size=size, color=color, align='right', bold=True)
    markX = left + totalChars * charWidth
    # dividers between the groups
    lastGroup = None
    for group, column, x, chars in columns:
        if lastGroup != None and group != lastGroup:
            dividerX = left + (x - 2) * charWidth
            scaledLine(dividerX, top - 26, dividerX,
                       top + tableVisibleCount(app) * rowHeight,
                       fill=BORDER_COLOR, lineWidth=1)
        lastGroup = group
    visible = tableRows(app)[table['scroll']:]
    for k in range(min(len(visible), tableVisibleCount(app))):
        index, row = visible[k]
        rl, rt, rw, rh = tableRowRect(app, k)
        hover = pointInRectView(app.mouseX, app.mouseY, rl, rt, rw, rh)
        if index == table['selected']:
            scaledRect(rl, rt, rw, rh, fill=READ_COLOR)
        elif hover:
            scaledRect(rl, rt, rw, rh, fill=TRACK_COLOR)
        y = rt + rh / 2
        for group, column, x, chars in columns:
            name = column['name']
            if group == 'in':
                value = row['in'].get(name)
            elif group == 'out':
                value = row['got'].get(name)
            else:
                value = (row['expected'] or dict()).get(name)
            text, dim = cellText(value, column['width'], fmt)
            color = DIM_TEXT_COLOR if dim else TEXT_COLOR
            if group == 'out' and name in row['wrong']:
                color = ERROR_COLOR
            elif group == 'expected':
                color = GOOD_COLOR if not dim else DIM_TEXT_COLOR
            drawText(text, left + (x + chars) * charWidth, y, size=size,
                     color=color, align='right', bold=group == 'out')
        if data['hasExpected']:
            if row['wrong']:
                mark = 'no' if compact else fitText('wrong (' + ', '.join(
                    row['wrong'][:3]) + ')', 22)
                drawText(mark, markX, y, size=size, color=ERROR_COLOR,
                         align='left', bold=True)
            else:
                drawText('ok', markX, y, size=size, color=GOOD_COLOR,
                         align='left', bold=True)
    return len(visible)

def drawTable(app):
    from zb_library import tableSummary, tableTitle
    from zb_editor import tableRows
    table = app.table
    if table == None:
        return
    data = table['data']
    if table['docked']:
        drawDockedTable(app)
        return
    left, top, width, height = TABLE_RECT
    scaledRect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT, fill='black', opacity=50)
    scaledRect(left, top, width, height, fill=PANEL_COLOR,
               border=TITLE_COLOR, borderWidth=2)
    kind = 'Step table' if data.get('kind') == 'steps' else 'Truth table'
    drawText(f'{kind}: {fitText(data.get("name", ""), 40)}', left + 20,
             top + 24, size=16, color=TITLE_COLOR, align='left', bold=True)
    drawText(tableTitle(data), left + width - 20, top + 24, size=11,
             color=DIM_TEXT_COLOR, align='right')
    clipTo(left + 4, top + 40, width - 8, height - 80)
    try:
        if data.get('kind') == 'steps':
            drawStepRows(app, left + 24, top + TABLE_HEAD, TABLE_ROW_HEIGHT,
                         TABLE_TEXT, False)
        else:
            drawTableRows(app, left + 24, top + TABLE_HEAD,
                          TABLE_ROW_HEIGHT, TABLE_TEXT, False)
    finally:
        unclip()
    rows = tableRows(app)
    shownTo = min(len(rows), table['scroll'] + tableVisibleCount(app))
    summary = tableSummary(data)
    if table['onlyWrong']:
        summary += '   (only wrong rows)'
    if len(rows) > tableVisibleCount(app):
        summary += f"   showing {table['scroll'] + 1}-{shownTo}"
    if hiddenColumnsText(table) != '':
        summary += '   ' + hiddenColumnsText(table)
    drawText(summary, left + 20, top + height - 38, size=11,
             color=ERROR_COLOR if '· 0 wrong' not in summary and
             data['hasExpected'] else TEXT_COLOR, align='left', bold=True)
    drawText('click a row: try it on the pins   space: play the rows   '
             'o: only wrong rows   arrows / wheel: scroll   h: bin/dec/hex   '
             'Esc: close', left + 20, top + height - 18, size=10,
             color=DIM_TEXT_COLOR, align='left')

def hiddenColumnsText(table):
    # '<- 2 columns  |  3 more ->' when the table is too wide to show whole
    before, after = table.get('hiddenCols', (0, 0))
    if before + after == 0:
        return ''
    pieces = []
    if before > 0:
        pieces.append(f'<- {before} column{"s" if before > 1 else ""}')
    if after > 0:
        pieces.append(f'{after} more ->')
    return '  |  '.join(pieces) + '  (left / right)'

def drawDockedTable(app):
    # The table while rows are being tried: over the side panel, so the
    # wires stay in view
    from zb_library import tableSummary
    table = app.table
    data = table['data']
    left, top, width, height = SIDE
    scaledRect(left, top, width, height, fill=PANEL_COLOR,
               border=TITLE_COLOR, borderWidth=2)
    kind = 'Steps' if data.get('kind') == 'steps' else 'Truth table'
    state = '  (playing)' if table['playing'] else ''
    drawText(kind + state, left + 10, top + 14, size=11, color=TITLE_COLOR,
             align='left', bold=True)
    drawText(fitText(tableSummary(data), 40), left + 10, top + 30,
             size=9, color=DIM_TEXT_COLOR, align='left')
    clipTo(left + 2, top + 34, width - 4, height - 36)
    try:
        if data.get('kind') == 'steps':
            drawStepRows(app, left + 10, top + DOCK_HEAD, DOCK_ROW_HEIGHT,
                         DOCK_TEXT, True)
        else:
            drawTableRows(app, left + 10, top + DOCK_HEAD, DOCK_ROW_HEIGHT,
                          DOCK_TEXT, True)
    finally:
        unclip()
    if app.explain != None:
        # why the selected row is wrong, under the rows
        y = top + height - 40 - DOCK_EXPLAIN_LINES * DOCK_LINE_HEIGHT
        scaledLine(left + 6, y - 8, left + width - 6, y - 8,
                   fill=BORDER_COLOR, lineWidth=1)
        lines = explainLines(app.explain, 40)[:DOCK_EXPLAIN_LINES]
        for i in range(len(lines)):
            line, kind = lines[i]
            drawText(line, left + 10, y + i * DOCK_LINE_HEIGHT, size=8.5,
                     color=EXPLAIN_COLORS[kind] or ERROR_COLOR,
                     align='left')
    hiddenText = hiddenColumnsText(table)
    if hiddenText != '':
        drawText(hiddenText, left + 10, top + height - 46, size=9,
                 color=WARN_COLOR, align='left', bold=True)
    drawText('space: play  arrows: next row', left + 10,
             top + height - 30, size=9, color=DIM_TEXT_COLOR, align='left')
    drawText('u: full table  Esc: close', left + 10, top + height - 14,
             size=9, color=DIM_TEXT_COLOR, align='left')

def drawStepRows(app, left, top, rowHeight, size, compact):
    # The step table of a Memory mission: step, what changed, the note,
    # expected, got
    from zb_editor import tableRows
    table = app.table
    data = table['data']
    charWidth = 0.6 * size
    outputs = data['outputs']
    if compact:
        heads = [('#', 3), ('set', 12), ('got', 12)]
    else:
        heads = [('step', 5), ('changes', 12), ('note', 36),
                 ('expected', 20), ('got', 20)]
    x = 0
    positions = []
    for name, chars in heads:
        positions.append(x)
        drawText(name, left + x * charWidth, top - 16, size=size,
                 color=TITLE_COLOR, align='left', bold=True)
        x += chars + 2
    markX = left + x * charWidth
    visible = tableRows(app)[table['scroll']:]
    for k in range(min(len(visible), tableVisibleCount(app))):
        index, row = visible[k]
        rl, rt, rw, rh = tableRowRect(app, k)
        hover = pointInRectView(app.mouseX, app.mouseY, rl, rt, rw, rh)
        if index == table['selected']:
            scaledRect(rl, rt, rw, rh, fill=READ_COLOR)
        elif hover:
            scaledRect(rl, rt, rw, rh, fill=TRACK_COLOR)
        y = rt + rh / 2
        def show(values):
            pieces = []
            for column in outputs:
                if column['name'] in values:
                    text, dim = cellText(values[column['name']],
                                         column['width'], app.numFormat)
                    pieces.append(f"{column['name']}={text}")
            return ' '.join(pieces)
        changes = ' '.join(f'{name}={value}' for name, value in
                           row['set'].items())
        texts = [str(index + 1), changes]
        if not compact:
            texts += [row['note'], show(row['expected'])]
        texts.append(show(row['got']) if row['got'] != None else '')
        for i in range(len(texts)):
            color = TEXT_COLOR
            if heads[i][0] == 'got' and row['wrong']:
                color = ERROR_COLOR
            elif heads[i][0] in ['note', 'expected']:
                color = DIM_TEXT_COLOR if heads[i][0] == 'note' else \
                    GOOD_COLOR
            drawText(fitText(texts[i], heads[i][1] + 1),
                     left + positions[i] * charWidth, y, size=size,
                     color=color, align='left',
                     bold=heads[i][0] == 'got')
        if row['got'] != None and len(row['expected']) > 0:
            drawText('no' if row['wrong'] else 'ok', markX, y, size=size,
                     color=ERROR_COLOR if row['wrong'] else GOOD_COLOR,
                     align='left', bold=True)


HELP_BUILD = [
    'Build mode',
    'palette      click a part, then click the canvas',
    'r            place the last part again',
    'drag ports   draw a wire (click empty space to bend it;',
    '             drop it on a wire to make a junction)',
    '8 bit->1 bit a SPLIT/MERGE appears: click the next ports',
    '             for bits 1, 2, ... (0-7 picks a bit, Esc stops)',
    'shift-click  place a part and keep placing',
    'drag parts   move them (shift-click / box-drag: select more)',
    'Del          delete    ctrl+C / V / D  copy, paste, duplicate',
    'ctrl+Z / Y   undo / redo',
    'Enter        look inside the selected part (Esc: back up)',
    'P            pack the selected parts into a new part',
    'c            copy a built-in recipe (on screen) to My parts',
    't            cycle the lecture tag of the selected part',
    's            the size of your part (ports: side panel)',
    '[ / ]        fewer / more inputs (or width) of a part',
    'w            tidy the selected wires (w w: every wire)',

    'New part     a blank part to build inside (button)',
    'ctrl+S / O   save (to its file) / open   ctrl+N  new',
    'm            missions',
    'Tab          run it',
]
HELP_RUN = [
    'Run mode',
    'n            next wave (one step of logic settling)',
    'p            next clock phase (fetch or execute)',
    'space        next instruction',
    'r            run / pause (at once) / resume   e  to end',
    'backspace    back one phase      j  go to a phase',
    '0            reset               l  pick a program',
    '+ / -        speed 0.05x - 7x    h  bin / dec / hex',
    'b            bit lanes           k  lecture check on / off',
    'w            why did it stop? (or differ from the lecture)',
    'click        a part: inspector; a RAM bit: flip it;',
    '             shift-click a RAM row (or its left edge):',
    '             breakpoint; an IN pin: flip it',
    'Enter / Esc  look inside a part / back up',
    'Tab          back to Build mode',
    'no CLOCK     logic mode: click pins or table rows;',
    '             Run / r / space plays the truth table',
]
HELP_BOTH = ['Either mode', 'right-drag   pan (or the arrow keys)',
             'ctrl + / -   zoom        f  fit to the window',
             'u            truth table (click a row: try it;',
             '             space: play the rows; o: only wrong)',
             'i            hover lights up a net, or a part''s wires',
             '             (green: feeds it, pink: it feeds)  on / off',
             'g            grid        ?  this help',
             'title        click Computer > ... to go up a level']

def drawHelp(app):
    left, top, width, height = 240, 65, 960, 660
    scaledRect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT, fill='black', opacity=50)
    scaledRect(left, top, width, height, fill=PANEL_COLOR,
               border=TITLE_COLOR, borderWidth=2)
    for column, lines in [(0, HELP_BUILD), (1, HELP_RUN + [''] + HELP_BOTH)]:
        x = left + 24 + column * 470
        for i in range(len(lines)):
            first = i == 0 or (lines[i - 1] == '' and lines[i] != '')
            drawText(lines[i], x, top + 30 + i * 22,
                     size=15 if first else 11,
                     color=TITLE_COLOR if first else TEXT_COLOR,
                     align='left', bold=first)
    drawText('Press ? or click to close', left + width / 2,
             top + height - 20, color=DIM_TEXT_COLOR)


######################################################################
# Everything
######################################################################

def drawApp(app):
    # The view only reads app, so it draws from a plain copy of app's fields
    # made once per frame (see FRAME above for why)
    frameApp = SimpleNamespace(**{name: value for name, value in
                                  vars(app).items()
                                  if not name.startswith('_')})
    startFrame(frameApp)
    try:
        drawEverything(frameApp)
    finally:
        endFrameCache()

def drawEverything(app):
    scaledRect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT, fill=BG_COLOR)
    drawCanvas(app)
    # Panels are drawn over the canvas, which hides parts that stick out
    scaledRect(0, 0, WINDOW_WIDTH, 81, fill=BG_COLOR)
    scaledRect(0, 678, WINDOW_WIDTH, 132, fill=BG_COLOR)
    left, top, width, height = getCanvas(app)
    scaledRect(0, 81, left, 598, fill=BG_COLOR)
    scaledRect(left + width, 81, WINDOW_WIDTH - left - width, 598,
               fill=BG_COLOR)
    scaledRect(left, top, width, height, fill=None, border=BORDER_COLOR)
    drawTitle(app)
    drawButtons(app, app.buttons[app.mode], app.isEnabled, app.isOn,
                app.buttonLabel)
    if app.mode == 'build':
        drawPalette(app)
    drawSide(app)
    drawBottom(app)
    drawTimeline(app)
    if app.table != None:
        drawTable(app)
    if app.table == None or app.table['docked']:
        drawTooltip(app)
        drawPartTip(app)
        drawPaletteTip(app)
    drawPicker(app)
    if app.showHelp:
        drawHelp(app)

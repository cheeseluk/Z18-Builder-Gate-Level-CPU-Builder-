# zb_main.py
# Z18 Builder: build a computer from parts, then run a .z18 program on it.
# Run with:  python z18builder/zb_main.py
#
#   model:      zb_values, zb_parts, zb_circuit, zb_sim, zb_library,
#               zb_kit, zb_missions (no graphics)
#   view:       zb_view.py (only draws)
#   controller: zb_editor.py (Build-mode actions) and this file (setup,
#               Build/Run modes, the wave animation, events)
#
# As in ../z18100/z18_main.py, only the clock edge (zb_sim.endPhase)
# changes the machine. Each phase is settled first (zb_sim.beginPhase);
# the animation then replays its waves, and the edge commits it.

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(HERE)
for folder in [PROJECT_DIR, os.path.join(PROJECT_DIR, 'z18100'), HERE]:
    if folder not in sys.path:
        sys.path.append(folder)

from cmu_graphics import *
from zb_paint import beginFrame, endFrame, fitWindow, toDesign, startSize
from cmu_graphics import pygameEvent
import importlib
import z18_cpu
from z18_assembler import assembleProgram, disassemble
from z18_isa import opcodeBits
from zb_values import Z, X, isKnown, mask, formatValue
from zb_parts import (PRIMITIVES, RAM_WORDS, rangePresets, widthPresets,
                      formatRanges, formatWidths)
from zb_circuit import (makeLibrary, makeCircuit, findPart, getDefinition,
                        partLayout, validate, loadCircuit)
from zb_sim import (flatten, loadProgram, beginPhase, endPhase, goToStep,
                    settle, snapshot, halt, describePrim, findProgramRAM,
                    findTagged, MAX_PHASES)
from zb_library import loadUserParts
from zb_kit import (attachRecipes, attachKit, kitWarnings,
                    makeReferenceMachine, makeChecker, checkerGoTo,
                    checkerStep, compareWithGolden, TAG_NAMES, goldenWhy,
                    instructionText)
from zb_editor import (CIRCUIT_DIR, PARTS_DIR, AUTOSAVE, USER_SHAPES,
                       initAppFields, syncProblems, getCanvas, getCam,
                       toWorld, inCanvas, fitView, zoomStep, panBy,
                       getCircuit, isEditable, editingPartName,
                       readOnlyMessage, hitTest, undo, redo, say,
                       emptySelection, refreshView, drillIn, drillOut,
                       cancelTool, startPlacing, placeAt, startWire,
                       addBend, finishWire, startMove, dragMove, endDrag,
                       selectBox, deleteSelection, copySelection, paste,
                       duplicate, getSelectedPart, getSelectedWire,
                       setParam, setLabel, cycleTag, cycleWireColor,
                       setLamp, toggleMode, packInto, copyRecipe,
                       verifyCurrent, newUserPart,
                       currentUserPart, listCircuits, saveAs, openCircuit,
                       listCircuitsByDate, isUnsaved, openFile, changeAnimLevel, advanceWave,
                       editSimState, tableForView, openTableData,
                       tableRows, setRootPins, rootPins, explainRow,
                       showExplanation, tidy, atRunTop, runBase, soloMessage,
                       partBoxSize, parseSize,
                       setPartSize, growPart, cyclePortSide,
                       movePortEarlier, renamePort, stepParam, cycleParam,
                       busConnect, pickBusBit, openPartSheet,
                       restoreStash, stashRoot)
from zb_explain import explainValue, partsOnLevel
from zb_view import (drawApp, drawVerify, LAYOUT, TOOLBAR_TOP, PALETTE_RECT,
                     SIDE, BOTTOM, TIMELINE, TRACK_LEFT, TRACK_RIGHT, IDLE,
                     WAVES, EDGE, FRAMES_PER_WAVE, WINDOW_WIDTH,
                     WINDOW_HEIGHT, paletteItems, paletteRowRect,
                     paletteTabRect, sideRowRect, sideButtonRects,
                     getPropertyRows,
                     pickerRowRect, ramRowAt, ramBitAt, getPrim, portNet, portValue,
                     netValue, netWave, isLive, getLevelInfo, paramText,
                     partTitle, crumbRects, crumbLevel)
import zb_missions

FRAME_RATE = 60
MIN_FLASH_FRAMES = 8
DOUBLE_CLICK_SECONDS = 0.35
PAN_STEP = 80                      # design units per arrow key
NUM_FORMATS = ['bin', 'dec', 'hex']
PROGRAM_DIRS = [os.path.join(PROJECT_DIR, 'z18100', 'programs'),
                os.path.join(HERE, 'programs')]
DEFAULT_PROGRAM = os.path.join(PROGRAM_DIRS[0], 'lecture_loop.z18')
PROGRAM_NAME_RECT = (1020, 6, 410, 30)
# The pygame that cmu_graphics runs on (for the mouse wheel)
PYGAME = importlib.import_module('cmu_graphics.deps').pygame
MAX_PICKER_ROWS = 14
NARRATION_CHARS = 165


######################################################################
# Setup
######################################################################

def onAppStart(app):
    app.stepsPerSecond = FRAME_RATE
    app.inspectorEnabled = False       # ctrl is used for shortcuts
    library = makeLibrary()
    attachRecipes(library)
    errors = loadUserParts(library, PARTS_DIR)
    root, startMessage = loadStartCircuit()
    layout = dict(LAYOUT)
    layout['programName'] = PROGRAM_NAME_RECT
    initAppFields(app, layout, library, root)
    app.lastFrameTime = None
    app.programPath = DEFAULT_PROGRAM
    app.programName = os.path.basename(DEFAULT_PROGRAM)
    app.missionProgress = zb_missions.loadProgress(PARTS_DIR)
    app.buttons = makeButtons()
    app.isEnabled = lambda action: isButtonEnabled(app, action)
    app.isOn = lambda action: isButtonOn(app, action)
    app.buttonLabel = lambda button: getButtonLabel(app, button)
    app.bench = None
    if os.environ.get('ZB_BENCH'):
        app.bench = {'frame': 0, 'last': None, 'gaps': [], 'draw': 0,
                     'draws': 0}
    say(app, startMessage)
    if len(errors) > 0:
        say(app, 'Could not load a saved part: ' + errors[0], 'error')

def loadStartCircuit():
    # The last session's circuit if there is one, else the lecture machine
    path = os.path.join(CIRCUIT_DIR, AUTOSAVE + '.json')
    if os.path.exists(path):
        try:
            return loadCircuit(path), ('Welcome back: this is your last '
                                       'circuit. Tab runs it, ? shows the '
                                       'keys.')
        except (OSError, ValueError, KeyError):
            pass
    return makeReferenceMachine(), ('This is the lecture\'s Z18100, built '
                                    'from kit parts. Tab runs it, ? shows '
                                    'the keys.')

BUILD_BUTTONS = [('Run  (Tab)', 'mode', 96), None,
                 ('Undo', 'undo', 58), ('Redo', 'redo', 58),
                 ('Delete', 'delete', 70), None,
                 ('Look inside', 'inside', 106), ('Up', 'up', 44),
                 ('Pack', 'pack', 56), ('New part', 'newPart', 88), None,
                 ('Fit', 'fit', 44), ('Grid', 'grid', 52),
                 ('Highlight', 'highlight', 92), ('Tidy', 'tidy', 52),
                 None,
                 ('New', 'new', 50), ('Open', 'open', 56),
                 ('Save', 'save', 56), ('Missions', 'missions', 86),
                 ('Table', 'table', 58), ('Help', 'help', 54)]
RUN_BUTTONS = [('Build (Tab)', 'mode', 104), None,
               ('Back', 'back', 58), ('Wave', 'wave', 58),
               ('Phase', 'phase', 64), ('Step', 'step', 58),
               ('Run', 'run', 62), ('To end', 'end', 72),
               ('Reset', 'reset', 62), None,
               ('Program', 'program', 82), ('Up', 'up', 44),
               ('Fit', 'fit', 44), ('Grid', 'grid', 52),
               ('Highlight', 'highlight', 92), None,
               ('Lanes', 'lanes', 64),
               ('bin', 'format', 52), ('Check', 'check', 64),
               ('Table', 'table', 58), ('Help', 'help', 54)]

def makeButtons():
    # {'build': [...], 'run': [...]}; None in the lists is a small gap
    buttons = dict()
    for mode, specs in [('build', BUILD_BUTTONS), ('run', RUN_BUTTONS)]:
        row = []
        left = 8
        for spec in specs:
            if spec == None:
                left += 14
                continue
            label, action, width = spec
            row.append({'label': label, 'left': left, 'top': TOOLBAR_TOP,
                        'width': width, 'height': 32, 'action': action})
            left += width + 6
        buttons[mode] = row
    return buttons

def readFile(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return None


######################################################################
# Model helpers (read-only)
######################################################################

def canRun(app):
    return app.sim != None and not app.sim['halted']

def isAnimating(app):
    return app.mode == 'run' and app.stage != IDLE

def pointInRect(x, y, left, top, width, height):
    return left <= x <= left + width and top <= y <= top + height

def getPC(app):
    # The value of the part tagged pc, or None
    prim = findTagged(app.sim, 'pc')
    if prim == None or not isKnown(prim['state']):
        return None
    return prim['state']

def atBreakpoint(app):
    pc = getPC(app)
    return app.sim['phase'] == 'fetch' and pc != None and \
        pc in app.breakpoints

def shiftIsDown():
    # cmu_graphics does not pass modifier keys to mouse events
    try:
        from cmu_graphics.deps import pygame
        return bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
    except Exception:
        return False

def partName(app, part):
    definition = getDefinition(app.library, part['type'])
    if part['label'] != '':
        return part['label']
    if part['ref'] != None:
        return TAG_NAMES.get(part['ref'], part['ref'])
    return definition['label'] if definition != None else part['type']


######################################################################
# Build <-> Run
######################################################################

def switchMode(app):
    if app.mode == 'build':
        enterRun(app)
    else:
        enterBuild(app)

def keepCenters(app, newMode):
    # The two modes' canvases differ in size: keep what is in the middle
    old = getCanvas(app)
    new = app.layout['runCanvas' if newMode == 'run' else 'buildCanvas']
    for cam in app.cams.values():
        cam['x'] += (old[2] - new[2]) / 2 / cam['zoom']
        cam['y'] += (old[3] - new[3]) / 2 / cam['zoom']

def enterRun(app):
    # Tab runs what is on screen: the whole circuit, or (when you are
    # looking inside a part) that part on its own, with its IN pins as
    # switches
    cancelTool(app)
    app.drag = None
    circuit = getCircuit(app)
    errors = [p for p in validate(app.library, circuit)
              if p['level'] == 'error']
    if len(errors) > 0:
        return say(app, 'Fix this before running: ' + errors[0]['text'],
                   'error')
    app.solo = None
    if len(app.path) > 0:
        app.solo = {'path': list(app.path), 'names': list(app.pathNames),
                    'circuit': circuit, 'readOnly': app.view['readOnly'],
                    'partName': app.view.get('partName')}
    sim = flatten(app.library, circuit)
    attachKit(sim)
    app.explain = None
    app.explainParts = set()
    keepCenters(app, 'run')
    app.mode = 'run'
    app.sim = sim
    app.selection = {'parts': set(app.selection['parts']), 'wires': set(),
                     'junctions': set()}
    ram = findProgramRAM(sim)
    app.programRam = None
    if ram != None and len(ram['path']) == 1:
        app.programRam = ram['path'][0]
    # No CLOCK: a logic circuit, with no phases to step (logic mode)
    app.logicMode = len(sim['clocks']) == 0
    app.kitWarnings = [] if app.logicMode else kitWarnings(sim)
    app.checkOn = any(prim['ref'] != None for prim in sim['prims']) and \
        not app.logicMode
    refreshView(app)
    resetRun(app)
    if app.logicMode:
        startLogicMode(app)
    else:
        say(app, 'Run mode: space runs one instruction, p one phase, n one '
                 'wave. Tab goes back to Build.')
    if app.solo != None:
        name = app.solo['names'][-1]
        say(app, f'Running {name} on its own: click its IN pins' +
            (', or the table rows' if app.table != None else '') +
            '. To run the whole circuit: Tab, Esc (up), Tab.')

LOGIC_KEYS = {'n': 'wave', 'p': 'phase', 'e': 'to end', 'backspace':
              'back', 'j': 'jump', 'l': 'program', 'k': 'check'}

def startLogicMode(app):
    # Run mode without a clock: click IN pins, or rows of the table
    app.narration = ['Logic mode: there is no CLOCK, so nothing steps in '
                     'phases. Click an IN pin to flip it, or a row of the '
                     'table to try it.',
                     'Add a CLOCK (Units) to step through fetch and '
                     'execute.']
    # settle at once, so the outputs show what the pins make
    settle(app.sim)
    app.settling = True
    app.goal = None
    startWaves(app)
    data, message = (None, 'Look inside parts with Enter') if \
        not atRunTop(app) else tableForView(app)
    if data != None:
        openTableData(app, data)
        app.table['docked'] = True
        say(app, 'Logic mode (no clock): the truth table is on the right. '
                 'Click a row, or space to play them all.')
    else:
        say(app, 'Logic mode (no clock): click the IN pins. ' +
            (message or ''))

def resetPins(app):
    # Logic mode's Reset: every IN pin back to 0, settled as waves
    stopForEdit(app)
    setRootPins(app, {name: 0 for name in rootPins(app)})
    app.settling = True
    app.goal = None
    startWaves(app)
    say(app, 'Every IN pin is 0 again')

def enterBuild(app):
    app.running = False
    app.table = None
    app.logicMode = False
    app.solo = None                    # (you stay at the level on screen)
    app.explain = None
    app.explainParts = set()
    clearAnimation(app)
    keepCenters(app, 'build')
    app.mode = 'build'
    app.sim = None
    app.checker = None
    app.difference = None
    app.differencePart = None
    app.narration = []
    app.kitWarnings = []
    app.hoverWire = None
    refreshView(app)

def resetRun(app):
    # Loads the program file into the RAM and starts from phase 0
    text = readFile(app.programPath)
    loadError = None
    if text == None:
        text = ''
        loadError = f'Could not read {app.programName}'
    result = assembleProgram(text)
    memory, rows, errors = result['memory'], result['rows'], result['errors']
    app.programMemory = memory
    app.rows = rows
    sim = app.sim
    loadProgram(sim, memory)
    sim['isa'] = result['isa']         # (the halt rule and captions read it)
    if loadError != None:
        halt(sim, 'Error: ' + loadError)
    elif len(errors) > 0:
        lineNum, message = errors[0]
        more = f' (and {len(errors) - 1} more)' if len(errors) > 1 else ''
        halt(sim, f'Assembler error (line {lineNum}): {message}{more}')
    sim['history'] = [snapshot(sim)]
    blocked = checkBlockedReason(app)
    app.checker = None
    if app.checkOn and blocked == None:
        app.checker = makeChecker(memory)
    app.difference = None
    app.running = False
    clearAnimation(app)
    app.narration = [f'{app.programName} is in the RAM. Space runs one '
                     'instruction; n shows one wave of logic at a time.']
    if blocked != None:
        app.narration.append(blocked + '.')
    afterSimChange(app)

def checkBlockedReason(app):
    # Why the lecture check cannot follow this program (it declares
    # instructions the lecture machine does not have), or None
    isa = app.sim.get('isa') if app.sim != None else None
    if isa == None or isa['standard']:
        return None
    codes = ', '.join(opcodeBits(opcode) for opcode in isa['declared'])
    what, it = 'its own instruction', 'it'
    if len(isa['declared']) > 1:
        what, it = 'its own instructions', 'them'
    return (f'{app.programName} declares {what} (op {codes}), so the '
            f'lecture check is off: the lecture machine would run {it} '
            'differently')

def afterSimChange(app):
    # The flow cache is keyed on simVersion; inner views of fast parts are
    # worked out once per refreshView
    app.simVersion += 1
    if len(app.path) > runBase(app):
        refreshView(app)
    syncDifferencePart(app)


######################################################################
# The animation
######################################################################

# app.stage is IDLE (the last finished phase stays on screen), WAVES
# while a settled phase is replayed wave by wave, or EDGE during the
# clock-edge flash. app.goal says how far to go before stopping:
#   'wave' (n), 'phase' (p), 'instr' (space) or 'run' (r).
# app.settling is True when the waves are from clicking an IN pin
# (they settle but no clock edge follows).

# app.frozen is True after Pause: the animation stops where it is, mid
# wave (or mid flash), until Run (or n, p, space) carries on.

# app.frozen is True after Pause: everything stops where it is (mid wave,
# mid flash, between table rows) until Resume carries on with whatever
# was ordered (a wave, a phase, an instruction, a run, the table).

def clearAnimation(app):
    app.stage = IDLE
    app.wave = 0
    app.waveT = 0
    app.flashFrames = 0
    app.goal = None
    app.settling = False
    app.frozen = False

def isMoving(app):
    # True while the animation has somewhere to go (not just waiting at
    # the end of a wave for n)
    if app.mode != 'run' or app.stage == IDLE:
        return False
    if app.stage == WAVES and app.goal == 'wave' and app.waveT >= 1:
        return False
    return True

def canPause(app):
    # In logic mode Run is about the table: only its playing pauses (the
    # short settle after a pin click doesn't take over the button)
    if app.logicMode:
        return tablePlaying(app)
    return isMoving(app) or app.running or tablePlaying(app)

def pauseOrResume(app):
    # Pause freezes everything on the spot; pressed again, it resumes.
    # Returns True if it did one of those (False: nothing to pause).
    if app.frozen:
        app.frozen = False
        if app.sim != None and not app.sim['halted']:
            app.sim['status'] = 'Running' if app.running else 'Stepping'
        say(app, 'Carrying on')
        return True
    if canPause(app):
        app.frozen = True
        if app.sim != None and not app.sim['halted']:
            app.sim['status'] = 'Paused'
        say(app, 'Paused right here. Resume (Run, r) carries on; n, p or '
                 'space step from here.')
        return True
    return False
    app.frozen = False

def freeze(app):
    # Pause: stop right here (if something is moving)
    app.frozen = app.stage != IDLE

def unfreeze(app):
    app.frozen = False

def startWaves(app):
    # The settle's last wave changes nothing (that is how it knows it is
    # done), so the animation stops at the last wave that changed a net
    changed = app.sim['netWave'].values()
    app.waveCount = max(changed) + 1 if len(changed) > 0 else 1
    app.wave = 0
    app.waveT = 0
    app.stage = WAVES
    afterSimChange(app)
    narrateWave(app)

def startPhase(app):
    # Settle the next phase (without committing it) and start its waves
    sim = app.sim
    if not beginPhase(sim):
        app.running = False
        app.goal = None
        return
    app.settling = False
    sim['status'] = 'Running' if app.running else 'Stepping'
    startWaves(app)

def commitPhase(app):
    # The clock edge. Returns True if it showed a new difference from the
    # lecture machine (which pauses the run).
    sim = app.sim
    if app.settling or not sim['begun']:
        clearAnimation(app)
        return False
    phaseName = sim['phase']
    endPhase(sim)
    app.stage = EDGE
    app.waveT = 1
    app.flashFrames = max(MIN_FLASH_FRAMES,
                          2 * FRAMES_PER_WAVE[app.animLevel])
    if not sim['halted'] and not app.running:
        sim['status'] = 'Paused'
    isNew = checkGolden(app, phaseName)
    afterSimChange(app)
    narrateEdge(app, phaseName)
    return isNew

def finishEdge(app):
    # The flash is over. Keep going if the goal is not reached yet.
    app.stage = IDLE
    app.flashFrames = 0
    sim = app.sim
    if sim['halted']:
        app.running = False
        app.goal = None
    elif app.goal == 'instr' and sim['phase'] == 'execute':
        startPhase(app)
    elif app.goal == 'run':
        if atBreakpoint(app):
            pauseAtBreakpoint(app)
        else:
            startPhase(app)
    else:
        app.goal = None

def pauseAtBreakpoint(app):
    app.running = False
    app.goal = None
    app.sim['status'] = f'Paused at breakpoint (address {getPC(app)})'

def nextWaveOrEdge(app):
    if app.wave < app.waveCount - 1:
        app.wave += 1
        app.waveT = 0
        narrateWave(app)
    elif app.settling:
        clearAnimation(app)
    else:
        commitPhase(app)

def elapsedFrames(app):
    # How many 60 fps frames of time passed since the last call. Drawing a
    # big machine can take longer than a frame, so the animation goes by
    # the clock, not by the number of onStep calls.
    now = time.perf_counter()
    last = app.lastFrameTime
    app.lastFrameTime = now
    if last == None:
        return 1
    return max(0.2, min(6, (now - last) * FRAME_RATE))

def animate(app):
    # Called every frame
    frames = elapsedFrames(app)
    if app.messageFrames > 0:
        app.messageFrames = max(0, app.messageFrames - frames)
        if app.messageFrames == 0:
            app.message = None
    if app.mode != 'run' or app.frozen:
        return                         # (paused: nothing moves)
    if app.stage == EDGE:
        app.flashFrames -= frames
        if app.flashFrames <= 0:
            finishEdge(app)
        return
    if app.stage != WAVES:
        return
    if app.waveT < 1:
        app.waveT = advanceWave(app.waveT, frames, app.animLevel)
        return
    if app.goal == 'wave':
        return                         # wait at the end of the wave
    nextWaveOrEdge(app)

def nextWave(app):
    # n: play exactly one more wave, then wait
    app.frozen = False
    app.running = False
    app.goal = 'wave'
    if app.stage == EDGE:
        app.stage = IDLE
    if app.stage == IDLE:
        if canRun(app):
            startPhase(app)
    elif app.waveT < 1:
        app.waveT = 1                  # finish the current wave now
    else:
        nextWaveOrEdge(app)
        app.goal = 'wave'

def nextPhase(app):
    # p: animate one clock phase, or skip to its clock edge
    app.frozen = False
    app.running = False
    if app.settling:
        clearAnimation(app)
    app.goal = 'phase'
    if app.stage == EDGE:
        app.stage = IDLE
    if app.stage == IDLE:
        if canRun(app):
            startPhase(app)
    else:
        commitPhase(app)

def nextInstruction(app):
    # space: animate the rest of this instruction, or skip to its end
    app.frozen = False
    app.running = False
    if app.settling:
        clearAnimation(app)
    if app.stage == EDGE:
        app.stage = IDLE
    if app.stage == IDLE:
        app.goal = 'instr'
        if canRun(app):
            startPhase(app)
        return
    app.goal = None
    if commitPhase(app):
        return
    if app.sim['phase'] == 'execute' and not app.sim['halted']:
        startPhase(app)
        commitPhase(app)

def toggleRun(app):
    # Run / Pause / Resume (and r): pauses whatever is moving right where
    # it is, resumes it, or (when nothing is) starts running
    sim = app.sim
    if pauseOrResume(app):
        return
    if not canRun(app):
        return
    if app.settling:
        clearAnimation(app)
    app.running = True
    app.goal = 'run'
    sim['status'] = 'Running'
    if app.stage == EDGE:
        app.stage = IDLE
    if app.stage == IDLE:
        startPhase(app)

######################################################################
# History, running to the end, the lecture check
######################################################################

def goToStepAndShow(app, step):
    # Shows the machine as it was after `step` clock phases
    sim = app.sim
    app.running = False
    step = max(0, min(len(sim['history']) - 1, step))
    goToStep(sim, step)
    clearAnimation(app)
    if not sim['halted']:
        sim['status'] = 'Ready' if step == 0 else 'Paused'
    if app.checker != None:
        checkerGoTo(app.checker, step)
        setDifference(app, compareWithGolden(sim, app.checker['cpu']),
                      None)
    if step == 0:
        app.narration = ['Back at the start (phase 0).']
    else:
        app.narration = [f'Phase {step}: the wires show what they carried '
                         'during it, the registers what they loaded at its '
                         'clock edge.']
    afterSimChange(app)

def stepBack(app):
    sim = app.sim
    if app.settling:
        clearAnimation(app)
        return
    if app.stage == WAVES:
        # A half-shown phase has not happened yet: just cancel it
        goToStepAndShow(app, sim['halfCycles'])
        return
    goToStepAndShow(app, sim['halfCycles'] - 1)

def runOnePhase(app):
    # One phase with no animation. Returns True at a new difference.
    sim = app.sim
    phaseName = sim['phase']
    if not sim['begun']:
        if not beginPhase(sim):
            return False
    endPhase(sim)
    return checkGolden(app, phaseName)

def runToEnd(app):
    # Runs (without animation) until a halt, a breakpoint or a difference
    sim = app.sim
    if not canRun(app):
        return
    app.running = False
    if app.settling:
        clearAnimation(app)
    stopped = False
    if sim['begun']:
        stopped = runOnePhase(app)     # finish the phase on screen
    clearAnimation(app)
    count = 0
    while not stopped and not sim['halted'] and count < MAX_PHASES:
        stopped = runOnePhase(app)
        count += 1
        if not stopped and atBreakpoint(app):
            pauseAtBreakpoint(app)
            break
    if sim['halted']:
        app.narration = [sim['status'],
                         f"after {sim['halfCycles']} phases "
                         f"({sim['instrCount']} instructions)"]
    elif stopped:
        app.narration = [app.difference['message']]
    else:
        app.narration = [sim['status']]
    if not sim['halted'] and not stopped and not atBreakpoint(app):
        sim['status'] = 'Paused'
    afterSimChange(app)

def promptForStep(app):
    app.running = False
    maxStep = len(app.sim['history']) - 1
    text = app.getTextInput(f'Go to clock phase (0 to {maxStep}):')
    try:
        target = int(text.strip())
    except (ValueError, AttributeError):
        return
    goToStepAndShow(app, target)

def dragTimeline(app, x):
    fraction = (x - TRACK_LEFT) / (TRACK_RIGHT - TRACK_LEFT)
    fraction = max(0, min(1, fraction))
    maxStep = len(app.sim['history']) - 1
    target = pythonRound(fraction * maxStep)
    if target != app.sim['halfCycles'] or app.stage != IDLE:
        goToStepAndShow(app, target)

def checkGolden(app, phaseName):
    # After a phase: compare with the lecture machine. Returns True if a
    # difference shows up that was not there before (and pauses).
    if not app.checkOn or app.checker == None:
        return False
    difference = checkerStep(app.checker, app.sim)
    isNew = difference != None and app.difference == None
    setDifference(app, difference, phaseName)
    if isNew:
        app.running = False
        app.goal = None
        if not app.sim['halted']:          # (a halt says more)
            app.sim['status'] = 'Paused: different from the lecture machine'
    return isNew

def setDifference(app, difference, phaseName):
    if difference == None:
        app.difference = None
        app.differencePart = None
        return
    sim = app.sim
    cpu = app.checker['cpu']
    where = f"Phase {sim['halfCycles']}"
    if phaseName != None:
        where += f' ({phaseName}, {instructionText(cpu["ir"])})'
    difference = dict(difference)
    difference['message'] = where + ': ' + difference['message']
    difference['why'] = goldenWhy(sim, difference)
    app.difference = difference
    syncDifferencePart(app)

def syncDifferencePart(app):
    # The part on screen that holds the value that differs
    app.differencePart = None
    difference = app.difference
    if difference == None or app.sim == None or app.view == None:
        return
    if not app.view['live']:
        return
    field = difference['field']
    prefix = app.view['prefix']
    for prim in app.sim['prims']:
        ref = prim['ref']
        if ref == field or (ref == 'flags' and field in ['n', 'z', 'o']):
            path = prim['path']
            if path[:len(prefix)] == prefix and len(path) > len(prefix):
                app.differencePart = path[len(prefix)]
            return

def toggleCheck(app):
    blocked = checkBlockedReason(app)
    if blocked != None:
        return say(app, blocked)
    app.checkOn = not app.checkOn
    if not app.checkOn:
        app.checker = None
        setDifference(app, None, None)
        return say(app, 'Lecture check off')
    app.checker = makeChecker(app.programMemory)
    checkerGoTo(app.checker, app.sim['halfCycles'])
    setDifference(app, compareWithGolden(app.sim, app.checker['cpu']),
                  None)
    say(app, 'Lecture check on: every phase is compared with '
             'z18100/z18_cpu.py')


######################################################################
# Changing the machine while it runs (RAM bits, IN pins)
######################################################################

def editState(app, prim, newState):
    # Gives a part a new state now. The future (history after this phase)
    # no longer holds, so it is cut.
    stopForEdit(app)
    editSimState(app.sim, prim, newState)

def stopForEdit(app):
    # Before the machine is changed by hand: stop, drop a half-shown
    # phase, and cut the lecture check's future too
    sim = app.sim
    app.running = False
    if app.stage == WAVES and not app.settling:
        goToStep(sim, sim['halfCycles'])       # cancel the half-shown phase
    clearAnimation(app)
    step = sim['halfCycles']
    if app.checker != None:
        checkerGoTo(app.checker, step)
        del app.checker['history'][step + 1:]

def flipRamBit(app, prim, address, bit):
    memory = list(prim['state'])
    word = memory[address] if isKnown(memory[address]) else 0
    word ^= 1 << (7 - bit)
    memory[address] = word
    editState(app, prim, memory)
    checker = app.checker
    if checker != None and prim is findProgramRAM(app.sim):
        checker['cpu']['mem'][address] = word
        checker['history'][-1] = z18_cpu.saveState(checker['cpu'])
    goToStep(app.sim, app.sim['halfCycles'])   # settle again
    afterSimChange(app)
    say(app, f'M[{address}] = {formatValue(word, 8)}  (the phases after '
             'this one were dropped from the timeline)')

def toggleBreakpoint(app, address):
    if address in app.breakpoints:
        app.breakpoints.remove(address)
        say(app, f'Breakpoint at address {address} removed')
    else:
        app.breakpoints.add(address)
        say(app, f'Breakpoint: running stops when the PC reaches {address}')

def setPin(app, part, prim):
    # An IN pin is a switch: 1-bit ones flip, wider ones ask for a value
    width = part['params']['width']
    if width == 1:
        value = 0 if prim['state'] == 1 else 1
    else:
        text = app.getTextInput(f"New value for {part['params']['name']} "
                                f'({width} bits; 12, 0b1100 or 0xC):')
        value = parseNumber(text)
        if value == None:
            return
        value &= mask(width)
    editState(app, prim, value)
    settle(app.sim)
    app.settling = True
    app.goal = None
    startWaves(app)

######################################################################
# The truth table (u) and the step table
######################################################################

def openTable(app):
    data, message = tableForView(app)
    if data == None:
        return say(app, message, 'error')
    openTableData(app, data)

def closeTable(app):
    app.table = None

def describeRow(app, data, row):
    if data.get('kind') == 'steps':
        return ', '.join(f'{name} = {value}' for name, value in
                         row['set'].items())
    pieces = []
    for column in data['inputs']:
        value = row['in'][column['name']]
        pieces.append(f"{column['name']} = "
                      f"{formatPort(app, value, column['width'])}")
    return ', '.join(pieces)

def applyTableRow(app, index):
    # Puts a row's inputs on the IN pins (in Run mode) and settles once,
    # shown as waves. A step table replays its steps up to this one.
    table = app.table
    data = table['data']
    table['selected'] = index
    if app.mode == 'run' and not atRunTop(app):
        return say(app, 'Rows can be tried at the top of what is running '
                        '(Esc goes up first)', 'error')
    if app.mode == 'build':
        enterRun(app)
        if app.mode != 'run':
            table['playing'] = False
            return
    table['docked'] = True
    stopForEdit(app)
    if data.get('kind') == 'steps':
        replaySteps(app, data, index)
    else:
        setRootPins(app, data['rows'][index]['in'])
    app.settling = True
    app.goal = None
    startWaves(app)
    row = data['rows'][index]
    if data.get('kind') != 'steps':
        explainRow(app, row)
    verdict = ''
    if row.get('wrong'):
        verdict = '  Wrong: ' + ', '.join(row['wrong']) + ' (red)'
    say(app, f'Row {index + 1}: {describeRow(app, data, row)}.{verdict}',
        'error' if verdict else None)

def replaySteps(app, data, index):
    # From power-on: every step's pin changes in turn, the last one shown
    resetRun(app)
    pins = rootPins(app)
    for k in range(index + 1):
        values = data['rows'][k]['set']
        if k < index:
            for name, value in values.items():
                if name in pins:
                    pins[name]['state'] = value
                    app.sim['seeds'].add(pins[name]['index'])
            settle(app.sim)
        else:
            setRootPins(app, values)
    app.sim['history'] = [snapshot(app.sim)]

def moveTableSelection(app, amount):
    rows = tableRows(app)
    if len(rows) == 0:
        return
    indexes = [i for i, row in rows]
    selected = app.table['selected']
    if selected in indexes:
        k = max(0, min(len(indexes) - 1, indexes.index(selected) + amount))
    else:
        k = 0
    scrollTableTo(app, k)
    applyTableRow(app, indexes[k])

def scrollTableTo(app, k):
    # Scrolls so the k-th shown row is in view
    from zb_view import tableVisibleCount
    count = tableVisibleCount(app)
    table = app.table
    if k < table['scroll']:
        table['scroll'] = k
    elif k >= table['scroll'] + count:
        table['scroll'] = k - count + 1

def scrollTable(app, amount):
    from zb_view import tableVisibleCount
    table = app.table
    most = max(0, len(tableRows(app)) - tableVisibleCount(app))
    table['scroll'] = max(0, min(most, table['scroll'] + amount))

def playTable(app):
    # Logic mode's Run (and r, and space): play the truth table row by
    # row, opening it (docked) first if it is closed. Again: pause.
    if pauseOrResume(app):
        return
    if app.table == None:
        data, message = tableForView(app) if atRunTop(app) else \
            (None, 'Go up (Esc) to play the table')
        if data == None:
            return say(app, message, 'error')
        openTableData(app, data)
        app.table['docked'] = True
    toggleTablePlay(app)

def toggleTablePlay(app):
    # space in the table (and Run in logic mode): pause right here,
    # resume, or start playing the rows
    table = app.table
    if pauseOrResume(app):
        return
    indexes = [i for i, row in tableRows(app)]
    if len(indexes) > 0 and table['selected'] == indexes[-1]:
        table['selected'] = None       # played to the end: start over
    table['playing'] = True
    playNextRow(app)

def playNextRow(app):
    # Space: the next row (after the selected one) goes on the pins
    table = app.table
    indexes = [i for i, row in tableRows(app)]
    selected = table['selected']
    if selected in indexes:
        k = indexes.index(selected) + 1
    else:
        k = 0
    if k >= len(indexes):
        table['playing'] = False
        return say(app, 'Played every row', 'good')
    scrollTableTo(app, k)
    applyTableRow(app, indexes[k])

def stepTablePlay(app):
    # Called every frame: when a row's waves are done, the next row
    # (playing stops on a wrong row)
    table = app.table
    if table == None or not table['playing'] or app.mode != 'run' or \
            app.stage != IDLE or app.frozen:
        return
    selected = table['selected']
    rows = table['data']['rows']
    if selected != None and rows[selected].get('wrong'):
        table['playing'] = False
        return say(app, f'Stopped on row {selected + 1}: '
                        f"{', '.join(rows[selected]['wrong'])} is wrong",
                   'error')
    playNextRow(app)

def tableKey(app, key, lower):
    # Keys while the table is open. Returns True if the key was used.
    table = app.table
    if key == 'escape':
        closeTable(app)
        return True
    if lower == 'u':
        if table['docked']:
            table['docked'] = False
        else:
            closeTable(app)
        return True
    if key == 'space':
        toggleTablePlay(app)
        return True
    if lower == 'o':
        table['onlyWrong'] = not table['onlyWrong']
        table['scroll'] = 0
        return True
    if key in ['left', 'right'] and sum(table.get('hiddenCols',
                                                   (0, 0))) > 0:
        # a table too wide to show whole: scroll its columns
        table['colScroll'] = max(0, table.get('colScroll', 0) +
                                 (-1 if key == 'left' else 1))
        if key == 'right' and table['hiddenCols'][1] == 0:
            table['colScroll'] -= 1        # already showing the last one
        return True
    if key in ['up', 'down']:
        amount = -1 if key == 'up' else 1
        if table['docked']:
            moveTableSelection(app, amount)
        else:
            scrollTable(app, amount)
        return True
    if lower == 'h':
        doAction(app, 'format')
        return True
    return not table['docked']         # the full table takes every key

def clickTable(app, x, y):
    # A click while the table is open. Returns True if it was used.
    from zb_view import tableRowAt, TABLE_RECT
    table = app.table
    index = tableRowAt(app, x, y)
    if index != None:
        table['playing'] = False
        applyTableRow(app, index)
        return True
    if table['docked']:
        return pointInRect(x, y, *SIDE)
    if not pointInRect(x, y, *TABLE_RECT):
        closeTable(app)
    return True


def parseNumber(text):
    if text == None:
        return None
    text = text.strip().lower().replace(' ', '')
    try:
        if text.startswith('0b'):
            return int(text[2:], 2)
        if text.startswith('0x'):
            return int(text[2:], 16)
        return int(text)
    except ValueError:
        return None


######################################################################
# Narration (generic: one sentence per part whose output changed)
######################################################################

def formatPort(app, value, width):
    if value == None:
        return '-'
    return formatValue(value, width, app.numFormat if width > 1 else 'bin')

def changedOutputs(app, part):
    # [(port, value)] of the part's outputs that changed in this wave
    result = []
    prim = getPrim(app, part)
    sim = app.view['sim']
    for port in partLayout(app.library, part)[2]:
        if port['dir'] != 'out':
            continue
        netIndex = portNet(app, part, port['name'])
        if netIndex == None or netWave(app, netIndex) != app.wave:
            continue
        if prim != None and port['name'] in prim['outNets']:
            net = sim['nets'][prim['outNets'][port['name']]]
            driven = net['driverValues'][(prim['index'], port['name'])]
            if len(net['drivers']) >= 2 and driven == Z:
                continue               # another part changed this bus
        result.append((port, netValue(app, netIndex)))
    return result

def describeChange(app, part, changed):
    name = partName(app, part)
    kind = part['type']
    definition = getDefinition(app.library, part['type'])
    if definition != None and definition['kind'] == 'composite' and \
            definition.get('implements'):
        kind = definition['implements']
    value = lambda portName, width: formatPort(
        app, portValue(app, part, portName), width)
    port, out = changed[0]
    if kind == 'TG':
        if portValue(app, part, 'en') == 1:
            return f"{name} is open (en = 1): it passes " \
                   f"{formatPort(app, out, port['width'])}"
        return f'{name} is closed (en = {value("en", 1)}): its output floats'
    if kind in ['MUX2', 'MUX4']:
        sel = portValue(app, part, 'sel')
        selWidth = 2 if kind == 'MUX4' else 1
        if isKnown(sel):
            return f"{name} passes input {sel} " \
                   f"({formatPort(app, out, port['width'])}) because sel " \
                   f"= {formatValue(sel, selWidth)}"
    if kind == 'DEMUX':
        sel = portValue(app, part, 'sel')
        if portValue(app, part, 'e') == 1 and isKnown(sel):
            return f'{name} sends its input to f{sel} and turns on en{sel} ' \
                   f'(sel = {sel})'
        return f'{name} is off (e = {value("e", 1)}): f0 and f1 float'
    if kind == 'RAM':
        dout = portValue(app, part, 'dout')
        if dout == Z:
            return f'{name} stops driving dout (RE = 0)'
        address = portValue(app, part, 'addr')
        where = f'M[{address}]' if isKnown(address) else 'M[x]'
        return f'{name} puts {where} = {formatPort(app, dout, 8)} on dout ' \
               '(RE = 1)'
    if kind == 'DECODER':
        outputs = PRIMITIVES['DECODER']['params']['outputs']
        if definition['kind'] == 'primitive':
            outputs = part['params']['outputs']
        on = [k for k in range(outputs)
              if portValue(app, part, 'd' + str(k)) == 1]
        bits = part['params'].get('bits', 4)
        if len(on) > 0:
            return f"{name} turns on output {on[0]} (in = " \
                   f"{value('in', bits)})"
        return f'{name}: every output is off (en = {value("en", 1)})'
    if kind == 'CLOCK':
        clk = portValue(app, part, 'clk')
        phase = 'execute' if clk == 1 else 'fetch'
        return f'{name}: CLK = {clk} ({phase})'
    if kind == 'ALU' and isKnown(portValue(app, part, 'out')):
        symbol = '-' if portValue(app, part, 'minus') == 1 else '+'
        return f"{name}: A {symbol} B = {value('out', 8)}  N{value('n', 1)} " \
               f"Z{value('z', 1)} O{value('o', 1)}"
    if len(changed) == 1 and port['name'] in ['out', 'q']:
        return f"{name} -> {formatPort(app, out, port['width'])}"
    pieces = [f"{p['name']} = {formatPort(app, v, p['width'])}"
              for p, v in changed[:4]]
    return f"{name}: {', '.join(pieces)}"

def packLines(header, sentences):
    # At most two lines of narration; says how many did not fit
    lines = [header]
    left = 0
    for sentence in sentences:
        line = lines[-1]
        joiner = '' if line.endswith(': ') else '.  '
        if len(line) + len(joiner) + len(sentence) <= NARRATION_CHARS:
            lines[-1] = line + joiner + sentence
        elif len(lines) < 2:
            lines.append(sentence)
        else:
            left += 1
    if left > 0:
        lines[-1] += f'  (+{left} more)'
    return lines

def narrateWave(app):
    sim = app.sim
    if app.settling:
        header = f'Settling, wave {app.wave + 1} of {app.waveCount}: '
    else:
        header = (f'{sim["phase"].capitalize()} phase, wave {app.wave + 1} '
                  f'of {app.waveCount}: ')
    sentences = []
    if isLive(app):
        for part in getCircuit(app)['parts']:
            changed = changedOutputs(app, part)
            if len(changed) > 0:
                sentences.append(describeChange(app, part, changed))
    if len(sentences) == 0:
        sentences = ['nothing on this level changes in this wave']
    app.narration = packLines(header, sentences)

def describeCommit(app, index, old, new):
    prim = app.sim['prims'][index]
    name = describePrim(prim)
    if prim['type'] == 'RAM':
        for address in range(RAM_WORDS):
            if old[address] != new[address]:
                return f'M[{address}] <- {formatPort(app, new[address], 8)}'
        return f'{name} (no change)'
    if prim['type'] == 'FLAGS':
        return f"{name} <- N{new['n']} Z{new['z']} O{new['o']}"
    width = prim['params'].get('width', 8)
    return f'{name} <- {formatPort(app, new, width)}'

def narrateEdge(app, phaseName):
    sim = app.sim
    if sim['halted']:
        app.narration = [sim['status'], 'Press w to see why, and which '
                                        'parts it is about.']
        return
    header = f'Clock edge (end of {phaseName}): '
    items = [describeCommit(app, index, old, new)
             for index, old, new in sim['changes']]
    if len(items) == 0:
        items = ['no register loads anything']
    lines = packLines(header, items)
    if app.difference != None:
        lines = lines[:1] + [app.difference['message']]
    app.narration = lines


######################################################################
# Pickers (programs, circuits, missions)
######################################################################

def getDescription(path):
    # A program's first comment line, which says what it demonstrates
    text = readFile(path)
    if text == None:
        return ''
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#'):
            return line.lstrip('#').strip().rstrip(':')
    return ''

def openProgramPicker(app):
    items = []
    for folder in PROGRAM_DIRS:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        where = os.path.basename(os.path.dirname(folder))
        for name in names:
            if name.endswith('.z18'):
                path = os.path.join(folder, name)
                items.append((f'{name}   ({where})', getDescription(path),
                              path))
    app.picker = {'title': 'Programs', 'items': items[:MAX_PICKER_ROWS],
                  'kind': 'program'}

def openCircuitPicker(app):
    # Left: circuits (newest first). Right: your parts, to edit inside.
    left = [('Circuits', '', ('heading',))]
    if app.stash != None:
        left.append((f"Back to {fitName(app.stash['name'])}",
                     'The circuit you had before', ('back',)))
    left += [('Lecture machine (reference)', 'The Z18100 built from kit '
              'parts', ('reference',)),
             ('Empty', 'A blank canvas', ('empty',))]
    for name in listCircuitsByDate():
        left.append((name, f'circuits/{name}.json', ('file', name)))
    right = [('Your parts', '', ('heading',))]
    for name in sorted(app.library['user']):
        if name.startswith('gates ') or name.startswith('('):
            continue
        definition = app.library['user'][name]
        note = 'verified' if definition['verified'] else 'not verified'
        right.append((name, f'edit its inside ({note})', ('part', name)))
    if len(right) == 1:
        right.append(('(none yet)', 'Pack parts (p) or finish a mission',
                      ('heading',)))
    rows = max(4, min(MAX_PICKER_ROWS, max(len(left), len(right))))
    left, right = left[:rows], right[:rows]
    left += [('', '', ('heading',))] * (rows - len(left))
    app.picker = {'title': 'Open', 'items': left + right, 'kind': 'open',
                  'perColumn': rows}

def fitName(name, chars=30):
    return name if len(name) <= chars else name[:chars - 1] + '.'

def openMissionPicker(app):
    # Two columns, with a heading over each group (Parts, Memory, Machine)
    items = []
    group = None
    for mission in zb_missions.MISSIONS:
        if mission['group'] != group:
            group = mission['group']
            items.append((group, '', ('heading',)))
        done = app.missionProgress.get(mission['id'], False)
        label = f"{mission['number']}. {mission['title']}"
        if done:
            label += '   (done)'
        items.append((label, mission['summary'], mission['id']))
    back = ''
    if app.stash != None:
        back = f": back to {fitName(app.stash['name'])}"
    items.append(('Leave missions', 'Free building' + back, None))
    perColumn = 0
    for item in items:                 # the first column ends before Machine
        if item[0] == 'Machine':
            break
        perColumn += 1
    app.picker = {'title': 'Missions', 'items': items, 'kind': 'mission',
                  'perColumn': max(perColumn, (len(items) + 1) // 2)}

def clickPicker(app, x, y):
    # A row picks it; a click anywhere else just closes the list
    picker = app.picker
    for i in range(len(picker['items'])):
        if pointInRect(x, y, *pickerRowRect(app, i)):
            if picker['items'][i][2] == ('heading',):
                return                     # a group heading: keep it open
            app.picker = None
            pick(app, picker['kind'], picker['items'][i][2])
            return
    app.picker = None

def pick(app, kind, value):
    if kind == 'program':
        app.programPath = value
        app.programName = os.path.basename(value)
        app.breakpoints = set()            # they belong to the old program
        if app.mode == 'run':
            resetRun(app)
        say(app, f'Program: {app.programName}')
    elif kind == 'open':
        if app.mode == 'run':
            enterBuild(app)
        app.mission = None
        app.table = None
        if value[0] == 'back':
            restoreStash(app)
            return
        if value[0] == 'part':
            openPartSheet(app, value[1])
            return
        # (a remembered circuit stays remembered: Open > Back to ...)
        if value[0] == 'reference':
            openCircuit(app, makeReferenceMachine())
            say(app, 'Opened the lecture machine')
        elif value[0] == 'empty':
            openCircuit(app, makeCircuit('untitled'))
            say(app, 'A blank canvas. Pick parts from the palette.')
        else:
            openFile(app, value[1])
    elif kind == 'mission':
        startMission(app, value)
    elif kind == 'preset':
        pickPreset(app, value)
    elif kind == 'verify':
        runVerify(app, value)


######################################################################
# Missions
######################################################################

def startMission(app, missionId):
    if app.mode == 'run':
        enterBuild(app)
    app.table = None
    if missionId == None:
        app.mission = None
        if not restoreStash(app):
            say(app, 'Free building')
        return
    mission = dict(zb_missions.getMission(missionId))
    mission['allowed'] = zb_missions.allowedTypes(mission, app.library)
    stashRoot(app)                     # Leave missions brings it back
    openCircuit(app, zb_missions.startCircuit(mission))
    app.mission = mission
    say(app, f"Mission {mission['number']}: {mission['title']}. The goal "
             'is in the side panel.')

def checkMission(app):
    mission = app.mission
    if mission == None:
        return
    detail = zb_missions.checkMissionDetail(app.library, mission, app.root)
    ok, message = detail['ok'], detail['message']
    if not ok:
        if detail['table'] != None:
            # straight onto a wrong row (or step) of the table
            selected = detail['failedRow']
            if selected == None:
                selected = detail['failedStep']
            openTableData(app, detail['table'], selected)
        problem = detail['problem']
        if problem != None:
            if problem.get('parts'):
                app.selection = {'parts': set(problem['parts']),
                                 'wires': set(problem.get('wires', [])),
                                 'junctions': set()}
            showExplanation(app, problem)
        return say(app, message, 'error')
    app.missionProgress[mission['id']] = True
    zb_missions.saveProgress(PARTS_DIR, app.missionProgress)
    name = zb_missions.rewardPart(app.library, mission, app.root, PARTS_DIR)
    if name != None:
        message += f'  "{name}" is now in My parts (verified).'
    say(app, message, 'good')


######################################################################
# Buttons and actions
######################################################################

def isButtonEnabled(app, action):
    if app.mode == 'build':
        if action == 'undo':
            return len(app.undo) > 0
        if action == 'redo':
            return len(app.redo) > 0
        if action in ['delete', 'pack']:
            selection = app.selection
            count = (len(selection['parts']) + len(selection['wires']) +
                     len(selection['junctions']))
            return isEditable(app) and count > 0
        if action in ['newPart', 'tidy']:
            return isEditable(app)
    if action == 'inside':
        return getSelectedPart(app) != None
    if action == 'up':
        return len(app.path) > runBase(app)
    if app.mode == 'run' and app.logicMode and action in [
            'back', 'wave', 'phase', 'step', 'end', 'program', 'check']:
        return False                   # no clock: nothing to step
    if app.mode == 'run' and app.logicMode and action == 'run':
        return True                    # Run plays the truth table
    if app.mode == 'run':
        if action in ['wave', 'phase', 'step', 'end']:
            return canRun(app) or app.stage == WAVES
        if action == 'run':
            return canPause(app) or app.frozen or canRun(app)
        if action == 'back':
            return app.sim['halfCycles'] > 0 or app.stage == WAVES
    return True

def isButtonOn(app, action):
    return ((action == 'lanes' and app.bitLanes) or
            (action == 'help' and app.showHelp) or
            (action == 'grid' and app.showGrid[app.mode]) or
            (action == 'highlight' and app.netHighlight) or
            (action == 'check' and app.checkOn and app.checker != None) or
            (action == 'missions' and app.mission != None) or
            (action == 'table' and app.table != None) or
            (action == 'run' and (canPause(app) or app.frozen)))

def tablePlaying(app):
    return app.table != None and app.table['playing']

def getButtonLabel(app, button):
    # Run turns into Pause while anything moves, and Resume when paused
    action = button['action']
    if action == 'run' and app.mode == 'run':
        if app.frozen:
            return 'Resume'
        if canPause(app):
            return 'Pause'
    if action == 'format':
        return app.numFormat
    return button['label']

def toggleGrid(app):
    # g / Grid: the grid of this mode (Build and Run each keep their own)
    app.showGrid[app.mode] = not app.showGrid[app.mode]
    say(app, 'Grid ' + ('on' if app.showGrid[app.mode] else 'off'))

def toggleHighlight(app):
    # i / Highlight: does hovering a wire light up its whole net?
    app.netHighlight = not app.netHighlight
    app.hoverNet = None
    app.hoverPart = None
    say(app, 'Net highlight on hover: ' + ('on' if app.netHighlight else
                                           'off'))

def doAction(app, action):
    if action == 'mode':
        switchMode(app)
    elif action == 'undo':
        undo(app)
    elif action == 'redo':
        redo(app)
    elif action == 'delete':
        deleteSelection(app)
    elif action == 'inside':
        lookInside(app)
    elif action == 'up':
        drillOut(app)
    elif action == 'pack':
        askPack(app)
    elif action == 'newPart':
        askNewPart(app)
    elif action == 'fit':
        getCam(app)
        fitView(app)
    elif action == 'grid':
        toggleGrid(app)
    elif action == 'highlight':
        toggleHighlight(app)
    elif action == 'new':
        pick(app, 'open', ('empty',))
    elif action == 'open':
        openCircuitPicker(app)
    elif action == 'save':
        askSave(app)
    elif action == 'missions':
        openMissionPicker(app)
    elif action == 'help':
        app.showHelp = not app.showHelp
    elif action == 'back':
        stepBack(app)
    elif action == 'wave':
        nextWave(app)
    elif action == 'phase':
        nextPhase(app)
    elif action == 'step':
        nextInstruction(app)
    elif action == 'run':
        if app.logicMode:
            playTable(app)
        else:
            toggleRun(app)
    elif action == 'end':
        runToEnd(app)
    elif action == 'reset':
        if app.logicMode:
            resetPins(app)
        else:
            resetRun(app)
    elif action == 'program':
        openProgramPicker(app)
    elif action == 'lanes':
        app.bitLanes = not app.bitLanes
    elif action == 'format':
        index = NUM_FORMATS.index(app.numFormat)
        app.numFormat = NUM_FORMATS[(index + 1) % len(NUM_FORMATS)]
    elif action == 'check':
        toggleCheck(app)
    elif action == 'tidy':
        tidy(app, time.time())
    elif action == 'table':
        if app.table != None:
            closeTable(app)
        else:
            openTable(app)

def ask(app, prompt):
    # A typed answer, or None if it was left empty
    text = app.getTextInput(prompt)
    if text == None or text.strip() == '':
        return None
    return text.strip()

def goToLevel(app, depth):
    # A click on the breadcrumb: up to that level
    if depth >= len(app.path):
        return
    if depth < runBase(app):
        return say(app, soloMessage(app))
    app.path = app.path[:depth]
    app.selection = emptySelection()
    cancelTool(app)
    refreshView(app)
    getCam(app)

def lookInside(app):
    part = getSelectedPart(app)
    if part == None:
        return say(app, 'Select a part first')
    drillIn(app, part['id'])

def askPack(app):
    if len(app.selection['parts']) == 0:
        return say(app, 'Select the parts to pack first (box-drag or '
                        'shift-click)')
    name = ask(app, 'Name for the new part (it goes in My parts):')
    if name != None:
        packInto(app, name)

def askNewPart(app):
    name = ask(app, 'Name for the new part (you build its inside next):')
    if name != None:
        newUserPart(app, name)

def askSave(app):
    name = ask(app, 'Save as circuits/NAME.json. NAME:')
    if name != None:
        saveAs(app, name)

def askCopyRecipe(app):
    if not app.view['readOnly']:
        return say(app, 'Open (Enter) a built-in part first: c copies its '
                        'recipe')
    name = ask(app, 'Name for your editable copy:')
    if name != None:
        copyRecipe(app, name)

def askSize(app, definition=None):
    # s: type the size of your part's box ('120 x 80', or 'auto')
    if definition == None:
        definition = currentUserPart(app)
    if definition == None:
        return say(app, 'Select one of your parts (or open it) first: s '
                        'sets the size of its box')
    (width, height), smallest = partBoxSize(app, definition)
    text = app.getTextInput(f"Size of {definition['name']} (now {width} x "
                            f'{height}; at least {smallest[0]} x '
                            f'{smallest[1]}). Type like 140 x 100, or '
                            'auto:')
    if text == None:
        return
    size = parseSize(text)
    if size == None:
        return say(app, f"'{text}' is not a size: type it like 140 x 100",
                   'error')
    setPartSize(app, definition, *size)

def askVerify(app):
    # A list of the built-ins to check against: the ones whose ports
    # match your part's pins on the left, the others (and what differs)
    # on the right
    from zb_library import STATEFUL_MESSAGE
    from zb_editor import partToVerify, verifyChoices
    definition = partToVerify(app)
    if definition == None:
        return say(app, 'Select one of your parts (or open it) to verify')
    if definition['stateful']:
        return say(app, STATEFUL_MESSAGE, 'error')
    choices = verifyChoices(app, definition)
    left = [('Your pins match', '', ('heading',))]
    right = [('Pins differ (rename or add pins first)', '', ('heading',))]
    for typeName, matches, note in choices:
        label = typeName
        if PRIMITIVES[typeName]['label'] != typeName:
            label += f"  ({PRIMITIVES[typeName]['label']})"
        (left if matches else right).append((label, note, typeName))
    if len(left) == 1:
        left.append(('(none yet)', 'Name your IN / OUT pins like a '
                     "built-in's ports", ('heading',)))
    rows = max(4, min(MAX_PICKER_ROWS, max(len(left), len(right))))
    left, right = left[:rows], right[:rows]
    left += [('', '', ('heading',))] * (rows - len(left))
    app.picker = {'title': f"Verify {definition['name']} against a "
                           'built-in part', 'items': left + right,
                  'kind': 'verify', 'perColumn': rows}

def runVerify(app, target):
    verifyCurrent(app, target)
    result = app.verifyResult
    if result != None and (result.get('mismatch') != None or
                           not result.get('ok')):
        app.showVerify = True          # the result, as a table

def askParam(app, part, key):
    # Types a new value for a parameter; returns an error message or None
    now = paramText(part['params'][key], part['type'], key)
    hint = ''
    if part['type'] == 'SPLIT' and key == 'ranges':
        hint = ' e.g. 7:4 3:0, or bits'
    elif part['type'] == 'MERGE' and key == 'widths':
        hint = ' e.g. 4 4, or 1x8'
    text = ask(app, f'{key} (now {now}){hint}:')
    if text == None:
        return None
    return setParam(app, part, key, text)

def openPresetPicker(app, part, key):
    # The menu of common SPLIT ranges (for this input width) or MERGE
    # widths, plus Custom... to type one
    if part['type'] == 'SPLIT':
        presets = rangePresets(part['params']['width'])
        describe = lambda value: f'outputs: {formatRanges(value)}'
    else:
        presets = widthPresets()
        describe = lambda value: f'inputs: {formatWidths(value)} ' \
                                 f'({sum(value)} bits out)'
    items = []
    for label, value in presets[:MAX_PICKER_ROWS - 1]:
        items.append((label, describe(value), ('set', part['id'], key,
                                               value)))
    now = paramText(part['params'][key], part['type'], key)
    items.append(('Custom...', f'type it (now {now})',
                  ('custom', part['id'], key)))
    app.picker = {'title': f"{part['type']} {key}", 'items': items,
                  'kind': 'preset'}

def pickPreset(app, value):
    part = findPart(getCircuit(app), value[1])
    if part == None:
        return
    key = value[2]
    if value[0] == 'custom':
        message = askParam(app, part, key)
    else:
        text = (formatRanges(value[3]) if part['type'] == 'SPLIT' else
                formatWidths(value[3]))
        message = setParam(app, part, key, text)
        if message == None:
            say(app, f'{key}: {text}')
    if message != None:
        say(app, message, 'error')

def doSideAction(app, action):
    kind = action[0]
    circuit = getCircuit(app)
    if kind == 'closeExplain':
        app.explain = None
        app.explainParts = set()
        return
    if kind == 'missionCheck':
        return checkMission(app)
    if kind == 'verify':
        return askVerify(app)
    if kind in ['size', 'autoSize', 'grow', 'portSide', 'portUp',
                'portName']:
        definition = app.library['user'].get(action[1])
        if definition == None:
            return
        if app.mode != 'build':
            return say(app, readOnlyMessage(app))
        if kind == 'size':
            return askSize(app, definition)
        if kind == 'autoSize':
            return setPartSize(app, definition, None, None)
        if kind == 'grow':
            return growPart(app, definition, action[2], action[3])
        if kind == 'portSide':
            return cyclePortSide(app, definition, action[2])
        if kind == 'portName':
            text = app.getTextInput(f'New name for port {action[2]} '
                                    '(letters, digits, _):')
            return renamePort(app, definition, action[2], text)
        return movePortEarlier(app, definition, action[2])
    if kind in ['wireColor', 'wireLamp']:
        from zb_circuit import findWire
        wire = findWire(circuit, action[1])
        if wire == None:
            return
        if not isEditable(app):
            return say(app, readOnlyMessage(app))
        if kind == 'wireColor':
            return cycleWireColor(app, wire)
        text = app.getTextInput('Lamp name for the control strip (empty: '
                                'no lamp):')
        return setLamp(app, wire, text or '')
    part = findPart(circuit, action[1])
    if part == None:
        return
    message = None
    if kind == 'label':
        text = app.getTextInput(f"Label for this {part['type']} (empty: "
                                'none):')
        message = setLabel(app, part, text or '')
    elif kind == 'param':
        key = action[2]
        if (part['type'], key) in [('SPLIT', 'ranges'), ('MERGE', 'widths')]:
            if not isEditable(app):
                return say(app, readOnlyMessage(app))
            return openPresetPicker(app, part, key)
        message = askParam(app, part, key)
    elif kind == 'step':
        message = stepParam(app, part, action[2], action[3])
    elif kind == 'cycle':
        message = cycleParam(app, part, action[2])
    elif kind == 'tag':
        cycleTag(app, part)
    elif kind == 'mode':
        toggleMode(app, part)
    if message != None:
        say(app, message, 'error')


######################################################################
# Events: mouse
######################################################################

def onMousePress(app, mouseX, mouseY, button=0):
    # The mouse comes in screen pixels; the layout uses design units
    x, y = toDesign(mouseX, mouseY)
    app.mouseX, app.mouseY = x, y
    mousePress(app, x, y, button)
    afterEvent(app)

def afterEvent(app):
    syncProblems(app)
    syncDifferencePart(app)

def mousePress(app, x, y, button):
    if app.showHelp:
        app.showHelp = False
        return
    if app.showVerify:
        app.showVerify = False
        return
    if app.picker != None:
        clickPicker(app, x, y)
        return
    if app.table != None and button == 0 and clickTable(app, x, y):
        return
    if button in [1, 2]:
        if inCanvas(app, x, y):
            app.drag = {'kind': 'pan', 'last': (x, y)}
        return
    rects = crumbRects(app)
    for k in range(len(rects) - 1):        # (the last one is here)
        if pointInRect(x, y, *rects[k][1]):
            return goToLevel(app, crumbLevel(app, k))
    for b in app.buttons[app.mode]:
        if pointInRect(x, y, b['left'], b['top'], b['width'], b['height']):
            if isButtonEnabled(app, b['action']):
                doAction(app, b['action'])
            return
    if app.mode == 'run':
        if pointInRect(x, y, *app.layout['programName']) and \
                not app.logicMode:
            return openProgramPicker(app)
        if clickTimeline(app, x, y):
            return
    elif pointInRect(x, y, *PALETTE_RECT):
        return clickPalette(app, x, y)
    if pointInRect(x, y, *SIDE):
        return clickSide(app, x, y)
    if app.mode == 'build' and pointInRect(x, y, *BOTTOM):
        return clickBottom(app, x, y)
    if inCanvas(app, x, y):
        if app.mode == 'build':
            pressBuildCanvas(app, x, y)
        else:
            pressRunCanvas(app, x, y)

def clickTimeline(app, x, y):
    if not pointInRect(x, y, *TIMELINE):
        return False
    if x < TRACK_LEFT - 10:
        promptForStep(app)
    elif x <= TRACK_RIGHT + 10:
        app.drag = {'kind': 'timeline'}
        dragTimeline(app, x)
    return True

def clickPalette(app, x, y):
    for i in range(4):
        if pointInRect(x, y, *paletteTabRect(i)):
            app.paletteTab = i
            return
    items = paletteItems(app)
    for i in range(len(items)):
        typeName, label, allowed = items[i]
        if pointInRect(x, y, *paletteRowRect(i)):
            if not allowed:
                say(app, 'This mission asks you to build it from other '
                         'parts', 'error')
            elif app.tool == 'place' and app.placeType == typeName:
                cancelTool(app)
            else:
                startPlacing(app, typeName)
            return

def clickSide(app, x, y):
    rows = getPropertyRows(app)
    for i in range(len(rows)):
        buttons = rows[i].get('buttons', [])
        for (label, action), rect in zip(buttons,
                                         sideButtonRects(i, buttons)):
            if pointInRect(x, y, *rect):
                doSideAction(app, action)
                return
        if rows[i]['action'] != None and pointInRect(x, y,
                                                     *sideRowRect(i)):
            doSideAction(app, rows[i]['action'])
            return

def clickBottom(app, x, y):
    # A click on a warning selects its parts
    left, top, width, height = BOTTOM
    for i in range(min(3, len(app.problems))):
        lineY = top + 14 + 16 * i
        if lineY - 8 <= y <= lineY + 8:
            problem = app.problems[i]
            ids = set(problem['parts'])
            app.selection = {'parts': ids,
                             'wires': set(problem.get('wires', [])),
                             'junctions': set()}
            showExplanation(app, problem)
            return

def explainStop(app):
    # w in Run mode: why did it stop (or why does it differ from the
    # lecture machine)? The parts involved are marked.
    sim = app.sim
    detail = sim.get('stopDetail')
    if detail != None and (sim['halted'] or sim['begun']):
        parts = partsOnLevel(sim, detail.get('prims', []),
                             app.view['prefix']) if app.view['live'] else ()
        showExplanation(app, detail, parts)
        return
    if app.difference != None:
        showExplanation(app, {'level': 'error', 'code': 'golden',
                              'text': app.difference['message'],
                              'why': app.difference.get('why', []),
                              'fix': 'Compare the part with the lecture\'s '
                                     'wiring (z18100/z18100_cpu_spec.md).'},
                        [app.differencePart] if app.differencePart else ())
        return
    say(app, 'Nothing to explain yet: the machine has not stopped. Hover '
             'an x wire to see where it comes from.')

def isDoubleClick(app, key):
    now = time.time()
    last = app.lastClick
    app.lastClick = (now, key)
    if last != None and last[1] == key and \
            now - last[0] < DOUBLE_CLICK_SECONDS:
        app.lastClick = None
        return True
    return False

def selectOnly(app, partId):
    app.selection = {'parts': {partId}, 'wires': set(), 'junctions': set()}

def pressBuildCanvas(app, x, y):
    shift = shiftIsDown()
    if app.tool == 'place':
        placeAt(app, x, y, keepPlacing=shift)   # shift: place more
        return
    hit = hitTest(app, x, y)
    if app.tool == 'bus':
        if hit['kind'] == 'port':
            busConnect(app, hit['end'])
        else:
            cancelTool(app)
            say(app, 'Stopped wiring bits')
        return
    if app.tool == 'wire':
        if hit['kind'] in ['port', 'junction', 'wire']:
            finishWire(app, hit)
        else:
            addBend(app, x, y)
        return
    if hit['kind'] in ['port', 'junction'] and not isEditable(app):
        hit = {'kind': 'part', 'part': hit['part']} if \
            hit['kind'] == 'port' else {'kind': None}
    if hit['kind'] in ['port', 'junction']:
        startWire(app, hit['end'])
        app.drag = {'kind': 'wire', 'start': (x, y)}
        return
    if hit['kind'] == 'part':
        partId = hit['part']
        if isDoubleClick(app, partId):
            drillIn(app, partId)
            return
        if shift:
            app.selection['parts'] ^= {partId}
            return
        if partId not in app.selection['parts']:
            selectOnly(app, partId)
        if isEditable(app):
            startMove(app, x, y)
        return
    if hit['kind'] == 'wire':
        if shift:
            app.selection['wires'] ^= {hit['wire']}
        else:
            app.selection = {'parts': set(), 'wires': {hit['wire']},
                             'junctions': set()}
        return
    if not shift:
        app.selection = emptySelection()
    world = toWorld(app, x, y)
    app.drag = {'kind': 'box', 'start': world, 'end': world, 'add': shift}

def pressRunCanvas(app, x, y):
    hit = hitTest(app, x, y, wantWires=False)
    if hit['kind'] == 'port':
        hit = {'kind': 'part', 'part': hit['part']}
    if hit['kind'] != 'part':
        app.selection = emptySelection()
        app.drag = {'kind': 'pan', 'last': (x, y)}
        return
    part = findPart(getCircuit(app), hit['part'])
    prim = getPrim(app, part)
    live = app.view['live'] and prim != None
    if part['type'] == 'RAM' and live and clickRAM(app, part, prim, x, y):
        selectOnly(app, part['id'])
        return
    if part['type'] == 'PIN_IN' and live:
        selectOnly(app, part['id'])
        setPin(app, part, prim)
        return
    if isDoubleClick(app, part['id']):
        drillIn(app, part['id'])
        return
    selectOnly(app, part['id'])

def clickRAM(app, part, prim, x, y):
    # A bit flips; shift-click (or the left edge) sets a breakpoint.
    # Returns True if the click was used.
    worldX, worldY = toWorld(app, x, y)
    address = ramRowAt(app, part, worldX, worldY)
    if address == None:
        return False
    if shiftIsDown() or worldX < part['x'] + 30:
        if prim is findProgramRAM(app.sim):
            toggleBreakpoint(app, address)
        return True
    bit = ramBitAt(app, part, worldX)
    if bit == None:
        return False
    flipRamBit(app, prim, address, bit)
    return True

def onMouseDrag(app, mouseX, mouseY):
    x, y = toDesign(mouseX, mouseY)
    app.mouseX, app.mouseY = x, y
    app.mouseInCanvas = inCanvas(app, x, y)
    drag = app.drag
    if drag == None:
        return
    if drag['kind'] == 'pan':
        lastX, lastY = drag['last']
        panBy(app, x - lastX, y - lastY)
        drag['last'] = (x, y)
    elif drag['kind'] == 'move':
        dragMove(app, x, y)
    elif drag['kind'] == 'box':
        drag['end'] = toWorld(app, x, y)
    elif drag['kind'] == 'timeline':
        dragTimeline(app, x)

def onMouseRelease(app, mouseX, mouseY):
    x, y = toDesign(mouseX, mouseY)
    drag = app.drag
    if drag == None:
        return
    if drag['kind'] == 'move':
        endDrag(app)
    else:
        app.drag = None
    if drag['kind'] == 'box':
        (x1, y1), (x2, y2) = drag['start'], drag['end']
        if abs(x2 - x1) + abs(y2 - y1) > 4:
            selectBox(app, x1, y1, x2, y2, drag['add'])
    elif drag['kind'] == 'wire' and app.tool == 'wire':
        startX, startY = drag['start']
        if abs(x - startX) + abs(y - startY) > 6:
            hit = hitTest(app, x, y)
            if (hit['kind'] in ['port', 'junction', 'wire'] and
                hit.get('end') != app.wireStart):
                finishWire(app, hit)
    afterEvent(app)

def onMouseMove(app, mouseX, mouseY):
    x, y = toDesign(mouseX, mouseY)
    app.mouseX, app.mouseY = x, y
    app.mouseInCanvas = inCanvas(app, x, y) and app.picker == None
    app.hoverWire = None
    app.hoverPort = None
    app.hoverNet = None
    app.hoverPart = None
    app.paletteHover = None
    if app.mode == 'build' and app.picker == None and \
            pointInRect(x, y, *PALETTE_RECT):
        items = paletteItems(app)
        for i in range(len(items)):
            if pointInRect(x, y, *paletteRowRect(i)):
                app.paletteHover = (items[i][0], i)
        return
    if not app.mouseInCanvas or app.showHelp:
        return
    hit = hitTest(app, x, y)
    nets = getLevelInfo(app)['nets']
    if hit['kind'] == 'port':
        app.hoverPort = (hit['part'], hit['port'])
        app.hoverWire = wireOnPortNet(app, hit['part'], hit['port'])
        if app.hoverWire != None:      # (a lone port lights nothing)
            app.hoverNet = nets['nodeNet'].get(('port', hit['part'],
                                                hit['port']))
    elif hit['kind'] == 'junction':
        app.hoverNet = nets['nodeNet'].get(('junction', hit['junction']))
    elif hit['kind'] == 'wire':
        app.hoverWire = hit['wire']
        app.hoverNet = nets['wireNet'].get(hit['wire'])
    elif hit['kind'] == 'part':
        app.hoverPart = hit['part']    # its wires and neighbours light up

def wireOnPortNet(app, partId, portName):
    # A wire on the port's net (so hovering a port shows its value)
    info = getLevelInfo(app)
    netIndex = info['nets']['nodeNet'].get(('port', partId, portName))
    for wireId, index in info['nets']['wireNet'].items():
        if index == netIndex:
            return wireId
    return None


######################################################################
# Events: keys and frames
######################################################################

def onKeyPress(app, key, modifiers):
    ctrl = 'control' in modifiers or 'meta' in modifiers
    keyPress(app, key, ctrl)
    afterEvent(app)

def keyPress(app, key, ctrl):
    lower = key.lower() if len(key) == 1 else key
    if key == '?':
        app.showHelp = not app.showHelp
        return
    if app.showHelp or app.showVerify:
        app.showHelp = False
        app.showVerify = False
        return
    if app.picker != None:
        if key == 'escape':
            app.picker = None
        return
    if app.table != None and not ctrl and tableKey(app, key, lower):
        return
    if ctrl:
        return controlKey(app, lower)
    if key == 'tab':
        return switchMode(app)
    if lower == 'u':
        return openTable(app)
    arrows = {'left': (PAN_STEP, 0), 'right': (-PAN_STEP, 0),
              'up': (0, PAN_STEP), 'down': (0, -PAN_STEP)}
    if key in arrows:
        return panBy(app, *arrows[key])
    if lower == 'f':
        getCam(app)
        return fitView(app)
    if lower == 'g':
        return toggleGrid(app)
    if lower == 'i':
        return toggleHighlight(app)
    if key == 'enter':
        return lookInside(app)
    if key == 'escape':
        return escape(app)
    if app.mode == 'build':
        buildKey(app, key, lower)
    else:
        runKey(app, key, lower)

def controlKey(app, lower):
    if lower in ['=', '+']:
        zoomStep(app, +1)
    elif lower in ['-', '_']:
        zoomStep(app, -1)
    elif lower == 'o':
        openCircuitPicker(app)
    elif lower == 's':
        if app.fileName != None and app.mission == None:
            saveAs(app, app.fileName)          # back where it came from
        else:
            askSave(app)
    elif app.mode != 'build':
        say(app, 'Press Tab to go back to Build mode to edit')
    elif lower == 'z':
        undo(app)
    elif lower == 'y':
        redo(app)
    elif lower == 'c':
        copySelection(app)
    elif lower == 'v':
        paste(app)
    elif lower == 'd':
        duplicate(app)
    elif lower == 'n':
        pick(app, 'open', ('empty',))

def escape(app):
    # Cancels the tool, then clears the selection, then goes up a level
    if app.tool != None:
        cancelTool(app)
        return
    if app.explain != None:
        app.explain = None
        app.explainParts = set()
        return
    app.drag = None
    selection = app.selection
    if len(selection['parts']) + len(selection['wires']) + \
            len(selection['junctions']) > 0:
        app.selection = emptySelection()
        return
    drillOut(app)

def buildKey(app, key, lower):
    if app.tool == 'bus' and key.isdigit():
        return pickBusBit(app, int(key))
    if key in ['delete', 'backspace']:
        deleteSelection(app)
    elif key in ['+', '=']:
        zoomStep(app, +1)
    elif key in ['-', '_']:
        zoomStep(app, -1)
    elif lower == 'r':
        if app.lastPlaced == None:
            say(app, 'Place a part from the palette first')
        else:
            startPlacing(app, app.lastPlaced)
    elif lower == 'p':
        askPack(app)
    elif lower == 'c':
        askCopyRecipe(app)
    elif lower == 't':
        part = getSelectedPart(app)
        if part == None:
            say(app, 'Select a register, IR, PC, Flags or RAM to tag')
        else:
            cycleTag(app, part)
    elif lower == 's':
        askSize(app)
    elif key in ['[', ']']:
        part = getSelectedPart(app)
        if part == None:
            return say(app, 'Select a part first: [ and ] change its '
                            'inputs (or its width)')
        key2 = 'inputs' if 'inputs' in part['params'] else 'width'
        if key2 not in part['params']:
            return say(app, f"{part['type']} has no inputs or width to "
                            'change')
        message = stepParam(app, part, key2, -1 if key == '[' else 1)
        if message != None:
            say(app, message, 'error')
    elif lower == 'm':
        openMissionPicker(app)
    elif lower == 'w':
        tidy(app, time.time())

def runKey(app, key, lower):
    name = LOGIC_KEYS.get(key if key in LOGIC_KEYS else lower)
    if app.logicMode and name != None:
        return say(app, f'No CLOCK, so there is no {name} here (logic '
                        'mode). Click IN pins, or u for the truth table.')
    if app.logicMode and key == '0':
        return resetPins(app)
    if app.logicMode and (lower == 'r' or key == 'space'):
        return playTable(app)          # run = play the truth table
    if lower == 'n':
        nextWave(app)
    elif lower == 'p':
        nextPhase(app)
    elif key == 'space':
        nextInstruction(app)
    elif lower == 'r':
        toggleRun(app)
    elif lower == 'e':
        runToEnd(app)
    elif key == 'backspace':
        stepBack(app)
    elif lower == 'j':
        promptForStep(app)
    elif key == '0':
        resetRun(app)
    elif lower == 'l':
        openProgramPicker(app)
    elif key in ['+', '=']:
        changeAnimLevel(app, +1)
    elif key in ['-', '_']:
        changeAnimLevel(app, -1)
    elif lower == 'h':
        doAction(app, 'format')
    elif lower == 'b':
        app.bitLanes = not app.bitLanes
    elif lower == 'k':
        toggleCheck(app)
    elif lower == 'w':
        explainStop(app)

def onStep(app):
    animate(app)
    stepTablePlay(app)
    if app.bench != None:
        benchStep(app)

def onResize(app):
    # The window was resized: the layout keeps its shape and is scaled to
    # fit, centered (zb_paint.fitWindow); the mouse follows the same scale
    fitWindow(app)

def onPygameEvent(event, callUserFn, app):
    # cmu_graphics hands every raw pygame event to receivers of its
    # pygameEvent signal. Its own handlers have no mouse wheel, so the
    # wheel is caught here: it zooms around the mouse. (The change shows
    # at the next onStep redraw, a frame later.)
    if event.type != PYGAME.MOUSEWHEEL or event.y == 0:
        return
    if app.picker != None or app.showHelp or app.showVerify:
        return
    x, y = PYGAME.mouse.get_pos()
    x, y = toDesign(x, y)
    if app.table != None and (not app.table['docked'] or
                              pointInRect(x, y, *SIDE)):
        scrollTable(app, -3 * event.y)
        return
    if inCanvas(app, x, y):
        zoomStep(app, 1 if event.y > 0 else -1, x, y)

# Set ZB_BENCH=1 to time the app: it runs the lecture machine for a few
# seconds, prints the frame times and quits
BENCH_FRAMES = 240

def benchStep(app):
    bench = app.bench
    now = time.perf_counter()
    shot = os.environ.get('ZB_SHOT')
    if shot:
        # Runs the program to the end and saves the window (to compare the
        # drawing backends on the same picture)
        if bench['frame'] == 0:
            if app.mode != 'run':
                enterRun(app)
            runToEnd(app)
        elif bench['frame'] == 10:
            app._app.getScreenshot(shot)
            app.quit()
        bench['frame'] += 1
        return
    if bench['frame'] == 0:
        if app.mode != 'run':
            enterRun(app)
        toggleRun(app)
        if os.environ.get('ZB_PROFILE'):
            import cProfile
            bench['profile'] = cProfile.Profile()
            bench['profile'].enable()
    elif bench['last'] != None:
        bench['gaps'].append(now - bench['last'])
    bench['last'] = now
    bench['frame'] += 1
    if bench['frame'] > BENCH_FRAMES:
        gaps = sorted(bench['gaps'][10:])
        average = sum(gaps) / len(gaps)
        print(f"frames {len(gaps)}: average {1000 * average:.1f} ms "
              f"({1 / average:.0f} fps), median "
              f"{1000 * gaps[len(gaps) // 2]:.1f} ms, worst "
              f"{1000 * gaps[-1]:.1f} ms, redrawAll "
              f"{1000 * bench['draw'] / max(1, bench['draws']):.1f} ms")
        if 'profile' in bench:
            import pstats
            bench['profile'].disable()
            pstats.Stats(bench['profile']).sort_stats('tottime').print_stats(
                int(os.environ['ZB_PROFILE']))
        app.quit()


######################################################################
# View
######################################################################

def redrawAll(app):
    start = time.perf_counter()
    beginFrame(app)
    drawApp(app)
    if app.showVerify:
        drawVerify(app)
    endFrame(app)
    if app.bench != None:
        app.bench['draw'] += time.perf_counter() - start
        app.bench['draws'] += 1

def main():
    pygameEvent.connect(onPygameEvent)
    width, height = startSize()
    runApp(width=width, height=height)

if __name__ == '__main__':
    main()

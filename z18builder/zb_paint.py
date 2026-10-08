# zb_paint.py
# Every picture the builder draws goes through the five functions here.
# They take design units and stay sharp on scaled displays, and they are
# the only way anything is drawn, so zb_view.py never calls the graphics
# library directly, and swapping the library means changing only this file.
#
# Two backends draw the same picture:
#   'fast'    (the default) draws with cmu_graphics's own renderer (wyvern,
#             a Cairo-like canvas) into one offscreen picture per frame,
#             then shows it with a single drawImage. cmu_graphics makes an
#             object for every drawRect / drawLabel, which is what made
#             frames slow; this skips that.
#   'shapes'  the ordinary drawRect, drawLine, ... calls.
# Set the environment variable ZB_DRAW=shapes to use plain calls. If the
# fast path fails (say a future cmu_graphics changes its renderer), it
# prints why and switches to 'shapes' for the rest of the run.
#
# The window can be resized. The layout is always the same DESIGN_WIDTH x
# DESIGN_HEIGHT design units: it is scaled to the largest size that fits
# the window with the same shape (16:9), centered, with dark
# bars filling the rest. The mouse goes back through the same scale
# (toDesign), so clicks land where the picture is.
#
# Use: beginFrame(app) at the start of redrawAll, endFrame() at the end,
# fitWindow(app) in onResize, toDesign(x, y) for the mouse.

import os
import math
import importlib
from cmu_graphics import *
from zb_helpers import (SCALE as SCREEN_SCALE, DESIGN_WIDTH, DESIGN_HEIGHT,
                        MIN_SCALE, BAR_COLOR, startSize)

# Screen pixels per design unit, and where the picture's top-left corner
# is in the window. It starts as the display scaling (zb_helpers.SCALE).
view = {'scale': SCREEN_SCALE, 'left': 0, 'top': 0, 'window': None}

def fitWindow(app):
    # Works out the scale and position for the window's current size
    size = (int(app.width), int(app.height))
    if view['window'] == size:
        return
    width, height = size
    scale = max(MIN_SCALE, min(width / DESIGN_WIDTH, height / DESIGN_HEIGHT))
    view['scale'] = scale
    view['left'] = max(0, rounded((width - DESIGN_WIDTH * scale) / 2))
    view['top'] = max(0, rounded((height - DESIGN_HEIGHT * scale) / 2))
    view['window'] = size

def getScale():
    return view['scale']

def onePixel():
    # One screen pixel, in design units
    return 1 / view['scale']

def toDesign(x, y):
    # A point in the window (screen pixels) -> design units
    return ((x - view['left']) / view['scale'],
            (y - view['top']) / view['scale'])

def pxX(value):
    # A design-unit x -> a whole screen pixel
    return math.floor(value * view['scale'] + 0.5) + view['left']

def pxY(value):
    return math.floor(value * view['scale'] + 0.5) + view['top']

def widthPx(width):
    return max(1, math.floor(width * view['scale'] + 0.5))

BACKEND = os.environ.get('ZB_DRAW', 'fast')
FONT_CACHE_SIZE = 4000

# The frame being drawn: {'surface', 'ctx', 'width', 'height'} or None
frame = None
state = {'backend': BACKEND, 'surface': None, 'size': None, 'image': None,
         'wyvern': None, 'shapeLogic': None, 'extents': dict()}


######################################################################
# Starting and finishing a frame
######################################################################

def loadRenderer():
    # cmu_graphics's renderer and its image cache, or None if not found
    if state['wyvern'] == None:
        helpers = importlib.import_module('cmu_graphics.deps')
        state['wyvern'] = helpers.wyvern
        state['shapeLogic'] = importlib.import_module(
            'cmu_graphics.shape_logic')
    return state['wyvern']

def useFast():
    return state['backend'] == 'fast'

def speedUpScreenCopy():
    # At the end of every frame cmu_graphics copies its picture to the
    # window as an RGBA image, and pygame alpha-blends every pixel of it
    # (about 13 ms for this window). The picture is opaque, so reading it
    # as RGBX (alpha ignored) gives the same pixels as a plain copy (under
    # 1 ms). This wraps cmu's own redraw to do that; it is part of 'fast'.
    try:
        module = importlib.import_module('cmu_graphics.cmu_graphics')
        App = module.App
        if getattr(App.redrawAll, 'zbFast', False):
            return
        original = App.redrawAll
        image = module.pygame.image
        realFrombuffer = image.frombuffer

        def opaqueFrombuffer(data, size, fmt, *args):
            if fmt == 'RGBA':
                fmt = 'RGBX'
            return realFrombuffer(data, size, fmt, *args)

        def redrawAll(self, screen, wyvernSurface, ctx):
            image.frombuffer = opaqueFrombuffer
            try:
                return original(self, screen, wyvernSurface, ctx)
            finally:
                image.frombuffer = realFrombuffer

        redrawAll.zbFast = True
        App.redrawAll = redrawAll
    except Exception as error:
        print(f'zb_paint: could not speed up the screen copy ({error!r})')

if BACKEND == 'fast':
    speedUpScreenCopy()

def fallBack(error):
    global frame
    print(f'zb_paint: fast drawing failed ({error!r}); using plain '
          'cmu_graphics shapes from now on')
    state['backend'] = 'shapes'
    frame = None

def beginFrame(app):
    # Starts a frame the size of the window, with the bars painted
    global frame
    frame = None
    fitWindow(app)
    size = (int(app.width), int(app.height))
    if useFast():
        try:
            wyvern = loadRenderer()
            if state['size'] != size:
                state['surface'] = wyvern.ImageSurface(*size)
                state['size'] = size
            frame = {'ctx': state['surface'].canvas, 'width': size[0],
                     'height': size[1]}
        except Exception as error:
            fallBack(error)

def paintBars(size):
    # The window outside the picture (only there when the window's shape
    # differs from the layout's): a bar on each side that has one
    width, height = size
    left, top = view['left'], view['top']
    right = pxX(DESIGN_WIDTH)
    bottom = pxY(DESIGN_HEIGHT)
    bars = [(0, 0, left, height), (right, 0, width - right, height),
            (0, 0, width, top), (0, bottom, width, height - bottom)]
    for x, y, w, h in bars:
        if w <= 0 or h <= 0:
            continue
        if frame == None:
            drawRect(x, y, w, h, fill=BAR_COLOR)
        else:
            ctx = frame['ctx']
            ctx.new_path()
            ctx.rectangle(x, y, w, h)
            setColor(ctx, BAR_COLOR, 100)
            ctx.fill()

def endFrame(app):
    # Paints the bars last, so nothing drawn past the layout's edge shows,
    # then shows the offscreen picture as one image
    global frame
    paintBars((int(app.width), int(app.height)))
    if frame == None:
        return
    try:
        width, height = frame['width'], frame['height']
        wyvern = state['wyvern']
        # (.data is already a fresh copy of the pixels)
        picture = wyvern.WyvernImage(state['surface'].data, width, height,
                                     width * 4)
        if state['image'] == None:
            from PIL import Image
            state['image'] = CMUImage(Image.new('RGBA', (1, 1)))
        # cmu_graphics keeps each image's pixels in a cache keyed by the
        # image; replacing the entry shows this frame (and keeps memory
        # flat) without cmu's slow PIL conversion
        images = state['shapeLogic'].activeDrawing.images
        images[state['image'].uuid] = picture
        frame = None
        drawImage(state['image'], 0, 0)
    except Exception as error:
        fallBack(error)


######################################################################
# Colors and fonts (as cmu_graphics's own shapes do them)
######################################################################

def colorOf(color, opacity):
    # (b, g, r, a): cmu_graphics hands wyvern its colors in this order
    if isinstance(color, str):
        table = state['shapeLogic'].CSS3_COLORS_TO_RGB
        color = table[color.lower()]
    return (color.blue / 255, color.green / 255, color.red / 255,
            opacity / 100)

def setColor(ctx, color, opacity):
    ctx.set_source_rgba(*colorOf(color, opacity))

def fontOf(font, bold):
    wyvern = state['wyvern']
    return (state['shapeLogic'].getFont(font, bold, False)[0],
            wyvern.FontWeight.BOLD if bold else wyvern.FontWeight.NORMAL,
            wyvern.FontSlant.NORMAL)

def textExtents(ctx, text, size, font, bold):
    # Measuring text is slow-ish and labels repeat, so remember sizes
    key = (text, size, font, bold)
    cache = state['extents']
    if key not in cache:
        if len(cache) > FONT_CACHE_SIZE:
            cache.clear()
        cache[key] = ctx.text_extents(text)
    return cache[key]


######################################################################
# The five drawing functions (design units in)
######################################################################

def fillAndBorder(ctx, fill, border, borderWidth, opacity):
    # Fills the current path, then draws the border inside it (cmu_graphics
    # strokes twice as wide, clipped to the shape)
    if fill != None:
        setColor(ctx, fill, opacity)
        ctx.fill_preserve()
    if border != None and borderWidth > 0:
        ctx.save()
        ctx.clip_preserve()
        setColor(ctx, border, opacity)
        ctx.set_dash([])
        ctx.set_line_width(2 * borderWidth)
        ctx.stroke()
        ctx.restore()
    ctx.new_path()

# Each one takes design units. With the fast backend it draws on the
# offscreen picture; otherwise (frame is None) it makes the cmu_graphics
# shape, but through view's scale and position instead of a fixed scale.

def scaledRect(left, top, width, height, fill, border=None, borderWidth=2,
               opacity=100):
    # Round the edges (not the size) so rects that touch still touch
    x1, y1 = pxX(left), pxY(top)
    x2, y2 = pxX(left + width), pxY(top + height)
    if frame == None:
        drawRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1), fill=fill,
                 border=border, borderWidth=widthPx(borderWidth),
                 opacity=opacity)
        return
    ctx = frame['ctx']
    ctx.new_path()
    ctx.rectangle(x1, y1, max(1, x2 - x1), max(1, y2 - y1))
    fillAndBorder(ctx, fill, border, widthPx(borderWidth), opacity)

def scaledLine(x1, y1, x2, y2, fill, lineWidth=2, dashes=False, opacity=100):
    if fill == None:
        return
    width = widthPx(lineWidth)
    # A line of odd width is only sharp when centered on a pixel's middle
    shift = 0.5 if width % 2 == 1 else 0
    sx1, sy1 = pxX(x1) + shift, pxY(y1) + shift
    sx2, sy2 = pxX(x2) + shift, pxY(y2) + shift
    if frame == None:
        drawLine(sx1, sy1, sx2, sy2, fill=fill, lineWidth=width,
                 dashes=dashes, opacity=opacity)
        return
    ctx = frame['ctx']
    ctx.new_path()
    ctx.set_dash([5, 5] if dashes else [])
    setColor(ctx, fill, opacity)
    ctx.set_line_width(width)
    ctx.move_to(sx1, sy1)
    ctx.line_to(sx2, sy2)
    ctx.stroke()

def scaledCircle(x, y, radius, fill):
    scale = view['scale']
    cx, cy = x * scale + view['left'], y * scale + view['top']
    if frame == None:
        drawCircle(cx, cy, max(0.5, radius * scale), fill=fill)
        return
    ctx = frame['ctx']
    ctx.new_path()
    ctx.arc(cx, cy, radius * scale, 0, 2 * math.pi)
    ctx.close_path()
    fillAndBorder(ctx, fill, None, 0, 100)

def scaledPolygon(points, fill, border=None, borderWidth=2):
    # points is a flat list: [x1, y1, x2, y2, ...]
    screen = []
    for i in range(0, len(points), 2):
        screen += [pxX(points[i]), pxY(points[i + 1])]
    if frame == None:
        drawPolygon(*screen, fill=fill, border=border,
                    borderWidth=widthPx(borderWidth))
        return
    ctx = frame['ctx']
    ctx.new_path()
    ctx.move_to(screen[0], screen[1])
    for i in range(2, len(screen), 2):
        ctx.line_to(screen[i], screen[i + 1])
    ctx.close_path()
    fillAndBorder(ctx, fill, border, widthPx(borderWidth), 100)

def scaledLabel(text, x, y, size, fill, font, align, bold):
    # (x, y) is the middle of the text's left edge, center or right edge,
    # as for cmu_graphics's drawLabel
    text = str(text)
    size = rounded(size * view['scale'])
    if text == '' or size <= 0 or fill == None:
        return
    x = x * view['scale'] + view['left']
    y = y * view['scale'] + view['top']
    if frame == None:
        drawLabel(text, x, y, size=size, fill=fill, font=font, align=align,
                  bold=bold)
        return
    ctx = frame['ctx']
    ctx.select_font_face(*fontOf(font, bold))
    ctx.set_font_size(size)
    xBearing, yBearing, width, height, xAdvance, yAdvance = textExtents(
        ctx, text, size, font, bold)
    outerSpaces = text[0] == ' ' or text[-1] == ' '
    if outerSpaces:
        width = max(width, xAdvance)
    height = -yBearing
    if align == 'left':
        left = x
    elif align == 'right':
        left = x - width
    else:
        left = x - width / 2
    ctx.new_path()
    ctx.move_to(left - (0 if outerSpaces else xBearing), y + height / 2)
    ctx.text_path(text)
    setColor(ctx, fill, 100)
    ctx.fill()


######################################################################
# Clipping (so the canvas cannot draw over the panels)
######################################################################

def clipTo(left, top, width, height):
    # Until unclip(), only the rectangle (design units) is drawn on. With
    # plain shapes there is no clipping: the panels drawn afterwards cover
    # whatever sticks out.
    if frame == None:
        return
    ctx = frame['ctx']
    ctx.save()
    ctx.new_path()
    x1, y1 = pxX(left), pxY(top)
    ctx.rectangle(x1, y1, pxX(left + width) - x1, pxY(top + height) - y1)
    ctx.clip()
    ctx.new_path()

def unclip():
    if frame == None:
        return
    frame['ctx'].restore()

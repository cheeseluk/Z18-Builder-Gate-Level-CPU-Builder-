# zb_helpers.py
# The small pieces the builder used to borrow from the parent project:
#   - display scaling and the window's start size (was ../scaled_draw.py)
#   - polyline geometry for wires and packets (was ../datapath.py)
# No drawing in this file.

import ctypes
from cmu_graphics import *


######################################################################
# Display scaling
######################################################################

def getScreenScale():
    # 1.25 at 125% scaling, 1.5 at 150%, ... and 1 when not on Windows
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return ctypes.windll.user32.GetDpiForSystem() / 96
    except Exception:
        return 1

SCALE = getScreenScale()

# The layout is 1440 x 810 design units: 16:9, like most screens
DESIGN_WIDTH = 1440
DESIGN_HEIGHT = 810
MIN_SCALE = 0.25
BAR_COLOR = rgb(12, 13, 17)
SCREEN_FILL = (0.92, 0.85)      # most a new window takes of the screen

def startSize(designWidth=DESIGN_WIDTH, designHeight=DESIGN_HEIGHT):
    # (width, height) for runApp: the layout at the display's scale, or
    # smaller (same shape) if that would not fit on the screen
    width, height = designWidth * SCALE, designHeight * SCALE
    fit = 1
    try:
        user32 = ctypes.windll.user32
        screenWidth, screenHeight = (user32.GetSystemMetrics(0),
                                     user32.GetSystemMetrics(1))
        fit = min(1, SCREEN_FILL[0] * screenWidth / width,
                  SCREEN_FILL[1] * screenHeight / height)
    except Exception:
        pass
    return rounded(width * fit), rounded(height * fit)


######################################################################
# Geometry for moving packets along wires
######################################################################

def segmentLength(p, q):
    return ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5

def pathLength(points):
    total = 0
    for i in range(len(points) - 1):
        total += segmentLength(points[i], points[i + 1])
    return total

def pointAlongPath(points, t):
    # The point a fraction t (0 to 1) of the way along the polyline,
    # measured by length, so packets move at a steady speed round corners
    t = max(0, min(1, t))
    distanceLeft = t * pathLength(points)
    for i in range(len(points) - 1):
        p = points[i]
        q = points[i + 1]
        length = segmentLength(p, q)
        if length > 0 and distanceLeft <= length:
            fraction = distanceLeft / length
            return (p[0] + (q[0] - p[0]) * fraction,
                    p[1] + (q[1] - p[1]) * fraction)
        distanceLeft -= length
    return points[-1]

def pathUpTo(points, t):
    # The first part of the polyline, from its start to pointAlongPath(t)
    t = max(0, min(1, t))
    distanceLeft = t * pathLength(points)
    result = [points[0]]
    for i in range(len(points) - 1):
        length = segmentLength(points[i], points[i + 1])
        if distanceLeft < length:
            result.append(pointAlongPath([points[i], points[i + 1]],
                                         distanceLeft / length))
            return result
        result.append(points[i + 1])
        distanceLeft -= length
    return result

def distanceToSegment(x, y, p, q):
    # Distance from (x, y) to an axis-aligned segment p-q
    closestX = max(min(p[0], q[0]), min(x, max(p[0], q[0])))
    closestY = max(min(p[1], q[1]), min(y, max(p[1], q[1])))
    return segmentLength((x, y), (closestX, closestY))

def distanceToPath(points, x, y):
    best = None
    for i in range(len(points) - 1):
        d = distanceToSegment(x, y, points[i], points[i + 1])
        if best == None or d < best:
            best = d
    return best

def segmentNormal(p, q):
    # A unit vector at a right angle to the (horizontal or vertical) segment
    if q[0] == p[0]:
        if q[1] > p[1]:
            return (-1, 0)
        return (1, 0)
    if q[0] > p[0]:
        return (0, 1)
    return (0, -1)

def offsetPolyline(points, distance):
    # The same path shifted sideways by distance (used for bit lanes).
    # At a corner, both neighboring normals are added so lanes stay parallel.
    result = []
    last = len(points) - 1
    for i in range(len(points)):
        nx, ny = 0, 0
        normals = []
        if i > 0:
            normals.append(segmentNormal(points[i - 1], points[i]))
        if i < last:
            normal = segmentNormal(points[i], points[i + 1])
            if len(normals) == 0 or normals[0] != normal:
                normals.append(normal)
        for normal in normals:
            nx += normal[0]
            ny += normal[1]
        result.append((points[i][0] + nx * distance,
                       points[i][1] + ny * distance))
    return result

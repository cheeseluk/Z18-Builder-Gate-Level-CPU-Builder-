# zb_values.py
# The values a net (a group of joined wires) can carry:
#   an int 0 .. 2^width - 1
#   Z  nothing drives the net (it floats)
#   X  unknown: uninitialized memory, a bus conflict, or garbage in
# Z and X apply to the whole net, not to single bits. No graphics here.

Z = 'Z'
X = 'X'
FORMATS = ['bin', 'dec', 'hex']


def mask(width):
    return (1 << width) - 1

def isKnown(value):
    return value != Z and value != X

def getBit(value, i):
    return (value >> i) & 1

def toSignedWidth(value, width):
    # Reads a pattern as two's complement: (0b11111101, 8) -> -3
    if value >= 1 << (width - 1):
        return value - (1 << width)
    return value

def bitString(value, width):
    # 45, 8 -> '00101101'. Z and X fill every bit.
    if value == Z:
        return 'Z' * width
    if value == X:
        return 'x' * width
    return format(value, f'0{width}b')

def formatValue(value, width, fmt='bin'):
    # One value in the chosen number format. 8-bit binary gets a space in
    # the middle, the way the lecture writes it: '0010 1101'.
    if not isKnown(value):
        text = bitString(value, width)
    elif fmt == 'dec':
        text = str(value)
        if width == 8 and value >= 0x80:
            text = str(toSignedWidth(value, 8))
        return text
    elif fmt == 'hex':
        return f'0x{value:0{(width + 3) // 4}X}'
    else:
        text = bitString(value, width)
    if width == 8:
        return text[:4] + ' ' + text[4:]
    return text

def formatAll(value, width):
    # 'bin 0000 0101  dec 5  hex 0x05' (tooltips)
    if value == Z:
        return formatValue(value, width) + '  (floating: nothing drives it)'
    if value == X:
        return formatValue(value, width) + '  (unknown)'
    text = f'bin {formatValue(value, width)}  dec {value}'
    if width > 1 and value >= 1 << (width - 1):
        text += f' ({toSignedWidth(value, width)})'
    return text + f'  hex 0x{value:X}'

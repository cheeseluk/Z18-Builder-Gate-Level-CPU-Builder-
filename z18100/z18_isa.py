# z18_isa.py
# The Z18100 instruction set in one table: every op code, how the lecture
# writes it, how the RAM table shows it, and what it does. The assembler
# reads it for parsing and for all three kinds of disassembly, so changing
# an instruction means changing one row here. No graphics here.
#
# A word is [7:4] op code | [3:0] operand. Each instruction is a dict:
#   opcode    0-9
#   name      the short name, which z18_cpu.OPCODE_NAMES reads ('LOAD R1')
#   syntax    how the lecture writes it, with an operand placeholder
#   short     the compact form for the RAM table, same placeholders
#   summary   one line for help ('R1 <- M[x]')
#   does      operand -> what this exact word does ('R2 <- M[13]')
#   aliases   other first words for the same instruction ('jnn')
#
# Placeholders (each stands for the 4-bit operand):
#   Mx   an address, written M13 (the M is optional when typing)
#   x    an address, written 13 (an M is allowed when typing)
#   s    a MUX select: R3, R2, R1 or a number
#   d    a DEMUX select: A, B or a number
#   [n]  an operand the hardware ignores: optional when typing, shown
#        only when it is not 0 (the lecture writes Sub as 0111 1111)
#
# An instruction set (an "isa") is the table made ready to use, by
# makeISA. LECTURE_ISA is the lecture machine's. A program can declare
# more instructions for a machine built in the builder (say, an
# unconditional jump on a free op code): see declareInstruction, and
# ".instruction" in z18_assembler.py.

import re

MEM_WORDS = 16
WORD_BITS = 8
OPCODE_COUNT = 10              # the lecture decoder has outputs 0-9 only
OPCODE_SLOTS = 16              # every op code a 4-bit field can hold
WORD_MASK = 0xFF
OPERAND_MASK = 0xF
PLACEHOLDERS = ['Mx', 'x', 's', 'd', '[n]']

# The MUX's data inputs, by select (note the reversed order), and the
# DEMUX's outputs. Only bits 1:0 (MUX) and bit 0 (DEMUX) reach them.
MUX_SELECT_FOR = {'r3': 1, 'r2': 2, 'r1': 3}
DEMUX_SELECT_FOR = {'a': 0, 'b': 1}
MUX_INPUTS = ['nothing (D0)', 'R3', 'R2', 'R1']
DEMUX_OUTPUTS = ['A', 'B']


def describeMux(operand):
    text = f'MUX reg <- {MUX_INPUTS[operand & 3]}'
    if operand > 3:
        text += ' (only bits 1:0 select)'
    return text

def describeDemux(operand):
    text = f'{DEMUX_OUTPUTS[operand & 1]} <- MUX reg'
    if operand > 1:
        text += ' (only bit 0 selects)'
    return text

def makeInstruction(opcode, name, syntax, short, summary, does, aliases=()):
    return {'opcode': opcode, 'name': name, 'syntax': syntax,
            'short': short, 'summary': summary, 'does': does,
            'aliases': list(aliases)}

INSTRUCTIONS = [
    makeInstruction(0, 'MOVE', 'Move R0, Output [n]', 'MOVE R0,OUT [n]',
                    'R0 <- Output', lambda x: 'R0 <- Output'),
    makeInstruction(1, 'LOAD R1', 'Load R1, Mx', 'LOAD R1,Mx',
                    'R1 <- M[x]', lambda x: f'R1 <- M[{x}]'),
    makeInstruction(2, 'LOAD R2', 'Load R2, Mx', 'LOAD R2,Mx',
                    'R2 <- M[x]', lambda x: f'R2 <- M[{x}]'),
    makeInstruction(3, 'LOAD R3', 'Load R3, Mx', 'LOAD R3,Mx',
                    'R3 <- M[x]', lambda x: f'R3 <- M[{x}]'),
    makeInstruction(4, 'MUX', 'MUX s', 'MUX s',
                    'MUX reg <- R1/R2/R3 (s = 3/2/1)', describeMux),
    makeInstruction(5, 'DEMUX', 'DEMUX d', 'DEMUX d',
                    'A (d = 0) or B (d = 1) <- MUX reg', describeDemux),
    makeInstruction(6, 'ADD', 'Add [n]', 'ADD [n]',
                    'Output <- A + B, set N Z O',
                    lambda x: 'Output <- A + B, set N Z O'),
    makeInstruction(7, 'SUB', 'Sub [n]', 'SUB [n]',
                    'Output <- A - B, set N Z O',
                    lambda x: 'Output <- A - B, set N Z O'),
    makeInstruction(8, 'JNN', 'Jump-if-not-negative x', 'JNN x',
                    'if N = 0: PC <- x', lambda x: f'if N = 0: PC <- {x}',
                    aliases=['jnn']),
    makeInstruction(9, 'STORE', 'Store Mx, R0', 'STORE Mx,R0',
                    'M[x] <- R0', lambda x: f'M[{x}] <- R0'),
]

# First words that are not instructions but that students try, and what
# to say about them
JUMP_HINT = ('the lecture machine has no unconditional jump: use '
             'Jump-if-not-negative (JNN). If you wired one into your '
             'machine, declare it first, like: .instruction 1010 Jump x')
MISSING_HINTS = {
    'jump': JUMP_HINT, 'jmp': JUMP_HINT, 'goto': JUMP_HINT,
    'halt': 'there is no halt instruction: the machine stops at an '
            'undefined op code, at xxxxxxxx, or when the PC passes 15',
}


######################################################################
# Templates (syntax, short forms and descriptions share them)
######################################################################

TEMPLATE_PART = re.compile(r' \[n\]|\bMx\b|\b[xsd]\b')

def fillTemplate(template, operand):
    # 'Load R1, Mx', 13 -> 'Load R1, M13'; 'Sub [n]', 0 -> 'Sub'
    def fill(match):
        part = match.group(0)
        if part == ' [n]':
            return f' {operand}' if operand != 0 else ''
        if part == 'Mx':
            return f'M{operand}'
        return str(operand)
    return TEMPLATE_PART.sub(fill, template)

def syntaxElements(syntax):
    # 'Load R1, Mx' -> ['Load', 'R1', 'Mx']
    return syntax.replace(',', ' ').split()

def opcodeBits(opcode):
    # 10 -> '1010'
    return format(opcode, '04b')


######################################################################
# Instruction sets
######################################################################

def makeISA(instructions, declared=()):
    # {'byOpcode': 16 entries, each an instruction or None (undefined),
    #  'patterns': {first word (lowercase): [(instruction, elements
    #               after the first word)]},
    #  'declared': the op codes a program declared,
    #  'standard': True for the lecture machine's set, unchanged}
    byOpcode = [None] * OPCODE_SLOTS
    for instruction in instructions:
        byOpcode[instruction['opcode']] = instruction
    patterns = dict()
    for instruction in byOpcode:
        if instruction == None:
            continue
        elements = syntaxElements(instruction['syntax'])
        for first in [elements[0].lower()] + instruction['aliases']:
            patterns.setdefault(first, []).append((instruction,
                                                   elements[1:]))
    return {'byOpcode': byOpcode, 'patterns': patterns,
            'declared': sorted(declared), 'standard': len(declared) == 0}

LECTURE_ISA = makeISA(INSTRUCTIONS)

def declareInstruction(opcode, syntax, description=''):
    # An instruction a program declares for its machine. syntax is checked
    # by the assembler (one placeholder at most; ' [n]' added if none).
    # In the description, placeholders become the operand: 'PC <- x'.
    first, space, rest = syntax.partition(' ')
    short = first.upper() + space + rest.replace(', ', ',')
    bits = opcodeBits(opcode)
    if description != '':
        summary = description
        does = lambda operand: fillTemplate(description, operand)
    else:
        summary = f'declared instruction (op {bits})'
        does = lambda operand: f'{first} (declared instruction, op {bits})'
    instruction = makeInstruction(opcode, first.upper(), syntax, short,
                                  summary, does)
    instruction['declared'] = True
    return instruction

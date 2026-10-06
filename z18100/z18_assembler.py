# z18_assembler.py
# Turns Z18100 assembly (written the way the lecture writes it) into the
# 16 words of memory, and turns words back into assembly. Every
# instruction comes from the table in z18_isa.py. No graphics here, and
# no files: callers read the .z18 file and pass its text in.
#
# Two passes:
#   parseProgram(text)    the declarations, then each line -> an item
#                         (what the line says); also returns the
#                         program's instruction set
#   layoutProgram(items)  items -> memory, rows, errors (where words go)
#
# Entry points:
#   assemble(text)         -> (memory, rows, errors), as the builder uses it
#   assembleProgram(text)  -> {'memory', 'rows', 'errors', 'ok', 'isa'}
#   assembleStrict(text)   -> memory, or raises AssemblerError
#     memory: 16 entries, each 0-255, or None if the program never sets it
#     rows:   16 entries, each None or {'lineNum', 'kind', 'source'} where
#             kind is 'code' or 'data' (how the source described the word)
#     errors: list of (lineNum, message), in line order
#
# One memory word per line. A line can be:
#   Load R2, M13          an instruction (see INSTRUCTION_HELP)
#   0010 1101             a raw 8-bit word (spaces or _ allowed)
#   data 7 / data -3      a number stored as data (two's complement);
#                         -128 to 255, so data 200 and data -56 are the
#                         same word
#   xxxxxxxx              an explicitly uninitialized word
#   .instruction 1010 Jump x = PC <- x
#                         declares an instruction the program's machine
#                         has (built in the builder). It takes no word
#                         and can go anywhere. The op code is 0-15 (four
#                         binary digits are binary; 0-9 replaces that
#                         lecture instruction). At most one placeholder
#                         (x, Mx, s, d, [n]); with none, [n] is added.
#                         The text after '=' is what it does, with the
#                         placeholder filled in.
# Numbers are decimal, 0b binary or 0x hex. Any line can start with an
# address, "13:" or "M13:", to place the word there (and the ones after).
# Everything after '#' or ';' is a comment.
#
# Rules worth knowing:
#   - A line with an error still uses up its address, so one typo does
#     not shift every later word. The word stays unset (xxxxxxxx).
#   - Writing an address twice is an error, and the first word is kept.
#   - disassemble shows every bit of the operand, so for every word w,
#     assembling disassemble(w) gives w back (with the same declarations).
#   - disassemble, shortDisassemble, explain and isInstruction take an
#     optional isa (assembleProgram's 'isa'); the default is the lecture
#     machine's. isa['standard'] is False when a program declares
#     instructions (the builder then turns the lecture check off).

import re

from z18_isa import (MEM_WORDS, WORD_BITS, OPCODE_SLOTS, WORD_MASK,
                     OPERAND_MASK, PLACEHOLDERS, MUX_SELECT_FOR,
                     DEMUX_SELECT_FOR, INSTRUCTIONS, MISSING_HINTS,
                     LECTURE_ISA, fillTemplate, syntaxElements,
                     opcodeBits, makeISA, declareInstruction)

# An xxxxxxxx word, before it becomes None in memory
UNINIT = object()

class AssemblerError(ValueError):
    # Raised by assembleStrict; .errors holds every (lineNum, message)
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__('; '.join(f'line {lineNum}: {message}'
                                   for lineNum, message in self.errors))


######################################################################
# Numbers. Each parser returns (value, None) or (None, errorMessage).
######################################################################

DIGITS = {2: '01', 10: '0123456789', 16: '0123456789abcdef'}

def readNumber(text):
    # '13', '-3', '07', '0b1101', '0x2D', '-0x03' -> an int; anything else
    # (including '1_0', '+5', '1.5', non-ASCII digits) -> None
    text = text.strip().lower()
    negative = text.startswith('-')
    if negative:
        text = text[1:]
    base = 10
    if text.startswith('0b'):
        base, text = 2, text[2:]
    elif text.startswith('0x'):
        base, text = 16, text[2:]
    if text == '' or any(c not in DIGITS[base] for c in text):
        return None
    value = int(text, base)
    return -value if negative else value

def capitalized(text):
    return text[:1].upper() + text[1:]

def parseNumber(token, low, high, what, shown=None):
    # shown: the text to quote in a message (default: the token)
    value = readNumber(token)
    if value == None:
        return None, f"Invalid {what} '{shown or token.strip()}'"
    if value < low or value > high:
        return None, (f'{capitalized(what)} {value} is out of range '
                      f'({low} to {high})')
    return value, None

def stripAddressM(token):
    # 'M13' -> '13' (the M is optional)
    token = token.strip()
    if token.lower().startswith('m'):
        return token[1:]
    return token

def parseAddress(token):
    # 'M13' or '13' -> 13
    return parseNumber(stripAddressM(token), 0, MEM_WORDS - 1, 'address',
                       shown=token.strip())

def isAddressText(text):
    # True if text is written like an address ('13', 'M13', '0xD'), in
    # range or not
    return readNumber(stripAddressM(text)) != None


######################################################################
# Lines
######################################################################

def stripComment(line):
    for mark in ['#', ';']:
        index = line.find(mark)
        if index != -1:
            line = line[:index]
    return line.strip()

def splitAddressPrefix(line):
    # '13: data 5' -> ('13', 'data 5'); 'Add' -> (None, 'Add'). Only a
    # number (or Mnn) before the colon is a prefix: in 'Load R2: M13' the
    # colon stays, and parseLine reports it.
    colon = line.find(':')
    if colon == -1 or not isAddressText(line[:colon]):
        return None, line.strip()
    return line[:colon].strip(), line[colon + 1:].strip()

def parseRawWord(text):
    # '0010 1101' -> 45, 'xxxx xxxx' -> UNINIT, anything else -> None
    compact = text.replace(' ', '').replace('_', '').lower()
    if len(compact) != WORD_BITS:
        return None
    if compact == 'x' * WORD_BITS:
        return UNINIT
    if any(c not in '01' for c in compact):
        return None
    return int(compact, 2)

def parseData(words):
    # ['data', '-3'] -> 253
    if len(words) != 2:
        return None, 'Expected: data <number>'
    value, error = parseNumber(words[1], -128, 255, 'data value')
    if error != None:
        return None, error
    return value & WORD_MASK, None

def parseLine(text, isa=None):
    # One line without its comment and address prefix -> (word, kind,
    # error). word is UNINIT for xxxxxxxx; kind is 'code' or 'data'.
    # isa: the instruction set (default: the lecture machine's)
    text = text.strip()
    if text == '':
        return None, 'code', 'Nothing to assemble'
    if ':' in text:
        return None, 'code', (f"Unexpected ':' in '{text}'. An address "
                               'prefix goes first and is a number, like '
                               '13: or M13:')
    raw = parseRawWord(text)
    if raw != None:
        return raw, 'data', None
    words = text.split()
    if words[0].lower() in ['data', '.data']:
        word, error = parseData(words)
        return word, 'data', error
    word, error = parseInstruction(text, isa)
    return word, 'code', error


######################################################################
# Instructions (every rule comes from z18_isa.INSTRUCTIONS)
######################################################################

# {first word (lowercase): [(instruction, [elements after it])]}, for the
# lecture machine (parsing uses isa['patterns'])
PATTERNS = LECTURE_ISA['patterns']

def familyUsage(candidates):
    # How to write an instruction family: 'Load R1/R2/R3, Mx'
    columns = [candidate[0]['syntax'].split(' ') for candidate in candidates]
    if len(set(len(words) for words in columns)) != 1:
        return candidates[0][0]['syntax']
    pieces = []
    for words in zip(*columns):
        comma = words[0].endswith(',')
        choices = []
        for word in words:
            word = word.rstrip(',')
            if word not in choices:
                choices.append(word)
        pieces.append('/'.join(choices) + (',' if comma else ''))
    return ' '.join(pieces)

def parseOperand(kind, token):
    # The operand bits a placeholder's token stands for
    lower = token.lower()
    if kind in ['Mx', 'x']:
        return parseAddress(token)
    if kind == 's' and lower in MUX_SELECT_FOR:
        return MUX_SELECT_FOR[lower], None
    if kind == 's':
        return parseNumber(token, 0, OPERAND_MASK, 'MUX select')
    if kind == 'd' and lower in DEMUX_SELECT_FOR:
        return DEMUX_SELECT_FOR[lower], None
    if kind == 'd':
        return parseNumber(token, 0, OPERAND_MASK, 'DEMUX select')
    return parseNumber(token, 0, OPERAND_MASK, 'operand')

def encode(opcode, operand):
    return (opcode << 4) + operand

def matchArguments(instruction, elements, args, usage):
    # (word, None) if args fit this instruction, else (None, failure)
    # where failure is {'position', 'expected', 'got', 'message'}
    required = [e for e in elements if e != '[n]']
    if len(args) < len(required):
        return None, {'position': -1, 'expected': None, 'got': None,
                      'message': f'Expected: {usage}'}
    if len(args) > len(elements):
        return None, {'position': -1, 'expected': None, 'got': None,
                      'message': f'Too many operands. Expected: {usage}'}
    operand = 0
    for i in range(len(args)):
        element, token = elements[i], args[i]
        if element in PLACEHOLDERS:
            value, error = parseOperand(element, token)
            if error != None:
                return None, {'position': i, 'expected': None, 'got': token,
                              'message': error}
            operand = value
        elif token.lower() != element.lower():
            return None, {'position': i, 'expected': element, 'got': token,
                          'message': f"Expected {element}, not '{token}' "
                                     f'({usage})'}
    return encode(instruction['opcode'], operand), None

def listChoices(choices):
    # ['R1', 'R2', 'R3'] -> 'R1, R2, or R3'
    if len(choices) <= 2:
        return ' or '.join(choices)
    return ', '.join(choices[:-1]) + ', or ' + choices[-1]

def failureMessage(name, failures, usage):
    # The clearest message when no instruction of a family fits: if they
    # all wanted a different word in the same place, list those words;
    # else the message from the one that got furthest
    positions = set(f['position'] for f in failures)
    if len(positions) == 1 and all(f['expected'] != None for f in failures):
        choices = []
        for failure in failures:
            if failure['expected'] not in choices:
                choices.append(failure['expected'])
        return (f"{name} needs {listChoices(choices)} here, not "
                f"'{failures[0]['got']}' ({usage})")
    furthest = max(failures, key=lambda f: f['position'])
    return furthest['message']

def parseInstruction(text, isa=None):
    # 'Load R2, M13' -> (45, None), or (None, errorMessage). Messages quote
    # what was typed, in its own case.
    if isa == None:
        isa = LECTURE_ISA
    tokens = text.replace(',', ' ').split()
    if len(tokens) == 0:
        return None, 'Nothing to assemble'
    first = tokens[0].lower()
    candidates = isa['patterns'].get(first)
    if candidates == None:
        message = f"Unknown instruction '{tokens[0]}'"
        if first.startswith('.'):
            message += ' (did you mean .instruction or .data?)'
        elif first in MISSING_HINTS:
            message += f' ({MISSING_HINTS[first]})'
        return None, message
    usage = familyUsage(candidates)
    failures = []
    for instruction, elements in candidates:
        word, failure = matchArguments(instruction, elements, tokens[1:],
                                       usage)
        if failure == None:
            return word, None
        failures.append(failure)
    name = syntaxElements(candidates[0][0]['syntax'])[0]
    return None, failureMessage(name, failures, usage)


######################################################################
# Declared instructions: ".instruction 1010 Jump x = PC <- x"
######################################################################

DECLARE_WORD = '.instruction'
NAME_SHAPE = re.compile(r'[A-Za-z][A-Za-z0-9_-]*$')

def isDeclaration(line):
    # line: without its comment. True for '.instruction ...' (any case)
    words = line.split()
    return len(words) > 0 and words[0].lower() == DECLARE_WORD

def parseOpcode(token):
    # '1010' (four binary digits are always binary), '10', '0xA',
    # '0b1010' -> 10
    if len(token) == 4 and all(c in '01' for c in token):
        return int(token, 2), None
    return parseNumber(token, 0, OPCODE_SLOTS - 1, 'op code')

def normalSyntax(syntax):
    # ' Store  Mx ,R0 ' -> 'Store Mx, R0'; a ' [n]' is added when there
    # is no placeholder, so 'Halt' and 'Halt 3' both assemble
    syntax = re.sub(r'\s*,\s*', ', ', ' '.join(syntax.split()))
    syntax = re.sub(r',\s*\[n\]$', ' [n]', syntax)
    if not any(e in PLACEHOLDERS for e in syntaxElements(syntax)):
        syntax += ' [n]'
    return syntax

def syntaxError(syntax):
    # What is wrong with a declared syntax (already normal), or None
    elements = syntaxElements(syntax)
    name = elements[0]
    if not NAME_SHAPE.match(name):
        return (f"Name '{name}' must start with a letter and use only "
                'letters, digits, - and _')
    if name.lower() in ['data', '.data']:
        return f"Name '{name}' is taken by data lines"
    if ':' in syntax:
        return "A syntax cannot contain ':' (it would read as an address)"
    placeholders = [e for e in elements if e in PLACEHOLDERS]
    if len(placeholders) > 1:
        return (f"Only one operand placeholder is allowed, not "
                f"{len(placeholders)} ({', '.join(placeholders)})")
    if '[n]' in elements and elements[-1] != '[n]':
        return '[n] must come last'
    for operand in range(OPERAND_MASK + 1):
        if parseRawWord(fillTemplate(syntax, operand)) != None:
            return (f"'{fillTemplate(syntax, operand)}' would read as a "
                    'raw 8-bit word')
    return None

def parseDeclaration(line):
    # '.instruction 1010 Jump x = PC <- x' -> (instruction, None), or
    # (None, errorMessage). Names are checked against the rest of the
    # program later, by declaredISA.
    usage = 'Expected: .instruction <op code> <syntax> [= description]'
    body = line.split(None, 1)[1] if len(line.split()) > 1 else ''
    syntaxPart, equals, description = body.partition('=')
    words = syntaxPart.split(None, 1)
    if len(words) < 2:
        return None, usage
    opcode, error = parseOpcode(words[0])
    if error != None:
        return None, error
    syntax = normalSyntax(words[1])
    error = syntaxError(syntax)
    if error != None:
        return None, error
    description = ' '.join(description.split())
    if equals != '' and description == '':
        return None, f"Nothing after '='. {usage}"
    return declareInstruction(opcode, syntax, description), None

def firstWords(instruction):
    # Every first word that selects this instruction, lowercase
    first = syntaxElements(instruction['syntax'])[0].lower()
    return [first] + instruction['aliases']

def declaredISA(declarations, base):
    # declarations: [(item, instruction)] in line order. Sets each bad
    # item's error and returns the instruction set with the good ones: a
    # declared op code replaces base's instruction for it.
    redeclared = set(instruction['opcode'] for item, instruction
                     in declarations)
    kept = [i for i in base['byOpcode']
            if i != None and i['opcode'] not in redeclared]
    added = []
    lineOf = dict()                    # op code -> line that declared it
    for item, instruction in declarations:
        opcode = instruction['opcode']
        bits = opcodeBits(opcode)
        if opcode in lineOf:
            item['error'] = (f'Op code {bits} is already declared by line '
                             f'{lineOf[opcode]}')
            continue
        name = syntaxElements(instruction['syntax'])[0]
        clash = [other for other in kept + added
                 if name.lower() in firstWords(other)]
        if len(clash) > 0:
            other = clash[0]
            item['error'] = (f"Name '{name}' is already used by op "
                             f"{opcodeBits(other['opcode'])} "
                             f"({other['syntax'].replace(' [n]', '')})")
            if not other.get('declared', False):
                item['error'] += (f'. To replace it, declare op '
                                  f"{opcodeBits(other['opcode'])}")
            continue
        lineOf[opcode] = item['lineNum']
        added.append(instruction)
    if len(redeclared) == 0:
        return base
    # (an op code whose declaration failed stays undefined: the program
    # has an error anyway, and it is still not the lecture's set)
    return makeISA(kept + added, set(base['declared']) | redeclared)


######################################################################
# Whole programs: parse every line, then lay the words out
######################################################################

def parseProgram(text, isa=None):
    # (items, programIsa). items: [item] for every line that says
    # something. An item is
    #   {'lineNum', 'source', 'address' (a prefix's address, or None),
    #    'hasWord', 'word', 'kind', 'error'}
    # A declaration's kind is 'declaration' (it takes no word). The
    # declarations are read first, so they work anywhere in the file, and
    # programIsa is isa (default: the lecture machine's) plus them.
    if isa == None:
        isa = LECTURE_ISA
    lines = text.splitlines()
    declarations = []
    for i in range(len(lines)):
        line = stripComment(lines[i])
        prefix, rest = splitAddressPrefix(line)
        if isDeclaration(line) or (prefix != None and isDeclaration(rest)):
            item = {'lineNum': i + 1, 'source': lines[i].strip(),
                    'address': None, 'hasWord': False, 'word': None,
                    'kind': 'declaration', 'error': None}
            if prefix != None:
                item['error'] = ('A declaration takes no address prefix: '
                                 'it is not a memory word')
                instruction = None
            else:
                instruction, item['error'] = parseDeclaration(line)
            declarations.append((item, instruction))
    good = [(item, instruction) for item, instruction in declarations
            if instruction != None]
    programIsa = declaredISA(good, isa)
    declaredAt = dict((item['lineNum'], item)
                      for item, instruction in declarations)
    items = []
    for i in range(len(lines)):
        if i + 1 in declaredAt:
            items.append(declaredAt[i + 1])
            continue
        item = {'lineNum': i + 1, 'source': lines[i].strip(),
                'address': None, 'hasWord': False, 'word': None,
                'kind': None, 'error': None}
        prefix, rest = splitAddressPrefix(stripComment(lines[i]))
        if prefix != None:
            item['address'], item['error'] = parseAddress(prefix)
            if item['error'] != None:
                items.append(item)     # (the rest of the line is skipped)
                continue
        if rest != '':
            item['hasWord'] = True
            item['word'], item['kind'], item['error'] = parseLine(
                rest, programIsa)
        if prefix != None or rest != '':
            items.append(item)
    return items, programIsa

def layoutProgram(items):
    # Puts each item's word at the next address:
    #   {'memory', 'rows', 'errors', 'ok'}
    memory = [None] * MEM_WORDS
    rows = [None] * MEM_WORDS
    errors = []
    overflow = []                      # lines past the end of memory
    address = 0
    for item in items:
        lineNum = item['lineNum']
        if item['address'] != None:
            address = item['address']
        elif item['error'] != None and not item['hasWord']:
            errors.append((lineNum, item['error']))      # a bad prefix
            continue
        if not item['hasWord']:
            continue
        if address >= MEM_WORDS:
            overflow.append(lineNum)
        elif item['error'] != None:
            errors.append((lineNum, item['error']))      # address used up
        elif rows[address] != None:
            errors.append((lineNum, f'Address {address} is already used '
                                    f"by line {rows[address]['lineNum']}"))
        else:
            word = item['word']
            memory[address] = None if word is UNINIT else word
            rows[address] = {'lineNum': lineNum, 'kind': item['kind'],
                             'source': item['source']}
        address += 1
    if len(overflow) > 0:
        more = len(overflow) - 1
        errors.append((overflow[0], f'Memory is full ({MEM_WORDS} words): '
                                    + ('this line does not fit' if more == 0
                                       else f'this line and {more} more do '
                                            'not fit')))
    errors.sort(key=lambda error: error[0])
    return {'memory': memory, 'rows': rows, 'errors': errors,
            'ok': len(errors) == 0}

def assembleProgram(text):
    # layoutProgram's result, plus 'isa': the program's instruction set
    # (isa['standard'] is False when the program declares instructions)
    items, isa = parseProgram(text)
    result = layoutProgram(items)
    result['isa'] = isa
    return result

def assemble(text):
    # (memory, rows, errors): check errors before using memory
    result = assembleProgram(text)
    return result['memory'], result['rows'], result['errors']

def assembleStrict(text):
    # The memory, or AssemblerError listing every error
    result = assembleProgram(text)
    if not result['ok']:
        raise AssemblerError(result['errors'])
    return result['memory']


######################################################################
# Disassembly (from the same table, filled by z18_isa.fillTemplate)
######################################################################

def formatWord(word):
    # 45 -> '0010 1101'
    bits = format(word, f'0{WORD_BITS}b')
    return bits[:4] + ' ' + bits[4:]

# Each function takes isa=None: the instruction set (default: the
# lecture machine's; a program's comes from assembleProgram)

def isInstruction(word, isa=None):
    # True for a word whose op code the instruction set defines (on the
    # lecture machine: one the decoder has an output for)
    if isa == None:
        isa = LECTURE_ISA
    return word != None and isa['byOpcode'][word >> 4] != None

def instructionOf(word, isa=None):
    if isa == None:
        isa = LECTURE_ISA
    return isa['byOpcode'][word >> 4], word & OPERAND_MASK

def disassemble(word, isa=None):
    # 45 -> 'Load R2, M13' (in the lecture's style). Every operand bit is
    # shown, and an undefined op code comes back as its raw bits, so the
    # result always assembles to the same word.
    if word == None:
        return 'x' * WORD_BITS
    if not isInstruction(word, isa):
        return formatWord(word)
    instruction, operand = instructionOf(word, isa)
    return fillTemplate(instruction['syntax'], operand)

def shortDisassemble(word, kind='code', isa=None):
    # A compact form for the RAM table: 'LOAD R2,M13', 'JNN 1', 'data 5'
    if word == None:
        return ''
    if kind == 'data':
        value = word - 0x100 if word >= 0x80 else word
        return f'data {value}'
    if not isInstruction(word, isa):
        return '(undefined)'
    instruction, operand = instructionOf(word, isa)
    return fillTemplate(instruction['short'], operand)

def explain(word, isa=None):
    # A short note on what the word does, e.g. 'R2 <- M[13]'
    if word == None:
        return 'uninitialized'
    if not isInstruction(word, isa):
        return 'undefined: no decoder output'
    instruction, operand = instructionOf(word, isa)
    return instruction['does'](operand)

# (op code, how to write it, what it does), for help screens
INSTRUCTION_HELP = [(str(i['opcode']), i['syntax'].replace(' [n]', ''),
                     i['summary']) for i in INSTRUCTIONS]


if __name__ == '__main__':
    # Try it: python z18_assembler.py
    print(assemble("""# The example program from 18-100 lectures 06-07 (spec section 5):
#
#   a = 7, b = 5
#   loop:  a = a - b
#          if a >= 0: goto loop
#   store a
#
# One memory word per line: [7:4] op code | [3:0] address/operand.
# "13:" puts a word at address 13. Words never set stay xxxxxxxx.

0:  Load R2, M13              # R2 = b
1:  Load R3, M14              # R3 = a            (the loop starts here)
    MUX 2                     # MUX latches R2    (select 2 -> R2)
    DEMUX 1                   # B = MUX reg = b
    MUX 1                     # MUX latches R3    (select 1 -> R3)
    DEMUX 0                   # A = MUX reg = a
    Sub 15                    # Output = A - B.   The lecture fills the unused
    Move R0, Output 15        # R0 = Output       operand with 1111
    Store M14, R0             # a = R0
    Jump-if-not-negative M1   # if N = 0 (a >= 0), go to address 1
10: Store M15, R0             # the final result

13: data 5                    # b
14: data 7                    # a
15: data 0                    # result slot"""))

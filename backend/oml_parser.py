"""
OML requirement extraction.

Reads the textual syntax of an OML (Ontological Modeling Language) description
and returns requirements in the shape requirements_parser already produces —
{'id', 'text'} plus an optional 'category' — so nothing downstream of the upload
endpoint needs to know which format the file arrived in.

Only the description subset of the language is handled: instance declarations
and the literal-valued properties asserted on them. Vocabularies declare types
rather than requirements, so they hold nothing this parser wants.
"""

import re
from typing import Dict, Iterator, List, Optional, Tuple

# An instance is a requirement when the local name of one of its types appears
# here. Matching the local name rather than the full IRI keeps this working
# across projects: the UAOS vocabulary writes `req:Requirement` and the
# openCAESAR tutorials write `mission:Requirement`, and both reduce to
# `Requirement`.
REQUIREMENT_TYPES = ('Requirement',)

# Where the requirement's prose lives, most specific first. Every INCOSE
# A-criterion is a judgement about English wording, so this is the one property
# the pipeline genuinely needs. `hasCanonicalName` is last because it is usually
# a short label rather than a full requirement statement — better than nothing,
# but only when the alternatives are absent.
TEXT_PROPERTIES = (
    'hasNaturalLanguageDescription',
    'hasDescription',
    'hasStatement',
    'hasText',
    'hasCanonicalName',
)

ID_PROPERTIES = ('hasID', 'hasId', 'hasIdentifier')

NAME_PROPERTIES = ('hasName',)

# `instance <name> : <type>[, <type>...] [` — the header of a named instance.
_INSTANCE_HEADER = re.compile(r'\binstance\s+([^\s:]+)\s*:\s*([^\[]+?)\s*\[')

# A property name immediately followed by a string literal, e.g. `tlo:hasID "1"`.
# The lookahead keeps the quote in place for _read_string to consume.
_PROPERTY = re.compile(r'([A-Za-z_][\w.\-]*(?::[A-Za-z_][\w.\-]*)?)\s*(?=")')

_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}


def parse_oml_requirements(text: str) -> List[Dict]:
    """Extract requirements from the text of an OML description."""
    source = _strip_comments(text)

    requirements = []
    for instance_name, types, body in _iter_instances(source):
        if not any(_local_name(t) in REQUIREMENT_TYPES for t in types):
            continue

        properties = _literal_properties(body)

        statement = _first_present(properties, TEXT_PROPERTIES)
        if not statement:
            # An instance carrying only relations (`req:refines other-req`) has
            # no wording to assess. Skipping it is better than handing the
            # analyser an empty string and getting seven meaningless verdicts.
            continue

        requirement = {
            # Falling back to the instance name keeps the requirement traceable
            # to its line in the model even when the vocabulary asserts no id.
            'id': _first_present(properties, ID_PROPERTIES) or instance_name,
            'text': statement,
        }

        label = _first_present(properties, NAME_PROPERTIES)
        if label:
            requirement['category'] = label

        requirements.append(requirement)

    return requirements


def _iter_instances(source: str) -> Iterator[Tuple[str, List[str], str]]:
    """Yield (instance name, type references, body) for each named instance."""
    for match in _INSTANCE_HEADER.finditer(source):
        types = [t.strip() for t in match.group(2).split(',') if t.strip()]
        # The regex ends on the opening bracket, so backing up one character
        # lands on it.
        body, _ = _bracketed_body(source, match.end() - 1)
        yield match.group(1), types, body


def _literal_properties(body: str) -> Dict[str, str]:
    """Collect the `property "literal"` assertions directly on an instance.

    Nested anonymous instances are stepped over rather than descended into: a
    value like `pizza:hasBase : pizza:DeepPanBase []` describes a related thing,
    not this one, and folding its properties in here would silently attribute
    them to the requirement.
    """
    properties: Dict[str, str] = {}
    index, end = 0, len(body)

    while index < end:
        char = body[index]

        if char == '[':
            _, index = _bracketed_body(body, index)
            continue

        if char == '"':
            # A literal with no property name in front of it — nothing to key
            # it by, so consume it and move on.
            _, index = _read_string(body, index)
            continue

        match = _PROPERTY.match(body, index)
        if match:
            value, index = _read_string(body, match.end())
            # First assertion wins, matching how the rest of the pipeline treats
            # a repeated field.
            properties.setdefault(_local_name(match.group(1)), value)
            continue

        index += 1

    return properties


def _bracketed_body(text: str, open_index: int) -> Tuple[str, int]:
    """Return the contents of the bracket at open_index, and the index past it.

    Tracks nesting and skips string literals so that a bracket inside a quoted
    requirement statement cannot end the block early.
    """
    depth = 0
    index, end = open_index, len(text)

    while index < end:
        char = text[index]

        if char == '"':
            _, index = _read_string(text, index)
            continue

        if char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
            if depth == 0:
                return text[open_index + 1:index], index + 1

        index += 1

    raise ValueError('Unterminated "[" in the OML source — the file is not valid OML.')


def _read_string(text: str, index: int) -> Tuple[str, int]:
    """Read the string literal starting at index; return it and the next index."""
    chars = []
    index += 1
    end = len(text)

    while index < end:
        char = text[index]

        if char == '\\' and index + 1 < end:
            escaped = text[index + 1]
            chars.append(_ESCAPES.get(escaped, escaped))
            index += 2
            continue

        if char == '"':
            return ''.join(chars), index + 1

        chars.append(char)
        index += 1

    raise ValueError('Unterminated string literal in the OML source — the file is not valid OML.')


def _strip_comments(text: str) -> str:
    """Remove // and /* */ comments, leaving string literals and IRIs intact.

    IRIs need the same protection as strings: every OML file opens with
    something like `description <http://example.com/x#> as x`, and the `//` in
    the scheme would otherwise take the rest of the line with it.
    """
    out = []
    index, end = 0, len(text)

    while index < end:
        char = text[index]

        if char == '"':
            closing = _end_of_string(text, index)
            out.append(text[index:closing])
            index = closing
        elif char == '<' and _is_iri(text, index):
            closing = text.index('>', index) + 1
            out.append(text[index:closing])
            index = closing
        elif text.startswith('//', index):
            newline = text.find('\n', index)
            index = end if newline == -1 else newline
        elif text.startswith('/*', index):
            closing = text.find('*/', index)
            index = end if closing == -1 else closing + 2
        else:
            out.append(char)
            index += 1

    return ''.join(out)


def _is_iri(text: str, index: int) -> bool:
    """True when the '<' at index opens an IRI rather than being stray syntax."""
    closing = text.find('>', index)
    if closing == -1:
        return False
    # IRIs cannot contain whitespace, so anything with a space or newline before
    # the '>' is some other use of the character.
    return not any(c.isspace() for c in text[index + 1:closing])


def _end_of_string(text: str, index: int) -> int:
    """Index just past the string literal starting at index."""
    index += 1
    end = len(text)

    while index < end:
        if text[index] == '\\':
            index += 2
            continue
        if text[index] == '"':
            return index + 1
        index += 1

    return end


def _local_name(reference: str) -> str:
    """Reduce `req:Requirement` or `<http://x#Requirement>` to `Requirement`."""
    reference = reference.strip().strip('<>')
    for separator in ('#', '/', ':'):
        if separator in reference:
            reference = reference.rsplit(separator, 1)[1]
    return reference


def _first_present(properties: Dict[str, str], keys: Tuple[str, ...]) -> Optional[str]:
    """Return the first non-empty value among keys, stripped."""
    for key in keys:
        value = properties.get(key, '').strip()
        if value:
            return value
    return None

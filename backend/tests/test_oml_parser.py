"""Tests for OML requirement extraction."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from oml_parser import parse_oml_requirements  # noqa: E402
from requirements_parser import validate_requirements  # noqa: E402

SAMPLE = Path(__file__).parent.parent.parent / 'samples' / 'PointMassRequirements.oml'


def _description(body: str) -> str:
    """Wrap instance declarations in the description header every OML file has."""
    return (
        'description <http://example.com/test#> as test {\n'
        '    uses <http://example.com/vocab#> as req\n'
        f'{body}\n'
        '}\n'
    )


def test_sample_file_parses_every_requirement():
    requirements = parse_oml_requirements(SAMPLE.read_text(encoding='utf-8'))

    assert len(requirements) == 13
    assert requirements[0] == {
        'id': '33334',
        'text': requirements[0]['text'],
        'category': 'Displace',
    }
    assert requirements[0]['text'].startswith('The System shall be able to move a point mass')


def test_sample_file_satisfies_the_pipeline_contract():
    """The analyser is handed OML output unchanged, so it must validate."""
    requirements = parse_oml_requirements(SAMPLE.read_text(encoding='utf-8'))

    assert validate_requirements(requirements) == {'valid': True, 'count': 13}
    assert all(r['id'] and r['text'] for r in requirements)


def test_trailing_whitespace_is_stripped():
    requirements = parse_oml_requirements(_description(
        '    instance r1 : req:Requirement [\n'
        '        req:hasNaturalLanguageDescription "The system shall stop.   "\n'
        '    ]'
    ))

    assert requirements[0]['text'] == 'The system shall stop.'


def test_brackets_inside_a_literal_do_not_end_the_instance():
    """PointMassRequirements uses [0.1"] for inch measurements inside statements."""
    requirements = parse_oml_requirements(_description(
        '    instance r1 : req:Requirement [\n'
        '        req:hasNaturalLanguageDescription "Accurate to +/- 2.5mm [0.1 in] in [X, Y, Z]."\n'
        '        req:hasID "R-1"\n'
        '    ]'
    ))

    assert len(requirements) == 1
    assert requirements[0]['id'] == 'R-1'
    assert requirements[0]['text'] == 'Accurate to +/- 2.5mm [0.1 in] in [X, Y, Z].'


def test_instances_of_other_types_are_ignored():
    requirements = parse_oml_requirements(_description(
        '    instance c1 : req:Component [\n'
        '        req:hasNaturalLanguageDescription "Not a requirement."\n'
        '    ]\n'
        '    instance r1 : req:Requirement [\n'
        '        req:hasNaturalLanguageDescription "The system shall stop."\n'
        '    ]'
    ))

    assert [r['text'] for r in requirements] == ['The system shall stop.']


def test_requirement_type_is_matched_on_local_name():
    """A different project's vocabulary prefix must not change the outcome."""
    requirements = parse_oml_requirements(_description(
        '    instance r1 : mission:Requirement [\n'
        '        mission:hasNaturalLanguageDescription "The system shall stop."\n'
        '    ]'
    ))

    assert len(requirements) == 1


def test_requirement_without_prose_is_skipped():
    """Relations alone give the INCOSE criteria nothing to judge."""
    requirements = parse_oml_requirements(_description(
        '    instance r1 : req:Requirement [\n'
        '        req:hasID "R-1"\n'
        '        req:specifies other:thing\n'
        '    ]'
    ))

    assert requirements == []


def test_id_falls_back_to_the_instance_name():
    requirements = parse_oml_requirements(_description(
        '    instance item-99 : req:Requirement [\n'
        '        req:hasNaturalLanguageDescription "The system shall stop."\n'
        '    ]'
    ))

    assert requirements[0]['id'] == 'item-99'


def test_text_property_precedence():
    """hasCanonicalName is a label, so a real statement outranks it."""
    requirements = parse_oml_requirements(_description(
        '    instance r1 : req:Requirement [\n'
        '        req:hasCanonicalName "Braking"\n'
        '        req:hasNaturalLanguageDescription "The system shall stop."\n'
        '    ]'
    ))

    assert requirements[0]['text'] == 'The system shall stop.'


def test_nested_instance_properties_are_not_attributed_to_the_parent():
    requirements = parse_oml_requirements(_description(
        '    instance r1 : req:Requirement [\n'
        '        req:hasNaturalLanguageDescription "The system shall stop."\n'
        '        req:verifiedBy : req:TestCase [\n'
        '            req:hasID "TC-1"\n'
        '            req:hasName "Brake test"\n'
        '        ]\n'
        '        req:hasID "R-1"\n'
        '    ]'
    ))

    assert requirements[0]['id'] == 'R-1'
    assert 'category' not in requirements[0]


def test_comments_are_ignored_but_iris_survive():
    """The // in an IRI scheme must not be read as the start of a comment."""
    requirements = parse_oml_requirements(
        '// leading comment\n'
        'description <http://example.com/test#> as test {\n'
        '    uses <http://example.com/vocab#> as req\n'
        '    /* the next one is out of scope\n'
        '    instance r0 : req:Requirement [\n'
        '        req:hasNaturalLanguageDescription "Commented out."\n'
        '    ]\n'
        '    */\n'
        '    instance r1 : req:Requirement [\n'
        '        req:hasNaturalLanguageDescription "The system shall stop." // inline\n'
        '    ]\n'
        '}\n'
    )

    assert [r['text'] for r in requirements] == ['The system shall stop.']


def test_escaped_quotes_inside_a_statement():
    requirements = parse_oml_requirements(_description(
        '    instance r1 : req:Requirement [\n'
        '        req:hasNaturalLanguageDescription "The system shall report \\"ready\\"."\n'
        '    ]'
    ))

    assert requirements[0]['text'] == 'The system shall report "ready".'


def test_multiple_types_on_one_instance():
    requirements = parse_oml_requirements(_description(
        '    instance r1 : req:Traceable, req:Requirement [\n'
        '        req:hasNaturalLanguageDescription "The system shall stop."\n'
        '    ]'
    ))

    assert len(requirements) == 1


def test_a_file_with_no_requirements_returns_nothing():
    """Callers report this; the parser does not invent an error for it."""
    assert parse_oml_requirements(_description('')) == []


def test_unterminated_bracket_is_rejected():
    with pytest.raises(ValueError, match='Unterminated'):
        parse_oml_requirements(_description(
            '    instance r1 : req:Requirement [\n'
            '        req:hasNaturalLanguageDescription "The system shall stop."\n'
        ))


def test_unterminated_string_is_rejected():
    with pytest.raises(ValueError, match='Unterminated'):
        parse_oml_requirements(_description(
            '    instance r1 : req:Requirement [\n'
            '        req:hasNaturalLanguageDescription "The system shall stop.\n'
            '    ]'
        ))

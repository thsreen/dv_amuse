"""Strict structured output cannot express a free-form map; it is sent as key/value pairs and restored."""
import json
import pytest

from dv_agent.codegen.reasoning import restore_maps, strict_schema
from dv_agent.codegen.units import InterfaceUnit


def objects(node, found):
    if isinstance(node, dict):
        if node.get('type') == 'object': found.append(node)
        for v in node.values(): objects(v, found)
    elif isinstance(node, list):
        for v in node: objects(v, found)
    return found


def test_every_object_in_a_strict_schema_is_closed_and_fully_required():
    for obj in objects(strict_schema(InterfaceUnit), []):
        assert obj.get('additionalProperties') is False and set(obj['required']) == set(obj['properties'])


def test_pairs_from_the_model_become_a_map_that_validates():
    answer = dict(agents=[dict(id='bus', protocol='custom', bindings=[dict(key='ack', value='ready'), dict(key='stb', value='request')],
                               fact_ids=['f'])],
                  facts=[dict(id='f', statement='s', source_id='CH', quote='a quoted sentence', plan_pointer='/p')])
    restored = restore_maps(InterfaceUnit, json.loads(json.dumps(answer)))
    assert restored['agents'][0]['bindings'] == {'ack': 'ready', 'stb': 'request'}
    assert InterfaceUnit.model_validate(restored).agents[0].bindings == {'ack': 'ready', 'stb': 'request'}


def test_an_answer_that_already_uses_maps_is_left_unchanged():
    answer = dict(agents=[dict(id='bus', protocol='custom', bindings={'ack': 'ready'}, fact_ids=['f'])], facts=[])
    assert restore_maps(InterfaceUnit, answer) == answer


@pytest.mark.parametrize('pairs',[[{'key':'x','value':'a'},{'key':'x','value':'b'}],[{'key':'x'}],[{'key':1,'value':'a'}]])
def test_invalid_maps_are_rejected_instead_of_losing_bindings(pairs):
    with pytest.raises(ValueError): restore_maps(InterfaceUnit,{'agents':[{'bindings':pairs}]})

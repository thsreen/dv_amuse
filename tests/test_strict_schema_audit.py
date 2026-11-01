"""Every model-facing schema must satisfy strict structured output before any live call is spent finding out."""
import importlib
import inspect

import pytest
from pydantic import BaseModel

from dv_agent.codegen.reasoning import strict_schema
from dv_agent.codegen.workplan import Fragment

MODULES = ('units', 'workplan', 'reasoning', 'contracts')


def models():
    found = {}
    for name in MODULES:
        module = importlib.import_module('dv_agent.codegen.' + name)
        for cls_name, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, BaseModel) and cls.__module__ == module.__name__ and cls is not BaseModel:
                found[f'{name}.{cls_name}'] = cls
    return found


def objects(node, path=''):
    if isinstance(node, dict):
        if node.get('type') == 'object':
            yield path, node
        for key, value in node.items():
            yield from objects(value, f'{path}/{key}')
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from objects(value, f'{path}[{i}]')


@pytest.mark.parametrize('name', sorted(models()))
def test_every_object_is_closed_fully_required_and_defines_what_it_requires(name):
    for path, obj in objects(strict_schema(models()[name])):
        assert obj.get('additionalProperties') is False, f'{name}{path}: object not closed (a free-form map?)'
        assert set(obj.get('required', [])) == set(obj.get('properties', {})), f'{name}{path}: required and properties differ'


def test_a_field_named_default_survives_schema_cleaning():
    """SequencerVariable.default was stripped as if it were the JSON-schema keyword, leaving it required but undefined."""
    schema = strict_schema(Fragment)
    variable = schema['$defs']['SequencerVariable']
    assert 'default' in variable['properties'] and 'default' in variable['required']

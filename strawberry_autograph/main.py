from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from functools import cached_property
from itertools import chain
from logging import getLogger
from typing import Any
from typing import get_args
from typing import get_origin
from typing import Union

import strawberry
from strawberry.field import StrawberryField
from strawberry.schema import Schema
from strawberry.types import ExecutionResult
from strawberry.utils.str_converters import to_camel_case  # noqa: WPS347
from strawberry.utils.str_converters import to_snake_case  # noqa: WPS347


logger = getLogger(__name__)

FieldTree = dict[str, 'FieldTree']
InputScalars = Union[
    strawberry.UNSET,
    None,
    Enum,
    datetime,
    str,
    int,
    float,
    bool,
]
ArbitraryInput = Union[
    InputScalars,
    list['ArbitraryInput'],
    dict[str, 'ArbitraryInput'],
]
ROOT_DEPTH = 1


def serialize_scalar(scalar: InputScalars):
    """Serialize scalar values using JSON for GraphQL compatibility."""
    scalar_type = type(scalar)
    if scalar_type in {str, int, float, bool, type(None)}:
        return json.dumps(scalar)
    elif scalar_type is datetime:
        return json.dumps(scalar.isoformat())
    elif isinstance(scalar, Enum):
        return scalar.value
    elif scalar is strawberry.UNSET:
        return json.dumps(None)
    raise TypeError(f'Unsupported type: {scalar_type}')


def parse_input_tree(
    field_name: str,
    field,
    level: int = 0,
) -> FieldTree:
    """Recursively parse a field and its subfields."""
    field_type = getattr(field, 'type', None)
    if field_type is None:
        return {field_name: {}}
    while core_field := getattr(field_type, 'of_type', None):  # noqa: WPS332, E501
        field_type = core_field
    subfields: FieldTree = dict(
        chain.from_iterable((
            parse_input_tree(fname, subfield, level=level + 1).items()
            for fname, subfield in getattr(field_type, 'fields', {}).items()
        )),
    )
    return {field_name: subfields}


def unwrap_strawberry_type(type_: Any) -> FieldTree:
    """Recursively unwraps a Strawberry response type."""
    type_annotations = getattr(type_, '__annotations__', {})
    tree: FieldTree = {}
    for field_name, field_type in type_annotations.items():
        origin = get_origin(field_type)
        # Optional types are unions with None
        if origin is Union:
            field_type = next(
                typ
                for typ in get_args(field_type)
                if typ is not type(None)  # noqa: WPS516
            )
        elif origin is list:
            field_type = get_args(field_type)[0]
        tree[to_camel_case(field_name)] = unwrap_strawberry_type(field_type)
    return tree


class GQLExecutableTemplate:  # noqa: WPS214
    """GraphQL operation template injectable with strawberry inputs."""

    def __init__(
        self,
        executor: Schema,
        *,
        name: str,
        request: StrawberryField,
        is_mutation: bool = False,
    ) -> None:
        """Store the operation as an attribute."""
        self.executor = executor
        self.field = request
        self.name = name
        self.reqtype = 'mutation' if is_mutation else 'query'
        self.method_name = to_snake_case(name)

    def __call__(self, **inputs: ArbitraryInput | Any) -> ExecutionResult:
        """Generate a GraphQL operation and execute it."""
        query = self.generate_query(**inputs)
        logger.debug(query)
        return self.executor.execute_sync(query)

    def __repr__(self) -> str:
        """Return the operation name and args in snake case."""
        return f'GQLTemplate({self})'

    def __str__(self) -> str:
        """Return the operation name and args in snake case."""
        args = ', '.join(map(to_snake_case, self.input_tree.keys()))
        args = f'({args})' if args else ''
        return f'{self.reqtype} {self.method_name}{args}'

    def generate_query(self, **inputs: ArbitraryInput | Any) -> str:
        """Generate a GraphQL operation."""
        inputs_string = self.serialize_input({
            to_camel_case(inkey): self._try_asdict(invalue)
            for inkey, invalue in inputs.items()
        })
        operation_string = (
            f'{self.reqtype} {self.name}({inputs_string})'
            if inputs_string
            else f'{self.reqtype} {self.name}'
        )
        return f'{operation_string} {{\n{self.serialized_fragment_tree}\n}}'

    @cached_property
    def input_tree(self) -> FieldTree:
        """Parse the argument structure."""
        nesting_pairings = (
            parse_input_tree(argname, argfield).items()
            for argname, argfield in self.field.args.items()
        )
        return dict(chain.from_iterable(nesting_pairings))

    @cached_property
    def fragment_tree(self) -> FieldTree:
        """Parse the response fragment structure."""
        response_type = self.field.extensions['strawberry-definition'].type
        while inner_type := getattr(response_type, 'of_type', None):  # noqa: WPS332, E501
            response_type = inner_type
        response_models = response_type.types
        fragment_trees = map(unwrap_strawberry_type, response_models)
        fragment_names = (
            rtp.__strawberry_definition__.name
            for rtp in response_models
        )
        return dict(zip(fragment_names, fragment_trees))

    @cached_property
    def serialized_fragment_tree(self) -> str:
        """Serialize the response fragment structure for template."""
        serialized = '\n'.join(
            self._serialize_fragment_tree_lines(self.fragment_tree),
        )
        return serialized

    def serialize_input(  # noqa: WPS210
        self,
        recursive_input: ArbitraryInput,
    ) -> str:
        """Recursively serialize input to a GraphQL-friendly format."""
        if isinstance(recursive_input, dict):
            preprocessed_pairs = (
                (to_camel_case(pkey), self.serialize_input(pvalue))
                for pkey, pvalue in recursive_input.items()
            )
            serialized_pairset = ', '.join((
                f'{camelkey}: {strvalue}'
                for camelkey, strvalue in preprocessed_pairs
            ))
            return f'{{ {serialized_pairset} }}'
        elif isinstance(recursive_input, list):
            serialized_array = ', '.join(
                self.serialize_input(element)
                for element in recursive_input
            )
            return f'[ {serialized_array} ]'
        return serialize_scalar(recursive_input)

    def _try_asdict(self, maybedataclass: Any) -> Any:
        try:
            return strawberry.asdict(maybedataclass)
        except TypeError:
            return maybedataclass

    def _serialize_fragment_tree_lines(  # noqa: WPS210
        self,
        tree: FieldTree,
        depth=ROOT_DEPTH,
    ) -> list[str]:
        """Recursively serialize response fragment fields."""
        lines = []
        indent = '\t' * depth
        for field_name, nested_fields in tree.items():
            prefix_for_root = '... on ' if depth == ROOT_DEPTH else ''
            line = f'{indent}{prefix_for_root}{field_name}'
            if nested_fields:
                lines.append(f'{line} {{')
                nested_serialization = self._serialize_fragment_tree_lines(
                    nested_fields,
                    depth=depth + 1,
                )
                lines.extend(nested_serialization)
                lines.append(f'{indent}}}')
            else:
                lines.append(line)

        return lines


class AutoGraphClient:
    """A graphql client that mirrors the whole app schema."""

    def __init__(self, schema: Schema):  # noqa: WPS210
        """Parse all operations as executable templates."""
        self.schema = schema
        queries = schema._schema.to_kwargs()['query'].fields  # noqa: WPS437
        mutations = schema._schema.to_kwargs()['mutation'].fields  # noqa: WPS437, E501
        query_templates = [
            GQLExecutableTemplate(
                self.schema,
                name=name,
                request=qfield,
                is_mutation=False,
            )
            for name, qfield in queries.items()
        ]
        mutation_templates = [
            GQLExecutableTemplate(
                self.schema,
                name=name,
                request=mfield,
                is_mutation=True,
            )
            for name, mfield in mutations.items()
        ]
        for template in (*query_templates, *mutation_templates):
            setattr(self, template.method_name, template)

    @cached_property
    def operations(self) -> list[str]:
        """List all executable template operations."""
        excluded_names = {
            'schema',
            'operations',
        }
        checks = {
            lambda name: name not in excluded_names,
            lambda name: not name.startswith('_'),
        }
        operation_names = list(
            filter(
                lambda name: all(check(name) for check in checks),
                self.__dict__,
            ),
        )
        operations = (getattr(self, name) for name in operation_names)
        return list(map(str, operations))

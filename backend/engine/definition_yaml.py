from __future__ import annotations

import copy
import re
from typing import Any

import yaml
from yaml.composer import ComposerError
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode


class DefinitionYamlError(ValueError):
    def __init__(self, message: str, *, line: int | None = None, column: int | None = None) -> None:
        super().__init__(message)
        self.line = line
        self.column = column


class _DefinitionLoader(yaml.SafeLoader):
    """Safe, deterministic YAML loader for repository definitions."""

    yaml_implicit_resolvers = copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)

    def compose_node(self, parent: Any, index: Any) -> Any:
        event = self.peek_event()  # type: ignore[no-untyped-call]
        if isinstance(event, AliasEvent) or getattr(event, "anchor", None):
            raise ComposerError(
                None,
                None,
                "YAML anchors and aliases are not allowed",
                event.start_mark,
            )
        return super().compose_node(parent, index)

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        for key_node, _value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "YAML merge keys are not allowed",
                    key_node.start_mark,
                )
        self.flatten_mapping(node)
        seen: set[Any] = set()
        for key_node, _value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
            except TypeError as exc:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "mapping keys must be scalar values",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "duplicate mapping keys are not allowed",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


for first_character, resolvers in list(_DefinitionLoader.yaml_implicit_resolvers.items()):
    _DefinitionLoader.yaml_implicit_resolvers[first_character] = [
        (tag, pattern)
        for tag, pattern in resolvers
        if tag not in {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp"}
    ]

_DefinitionLoader.add_implicit_resolver(  # type: ignore[no-untyped-call]
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.IGNORECASE),
    list("tTfF"),
)


class _DefinitionDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)


def _represent_string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_DefinitionDumper.add_representer(str, _represent_string)


def load_definition_yaml(raw: str) -> Any:
    loader = _DefinitionLoader(raw)
    try:
        return loader.get_single_data()
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        message = _safe_yaml_error_message(exc)
        raise DefinitionYamlError(
            message,
            line=(mark.line + 1) if mark is not None else None,
            column=(mark.column + 1) if mark is not None else None,
        ) from exc
    finally:
        loader.dispose()  # type: ignore[no-untyped-call]


def dump_definition_yaml(value: Any) -> str:
    return yaml.dump(
        value,
        Dumper=_DefinitionDumper,
        allow_unicode=True,
        default_flow_style=False,
        indent=2,
        sort_keys=False,
    )


def _safe_yaml_error_message(exc: yaml.YAMLError) -> str:
    problem = getattr(exc, "problem", "")
    if problem == "YAML anchors and aliases are not allowed":
        return problem
    if problem == "YAML merge keys are not allowed":
        return problem
    if problem == "duplicate mapping keys are not allowed":
        return problem
    if problem == "mapping keys must be scalar values":
        return problem
    if isinstance(exc, ConstructorError):
        return "YAML contains an unsupported value or tag"
    if isinstance(exc, ComposerError):
        return "YAML must contain exactly one document"
    return "Invalid YAML syntax"

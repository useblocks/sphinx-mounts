"""Variant conditions and variant data — the ``[[source.variant_sources]]`` engine.

**Import discipline: this module is deliberately dependency-free.** It imports
nothing from :mod:`sphinx_mounts`, nothing from Sphinx and nothing from
docutils — only the standard library. The same is true of
:mod:`sphinx_mounts.dialect`. Both are written that way so that extracting
them into a shared ``sphinx-variants`` package later is a ``git mv`` rather
than a rewrite: the condition grammar is a two-engine contract (see
``tests/fixtures/variant_condition_conformance.toml``), and a contract that
can only live inside a mounting extension is one a second Sphinx extension
cannot adopt without depending on this one.

Anything that needs a Sphinx type — the ``ExtensionError`` wrapping, the
typed ``mounts.*`` warnings, ``config.root_doc`` — belongs in
:mod:`sphinx_mounts.config` or :mod:`sphinx_mounts.extension`, which catch the
plain exceptions raised here and re-raise them in Sphinx's vocabulary.

Two halves:

**The condition engine** (:func:`validate`, :func:`interpret`) is an
*interpreter*, not an :func:`eval` with a small globals dict. ``ast.parse``
produces one tree; :func:`validate` walks it against a whitelist, and
:func:`interpret` walks the *same* tree over the plain merged mapping. There
is no namespace object, no ``var`` binding and no builtins to remove, because
nothing is ever executed. That turns the whitelist's completeness from a
*security* property into a *correctness* one: a node type the interpreter does
not handle raises :class:`VariantEvalError` instead of running.

**The variant-data reader** (:func:`resolve_variant_data`) is a private copy of
sphinx-needs' ``deep_merge`` / ``validate_variant_data`` /
``load_variant_data_file`` semantics. The copy exists so that sphinx-mounts
never imports, depends on, or version-gates against sphinx-needs, and it cannot
disagree with it: ``deep_merge(file, inline)`` is idempotent, so re-merging an
already-merged map is a proven no-op. See :func:`resolve_variant_data`.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
import json
import operator
from pathlib import Path
from typing import Any

#: Comparison operators the grammar accepts, ``is`` / ``is not`` excluded
#: (they are handled separately because their right-hand side must be ``None``).
_CMP_OPS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)
_IS_OPS = (ast.Is, ast.IsNot)

#: String methods callable on a ``var.*`` field.
#:
#: Split by *return type*, because the boolean-top-level rule is type-aware and
#: the conformance corpus is what says so: rows 16/17 ACCEPT a bare
#: ``var.name.startswith('Wid')`` / ``.endswith('get')`` (they return ``bool``),
#: while rows 34/35 REJECT a bare ``var.name.upper()`` / ``.lower()`` (they
#: return ``str``). Prose summaries of the grammar — ubCode's own schema doc
#: comment and its ``usage/variants.rst`` — say "bare string-method calls" are
#: refused, which is imprecise; the corpus is the contract.
_PREDICATE_METHODS = frozenset({"startswith", "endswith"})
_TRANSFORM_METHODS = frozenset({"upper", "lower"})
_STR_METHODS = _PREDICATE_METHODS | _TRANSFORM_METHODS

#: Leaf value types the variant data may hold.
_SCALAR_TYPES = (str, bool, int, float)


class VariantConditionError(Exception):
    """A rule condition is outside the grammar — a *configuration* error.

    Statically knowable, so it is refused rather than evaluated. The caller
    turns this into a hard, non-suppressible failure.
    """


class VariantEvalError(Exception):
    """A rule condition is inside the grammar but cannot be *evaluated*.

    An unknown ``var.*`` key or a type mismatch. Data-dependent rather than
    statically knowable, so it is reported and the rule is treated as FALSE —
    the warn-and-exclude contract the ``.. if::`` directive already has, and
    the safe direction for a key whose purpose is keeping content out.
    """


class VariantDataError(Exception):
    """The variant data itself is unreadable or malformed.

    Deliberately the same name sphinx-needs uses for the same condition, so a
    reader comparing the two implementations is not misled by a rename.
    """


# ---------------------------------------------------------------------------
# Pass 1 — the static whitelist
# ---------------------------------------------------------------------------


def _is_var_rooted(node: ast.AST) -> bool:
    """Whether ``node`` is ``var`` or a chain of plain attributes rooted at it.

    A leading-underscore segment is refused outright. Nothing can reach
    ``__class__`` through the interpreter anyway — it holds no objects, only
    the plain mapping — but refusing the spelling keeps the *grammar* the same
    shape as the one a future ``eval``-based reader would need.
    """
    while isinstance(node, ast.Attribute):
        if node.attr.startswith("_"):
            return False
        node = node.value
    return isinstance(node, ast.Name) and node.id == "var"


def _refuse_bare_name(name: str) -> None:
    """Raise the right message for a field reference not rooted at ``var``.

    ``true`` / ``false`` get their own sentence because they are by far the
    likeliest way a bare name appears: a TOML author writes the spelling TOML
    uses, and the parser reads it as a *field name*. Saying "write ``var.false``"
    would be accurate and useless.
    """
    if name.startswith("var."):
        # Rooted at `var`, but some segment starts with an underscore.
        msg = (
            f"`{name}` accesses a leading-underscore field, which a rule "
            f"condition may not name; variant data keys are ordinary names"
        )
        raise VariantConditionError(msg)
    if name in {"true", "false"}:
        python = "True" if name == "true" else "False"
        msg = (
            f"`{name}` is read as a field name, not as a boolean: a condition "
            f"is an expression rather than a TOML value, so the literals are "
            f"Python-spelled — write `{python}`"
        )
        raise VariantConditionError(msg)
    msg = (
        f"`{name}` is not rooted at `var`; a rule condition may only reference "
        f"the variant data, so write `var.{name}`. Unlike the `if` directive, "
        f"the leading `var` is required here: a bare name is not expected to be "
        f"defined for every tool that reads this file, and would then select a "
        f"different set of documents"
    )
    raise VariantConditionError(msg)


def _dotted(node: ast.AST) -> str:
    """Render an attribute chain / name as the author wrote it."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    parts.reverse()
    return ".".join(parts)


def _validate_operand(node: ast.AST) -> None:
    """Validate a comparison operand.

    One of: a ``var.*`` path, a scalar literal, a list/tuple of scalar
    literals, or a whitelisted string-method call on a ``var.*`` path.
    """
    if _is_var_rooted(node):
        if isinstance(node, ast.Name):
            msg = "bare `var` is not a value; access a field, e.g. `var.edition`"
            raise VariantConditionError(msg)
        return
    if isinstance(node, ast.Name | ast.Attribute):
        _refuse_bare_name(_dotted(node))
    if isinstance(node, ast.Constant):
        if node.value is None or isinstance(node.value, _SCALAR_TYPES):
            return
        msg = f"unsupported literal {node.value!r}"
        raise VariantConditionError(msg)
    if isinstance(node, ast.List | ast.Tuple):
        for elt in node.elts:
            if not (
                isinstance(elt, ast.Constant) and isinstance(elt.value, _SCALAR_TYPES)
            ):
                msg = "a list literal may hold only scalar literals"
                raise VariantConditionError(msg)
        return
    if isinstance(node, ast.Call):
        _validate_call(node)
        return
    msg = (
        f"unsupported expression `{type(node).__name__}`; a rule condition is "
        f"comparisons, `in` / `not in`, `is None` / `is not None`, "
        f"`.startswith(…)` / `.endswith(…)`, `and` / `or` / `not`, parentheses, "
        f"nested `var.*` access and the literals `True` / `False`"
    )
    raise VariantConditionError(msg)


def _validate_call(node: ast.Call) -> None:
    """Validate a call: only the four string methods, on a ``var.*`` field."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _STR_METHODS:
        name = _dotted(func) if isinstance(func, ast.Name | ast.Attribute) else "?"
        msg = (
            f"unsupported call `{name}`: only `.startswith()`, `.endswith()`, "
            f"`.upper()` and `.lower()` on a `var.*` field are available — there "
            f"are no builtins and no filter functions in a rule condition"
        )
        raise VariantConditionError(msg)
    if not _is_var_rooted(func.value) or isinstance(func.value, ast.Name):
        msg = "a string method may only be called on a `var.*` field"
        raise VariantConditionError(msg)
    if node.keywords:
        msg = "keyword arguments are not supported"
        raise VariantConditionError(msg)
    if func.attr in _TRANSFORM_METHODS:
        if node.args:
            msg = f"`.{func.attr}()` takes no arguments"
            raise VariantConditionError(msg)
        return
    if len(node.args) != 1 or not (
        isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
    ):
        msg = f"`.{func.attr}()` takes exactly one string literal"
        raise VariantConditionError(msg)


def _refuse_non_boolean(node: ast.AST) -> None:
    """Raise for a sub-expression whose value is not a boolean."""
    if isinstance(node, ast.Name | ast.Attribute):
        name = _dotted(node)
        if not _is_var_rooted(node):
            _refuse_bare_name(name)
        msg = (
            f"`{name}` is used as a condition on its own, which is not a "
            f"boolean; compare it instead (for example `{name} == True`)"
        )
        raise VariantConditionError(msg)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        name = f"{_dotted(node.func.value)}.{node.func.attr}()"
        msg = (
            f"`{name}` returns a string, not a boolean, so it cannot be a "
            f"condition on its own; compare it instead (for example "
            f"`{name} == 'VALUE'`)"
        )
        raise VariantConditionError(msg)
    msg = (
        f"a rule condition must be boolean-valued; got "
        f"`{type(node).__name__}`. Write an explicit comparison"
    )
    raise VariantConditionError(msg)


def _validate_boolean(node: ast.AST) -> None:
    """Validate a boolean-valued sub-expression.

    ``not var.debug`` is refused even though its *top level* is boolean. The
    reason is parity: ubCode enforces the same rule over a flattened DNF, where
    a negation arrives as a negated leaf with nothing left to say whether it was
    the top level, so it refuses both. Narrower is the safe direction for a
    grammar two engines must agree on — a refused form is a configuration error
    the author rewrites once, never a silent disagreement about which documents
    exist. Corpus row: ``not var.debug`` → reject.
    """
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            _validate_boolean(value)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.Not):
            msg = "only `not` is supported as a unary operator"
            raise VariantConditionError(msg)
        _validate_boolean(node.operand)
        return
    if isinstance(node, ast.Compare):
        _validate_compare(node)
        return
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return
    if isinstance(node, ast.Call):
        # Type-aware: `.startswith()` / `.endswith()` return `bool`, so a bare
        # call IS a valid boolean top level (corpus rows 16, 17); `.upper()` /
        # `.lower()` return `str` and are not (rows 34, 35).
        _validate_call(node)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in _PREDICATE_METHODS
        ):
            return
    _refuse_non_boolean(node)


def _validate_compare(node: ast.Compare) -> None:
    """Validate a single comparison."""
    for op in node.ops:
        if not isinstance(op, _CMP_OPS + _IS_OPS):
            msg = f"unsupported comparison operator `{type(op).__name__}`"
            raise VariantConditionError(msg)
    if len(node.ops) != 1:
        msg = "chained comparisons are not supported; write them with `and`"
        raise VariantConditionError(msg)
    if isinstance(node.ops[0], _IS_OPS):
        rhs = node.comparators[0]
        if not (isinstance(rhs, ast.Constant) and rhs.value is None):
            msg = "`is` / `is not` may only be used with `None`"
            raise VariantConditionError(msg)
        _validate_operand(node.left)
        return
    _validate_operand(node.left)
    _validate_operand(node.comparators[0])


def validate(expr: str) -> ast.expr:
    """Parse and whitelist-check a rule condition.

    :param expr: The condition exactly as written in ``if = "…"``.
    :return: The validated expression node, ready for :func:`interpret`.
    :raises VariantConditionError: If the condition is outside the grammar.
    """
    text = expr.strip()
    if not text:
        msg = "the condition is empty"
        raise VariantConditionError(msg)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        msg = f"syntax error: {exc.msg}"
        raise VariantConditionError(msg) from exc
    _validate_boolean(tree.body)
    return tree.body


# ---------------------------------------------------------------------------
# Pass 2 — the interpreter
# ---------------------------------------------------------------------------


def _lookup(node: ast.AST, data: dict[str, Any]) -> Any:
    """Resolve a ``var.*`` attribute chain against the merged mapping."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    parts.reverse()
    current: Any = data
    walked: list[str] = []
    for part in parts:
        walked.append(part)
        if not isinstance(current, dict) or part not in current:
            msg = f"unknown variant data key `var.{'.'.join(walked)}`"
            raise VariantEvalError(msg)
        current = current[part]
    return current


def _string_method(node: ast.Call, data: dict[str, Any]) -> Any:
    """Evaluate one of the four whitelisted string methods."""
    func = node.func
    if not isinstance(func, ast.Attribute):  # pragma: no cover - validate() forbids it
        msg = "a string method may only be called on a `var.*` field"
        raise VariantEvalError(msg)
    receiver = _lookup(func.value, data)
    name = func.attr
    if not isinstance(receiver, str):
        msg = (
            f"`.{name}()` needs a string; "
            f"`{_dotted(func.value)}` is a {type(receiver).__name__}"
        )
        raise VariantEvalError(msg)
    if name == "upper":
        return receiver.upper()
    if name == "lower":
        return receiver.lower()
    argument = node.args[0]
    literal = argument.value if isinstance(argument, ast.Constant) else ""
    if name == "startswith":
        return receiver.startswith(literal)
    return receiver.endswith(literal)


def _operand(node: ast.AST, data: dict[str, Any]) -> Any:
    """Evaluate one comparison operand."""
    if isinstance(node, ast.Attribute):
        return _lookup(node, data)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List | ast.Tuple):
        return [elt.value for elt in node.elts if isinstance(elt, ast.Constant)]
    if isinstance(node, ast.Call):
        return _string_method(node, data)
    msg = f"cannot evaluate `{type(node).__name__}`"
    raise VariantEvalError(msg)


#: Comparison dispatch. The *semantics* are Python's own — only the lookup is
#: ours — so the grammar cannot drift from what an ``eval``-based reader of the
#: same string would compute.
_COMPARATORS: dict[type[ast.cmpop], Callable[[Any, Any], Any]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}


def _compare(op: ast.cmpop, left: Any, right: Any) -> bool:
    """Apply one comparison operator.

    A :class:`TypeError` (comparing a string with a number, say) becomes an
    *evaluation* error, which excludes — the same side of the line an unknown
    key is on, and for the same reason: it is the data that refuses, not the
    grammar.
    """
    apply = _COMPARATORS.get(type(op))
    if apply is None:  # pragma: no cover - validate() forbids it
        msg = f"unsupported comparison operator `{type(op).__name__}`"
        raise VariantEvalError(msg)
    try:
        return bool(apply(left, right))
    except TypeError as exc:
        msg = f"type mismatch: {exc}"
        raise VariantEvalError(msg) from exc


def interpret(node: ast.expr, data: dict[str, Any]) -> bool:
    """Evaluate a validated condition against the merged variant data.

    :param node: The node :func:`validate` returned.
    :param data: The merged variant map — a plain mapping, not a proxy.
    :raises VariantEvalError: On an unknown key or a type mismatch.
    """
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(interpret(value, data) for value in node.values)
        return any(interpret(value, data) for value in node.values)
    if isinstance(node, ast.UnaryOp):
        return not interpret(node.operand, data)
    if isinstance(node, ast.Compare):
        left = _operand(node.left, data)
        right = _operand(node.comparators[0], data)
        return _compare(node.ops[0], left, right)
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.Call):
        return bool(_operand(node, data))
    msg = f"cannot evaluate `{type(node).__name__}`"
    raise VariantEvalError(msg)


def evaluate(expr: str, data: dict[str, Any]) -> bool:
    """Validate and evaluate ``expr`` in one call. Convenience for tests."""
    return interpret(validate(expr), data)


# ---------------------------------------------------------------------------
# Variant data — a private copy of sphinx-needs' semantics
# ---------------------------------------------------------------------------


def validate_variant_data(data: Any, path: str = "var") -> None:
    """Check that ``data`` has the shape a variant map is allowed to have.

    Keys must be strings; leaves must be ``str`` / ``bool`` / ``int`` /
    ``float``; a list must be empty or uniform-scalar; nested mappings recurse.

    :raises VariantDataError: On any violation, naming the dotted path.
    """
    if not isinstance(data, dict):
        msg = f"{path}: expected a mapping, got {type(data).__name__}"
        raise VariantDataError(msg)
    for key, value in data.items():
        if not isinstance(key, str):
            msg = f"{path}: all keys must be strings, got {type(key).__name__}"
            raise VariantDataError(msg)
        full = f"{path}.{key}"
        if isinstance(value, dict):
            validate_variant_data(value, full)
        elif isinstance(value, list):
            _validate_variant_list(value, full)
        elif not isinstance(value, _SCALAR_TYPES):
            msg = (
                f"{full}: expected str/bool/int/float/list/mapping, "
                f"got {type(value).__name__}"
            )
            raise VariantDataError(msg)


def _validate_variant_list(value: list[Any], full: str) -> None:
    """An array must be empty, or uniform and scalar."""
    if not value:
        return
    first_type = type(value[0])
    if first_type not in _SCALAR_TYPES:
        msg = (
            f"{full}: array elements must be str/bool/int/float, "
            f"got {first_type.__name__}"
        )
        raise VariantDataError(msg)
    for index, item in enumerate(value):
        if type(item) is not first_type:
            msg = (
                f"{full}[{index}]: expected {first_type.__name__}, got "
                f"{type(item).__name__} (arrays must be uniform type)"
            )
            raise VariantDataError(msg)


def load_variant_data_file(path: Path) -> dict[str, Any]:
    """Load a variant-data JSON file and validate its shape.

    JSON only, and the top level must be an object — the same three failures
    sphinx-needs reports (missing file, undecodable JSON, non-object).

    :raises VariantDataError: On any of them.
    """
    if not path.is_file():
        msg = f"variant data file not found: {path}"
        raise VariantDataError(msg)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"invalid JSON in {path}: {exc}"
        raise VariantDataError(msg) from exc
    except OSError as exc:  # pragma: no cover - defensive
        msg = f"could not read {path}: {exc}"
        raise VariantDataError(msg) from exc
    if not isinstance(raw, dict):
        msg = (
            f"variant data file must contain a JSON object, "
            f"got {type(raw).__name__}: {path}"
        )
        raise VariantDataError(msg)
    validate_variant_data(raw)
    return raw


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``override`` into ``base``; ``override`` wins at the leaves.

    Recurses **only when both sides are mappings**. Everything else is a
    wholesale replacement — a list replaces a list entirely, a scalar replaces
    a mapping and vice versa. That is sphinx-needs' rule, reproduced exactly,
    and it is what makes the merge idempotent (see
    :func:`resolve_variant_data`).
    """
    result = base.copy()
    for key, value in override.items():
        existing = result.get(key)
        if key in result and isinstance(existing, dict) and isinstance(value, dict):
            result[key] = deep_merge(existing, value)
        else:
            result[key] = value
    return result


def resolve_variant_data(
    inline: Any,
    file_ref: Path | None,
) -> dict[str, Any]:
    """Compute the merged variant map: file first, inline deep-merged on top.

    The merge is **unconditional**, and that is the whole trick. Three worlds
    have to give the same answer:

    * sphinx-needs absent — nothing else computes the map, so this is the whole
      computation;
    * sphinx-needs installed but not yet resolving at ``config-inited``
      (every release up to and including 8.3.1) — ``needs_variant_data`` holds
      the *inline* half only, and this supplies the merge it has not performed;
    * sphinx-needs resolving at ``config-inited`` (post-#1787) —
      ``needs_variant_data`` is already merged, and re-merging it is a no-op,
      because ``deep_merge(file, already_merged) == already_merged`` for every
      shape ``deep_merge`` can produce.

    So there is no version sniffing, no import of sphinx-needs and no feature
    detection, and the answer always agrees with whatever sphinx-needs computed.
    ``tests/test_variant_data.py`` pins all three cells plus the idempotency.

    :param inline: The inline mapping (``needs_variant_data`` or the TOML's
        ``[needs.variant_data]`` table). ``None`` and ``{}`` both mean "none".
    :param file_ref: An **already anchored** absolute path, or ``None``. The
        two anchors are the caller's business — see
        :func:`sphinx_mounts.config.load_variant_sources_from_toml`.
    :raises VariantDataError: If the file or the inline mapping is malformed.
    """
    base: dict[str, Any] = {}
    if file_ref is not None:
        base = load_variant_data_file(file_ref)
    if inline:
        validate_variant_data(inline)
    return deep_merge(base, inline or {})

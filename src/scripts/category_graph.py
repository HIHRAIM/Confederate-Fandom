"""The category tree, as text and as a graph — Pywikibot's category_graph.py.

    Pywikibot's category_graph.py is (C) Pywikibot team, 2021-2025, MIT
    licence. It walks a category down to a depth and writes the tree, either
    as an indented list or in Graphviz's DOT language. Both are kept; the
    picture is not, because rendering DOT needs Graphviz installed and the bot
    must not depend on a program its host may not have. The .dot file opens in
    any of the online viewers, and in Graphviz where somebody has it.

Standalone: it asks the wiki for the tree itself and needs no page list.

A category tree is a graph and not a tree — categories on a wiki are
routinely each other's ancestors — so a category already seen is written once
and marked, and the walk does not go round it again. Without that the file
grows until the disk stops it, which is what a loop in a category tree does to
a naive walk.
"""
import sys

from tasks import mechanic as mech
from tasks.params import CHOICE, INT, TEXT, Param

TREE = "tree"
DOT = "dot"

DEFAULT_DEPTH = 3

MAX_NODES = 20000


def prepare(ctx):
    """Check that there is a category to start from."""
    root = (ctx.params.get("graph_root") or "").strip().lstrip(":")
    if not root:
        raise ValueError("не указана категория, с которой начинать")
    return root


def _walk(ctx, root, depth):
    """The tree under one category. -> a list of (level, title, seen before).

    Depth-first, because that is the order a person reads an indented list in.
    """
    import pywikibot

    seen = set()
    out = []
    stack = [(0, pywikibot.Category(ctx.site, root))]
    while stack and len(out) < MAX_NODES:
        level, category = stack.pop()
        title = category.title(with_ns=False)
        already = title in seen
        out.append((level, title, already))
        if already or level >= depth:
            continue
        seen.add(title)
        try:
            children = sorted(category.subcategories(),
                              key=lambda c: c.title(), reverse=True)
        except Exception as e:
            out.append((level + 1, "не удалось прочитать: {}".format(
                type(e).__name__), True))
            continue
        for child in children:
            stack.append((level + 1, child))
    return out


def finish(ctx):
    """Build the tree and return the lines of the report file."""
    root = ctx.state.get(SPEC.code)
    depth = int(ctx.params.get("graph_depth") or DEFAULT_DEPTH)
    shape = ctx.params.get("graph_shape") or TREE
    nodes = _walk(ctx, root, depth)

    ctx.note("категорий в дереве: {}".format(len(nodes)))
    if len(nodes) >= MAX_NODES:
        ctx.note("дерево обрезано на {} категориях".format(MAX_NODES))

    if shape == DOT:
        lines = ["digraph categories {", '  rankdir="LR";']
        parents = {}
        for level, title, _already in nodes:
            parents[level] = title
            if level:
                lines.append('  "{}" -> "{}";'.format(
                    parents.get(level - 1, root).replace('"', "'"),
                    title.replace('"', "'")))
        lines.append("}")
        return lines

    return ["{}{}{}".format("  " * level, title,
                            "  (уже выше в дереве)" if already else "")
            for level, title, already in nodes]


SPEC = mech.Mechanic(
    code="category-graph",
    kind=mech.REPORT,
    module=sys.modules[__name__],
    rights=(),
    standalone=True,
    params=(
        Param("graph_root", TEXT, "param_graph_root"),
        Param("graph_depth", INT, "param_graph_depth",
              default=DEFAULT_DEPTH, minimum=1, maximum=10),
        Param("graph_shape", CHOICE, "param_graph_shape", options=(
            (TREE, "graph_shape_tree"),
            (DOT, "graph_shape_dot"),
        ), default=TREE),
    ),
)

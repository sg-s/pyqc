import ast
import builtins
import glob
import os

from beartype import beartype
from beartype.typing import List, Optional, Tuple
from stdlib_list import stdlib_list

builtin_things = dir(builtins)


@beartype
def import_mapper(exprs: List) -> dict:
    """parses expressions and returns a mapper
    b/w imported names and full names"""

    mapper = dict()

    for expr in exprs:
        if not isinstance(expr, ast.ImportFrom):
            continue
        names = [name.name for name in expr.names]
        asnames = [name.asname for name in expr.names]

        for name, asname in zip(names, asnames):
            if asname is None:
                mapper[name] = expr.module + "." + name
            else:
                mapper[asname] = expr.module + "." + name

    return mapper


@beartype
def find_function_calls(
    *,
    exprs: List,
    lines: List[str],
    mapper: Optional[dict] = None,
    module_name: str,
) -> List:
    """scans a list of expression for function calls

    returns a list of function calls

    mapper is a dictionary that maps short names to
    fully qualified names. if not provided, it will be
    inferred from the expressions here.
    """

    if module_name.endswith(".py"):
        module_name = module_name.replace(".py", "")

    if mapper is None:
        mapper = import_mapper(exprs)

    function_calls = []

    for expr in exprs:
        # do we have to go one level deeper?
        if isinstance(expr, (ast.Try, ast.For)):
            function_calls.extend(
                find_function_calls(
                    exprs=expr.body,
                    lines=lines,
                    mapper=mapper,
                    module_name=module_name,
                )
            )

        if not isinstance(expr, (ast.Assign, ast.Expr)):
            continue
        value = expr.value

        if not isinstance(value, ast.Call):
            continue

        # special case where a function is called in a
        # multi-line fashion, with a trailing (

        # python is 0 indexed, so account for that
        line_number = value.lineno - 1

        if lines[line_number][-1] == "(":
            z = len(lines[line_number])
        else:
            z = value.end_col_offset
        function_call = lines[line_number][value.col_offset : z]

        # print("================")
        # print(expr.lineno)
        # print(f"end col offset = {z}")
        # print(f"start col offset = {value.col_offset}")
        # rint(function_call)

        z = function_call.find("(")
        function_call = function_call[:z]

        if "." in function_call:
            # this function is a complex call, so
            # need to figure out the root

            chunks = function_call.split(".")
            if chunks[0] in mapper.keys():
                chunks[0] = mapper[chunks[0]]

            if chunks[0] not in stdlib_list():
                function_calls.append(".".join(chunks))
        else:
            if function_call in mapper.keys():
                function_calls.append(mapper[function_call])
            elif function_call not in builtin_things:
                # this is a function to a call
                # to an unqualified function name.
                # let's check if this function exists
                # in this module
                if f"def {function_call}(" in "\n".join(lines):
                    function_calls.append(module_name + "." + function_call)
                else:
                    # print("WARNING. Could not find function:")
                    # print(function_call)
                    function_calls.append(function_call)
    return function_calls


@beartype
def parse_py_file(py_file: str) -> Tuple[List, List]:
    """utility to convert a python file to a list of
    expressions"""

    with open(py_file) as file:
        data = file.read()

    lines = data.splitlines()
    m = ast.parse(data)
    expressions = m.body

    return expressions, lines


@beartype
def find_function_calls_in_py_file(
    *,
    py_file: str,
    repo_root: str,
) -> dict:
    expressions, lines = parse_py_file(py_file)

    module_name = py_file.replace(repo_root, "")
    module_name = module_name.replace("/", ".")
    module_name = module_name.replace(".py", "")

    # remove leading .
    if module_name[0] == ".":
        module_name = module_name[1:]

    call_graph = dict()

    # figure out how to map imports
    mapper = import_mapper(expressions)

    # first do main -- functions called in the main module,
    # outside of any function
    call_graph[f"{module_name}.main"] = find_function_calls(
        exprs=expressions,
        lines=lines,
        module_name=module_name,
    )

    # now do functions in this module
    for expression in expressions:
        if isinstance(expression, ast.FunctionDef):
            func_name = expression.name
            call_graph[f"{module_name}.{func_name}"] = find_function_calls(
                exprs=expression.body,
                lines=lines,
                mapper=mapper,
                module_name=module_name,
            )

    return call_graph


@beartype
def find_function_calls_in_repo(repo_root: str) -> dict:
    """finds all function calls in a repo

    scans all .py files in the repo"""

    py_files = glob.glob(os.path.join(repo_root, "**", "*.py"))

    call_graph = dict()

    for py_file in py_files:
        call_graph = call_graph | find_function_calls_in_py_file(
            py_file=py_file,
            repo_root=repo_root,
        )

    # clean up the call graph to remove
    # all nodes with zero out degree
    remove_keys = []
    for key in call_graph.keys():
        if call_graph[key] == []:
            remove_keys.append(key)

    for key in remove_keys:
        call_graph.pop(key, None)

    return call_graph


@beartype
def find_functions_in_repo(repo_root: str) -> List[str]:
    """finds all function definitions in a repo

    returns a list of fully qualified names for every
    function that is defined in this repo
    """

    py_files = glob.glob(os.path.join(repo_root, "**", "*.py"))

    functions = []
    for py_file in py_files:
        functions_in_file = find_functions_in_file(py_file)

        namespace = (
            py_file.replace(repo_root, "").replace("/", ".").replace(".py", "")
        )

        # remove leading .
        if namespace[0] == ".":
            namespace = namespace[1:]

        functions_in_file = [
            namespace + "." + thing for thing in functions_in_file
        ]
        functions.extend(functions_in_file)

    return functions


def find_functions_in_file(py_file: str) -> List[str]:
    """find all functions defined in a py file"""

    functions = []
    expressions, _ = parse_py_file(py_file)

    for expression in expressions:
        if not isinstance(expression, ast.FunctionDef):
            continue

        functions.append(expression.name)
    return functions


@beartype
def make_call_graph(
    *,
    repo_root: str,
    exclude: Optional[List[str]] = None,
):
    functions = find_functions_in_repo(repo_root)

    call_graph = find_function_calls_in_repo(repo_root)

    # remove values from call graph that don't exist
    # in function list
    remove_keys = []
    for key in call_graph.keys():
        call_graph[key] = set(call_graph[key]).intersection(set(functions))
        if len(call_graph[key]) == 0:
            remove_keys.append(key)

    for key in remove_keys:
        call_graph.pop(key, None)

    # remove keys that conform to exclude
    if exclude is not None:
        remove_keys = []
        for thing in exclude:
            for key in call_graph.keys():
                if thing in key:
                    remove_keys.append(key)
        remove_keys = list(set(remove_keys))
        for key in remove_keys:
            call_graph.pop(key, None)

    return call_graph


def call_graph_to_mermaid(call_graph: dict) -> str:
    txt = ["flowchart LR"]

    # declare all nodes
    all_nodes = list(call_graph.keys())
    for key in call_graph.keys():
        all_nodes.extend(call_graph[key])

    all_nodes = list(set(all_nodes))

    for node in all_nodes:
        txt.append(node)

    # now declare all edges
    for key in call_graph.keys():
        values = call_graph[key]
        for value in values:
            edge = f"{key} --> {value}"
            txt.append(edge)

    with open("/Users/srinivas/Desktop/graph.txt", "w") as file:
        file.write("\n".join(txt))

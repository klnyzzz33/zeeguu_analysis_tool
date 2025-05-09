import ast
import json
import os
import sys
from collections import defaultdict

from pyvis.network import Network

skip_analyze = [".githooks", ".github", ".venv"]


class Module:
    def __init__(self, name, path=None):
        self.name = name
        self.path = path
        self.exports = []
        self.internal_imports = []
        self.external_imports = []
        self.method_calls = defaultdict(int)
        self.dependencies = []
        self.LOC = 0

    def to_dict(self):
        return {
            "name": self.name,
            "path": self.path,
            "exports": self.exports,
            "internal_imports": ["module: " + str(module.name) + ", submodule: " + str(submodule) + ", alias: "
                                 + str(alias) for (module, submodule, alias) in self.internal_imports],
            "external_imports": self.external_imports,
            "method_calls": self.method_calls,
            "dependencies": self.dependencies,
            "LOC": self.LOC
        }

    def __str__(self):
        return json.dumps(self.to_dict(), indent=2)

    def __repr__(self):
        return self.__str__()


class CustomVisitor(ast.NodeVisitor):
    def __init__(self, module, module_names):
        self.module = module
        self.module_names = module_names
        self.loc_exclude = set()

    def visit_Import(self, node):
        for alias in node.names:
            import_entry = (alias.name, None, alias.asname)
            if alias.name in self.module_names:
                self.module.internal_imports.append(import_entry)
            else:
                self.module.external_imports.append(import_entry)

        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            import_entry = (node.module, alias.name, alias.asname)
            if node.module in self.module_names:
                self.module.internal_imports.append(import_entry)
            else:
                self.module.external_imports.append(import_entry)

        self.generic_visit(node)

    def visit_Call(self, node):
        method_name = None
        if isinstance(node.func, ast.Name):
            method_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            full_name = []
            current = node.func
            while isinstance(current, ast.Attribute):
                full_name.insert(0, current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                full_name.insert(0, current.id)
            method_name = ".".join(full_name)

        if method_name and not method_name.startswith("self."):
            self.module.method_calls[method_name] += 1

        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._exclude_docstring(node)

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._exclude_docstring(node)

        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self._exclude_docstring(node)

        self.generic_visit(node)

    def _exclude_docstring(self, node):
        docstring = ast.get_docstring(node, clean=False)
        if docstring:
            doc_node = node.body[0]
            self.loc_exclude.update(range(doc_node.lineno, doc_node.end_lineno + 1))

    def generic_visit(self, node):
        if hasattr(node, 'lineno') and node.lineno not in self.loc_exclude:
            self.module.LOC += 1
        super().generic_visit(node)


def get_exports_from_modules_recursive(base_dir, parent_package):
    result = {}

    files = os.listdir(base_dir)
    is_package = False
    for file in files:
        if file == "__init__.py":
            is_package = True
            basename = os.path.basename(base_dir)
            parent_package = parent_package + "." + basename if parent_package != "" else basename
            break

    for file in files:
        full_path = os.path.join(base_dir, file)
        sub_package_name = parent_package + "." + file if parent_package != "" else file
        if is_package and file.endswith(".py"):
            module_name = sub_package_name
            module_name = module_name.replace(os.sep, ".")
            module_name = module_name.replace(".__init__.py", "")
            module_name = module_name.replace(".py", "")

            with open(full_path, mode="r", encoding="utf-8") as f:
                function_defs = []
                tree = ast.parse(f.read())
                for node in tree.body:
                    if isinstance(node, ast.FunctionDef):
                        function_defs.append(node.name)

                module = Module(module_name, full_path)
                module.exports = function_defs
                result[module_name] = module
        elif os.path.isdir(full_path) and file not in skip_analyze:
            result.update(get_exports_from_modules_recursive(full_path, parent_package))

    return result


def parse_method_calls_in_modules(modules):
    module_names = list(modules.keys())
    result = {}

    for (module_name, module) in modules.items():
        with open(module.path, mode="r", encoding="utf-8") as f:
            source_tree = ast.parse(f.read())
            visitor = CustomVisitor(module, module_names)
            visitor.visit(source_tree)

            result[module_name] = visitor.module

    return result


def resolve_internal_imports(modules):
    result = {}

    for (module_name, module) in modules.items():
        modified_module = module
        resolved_internal_imports = []
        for (import_module_name, submodule, import_alias) in module.internal_imports:
            resolved_internal_imports.append((modules[import_module_name], submodule, import_alias))

        modified_module.internal_imports = resolved_internal_imports
        result[module_name] = modified_module

    return result


def calculate_dependencies(modules):
    result = {}
    module_names = list(modules.keys())

    for (module_name, module) in modules.items():
        modified_module = module
        dependencies = defaultdict(int)
        internal_imports = module.internal_imports
        for (method_name, method_call_count) in module.method_calls.items():
            dependency = None

            pos = method_name.rfind('.')
            if pos != -1:
                dependency_name = method_name[:pos]
                dependency = handle_qualified_call(modules, module_names, internal_imports, dependency_name)
            else:
                dependency = handle_unqualified_call(internal_imports, method_name)

            if dependency:
                dependencies[dependency] += method_call_count

        modified_module.dependencies = dependencies
        result[module_name] = modified_module

    return result


def handle_qualified_call(modules, module_names, internal_imports, dependency_name):
    dependency = None

    for (import_module, import_submodule, import_alias) in reversed(internal_imports):
        if import_alias == dependency_name:
            if import_submodule:
                qualified_name = import_module.name + '.' + import_submodule
                if qualified_name in module_names:
                    dependency = modules[qualified_name].name
                    break
            else:
                dependency = import_module.name
                break
        elif import_submodule == dependency_name:
            qualified_name = import_module.name + '.' + import_submodule
            if qualified_name in module_names:
                dependency = modules[qualified_name].name
                break
        elif import_module.name == dependency_name:
            dependency = import_module.name
            break

    return dependency


def handle_unqualified_call(internal_imports, method_name):
    dependency = None

    for (import_module, import_submodule, import_alias) in reversed(internal_imports):
        if import_alias == method_name:
            dependency = import_module.name
            break
        elif import_submodule == '*' or import_submodule == method_name:
            for export in import_module.exports:
                if export == method_name:
                    dependency = import_module.name
                    break
            if dependency:
                break

    return dependency


def aggregate_modules_by_level(modules, level):
    aggregated = {}

    group_map = defaultdict(list)
    for module in modules.values():
        parts = module.name.split(".")
        group_key = ".".join(parts[:level])
        group_map[group_key].append(module)

    for group_key, module_list in group_map.items():
        agg_module = Module(name=group_key)
        agg_module.LOC = 0
        agg_module.dependencies = defaultdict(int)

        for mod in module_list:
            agg_module.LOC += mod.LOC

            for dep, weight in mod.dependencies.items():
                dep_key = ".".join(dep.split(".")[:level])
                if dep_key != group_key:
                    agg_module.dependencies[dep_key] += weight

        aggregated[group_key] = agg_module

    return aggregated


def create_graph(modules):
    g = Network(directed=True)
    g.force_atlas_2based(gravity=-50, central_gravity=0.01, spring_length=150, spring_strength=0.08, damping=0.4)

    max_loc = 0
    max_dependencies = 0
    for module in modules.values():
        if module.LOC > max_loc:
            max_loc = module.LOC
        for count in module.dependencies.values():
            if count > max_dependencies:
                max_dependencies = count

    node_sizes = {}
    for module in modules.values():
        size = (module.LOC / max_loc) * 50 + 10
        font_size = (module.LOC / max_loc) * 20 + 10
        node_sizes[module.name] = size
        g.add_node(
            module.name,
            label=module.name,
            size=size,
            font={"size": font_size}
        )

    for module in modules.values():
        for dependency, count in module.dependencies.items():
            edge_width = (count / max_dependencies) * 5 + 1
            font_size = (count / max_dependencies) * 15 + 10
            from_size = node_sizes[module.name]
            to_size = node_sizes[dependency]
            base_length = 300 - (count / max_dependencies) * 100
            edge_length = from_size + to_size + base_length
            g.add_edge(
                module.name,
                dependency,
                width=edge_width,
                label=str(count),
                font={"size": font_size},
                arrows={"to": {"enabled": True, "scaleFactor": 0.35}},
                arrowStrikethrough=False,
                smooth={"enabled": False},
                length=edge_length
            )

    g.show("module_view.html")


def main():
    input_params = sys.argv
    if len(input_params) < 2:
        print("Usage: python recover_module_view.py <repo_dir>")
        exit(1)

    repo_dir = input_params[1]
    modules = get_exports_from_modules_recursive(repo_dir, "")

    modules = parse_method_calls_in_modules(modules)

    modules = resolve_internal_imports(modules)

    modules = calculate_dependencies(modules)

    # print(modules)

    modules = aggregate_modules_by_level(modules, 2)

    create_graph(modules)


if __name__ == "__main__":
    main()

# TODO
# 1. handling class imports
# 2. handle imports from __init__.py files
# 3. (optional) make it possible to aggregate subpackages with different levels (like archlens)

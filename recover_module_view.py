import ast
import json
import os
import sys
from collections import defaultdict

from pyvis.network import Network


class Module:
    def __init__(self, name, path=None):
        self.name = name
        self.path = path
        self.method_defs = set()
        self.exports = set()
        self.internal_imports = []
        self.external_imports = []
        self.method_calls = defaultdict(int)
        self.dependencies = defaultdict(int)
        self.LOC = 0
        self.is_package = False
        self.explore_queue = []

    def to_dict(self):
        return {
            "name": self.name,
            "path": self.path,
            "method_defs": list(self.method_defs),
            "exports": list(self.exports),
            "internal_imports": ["module: " + str(module.name) + ", submodule: " + str(submodule) + ", alias: "
                                 + str(alias) for (module, submodule, alias) in self.internal_imports],
            "external_imports": self.external_imports,
            "method_calls": self.method_calls,
            "dependencies": self.dependencies,
            "LOC": self.LOC,
            "is_package": self.is_package,
        }

    def __str__(self):
        return json.dumps(self.to_dict(), indent=2)

    def __repr__(self):
        return self.__str__()


class CustomVisitor(ast.NodeVisitor):
    def __init__(self, module, modules):
        self.module = module
        self.modules = modules
        self.loc_lines = set()
        self.loc_exclude = set()

    def visit_Import(self, node):
        module_names = self.modules.keys()
        for alias in node.names:
            import_entry = (alias.name, None, alias.asname)
            if alias.name in module_names:
                self.module.internal_imports.append(import_entry)

                if alias.asname:
                    self.module.exports.add(alias.asname)
            else:
                self.module.external_imports.append(import_entry)

        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module_names = self.modules.keys()
        for alias in node.names:
            if node.level > 0:
                cut_index = node.level if not self.module.is_package else node.level - 1
                base_module_name = self.module.name.split(".")[:-cut_index] \
                    if cut_index > 0 else self.module.name.split(".")

                node.module = ".".join(base_module_name + ([node.module] if node.module else []))

            import_entry = (node.module, alias.name, alias.asname)
            if node.module in module_names:
                self.module.internal_imports.append(import_entry)

                if alias.asname:
                    self.module.exports.add(alias.asname)
                elif alias.name:
                    if alias.name != "*":
                        self.module.exports.add(alias.name)
                    else:
                        self.module.explore_queue.append(node.module)
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
            elif isinstance(current, ast.Call):
                return self.generic_visit(node)
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
        if hasattr(node, 'lineno') and node.lineno not in self.loc_lines and node.lineno not in self.loc_exclude:
            self.loc_lines.add(node.lineno)

        super().generic_visit(node)


def get_star_exports(module_name, modules, visited=set()):
    if module_name in visited:
        return []
    visited.add(module_name)

    module = modules[module_name]
    exports = module.exports

    for (import_module_name, submodule, import_alias) in module.internal_imports:
        if submodule == "*":
            exports.update(get_star_exports(import_module_name, modules, visited))

    return exports


def get_top_level_exports_from_modules(base_dir, parent_package, skip_analyze=[]):
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
                method_defs = set()
                source_tree = ast.parse(f.read())
                for node in source_tree.body:
                    if isinstance(node, ast.FunctionDef):
                        method_defs.add(node.name)

                module = Module(module_name, full_path)
                module.method_defs = method_defs
                module.exports = method_defs.copy()
                if file == "__init__.py":
                    module.is_package = True
                result[module_name] = module
        elif os.path.isdir(full_path) and file not in skip_analyze:
            result.update(get_top_level_exports_from_modules(full_path, parent_package, skip_analyze))

    return result


def parse_imports_and_method_calls(modules):
    result = {}

    for (module_name, module) in modules.items():
        with open(module.path, mode="r", encoding="utf-8") as f:
            source_tree = ast.parse(f.read())
            visitor = CustomVisitor(module, modules)
            visitor.visit(source_tree)
            visitor.module.LOC = len(visitor.loc_lines)

            result[module_name] = visitor.module

    for (module_name, module) in result.items():
        for mod in module.explore_queue:
            module.exports.update(get_star_exports(mod, modules))

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
        internal_imports = module.internal_imports
        dependencies = {imp[0].name: 0 for imp in internal_imports}
        for (method_name, method_call_count) in module.method_calls.items():
            dependency = None

            pos = method_name.rfind('.')
            if pos != -1:
                dependency_name = method_name[:pos]
                dependency = handle_qualified_call(module_names, internal_imports, dependency_name)
            else:
                dependency = handle_unqualified_call(module.method_defs, internal_imports, method_name)

            if dependency:
                dependencies[dependency] += method_call_count

        modified_module.dependencies = dependencies
        result[module_name] = modified_module

    return result


def handle_qualified_call(module_names, internal_imports, dependency_name):
    for (import_module, import_submodule, import_alias) in reversed(internal_imports):
        if import_alias == dependency_name:
            if import_submodule:
                dependency = import_module.name + '.' + import_submodule
                if dependency in module_names:
                    return dependency
            return import_module.name
        elif import_submodule == dependency_name:
            dependency = import_module.name + '.' + import_submodule
            if dependency in module_names:
                return dependency
            return import_module.name
        elif import_module.name == dependency_name:
            return import_module.name
        elif import_submodule == '*':
            for export in import_module.exports:
                if export == dependency_name:
                    return import_module.name

    return None


def handle_unqualified_call(method_defs, internal_imports, method_name):
    if method_name in method_defs:
        return None

    for (import_module, import_submodule, import_alias) in reversed(internal_imports):
        if import_alias == method_name or import_submodule == method_name:
            return import_module.name
        elif import_submodule == '*':
            for export in import_module.exports:
                if export == method_name:
                    return import_module.name

    return None


def aggregate_modules_by_levels(modules, levels, only_aggregates):
    aggregated = {}

    group_map = defaultdict(list)
    for module in modules.values():
        group_key = get_aggregate_key(module.name, levels, only_aggregates)
        if group_key:
            group_map[group_key].append(module)

    for group_key, module_list in group_map.items():
        agg_module = Module(name=group_key)
        agg_module.LOC = 0
        agg_module.dependencies = defaultdict(int)

        for mod in module_list:
            agg_module.LOC += mod.LOC

            for dep_name, weight in mod.dependencies.items():
                dep_group_key = get_aggregate_key(dep_name, levels, only_aggregates)
                if dep_group_key and dep_group_key != group_key:
                    agg_module.dependencies[dep_group_key] += weight

        aggregated[group_key] = agg_module

    return aggregated


def get_aggregate_key(module_name, levels, only_aggregates=False):
    group_key = module_name
    parts = module_name.split(".")

    for i in range(1, len(parts) + 1):
        sub_module = ".".join(parts[:i])
        if sub_module in levels.keys():
            depth_limit = i + levels[sub_module]
            if len(parts) > depth_limit:
                group_key = ".".join(parts[:depth_limit])
            break
        elif only_aggregates:
            group_key = None

    return group_key


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
            color = "blue" if count > 0 else "grey"
            arrow_setting = {"to": {"enabled": True, "scaleFactor": 0.35}} if count > 0 else None
            label = str(count) if count > 0 else None
            g.add_edge(
                module.name,
                dependency,
                width=edge_width,
                font={"size": font_size},
                arrowStrikethrough=False,
                smooth={"enabled": True},
                length=edge_length,
                color=color,
                arrows=arrow_setting,
                label=label
            )

    g.show("module_view.html")


def main():
    input_params = sys.argv
    if len(input_params) < 2:
        print("Usage: python recover_module_view.py <repo_dir>")
        exit(1)
    repo_dir = input_params[1]

    with open("settings.json", mode="r", encoding="utf-8") as f:
        config = json.load(f)

        skip_analyze = config["skip_analyze"]
        modules = get_top_level_exports_from_modules(repo_dir, "", skip_analyze)

        modules = parse_imports_and_method_calls(modules)

        modules = resolve_internal_imports(modules)

        modules = calculate_dependencies(modules)

        levels = config["levels"]
        only_aggregates = config["only_aggregates"]
        modules = aggregate_modules_by_levels(modules, levels, only_aggregates)

        create_graph(modules)


if __name__ == "__main__":
    main()

# TODO
# 1. handling class imports

import sys
import os
import ast
import json
from collections import defaultdict


class Module:
    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.exports = []
        self.internal_imports = []
        self.external_imports = []
        self.method_calls = []
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
        elif os.path.isdir(full_path):
            result.update(get_exports_from_modules_recursive(full_path, parent_package))

    return result


def parse_method_calls_in_modules(modules):
    module_names = list(modules.keys())
    result = {}

    for (module_name, module) in modules.items():
        with open(module.path, mode="r", encoding="utf-8") as f:
            modified_module = module
            loc_exclude = set()
            loc = set()

            method_call_count = defaultdict(int)

            source_tree = ast.parse(f.read())
            for node in ast.walk(source_tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in module_names:
                            modified_module.internal_imports.append((alias.name, None, alias.asname))
                        else:
                            modified_module.external_imports.append((alias.name, None, alias.asname))
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if node.module in module_names:
                            modified_module.internal_imports.append((node.module, alias.name, alias.asname))
                        else:
                            modified_module.external_imports.append((node.module, alias.name, alias.asname))
                elif isinstance(node, ast.Call):
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

                    # We do not care about method calls that start with 'self.', since it's for sure defined inside the current file
                    if method_name and not method_name.startswith("self."):
                        method_call_count[method_name] += 1
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                    has_docstring = ast.get_docstring(node, clean=False)
                    if has_docstring:
                        docstring = node.body[0]
                        loc_exclude.update(list(range(docstring.lineno, docstring.end_lineno + 1)))

                if hasattr(node, 'lineno') and node.lineno not in loc_exclude:
                    loc.add(node.lineno)

            modified_module.method_calls = method_call_count
            modified_module.LOC = len(loc)
            result[module_name] = modified_module

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

    for (module_name, module) in modules.items():
        modified_module = module
        dependencies = defaultdict(int)
        internal_imports = module.internal_imports
        for (method_name, method_call_count) in module.method_calls.items():
            pos = method_name.rfind('.')
            dependency = None
            if pos != -1:
                dependency_name = method_name[:pos]
                dependency = next((module.name for (module, _, alias) in internal_imports
                                if module.name == dependency_name or alias == dependency_name), None)
                # TODO ide jön az utolsó case
            else:
                # itt export vizsgálat
                for (import_module, import_submodule, import_alias) in reversed(internal_imports):
                    if import_submodule == '*' or import_submodule == method_name:
                        for export in import_module.exports:
                            if export == method_name:
                                dependency = import_module.name
                                break
                        if dependency:
                            break
                    elif import_alias == method_name:
                        dependency = import_module.name
                        break
            dependencies[dependency] += method_call_count

        modified_module.dependencies = dependencies
        result[module_name] = modified_module

    return result


def main():
    input_params = sys.argv
    if len(input_params) < 2:
        print("Usage: python index_modules.py <repo_dir>")
        exit(1)

    repo_dir = input_params[1]
    modules = get_exports_from_modules_recursive(repo_dir, "")

    modules = parse_method_calls_in_modules(modules)

    modules = resolve_internal_imports(modules)

    modules = calculate_dependencies(modules)

    print(json.dumps([module.to_dict() for module in modules.values()], indent=2))


if __name__ == "__main__":
    main()

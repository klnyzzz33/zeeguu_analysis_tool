import sys
import os
import ast


class Module:
    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.exports = []
        self.imports = []
        self.method_calls = []

    def __str__(self):
        return (self.name + " '<" + self.path + ">': exports=" + str(self.exports) + ", imports=" + str(self.imports)
                + ", method_calls=" + str(self.method_calls))

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

            function_defs = []
            with open(full_path) as f:
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
    result = {}

    for (module_name, module) in modules.items():
        with open(module.path, mode="r", encoding="utf-8") as f:
            modified_module = module

            source_tree = ast.parse(f.read())
            for node in ast.walk(source_tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        modified_module.imports.append((alias.name, None, alias.asname))
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        modified_module.imports.append((node.module, alias.name, alias.asname))
                elif isinstance(node, ast.Call):
                    print(node.func.id)
                    print(node.func.attr)
                    if isinstance(node.func, ast.Name):
                        modified_module.method_calls.append(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        modified_module.method_calls.append(node.func.attr)

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
    for (module_name, module) in modules.items():
        print(module)


if __name__ == "__main__":
    main()

## PyFile: {OrderedList<PyFile> imports, List<Method> methodCalls, List<Method> methodDefs}

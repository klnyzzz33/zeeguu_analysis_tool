import sys
import os
import ast

input_params = sys.argv
if len(input_params) < 2:
    print("Usage: python index_modules.py <repo_dir>")
    exit(1)


def get_module_files_recursive(base_dir, parent_package):
    result = []
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
            result.append(module_name)
        elif os.path.isdir(full_path):
            result.extend(get_module_files_recursive(full_path, parent_package))

    return result

repo_dir = input_params[1]
module_names = get_module_files_recursive(repo_dir, "")
print(module_names)

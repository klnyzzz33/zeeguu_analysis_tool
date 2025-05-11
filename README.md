## Zeeguu analysis tool

Architectural recovery tool which makes it possible to extract module views from python source code.
The module views are polymetric:
- node sizes represent total LOC in the given module,
- edges and edge widths represent dependecies (low-level method calls) between modules.

Usage:
```python recover_module_view.py <repo_dir>```  
where ```<repo_dir>``` is the *absolute* path in your file system to the python repository you would like to analyze.

It's possible to specify options in the ```settings.json``` file.  
The following options can be used:
- *levels:* key-value pairs which specify the aggregation level in the given submodules,
- *only_aggregates:* if true, the extracted module view will only contain the nodes specified in the *levels* section,
- *skip_analyze:* list of relative paths in the target repository which specify subfolders that should be skipped from processing,
- *use_heatmap:* if true, the extracted module view will have a heatmap in the legend corresponding to the LOC values.

**Note:** the tool does static analysis therefore it has its limitations and it's not 100% accurate since that would require dynamic analysis on a running system.

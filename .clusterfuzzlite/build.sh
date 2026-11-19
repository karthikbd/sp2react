#!/bin/bash -eu
# Builds the Atheris fuzzers in tests/fuzz for ClusterFuzzLite.
pip3 install --no-deps .
# the generated API's $filter parser is a template file, which PyInstaller would not bundle: make it a module
cp src/sp2react/scaffold/templates/backend/app/odata.py tests/fuzz/generated_odata.py
for fuzzer in $(find "$SRC/sp2react/tests/fuzz" -name 'fuzz_*.py'); do
  compile_python_fuzzer "$fuzzer"
done

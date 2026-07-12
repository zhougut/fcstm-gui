#!/usr/bin/env python
"""Generate, compile, and execute every packaged pyfcstm runtime template."""

from __future__ import print_function, unicode_literals

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.application.generation import GenerationService
from pyfcstm.model import load_state_machine_from_text


SOURCE = """def int count = 0;
state Probe {
    state Idle { during { count = count + 1; } }
    [*] -> Idle;
}
"""


def _run(command, cwd):
    print("+ " + " ".join(str(item) for item in command), flush=True)
    subprocess.run([str(item) for item in command], cwd=str(cwd), check=True)


def _executable(directory, name):
    return directory / (name + (".exe" if os.name == "nt" else ""))


def _verify_python(directory):
    spec = importlib.util.spec_from_file_location(
        "fcstm_generated_probe", str(directory / "machine.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    machine = module.ProbeMachine()
    machine.cycle()
    if machine.current_state_path != ("Probe", "Idle") or machine.vars["count"] != 1:
        raise RuntimeError("generated Python runtime returned an invalid first cycle")
    machine.cycle()
    if machine.vars["count"] != 2:
        raise RuntimeError("generated Python lifecycle logic did not execute")


def _c_harness(poll):
    cycle = "ProbeMachine_cycle(&machine)" if poll else "ProbeMachine_cycle(&machine, NULL, 0)"
    return """#include \"machine.h\"
#include <stddef.h>
#include <string.h>
int main(void) {
    ProbeMachine machine;
    if (!ProbeMachine_init(&machine)) return 10;
    if (!%s) return 11;
    if (strcmp(ProbeMachine_current_state_path(&machine), \"Probe.Idle\") != 0) return 12;
    if (!%s) return 13;
    if (ProbeMachine_vars(&machine)->count != 2) return 14;
    return 0;
}
""" % (cycle, cycle)


def _verify_c(directory, compiler, poll, label):
    harness = directory / "verify.c"
    harness.write_text(_c_harness(poll), encoding="utf-8")
    output = _executable(directory, "verify-" + label)
    _run(
        [compiler, "-std=c99", "-Wall", "-Wextra", "machine.c", "verify.c", "-lm", "-o", output],
        directory,
    )
    _run([output], directory)


def _cpp_harness(namespace):
    return """#include \"machine.hpp\"
#include <cstring>
int main() {
    pyfcstm_generated::%s::MachineWrapper machine;
    if (!machine.init()) return 20;
    if (!machine.cycle()) return 21;
    if (std::strcmp(machine.current_state_path(), \"Probe.Idle\") != 0) return 22;
    if (!machine.cycle()) return 23;
    if (machine.vars()->count != 2) return 24;
    return 0;
}
""" % namespace


def _verify_cpp(directory, compiler, cxx, poll, label):
    namespace = "ProbeMachine_cpp_poll" if poll else "ProbeMachine_cpp"
    harness = directory / "verify.cpp"
    harness.write_text(_cpp_harness(namespace), encoding="utf-8")
    c_object = directory / "machine-c.o"
    cpp_object = directory / "machine-cpp.o"
    verify_object = directory / "verify.o"
    output = _executable(directory, "verify-" + label)
    _run([compiler, "-std=c99", "-c", "machine.c", "-o", c_object], directory)
    _run([cxx, "-std=c++98", "-Wall", "-Wextra", "-c", "machine.cpp", "-o", cpp_object], directory)
    _run([cxx, "-std=c++98", "-Wall", "-Wextra", "-c", "verify.cpp", "-o", verify_object], directory)
    _run([cxx, c_object, cpp_object, verify_object, "-lm", "-o", output], directory)
    _run([output], directory)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir")
    parser.add_argument("--cc", default=os.environ.get("CC") or "gcc")
    parser.add_argument("--cxx", default=os.environ.get("CXX") or "g++")
    args = parser.parse_args(argv)
    root = Path(args.output_dir).resolve() if args.output_dir else Path(
        tempfile.mkdtemp(prefix="fcstm-generated-template-check-")
    )
    if root.exists():
        shutil.rmtree(str(root))
    root.mkdir(parents=True)
    model = load_state_machine_from_text(SOURCE)
    service = GenerationService()
    for name in ("python", "c", "c_poll", "cpp", "cpp_poll"):
        target = root / name
        result = service.generate(model, str(target), template_name=name)
        print("generated {}: {} files".format(name, len(result.files)), flush=True)
        if name == "python":
            _verify_python(target)
        elif name in ("c", "c_poll"):
            _verify_c(target, args.cc, name.endswith("_poll"), name)
        else:
            _verify_cpp(target, args.cc, args.cxx, name.endswith("_poll"), name)
    print("all generated template runtimes executed successfully", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

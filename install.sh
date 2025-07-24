#!/bin/bash

python -V
pip -V

pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pip -U
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

pip install -r requirements.txt
pip install -r requirements-test.txt
pip install -r requirements-build.txt

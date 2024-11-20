set -e

# export LLVM_BUILD_DIR=~/llvm-project/build
# LLVM_INCLUDE_DIRS=$LLVM_BUILD_DIR/include \
#   LLVM_LIBRARY_DIR=$LLVM_BUILD_DIR/lib \
#   LLVM_SYSPATH=$LLVM_BUILD_DIR \
#   pip install ./python

export DEBUG=1
pip install -e ./python

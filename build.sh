
rm -rf build/
mkdir -p build

cd build/

cmake .. \
	-DMLIR_DIR=$HOME/llvm-project/build/lib/cmake/mlir \
	-DMLIR_INCLUDE_DIR=$HOME/llvm-project/mlir/include \
	-DLLVM_INCLUDE_DIR=$HOME/llvm-project/llvm/include \
	-DTRITON_CODEGEN_BACKENDS="amd;nvidia" \
	-G Ninja
	



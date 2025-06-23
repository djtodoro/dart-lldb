# Dart LLDB JIT Debug Plugin

This plugin enables debugging of JIT-compiled Dart code using LLDB. It integrates with Dart's internal JIT system to provide source-level debugging for dynamically generated code.

## Building

### Prerequisites

- CMake 3.10+
- LLDB development libraries
- C++ compiler with C++17 support

```bash
# Install LLVM/LLDB development packages
echo "deb http://apt.llvm.org/$(lsb_release -cs)/ llvm-toolchain-$(lsb_release -cs)-19 main" | sudo tee /etc/apt/sources.list.d/llvm.list
wget -O - https://apt.llvm.org/llvm-snapshot.gpg.key | sudo apt-key add -
sudo apt-get update
sudo apt-get install -y llvm-19-dev liblldb-19-dev python3-lldb-19
```

```bash
sudo apt-get install lldb-19
cd /usr/bin
sudo ln -S ./lldb ../lib/llvm-19/bin/lldb
```

### Build steps

```bash
mkdir build
cd build
cmake -DCMAKE_BUILD_TYPE=Release -GNinja ..
ninja
```

### Installation (optional)

```bash
sudo ninja install
```

This will install the plugin to `/usr/local/lib` and the dart-lldb script to `/usr/local/bin`.

## Usage

### Local

```bash
$ dart-lldb --pending-breakpoints 'RunningIsolates.isolateShutdown;RemovingTransformer.transformNamedExpressionList;InterfaceType.get_hasNonObjectMemberAccess' ./out/DebugX64/dart --gdb-jit-interface basic.dart
```

### Remote

1. Start Dart under QEMU with gdbserver mode:

```bash
qemu-arm -g 1234 -L /path/to/sysroot /path/to/dart --gdb-jit-interface your_script.dart
```

2. In another terminal, connect using dart-lldb:

```bash
 dart-lldb --remote localhost:1234 --sysroot /path/to/sysroot /path/to/dart
 ```

## Commands

Once the plugin is loaded, you can use these commands:

- `dart-jit-setup` - Initialize JIT debugging for the current target
- `dart-jit list` - List all JIT-compiled functions
- `dart-jit break <function-name>` - Set a breakpoint in a JIT-compiled function
- `dart-jit add <address> <size> <name> [file]` - Manually register a JIT function (for testing)

## Integration with Dart VM

This plugin works with Dart's JIT compiler. The Dart VM must be compiled with GDB JIT interface support and run with the `--gdb-jit-interface` flag.

TODO: Add patch for Dart project here, that introduces `--gdb-jit-interface`.

#!/bin/bash
# dart-lldb.sh - Simple wrapper script to launch LLDB with Dart JIT debugging support

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
PYTHON_SCRIPT="$SCRIPT_DIR/dart_lldb_init.py"

# Determine plugin path based on script location
if [[ "$SCRIPT_DIR" == *"/bin" ]]; then
    # Running from installed location
    PLUGIN_PATH="$(dirname "$SCRIPT_DIR")/lib/libDartJITPlugin.so"
else
    # Running from source directory
    PLUGIN_PATH="$SCRIPT_DIR/build/lib/libDartJITPlugin.so"
    if [ ! -f "$PLUGIN_PATH" ]; then
        echo "Plugin not found at $PLUGIN_PATH"
        echo "Please build the plugin first using:"
        echo "  cd $SCRIPT_DIR && mkdir -p build && cd build && cmake -GNinja .. && ninja"
        exit 1
    fi
fi

# Show what we're using
echo "Using plugin: $PLUGIN_PATH"
echo "Using script: $PYTHON_SCRIPT"

# Check for remote debugging arguments
REMOTE_ARGS=""
REMOTE_HOST=""
SYSROOT=""
PENDING_BREAKPOINTS=""
ARGS=()
TARGET_BINARY=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --remote)
            if [[ -z "$2" || "$2" == --* ]]; then
                echo "Error: --remote requires a HOST:PORT argument"
                exit 1
            fi
            REMOTE_HOST="$2"
            shift 2
            ;;
        --sysroot)
            if [[ -z "$2" || "$2" == --* ]]; then
                echo "Error: --sysroot requires a PATH argument"
                exit 1
            fi
            SYSROOT="$2"
            shift 2
            ;;
        --pending-breakpoints)
            if [[ -z "$2" || "$2" == --* ]]; then
                echo "Error: --pending-breakpoints requires a list of function names separated by semicolons"
                exit 1
            fi
            PENDING_BREAKPOINTS="$2"
            shift 2
            ;;
        --help)
            echo "Usage: dart-lldb [options] [dart_binary] [dart_args...]"
            echo ""
            echo "Options:"
            echo "  --remote HOST:PORT        Connect to a remote debug server"
            echo "  --sysroot PATH            Set the sysroot for remote debugging"
            echo "  --pending-breakpoints LIST Set pending breakpoints for JIT functions"
            echo "                            (function names separated by semicolons)"
            echo "  --help                    Show this help message"
            echo ""
            echo "Examples:"
            echo "  dart-lldb ./out/DebugX64/dart --gdb-jit-interface basic.dart"
            echo "  dart-lldb --pending-breakpoints 'RunningIsolates.isolateShutdown;main' ./out/DebugX64/dart --gdb-jit-interface basic.dart"
            echo "  dart-lldb --remote localhost:1234 --sysroot /path/to/sysroot ./out/DebugX64/dart"
            exit 0
            ;;
        *)
            # First non-option is the target binary
            if [ -z "$TARGET_BINARY" ]; then
                TARGET_BINARY="$1"
                shift
            else
                ARGS+=("$1")
                shift
            fi
            ;;
    esac
done

make_watch_cmds () {
  local list="$1"
  local cmds=""
  IFS=';' read -ra BP_ARRAY <<< "$list"
  for pat in "${BP_ARRAY[@]}"; do
      pat=$(echo "$pat" | xargs)          # trim
      [ -z "$pat" ] && continue
      cmds="$cmds -o \"dart-jit watch $pat\""
  done
  echo "$cmds"
}

# Setup remote debugging if requested
if [ -n "$REMOTE_HOST" ]; then
    # Set platform and sysroot using the correct approach
    if [ -n "$SYSROOT" ]; then
        # Use platform select with --sysroot option
        REMOTE_ARGS="$REMOTE_ARGS -o \"platform select --sysroot \\\"$SYSROOT\\\" remote-linux\""
    else
        # No sysroot, just select remote-linux platform
        REMOTE_ARGS="$REMOTE_ARGS -o \"platform select remote-linux\""
    fi
    
    # Make sure we have a target binary
    if [ -z "$TARGET_BINARY" ]; then
        echo "Error: No Dart binary specified for remote debugging"
        exit 1
    fi
    
    # First create the target with proper quoting
    REMOTE_ARGS="$REMOTE_ARGS -o \"target create \\\"$TARGET_BINARY\\\"\""
    
    # Connect to remote process with the correct command
    REMOTE_ARGS="$REMOTE_ARGS -o \"gdb-remote $REMOTE_HOST\""
    
    # Setup dart JIT debugging with the single command
    REMOTE_ARGS="$REMOTE_ARGS -o \"dart_jit_setup\""

    # For pending breakpoints, we'll add them directly to the global variable
    if [ -n "$PENDING_BREAKPOINTS" ]; then
        echo "Installing pending breakpoints (remote): $PENDING_BREAKPOINTS"
        WATCH_CMDS=$(make_watch_cmds "$PENDING_BREAKPOINTS")
        REMOTE_ARGS="$REMOTE_ARGS $WATCH_CMDS"
    fi

    # Continue the process after setup
    REMOTE_ARGS="$REMOTE_ARGS -o \"process continue\""
fi

# Launch LLDB, load the plugin, and import the initialization script
LLDB_CMD="lldb-19 -o \"plugin load $PLUGIN_PATH\" -o \"command script import $PYTHON_SCRIPT\""

# Add remote debugging commands if needed
if [ -n "$REMOTE_ARGS" ]; then
    LLDB_CMD="$LLDB_CMD $REMOTE_ARGS"
else
    # Handle local debugging
    if [ -n "$TARGET_BINARY" ]; then
        # Create the target first
        LLDB_CMD="$LLDB_CMD -o \"target create \\\"$TARGET_BINARY\\\"\""
        
        # Add dart_jit_setup to initialize JIT debugging
        LLDB_CMD="$LLDB_CMD -o \"dart_jit_setup\""
        
        # For pending breakpoints, we'll add them directly to the global variable
        if [ -n "$PENDING_BREAKPOINTS" ]; then
            echo "Installing pending breakpoints: $PENDING_BREAKPOINTS"
            WATCH_CMDS=$(make_watch_cmds "$PENDING_BREAKPOINTS")
            LLDB_CMD="$LLDB_CMD $WATCH_CMDS"
        fi

        # Set the target arguments
        if [ ${#ARGS[@]} -gt 0 ]; then
            ARGS_STR=""
            for arg in "${ARGS[@]}"; do
                ARGS_STR="$ARGS_STR \"$arg\""
            done
            # Use -- separator for arguments to ensure proper parsing
            LLDB_CMD="$LLDB_CMD -o \"settings set -- target.run-args $ARGS_STR\""
        fi
        
        # Run the target
        # Note: When using JIT debugging, you'll need to:
        # 1. Wait for JIT compilation to occur (watch for RegisterCode messages)
        # 2. Use Ctrl+C to interrupt execution after RegisterCode messages appear
        # 3. Run 'dart-jit list' to see available functions
        # 4. Set breakpoints with 'dart-jit break functionName'
        # 5. Use 'continue' to resume execution
        LLDB_CMD="$LLDB_CMD -o \"process launch\""
    fi
fi

# Execute the command
echo "Starting LLDB with Dart JIT debugging support..."
eval "$LLDB_CMD"

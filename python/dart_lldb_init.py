#!/usr/bin/env python3
"""
Dart LLDB plugin initialization script

This script is used to initialize Dart JIT debugging for LLDB
"""

import os
import lldb

def __lldb_init_module(debugger, internal_dict):
    """
    LLDB initialization function called when the script is loaded
    """
    # The plugin is loaded by the shell script before importing this script
    # Add convenience functions for the Dart JIT debugging commands
    
    # Check if the dart_jit_setup command exists, if not, define it
    result = lldb.SBCommandReturnObject()
    debugger.HandleCommand("settings set prompt 'dart-lldb> '")
    debugger.GetCommandInterpreter().HandleCommand("help dart_jit_setup", result)
    if not result.Succeeded():
        debugger.HandleCommand('command script add -f dart_lldb_init.dart_jit_setup dart_jit_setup --overwrite')
    
    # Show help text
    print("""
Dart JIT Debugging Commands:
---------------------------
dart_jit_setup   - Initialize JIT debugging for current target
dart-jit list    - List all JIT-compiled functions
dart-jit break   - Set a breakpoint in a JIT-compiled function
dart-jit help    - Show this help message

Usage Example:
  (lldb) dart_jit_setup
  (lldb) run
  (lldb) dart-jit list
  (lldb) dart-jit break myFunction
  
Remote Debugging Example:
  $ dart-lldb --remote localhost:1234 --sysroot /path/to/sysroot out/DebugXARM/dart
""")

def dart_jit_setup(debugger, command, result, internal_dict):
    """
    Setup JIT debugging for the current target
    """
    # Forward to the plugin's command if it exists, otherwise handle it ourselves
    interpreter = debugger.GetCommandInterpreter()
    cmd_result = lldb.SBCommandReturnObject()
    
    # Try to run the built-in command (added by the plugin)
    interpreter.HandleCommand("dart_jit_setup", cmd_result)
    
    # If it failed or doesn't exist, implement it here
    if not cmd_result.Succeeded():
        # Get the selected target
        target = debugger.GetSelectedTarget()
        if not target.IsValid():
            result.SetError("No valid target selected. Please select a target first.")
            return
        
        # Set a breakpoint on the JIT registration function
        bp = target.BreakpointCreateByName("__jit_debug_register_code")
        if not bp.IsValid():
            result.SetError("Failed to set breakpoint on __jit_debug_register_code. "
                         "Is the target process using the GDB JIT interface?")
            return
        
        # Make this internal and non-stopping
        commands = lldb.SBStringList()
        commands.AppendString("continue")
        bp.SetCommandLineCommands(commands)
        
        # Print success message
        print("Dart JIT debugging initialized.")
        print("Run your program with the --gdb-jit-interface flag to enable JIT debug info.")
        print("Use 'dart-jit list' after execution to see registered functions.")
        
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)
    else:
        # Just pass through the success result
        result.AppendMessage(cmd_result.GetOutput())
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)

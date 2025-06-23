#!/usr/bin/env python3
"""
Dart LLDB plugin initialization script

This script is used to initialize Dart JIT debugging for LLDB
"""

import os
import lldb
import re
import yaml

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
    
    # Add our custom commands
    debugger.HandleCommand('command script add -f dart_lldb_init.cmd_dart_jit_list "dart-jit list" --overwrite')
    debugger.HandleCommand('command script add -f dart_lldb_init.cmd_dart_jit_break "dart-jit break" --overwrite')
    debugger.HandleCommand('command script add -f dart_lldb_init.cmd_dart_jit_help "dart-jit help" --overwrite')
    
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

def find_jit_debug_descriptor(process):
    """
    Find the JIT debug descriptor in the target process
    """
    if not process.IsValid():
        return None
    
    # Look for the symbol in the target
    target = process.GetTarget()
    symbol = target.FindSymbols("__jit_debug_descriptor")
    if not symbol or symbol.GetSize() == 0:
        return None
    
    # Get the address of the symbol
    symbol_context = symbol[0].GetSymbol()
    if not symbol_context.IsValid():
        return None
    
    addr = symbol_context.GetStartAddress().GetLoadAddress(target)
    if addr == lldb.LLDB_INVALID_ADDRESS:
        return None
    
    return addr

def parse_debug_info(data):
    """
    Parse the debug info from a JIT entry
    """
    if not data:
        return None
    
    # Try to parse as YAML
    try:
        # Look for YAML document markers
        yaml_content = ""
        in_yaml = False
        for line in data.split('\n'):
            if line.strip() == '---':
                if not in_yaml:
                    in_yaml = True
                    yaml_content = ""
                else:
                    in_yaml = False
                    break
            elif in_yaml:
                yaml_content += line + "\n"
        
        if yaml_content:
            return yaml.safe_load(yaml_content)
    except Exception as e:
        print(f"Error parsing debug info: {e}")
    
    return None

def get_jit_entries(process):
    """
    Get all JIT entries from the process
    """
    entries = []
    
    # Find the JIT debug descriptor
    descriptor_addr = find_jit_debug_descriptor(process)
    if not descriptor_addr:
        return entries
    
    # Read the descriptor
    error = lldb.SBError()
    descriptor = process.ReadUnsignedFromMemory(descriptor_addr, 8, error)  # Read first 8 bytes
    if error.Fail():
        return entries
    
    # Get the first entry pointer
    first_entry_ptr_addr = descriptor_addr + 24  # Offset to first_entry field
    first_entry_ptr = process.ReadPointerFromMemory(first_entry_ptr_addr, error)
    if error.Fail() or first_entry_ptr == 0:
        return entries
    
    # Read all entries
    current_entry = first_entry_ptr
    while current_entry != 0:
        # Read entry fields
        symfile_addr = process.ReadPointerFromMemory(current_entry + 16, error)  # Offset to symfile_addr
        if error.Fail():
            break
        
        symfile_size = process.ReadUnsignedFromMemory(current_entry + 24, 8, error)  # Offset to symfile_size
        if error.Fail():
            break
        
        # Read the symfile data
        data = process.ReadCStringFromMemory(symfile_addr, symfile_size, error)
        if not error.Fail() and data:
            # Parse the debug info
            info = parse_debug_info(data)
            if info:
                entries.append(info)
        
        # Move to next entry
        next_entry = process.ReadPointerFromMemory(current_entry, error)  # Offset to next_entry
        if error.Fail():
            break
        
        current_entry = next_entry
    
    return entries

def cmd_dart_jit_list(debugger, command, result, internal_dict):
    """
    List all JIT-compiled functions
    """
    target = debugger.GetSelectedTarget()
    if not target.IsValid():
        result.SetError("No valid target selected.")
        return
    
    process = target.GetProcess()
    if not process.IsValid():
        result.SetError("No valid process. Please run the program first.")
        return
    
    # Get all JIT entries
    entries = get_jit_entries(process)
    if not entries:
        result.SetError("No JIT-compiled functions found. Make sure the program is running with --gdb-jit-interface.")
        return
    
    # Display the entries
    result.AppendMessage(f"Found {len(entries)} JIT-compiled functions:")
    for i, entry in enumerate(entries):
        name = entry.get('name', 'unknown')
        file = entry.get('file', 'unknown')
        addr = entry.get('start', '0x0')
        size = entry.get('size', 0)
        
        result.AppendMessage(f"{i+1}. {name} - {addr} (size: {size})")
        result.AppendMessage(f"   Source: {file}")
    
    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)

def cmd_dart_jit_break(debugger, command, result, internal_dict):
    """
    Set a breakpoint in a JIT-compiled function
    """
    args = command.split()
    if not args:
        result.SetError("Please specify a function name or pattern to set a breakpoint.")
        return
    
    pattern = args[0]
    
    target = debugger.GetSelectedTarget()
    if not target.IsValid():
        result.SetError("No valid target selected.")
        return
    
    process = target.GetProcess()
    if not process.IsValid():
        result.SetError("No valid process. Please run the program first.")
        return
    
    # Get all JIT entries
    entries = get_jit_entries(process)
    if not entries:
        result.SetError("No JIT-compiled functions found. Make sure the program is running with --gdb-jit-interface.")
        return
    
    # Find matching entries
    matched = False
    for entry in entries:
        name = entry.get('name', '')
        if pattern.lower() in name.lower():
            # Set a breakpoint at the function
            addr_str = entry.get('start', '0x0')
            try:
                addr = int(addr_str, 16) if isinstance(addr_str, str) else addr_str
                bp = target.BreakpointCreateByAddress(addr)
                if bp.IsValid():
                    result.AppendMessage(f"Breakpoint set on function '{name}' at address {addr_str}")
                    matched = True
                else:
                    result.AppendMessage(f"Failed to set breakpoint on function '{name}' at address {addr_str}")
            except Exception as e:
                result.AppendMessage(f"Error setting breakpoint on function '{name}': {e}")
    
    if not matched:
        result.SetError(f"No functions matching '{pattern}' found.")
    else:
        result.SetStatus(lldb.eReturnStatusSuccessFinishResult)

def cmd_dart_jit_help(debugger, command, result, internal_dict):
    """
    Show help for dart-jit commands
    """
    result.AppendMessage("""
Dart JIT Debugging Commands:
---------------------------
dart_jit_setup           - Initialize JIT debugging for current target
dart-jit list            - List all JIT-compiled functions
dart-jit break <pattern> - Set a breakpoint in a JIT-compiled function matching pattern
dart-jit help            - Show this help message

Usage Example:
  (lldb) dart_jit_setup
  (lldb) run
  (lldb) dart-jit list
  (lldb) dart-jit break myFunction
  
Workflow for JIT debugging:
1. Initialize JIT debugging with dart_jit_setup
2. Run your program with the --gdb-jit-interface flag
3. Wait for JIT compilation to occur (you'll see RegisterCode messages)
4. Use Ctrl+C to interrupt execution after RegisterCode messages appear
5. Use 'dart-jit list' to see available functions
6. Set breakpoints with 'dart-jit break functionName'
7. Use 'continue' to resume execution
""")
    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)

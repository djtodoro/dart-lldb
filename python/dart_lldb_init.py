#!/usr/bin/env python3
"""
Dart LLDB plugin initialization script

This script is used to initialize Dart JIT debugging for LLDB
"""

import os
import lldb
import re
import yaml
import threading
import time

# Global variables for pending breakpoints
pending_breakpoints = []
monitoring_enabled = False
monitor_thread = None
bp_handler = None

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
        module_name = __name__
        debugger.HandleCommand(f'command script add -f {module_name}.dart_jit_setup dart_jit_setup --overwrite')
    
    # Add our custom commands using the current module reference
    module_name = __name__
    debugger.HandleCommand(f'command script add -f {module_name}.cmd_dart_jit_list "dart-jit list" --overwrite')
    debugger.HandleCommand(f'command script add -f {module_name}.cmd_dart_jit_break "dart-jit break" --overwrite')
    debugger.HandleCommand(f'command script add -f {module_name}.cmd_dart_jit_help "dart-jit help" --overwrite')
    debugger.HandleCommand(f'command script add -f {module_name}.cmd_dart_jit_pending "dart-jit pending" --overwrite')
    
    # Show help text
    print("""
Dart JIT Debugging Commands:
---------------------------
dart_jit_setup   - Initialize JIT debugging for current target
dart-jit list    - List all JIT-compiled functions
dart-jit break   - Set a breakpoint in a JIT-compiled function
dart-jit pending - Set a pending breakpoint for a future JIT function
dart-jit help    - Show this help message

Usage Example:
  (lldb) dart_jit_setup
  (lldb) run
  (lldb) dart-jit list
  (lldb) dart-jit break myFunction
  
Remote Debugging Example:
  $ dart-lldb --remote localhost:1234 --sysroot /path/to/sysroot out/DebugXARM/dart
""")

def monitor_for_new_functions(debugger):
    """
    Background thread to monitor for new JIT functions
    """
    global monitoring_enabled, pending_breakpoints
    
    print("\n==== Starting JIT function monitoring thread ====")
    
    # Keep a reference to the debugger
    if not debugger:
        print("ERROR: No debugger provided to monitor thread")
        return
    
    try:
        # Initial delay to let the program start
        time.sleep(2.0)
        
        last_check_time = time.time()
        last_entry_count = 0
        
        while monitoring_enabled:
            try:
                # Sleep briefly to avoid high CPU usage
                time.sleep(0.5)
                
                # Only check periodically (every 1 second)
                current_time = time.time()
                if current_time - last_check_time < 1.0:
                    continue
                    
                last_check_time = current_time
                
                # Get the current target
                target = debugger.GetSelectedTarget()
                if not target or not target.IsValid():
                    continue
                
                # Get the process
                process = target.GetProcess()
                if not process or not process.IsValid():
                    continue
                
                # Skip if process isn't in a good state for debugging
                state = process.GetState()
                if state != lldb.eStateStopped and state != lldb.eStateRunning:
                    continue
                
                # Try to get JIT entries
                entries = get_jit_entries(process)
                if not entries:
                    continue
                    
                # Check if we have new entries
                if len(entries) <= last_entry_count:
                    continue
                
                # We have new entries!
                print(f"\n==== MONITOR: Found {len(entries) - last_entry_count} new JIT functions ====")
                new_entries = entries[last_entry_count:]
                last_entry_count = len(entries)
                
                # Check if we have any pending breakpoints
                if not pending_breakpoints:
                    print("MONITOR: No pending breakpoints to process")
                    continue
                    
                print(f"MONITOR: Current pending breakpoints: {pending_breakpoints}")
                
                # Process pending breakpoints for the new entries
                for entry in new_entries:
                    name = entry.get('name', '')
                    addr_str = entry.get('start', '0x0')
                    file = entry.get('file', 'unknown')
                    
                    print(f"MONITOR: Processing new function: '{name}' at {addr_str}")
                    print(f"MONITOR: Source file: {file}")
                    
                    # Check each pending breakpoint pattern
                    matched = False
                    for pattern in pending_breakpoints[:]:
                        print(f"MONITOR: Checking if '{pattern}' matches '{name}'")
                        if pattern.lower() in name.lower():
                            print(f"MONITOR: MATCH FOUND: '{pattern}' in '{name}'")
                            
                            # Set a breakpoint
                            try:
                                addr = int(addr_str, 16) if isinstance(addr_str, str) else addr_str
                                bp = target.BreakpointCreateByAddress(addr)
                                if bp.IsValid():
                                    print(f"MONITOR: SUCCESS: Breakpoint set on function '{name}' at address {addr_str}")
                                    matched = True
                                    
                                    # Remove from pending list if exact match
                                    if pattern.lower() == name.lower():
                                        pending_breakpoints.remove(pattern)
                                        print(f"MONITOR: Removed '{pattern}' from pending list (exact match)")
                                else:
                                    print(f"MONITOR: FAILED: Could not set breakpoint on function '{name}' at address {addr_str}")
                            except Exception as e:
                                print(f"MONITOR: ERROR: Exception setting breakpoint: {e}")
                    
                    if not matched:
                        print(f"MONITOR: No pending breakpoints matched '{name}'")
                
                print("==== MONITOR: Finished processing new JIT functions ====\n")
                
            except Exception as e:
                print(f"MONITOR: Error in monitoring thread: {e}")
                # Continue running despite errors
                
    except Exception as e:
        print(f"MONITOR: Fatal error in monitoring thread: {e}")
    
    print("==== JIT function monitoring thread stopped ====")

def dart_jit_setup(debugger, command, result, internal_dict):
    """
    Setup JIT debugging for the current target
    """
    global monitoring_enabled, monitor_thread
    
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
        
        # Define a simple callback function (not a class method)
        def jit_registration_callback(frame, bp_loc, dict):
            """Callback for JIT code registration breakpoint"""
            print("\n==== JIT CODE REGISTRATION DETECTED ====")
            
            # Find the process
            process = frame.GetThread().GetProcess()
            if not process or not process.IsValid():
                print("Invalid process in callback")
                return False
                
            # First, read the __jit_debug_descriptor directly
            # This gives us the latest entry without having to scan all entries
            descriptor_addr = find_jit_debug_descriptor(process)
            if not descriptor_addr:
                print("Could not find __jit_debug_descriptor")
                return False
                
            # Read relevant_entry pointer from descriptor
            error = lldb.SBError()
            relevant_entry_addr = process.ReadPointerFromMemory(descriptor_addr + 16, error)  # Offset to relevant_entry
            if error.Fail() or relevant_entry_addr == 0:
                print("Could not read relevant_entry from descriptor")
                return False
                
            # Read symfile_addr and symfile_size from the relevant entry
            symfile_addr = process.ReadPointerFromMemory(relevant_entry_addr + 16, error)  # Offset to symfile_addr
            if error.Fail() or symfile_addr == 0:
                print("Could not read symfile_addr from entry")
                return False
                
            symfile_size = process.ReadUnsignedFromMemory(relevant_entry_addr + 24, 8, error)  # Offset to symfile_size
            if error.Fail() or symfile_size == 0:
                print("Could not read symfile_size from entry")
                return False
                
            # Read the YAML data directly from memory
            yaml_data = process.ReadCStringFromMemory(symfile_addr, symfile_size, error)
            if error.Fail() or not yaml_data:
                print("Could not read YAML data from memory")
                return False
                
            print(f"DEBUG INFO:\n{yaml_data}")
                
            # Parse the YAML data manually to avoid potential parsing issues
            function_name = "unknown"
            function_addr = 0
            function_size = 0
            source_file = "unknown"
            
            for line in yaml_data.splitlines():
                line = line.strip()
                if line.startswith("name:"):
                    function_name = line[5:].strip()
                elif line.startswith("start:"):
                    addr_str = line[6:].strip()
                    try:
                        function_addr = int(addr_str, 16) if addr_str.startswith("0x") else int(addr_str)
                    except ValueError:
                        print(f"Failed to parse address: {addr_str}")
                        function_addr = 0
                elif line.startswith("size:"):
                    try:
                        function_size = int(line[5:].strip())
                    except ValueError:
                        function_size = 0
                elif line.startswith("file:"):
                    source_file = line[5:].strip()
            
            if function_addr == 0:
                print("Failed to parse function address from YAML")
                return False
                
            print(f"New JIT function registered: '{function_name}' at 0x{function_addr:x} (size: {function_size})")
            print(f"Source file: {source_file}")
            
            # Check if there are pending breakpoints to process
            global pending_breakpoints
            print(f"Current pending breakpoints: {pending_breakpoints}")
            
            if not pending_breakpoints:
                print("No pending breakpoints to process")
                return False  # Continue execution
            
            # Check if any pending breakpoints match
            matched = False
            for pattern in pending_breakpoints[:]:
                print(f"Checking if '{pattern}' matches '{function_name}'")
                if pattern.lower() in function_name.lower():
                    print(f"MATCH FOUND: '{pattern}' in '{function_name}'")
                    # Set a breakpoint
                    try:
                        target = process.GetTarget()
                        
                        # Create a breakpoint at the function address
                        bp = target.BreakpointCreateByAddress(function_addr)
                        
                        if bp.IsValid():
                            print(f"SUCCESS: Breakpoint set on function '{function_name}' at address 0x{function_addr:x}")
                            bp.SetEnabled(True)
                            matched = True
                            
                            # Give the breakpoint a name for easier identification
                            bp.AddName(f"JIT:{function_name}")
                            
                            # Remove if exact match
                            if pattern.lower() == function_name.lower():
                                pending_breakpoints.remove(pattern)
                                print(f"Removed '{pattern}' from pending list (exact match)")
                        else:
                            print(f"FAILED: Could not set breakpoint on function '{function_name}' at address 0x{function_addr:x}")
                    except Exception as e:
                        print(f"ERROR: Exception setting breakpoint on function '{function_name}': {e}")
            
            if not matched:
                print(f"No pending breakpoints matched '{function_name}'")
            
            print("==== JIT CODE REGISTRATION COMPLETED ====\n")
            return False  # Continue execution
        
        # Set the callback function directly
        bp.SetScriptCallbackFunction("dart_lldb_init.jit_registration_callback")
        
        # Store a reference to prevent garbage collection
        global bp_handler
        bp_handler = jit_registration_callback
        
        # Important: Don't set commands that auto-continue here
        # Let the callback handle continuation with its return value
        
        # Start the background monitoring thread if not already running
        if not monitoring_enabled:
            monitoring_enabled = True
            monitor_thread = threading.Thread(target=monitor_for_new_functions, args=(debugger,))
            monitor_thread.daemon = True
            monitor_thread.start()
        
        # Print success message
        print("Dart JIT debugging initialized.")
        print("Run your program with the --gdb-jit-interface flag to enable JIT debug info.")
        print("You can set pending breakpoints with 'dart-jit pending <function_name>'")
        print("These will be activated automatically when matching functions are compiled.")
        
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

def cmd_dart_jit_pending(debugger, command, result, internal_dict):
    """
    Set a pending breakpoint for a function that will be JIT compiled in the future
    """
    global pending_breakpoints
    
    args = command.split()
    if not args:
        result.SetError("Please specify a function name or pattern for the pending breakpoint.")
        return
    
    pattern = args[0]
    
    # Check if we already have this pattern
    if pattern in pending_breakpoints:
        result.AppendMessage(f"Pending breakpoint for '{pattern}' already exists.")
    else:
        # Add to our pending list
        pending_breakpoints.append(pattern)
        result.AppendMessage(f"Pending breakpoint set for function pattern '{pattern}'.")
        result.AppendMessage("This breakpoint will be automatically set when a matching function is compiled.")
    
    # Show all pending breakpoints
    result.AppendMessage("\nCurrent pending breakpoints:")
    for i, p in enumerate(pending_breakpoints):
        result.AppendMessage(f"{i+1}. {p}")
    
    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)

def cmd_dart_jit_help(debugger, command, result, internal_dict):
    """
    Show help for dart-jit commands
    """
    result.AppendMessage("""
Dart JIT Debugging Commands:
---------------------------
dart_jit_setup             - Initialize JIT debugging for current target
dart-jit list              - List all JIT-compiled functions
dart-jit break <pattern>   - Set a breakpoint in a JIT-compiled function matching pattern
dart-jit pending <pattern> - Set a pending breakpoint for a function not yet compiled
dart-jit help              - Show this help message

Usage Example:
  (lldb) dart_jit_setup
  (lldb) dart-jit pending RunningIsolates.isolateShutdown
  (lldb) run
  (lldb) dart-jit list
  (lldb) dart-jit break myFunction
  
Workflow for JIT debugging:
1. Initialize JIT debugging with dart_jit_setup
2. Set any pending breakpoints with 'dart-jit pending functionName'
3. Run your program with the --gdb-jit-interface flag
4. Pending breakpoints will be set automatically when matching functions are compiled
5. You can also manually interrupt (Ctrl+C) after seeing RegisterCode messages
6. Use 'dart-jit list' to see available functions
7. Set additional breakpoints with 'dart-jit break functionName'
8. Use 'continue' to resume execution
""")
    result.SetStatus(lldb.eReturnStatusSuccessFinishResult)

//
// DartJITPlugin.cpp - LLDB plugin for Dart JIT debugging
//

#include <lldb/API/SBAddress.h>
#include <lldb/API/SBCommandInterpreter.h>
#include <lldb/API/SBCommandReturnObject.h>
#include <lldb/API/SBDebugger.h>
#include <lldb/API/SBFrame.h>
#include <lldb/API/SBTarget.h>
#include <lldb/API/SBThread.h>
#include <lldb/API/SBValue.h>
#include <lldb/API/SBProcess.h>
#include <lldb/API/SBBreakpoint.h>
#include <lldb/API/SBBreakpointLocation.h>
#include <lldb/API/SBModule.h>
#include <lldb/API/SBSymbol.h>
#include <lldb/API/SBSymbolContext.h>
#include <lldb/API/SBStringList.h>
#include <lldb/API/SBError.h>
#include <lldb/API/SBListener.h>
#include <lldb/API/SBEvent.h>
#include <lldb/API/SBStream.h>
#include <lldb/API/SBFileSpec.h>
#include <lldb/API/SBData.h>

#include <fstream>
#include <iostream>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>
#include <cinttypes>

using namespace lldb;

// Data structures to store JIT debug info
static std::mutex g_jit_mutex;
static std::unordered_map<uint64_t, std::string> g_jit_functions;
static std::unordered_map<uint64_t, std::string> g_jit_files;
static std::unordered_map<uint64_t, uint64_t> g_jit_sizes;

// Forward declarations
static bool ParseYAMLDebugInfo(const std::string& yaml, 
                             uint64_t& addr, 
                             uint64_t& size, 
                             std::string& name, 
                             std::string& file);

// Command to list all JIT-compiled functions
class DartJITListCommand : public SBCommandPluginInterface {
public:
  bool DoExecute(SBDebugger debugger, char **command,
                 SBCommandReturnObject &result) override {
    std::lock_guard<std::mutex> lock(g_jit_mutex);
    
    if (g_jit_functions.empty()) {
      result.AppendMessage("No JIT-compiled Dart functions registered.");
      result.SetStatus(eReturnStatusSuccessFinishResult);
      return true;
    }
    
    std::stringstream ss;
    ss << "Dart JIT-compiled functions:\n";
    ss << "----------------------------\n";
    ss << "Address            Size     Function Name                  Source File\n";
    ss << "------------------ -------- ------------------------------ ---------------------------\n";
    
    for (const auto& pair : g_jit_functions) {
      uint64_t addr = pair.first;
      const std::string& name = pair.second;
      const std::string& file = g_jit_files[addr];
      uint64_t size = g_jit_sizes[addr];
      
      char addr_str[32];
      snprintf(addr_str, sizeof(addr_str), "0x%016" PRIX64, addr);
      
      ss << addr_str << " ";
      ss << std::setw(8) << size << " ";
      
      // Truncate long names with ellipsis
      std::string display_name = name;
      if (display_name.length() > 30) {
        display_name = display_name.substr(0, 27) + "...";
      }
      ss << std::left << std::setw(30) << display_name << " ";
      
      // Truncate long file paths
      std::string display_file = file;
      if (display_file.length() > 40) {
        // Find the last path separator and keep just the filename part
        size_t last_slash = display_file.find_last_of("/\\");
        if (last_slash != std::string::npos) {
          display_file = "..." + display_file.substr(last_slash);
        } else {
          display_file = display_file.substr(0, 37) + "...";
        }
      }
      ss << display_file << "\n";
    }
    
    result.AppendMessage(ss.str().c_str());
    result.SetStatus(eReturnStatusSuccessFinishResult);
    return true;
  }
};

// Set a breakpoint on a JIT-compiled function
class DartJITBreakCommand : public SBCommandPluginInterface {
public:
  bool DoExecute(SBDebugger debugger, char **command,
                 SBCommandReturnObject &result) override {
    if (!command || !command[0]) {
      result.AppendMessage("Usage: dart-jit-break <function-name>");
      result.SetStatus(eReturnStatusFailed);
      return false;
    }
    
    std::string func_name = command[0];
    
    SBTarget target = debugger.GetSelectedTarget();
    if (!target.IsValid()) {
      result.AppendMessage("No valid target selected. Please select a target first.");
      result.SetStatus(eReturnStatusFailed);
      return false;
    }
    
    // Find the function address by name
    uint64_t func_addr = 0;
    uint64_t func_size = 0;
    {
      std::lock_guard<std::mutex> lock(g_jit_mutex);
      for (const auto& pair : g_jit_functions) {
        if (pair.second.find(func_name) != std::string::npos) {
          func_addr = pair.first;
          func_size = g_jit_sizes[func_addr];
          break;
        }
      }
    }
    
    if (func_addr == 0) {
      std::stringstream ss;
      ss << "Function '" << func_name << "' not found in JIT-compiled code. ";
      ss << "Use 'dart-jit list' to see available functions.";
      result.AppendMessage(ss.str().c_str());
      result.SetStatus(eReturnStatusFailed);
      return false;
    }
    
    // Create a breakpoint at the function address
    SBBreakpoint bp = target.BreakpointCreateByAddress(func_addr);
    if (!bp.IsValid()) {
      std::stringstream ss;
      ss << "Failed to create breakpoint at address 0x" << std::hex << func_addr;
      result.AppendMessage(ss.str().c_str());
      result.SetStatus(eReturnStatusFailed);
      return false;
    }
    
    // We can't set a comment - not supported in this LLDB version
    // Just keep track of it in our internal maps
    
    std::stringstream ss;
    ss << "Breakpoint set at 0x" << std::hex << func_addr;
    ss << " (function '" << func_name << "', size: " << std::dec << func_size << " bytes)";
    result.AppendMessage(ss.str().c_str());
    result.SetStatus(eReturnStatusSuccessFinishResult);
    return true;
  }
};

// Add a module for JIT-compiled code
class DartJITAddCommand : public SBCommandPluginInterface {
public:
  bool DoExecute(SBDebugger debugger, char **command,
                 SBCommandReturnObject &result) override {
    // This command manually adds a JIT entry for testing
    if (!command || !command[0] || !command[1] || !command[2]) {
      result.AppendMessage("Usage: dart-jit-add <address> <size> <name> [file]");
      result.SetStatus(eReturnStatusFailed);
      return false;
    }
    
    uint64_t addr = strtoull(command[0], nullptr, 0);
    uint64_t size = strtoull(command[1], nullptr, 0);
    std::string name = command[2];
    std::string file = (command[3]) ? command[3] : "unknown";
    
    if (addr == 0) {
      result.AppendMessage("Invalid address");
      result.SetStatus(eReturnStatusFailed);
      return false;
    }
    
    {
      std::lock_guard<std::mutex> lock(g_jit_mutex);
      g_jit_functions[addr] = name;
      g_jit_files[addr] = file;
      g_jit_sizes[addr] = size;
    }
    
    // Create a symbol in the target for this JIT code
    SBTarget target = debugger.GetSelectedTarget();
    if (target.IsValid()) {
      SBAddress addr_obj = target.ResolveLoadAddress(addr);
      if (addr_obj.IsValid()) {
        // Unfortunately we can't easily add symbols in LLDB API
        // Just log the info and use the data structures we maintain
        std::cout << "Adding symbol for " << name << " at 0x" 
                  << std::hex << addr << std::dec << std::endl;
      }
    }
    
    std::stringstream ss;
    ss << "Added JIT function '" << name << "' at 0x" << std::hex << addr;
    ss << " (size: " << std::dec << size << " bytes, file: " << file << ")";
    result.AppendMessage(ss.str().c_str());
    result.SetStatus(eReturnStatusSuccessFinishResult);
    return true;
  }
};

// Parse YAML debug info produced by the Dart VM
static bool ParseYAMLDebugInfo(const std::string& yaml, 
                             uint64_t& addr, 
                             uint64_t& size, 
                             std::string& name, 
                             std::string& file) {
  // Default values
  addr = 0;
  size = 0;
  name = "unknown";
  file = "unknown";
  
  std::istringstream stream(yaml);
  std::string line;
  
  // Simple YAML parser
  while (std::getline(stream, line)) {
    // Skip empty lines and the YAML document markers
    if (line.empty() || line == "---") {
      continue;
    }
    
    // Extract key-value pairs
    size_t colon_pos = line.find(':');
    if (colon_pos != std::string::npos) {
      std::string key = line.substr(0, colon_pos);
      std::string value = line.substr(colon_pos + 1);
      
      // Remove leading and trailing spaces
      size_t start = value.find_first_not_of(" \t");
      if (start != std::string::npos) {
        value = value.substr(start);
      }
      
      if (key == "name") {
        name = value;
      } else if (key == "start") {
        addr = strtoull(value.c_str(), nullptr, 0);
      } else if (key == "size") {
        size = strtoull(value.c_str(), nullptr, 0);
      } else if (key == "file") {
        file = value;
      }
    }
  }
  
  // Valid if we have at least an address and size
  return (addr != 0 && size != 0);
}

// Breakpoint callback for monitoring JIT code registrations
static bool BreakpointCallback(void* baton, 
                              SBProcess& process,
                              SBThread& thread, 
                              lldb::SBBreakpointLocation& location) {
  // This is called when we hit __jit_debug_register_code
  
  // Find the __jit_debug_descriptor symbol to get the JIT entry
  SBTarget target = process.GetTarget();
  
  // Use FindSymbols which returns an SBSymbolContextList
  lldb::SBSymbolContextList symbols = target.FindSymbols("__jit_debug_descriptor", eSymbolTypeData);
  
  if (symbols.GetSize() == 0) {
    std::cerr << "DartJITPlugin: Could not find __jit_debug_descriptor symbol" << std::endl;
    return false;
  }
  
  lldb::SBSymbolContext context = symbols.GetContextAtIndex(0);
  SBSymbol descriptor_symbol = context.GetSymbol();
  
  if (!descriptor_symbol.IsValid()) {
    std::cerr << "DartJITPlugin: Could not find __jit_debug_descriptor symbol" << std::endl;
    return false;
  }
  
  SBAddress descriptor_addr = descriptor_symbol.GetStartAddress();
  SBError error;
  
  // Read the descriptor fields
  uint32_t version = process.ReadUnsignedFromMemory(descriptor_addr.GetLoadAddress(target), 4, error);
  if (error.Fail()) return false;
  
  uint32_t action = process.ReadUnsignedFromMemory(descriptor_addr.GetLoadAddress(target) + 4, 4, error);
  if (error.Fail()) return false;
  
  addr_t relevant_entry_addr = process.ReadPointerFromMemory(descriptor_addr.GetLoadAddress(target) + 8, error);
  if (error.Fail()) return false;
  
  // If there's no entry or action is not register (1), just return
  if (relevant_entry_addr == 0 || action != 1) {
    return false;
  }
  
  // Read the JITCodeEntry structure
  addr_t next_entry = process.ReadPointerFromMemory(relevant_entry_addr, error);
  if (error.Fail()) return false;
  
  addr_t prev_entry = process.ReadPointerFromMemory(relevant_entry_addr + process.GetAddressByteSize(), error);
  if (error.Fail()) return false;
  
  addr_t symfile_addr = process.ReadPointerFromMemory(relevant_entry_addr + 2 * process.GetAddressByteSize(), error);
  if (error.Fail()) return false;
  
  uint64_t symfile_size = process.ReadUnsignedFromMemory(relevant_entry_addr + 3 * process.GetAddressByteSize(), 8, error);
  if (error.Fail()) return false;
  
  // Read the YAML data
  char* buffer = new char[symfile_size + 1];
  process.ReadMemory(symfile_addr, buffer, symfile_size, error);
  if (error.Fail()) {
    delete[] buffer;
    return false;
  }
  buffer[symfile_size] = '\0';
  
  std::string yaml(buffer, symfile_size);
  delete[] buffer;
  
  // Parse the YAML data
  uint64_t code_addr = 0;
  uint64_t code_size = 0;
  std::string func_name;
  std::string source_file;
  
  if (!ParseYAMLDebugInfo(yaml, code_addr, code_size, func_name, source_file)) {
    std::cerr << "DartJITPlugin: Failed to parse YAML debug info" << std::endl;
    return false;
  }
  
  // Store the information
  {
    std::lock_guard<std::mutex> lock(g_jit_mutex);
    g_jit_functions[code_addr] = func_name;
    g_jit_files[code_addr] = source_file;
    g_jit_sizes[code_addr] = code_size;
  }
  
  // Unfortunately we can't easily add symbols in LLDB API
  // Just log the info and use the data structures we maintain
  std::cout << "Registered symbol for function " << func_name 
            << " at 0x" << std::hex << code_addr 
            << " size: " << std::dec << code_size << std::endl;
  
  std::cout << "DartJITPlugin: Registered function '" << func_name 
            << "' at 0x" << std::hex << code_addr 
            << " (size: " << std::dec << code_size << " bytes, file: " << source_file << ")" 
            << std::endl;
  
  return false; // Continue execution
}

// Main multiword command for Dart JIT debugging
class DartJITCommand : public SBCommandPluginInterface {
public:
  bool DoExecute(SBDebugger debugger, char **command,
                 SBCommandReturnObject &result) override {
    if (!command || !command[0]) {
      result.AppendMessage("Dart JIT debugger plugin commands:\n"
                          "  dart-jit list   - List all JIT-compiled functions\n"
                          "  dart-jit break  - Set a breakpoint in a JIT-compiled function\n"
                          "  dart-jit add    - Manually add a JIT function (for testing)\n");
      result.SetStatus(eReturnStatusSuccessFinishNoResult);
      return true;
    }
    
    std::string subcommand = command[0];
    
    if (subcommand == "list") {
      DartJITListCommand list_cmd;
      return list_cmd.DoExecute(debugger, command + 1, result);
    } else if (subcommand == "break") {
      DartJITBreakCommand break_cmd;
      return break_cmd.DoExecute(debugger, command + 1, result);
    } else if (subcommand == "add") {
      DartJITAddCommand add_cmd;
      return add_cmd.DoExecute(debugger, command + 1, result);
    } else {
      result.AppendMessage("Unknown subcommand. Use 'dart-jit' for help.");
      result.SetStatus(eReturnStatusFailed);
      return false;
    }
  }
};

// Set up JIT debugging in the target
class DartJITSetupCommand : public SBCommandPluginInterface {
public:
  bool DoExecute(SBDebugger debugger, char **command,
                 SBCommandReturnObject &result) override {
    SBTarget target = debugger.GetSelectedTarget();
    if (!target.IsValid()) {
      result.AppendMessage("No valid target selected. Please select a target first.");
      result.SetStatus(eReturnStatusFailed);
      return false;
    }
    
    // Set a breakpoint on the JIT registration function
    SBBreakpoint bp = target.BreakpointCreateByName("__jit_debug_register_code");
    if (!bp.IsValid()) {
      result.AppendMessage("Failed to set breakpoint on __jit_debug_register_code. "
                         "Is the target process using the GDB JIT interface?");
      result.SetStatus(eReturnStatusFailed);
      return false;
    }
    
    // Make this internal and non-stopping
    SBStringList commands;
    commands.AppendString("continue");
    bp.SetCommandLineCommands(commands);
    bp.SetCallback(BreakpointCallback, nullptr);
    
    std::stringstream ss;
    ss << "Dart JIT debugging enabled. "
       << "Breakpoint set on __jit_debug_register_code with callback.\n"
       << "Run your program with --gdb-jit-interface flag.\n"
       << "Use 'dart-jit list' to see registered functions.";
    result.AppendMessage(ss.str().c_str());
    result.SetStatus(eReturnStatusSuccessFinishResult);
    return true;
  }
};

// Plugin initialization function
namespace lldb {
bool PluginInitialize(SBDebugger debugger) {
  SBCommandInterpreter interpreter = debugger.GetCommandInterpreter();
  
  // Add the dart-jit multiword command
  SBCommand dartjit = interpreter.AddMultiwordCommand(
      "dart-jit", "Dart JIT debugging commands");
  
  if (dartjit.IsValid()) {
    dartjit.AddCommand("list", new DartJITListCommand(),
                      "List all JIT-compiled Dart functions", nullptr);
    dartjit.AddCommand("break", new DartJITBreakCommand(),
                      "Set a breakpoint in a JIT-compiled Dart function", nullptr);
    dartjit.AddCommand("add", new DartJITAddCommand(),
                      "Manually add a JIT function (for testing)", nullptr);
  }
  
  // Add only dart_jit_setup command for simplicity
  interpreter.AddCommand("dart_jit_setup", new DartJITSetupCommand(),
                        "Set up Dart JIT debugging in the current target", nullptr);
  
  std::cout << "Dart JIT debugging plugin loaded." << std::endl;
  std::cout << "Use 'dart_jit_setup' after loading your target to enable JIT debugging." << std::endl;
  
  return true;
}
} // namespace lldb

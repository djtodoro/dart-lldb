//
// DartJITPlugin.h - Header for LLDB plugin for Dart JIT debugging
//

#ifndef DART_JIT_PLUGIN_H
#define DART_JIT_PLUGIN_H

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

#include <string>

// Forward declarations of classes
class DartJITListCommand;
class DartJITBreakCommand;
class DartJITAddCommand;
class DartJITCommand;
class DartJITSetupCommand;

// Utility function declarations
bool ParseYAMLDebugInfo(const std::string& yaml, 
                       uint64_t& addr, 
                       uint64_t& size, 
                       std::string& name, 
                       std::string& file);

bool BreakpointCallback(void* baton, 
                       lldb::SBProcess& process,
                       lldb::SBThread& thread, 
                       lldb::SBBreakpointLocation& location);

#endif // DART_JIT_PLUGIN_H

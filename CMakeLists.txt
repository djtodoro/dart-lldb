cmake_minimum_required(VERSION 3.10)
project(DartJITPlugin)

# Set position independent code
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Set project directories
set(PROJECT_SRC_DIR "${CMAKE_SOURCE_DIR}/src")
set(PROJECT_SCRIPTS_DIR "${CMAKE_SOURCE_DIR}/scripts")
set(PROJECT_PYTHON_DIR "${CMAKE_SOURCE_DIR}/python")

# Find LLDB-19 libraries specifically
find_library(LLDB_LIBRARY
    NAMES lldb-19 lldb19 liblldb-19 liblldb-19.so liblldb-19.1 liblldb.so.19 liblldb.so.19.1
    HINTS 
        /usr/lib
        /usr/local/lib
        /usr/lib/llvm-19/lib
        /usr/lib/x86_64-linux-gnu
    PATHS 
        /usr/lib
        /usr/local/lib
        /usr/lib/llvm-19/lib
        /usr/lib/x86_64-linux-gnu
    NO_DEFAULT_PATH
)

if(NOT LLDB_LIBRARY)
    # Fall back to general LLDB if version 19 not found
    find_library(LLDB_LIBRARY
        NAMES lldb LLDB
        HINTS /usr/lib /usr/local/lib
        PATHS /usr/lib /usr/local/lib
    )
endif()

if(NOT LLDB_LIBRARY)
    message(FATAL_ERROR "Could not find LLDB library! Please install LLDB 19 development packages.")
endif()

message(STATUS "Found LLDB at: ${LLDB_LIBRARY}")

# Find Python executable and packages
find_package(Python3 COMPONENTS Interpreter Development)
if(Python3_FOUND)
    message(STATUS "Found Python3: ${Python3_EXECUTABLE} (version: ${Python3_VERSION})")
    include_directories(${Python3_INCLUDE_DIRS})
else()
    message(WARNING "Python3 not found. Python support might be limited.")
endif()

# Include directories - prioritize LLDB-19 include paths
include_directories(
    ${PROJECT_SRC_DIR}
    /usr/lib/llvm-19/include/lldb
    /usr/include/lldb-19
    /usr/include/lldb
    /usr/local/include/lldb
    /usr/lib/llvm-19/include/
)

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Build the plugin as a shared library
add_library(DartJITPlugin SHARED
    ${PROJECT_SRC_DIR}/DartJITPlugin.cpp
)

# Link against LLDB
target_link_libraries(DartJITPlugin PRIVATE
    ${LLDB_LIBRARY}
)

# Add compile definitions to indicate LLDB version
if(LLDB_LIBRARY MATCHES ".*lldb-19.*|.*lldb.so.19.*")
    target_compile_definitions(DartJITPlugin PRIVATE LLDB_VERSION=19)
else()
    # Try to extract version from library path
    string(REGEX MATCH "lldb-([0-9]+)" LLDB_VERSION_MATCH "${LLDB_LIBRARY}")
    if(LLDB_VERSION_MATCH)
        string(REGEX REPLACE "lldb-([0-9]+)" "\\1" LLDB_VERSION "${LLDB_VERSION_MATCH}")
        target_compile_definitions(DartJITPlugin PRIVATE LLDB_VERSION=${LLDB_VERSION})
    endif()
endif()

# Set output directories
set_target_properties(DartJITPlugin PROPERTIES
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)

# Create version info file
configure_file(
    "${CMAKE_SOURCE_DIR}/version_info.txt.in"
    "${CMAKE_BINARY_DIR}/bin/version_info.txt"
    @ONLY
)

# Installation targets
install(TARGETS DartJITPlugin
    LIBRARY DESTINATION lib
    RUNTIME DESTINATION bin
)

# Copy scripts and Python modules to build directory
add_custom_target(copy_dartLLDB_scripts ALL
  # Create directories
  COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/bin"
  COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/lib/dart_lldb"
  
  # Copy main script
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
    "${PROJECT_SCRIPTS_DIR}/dart-lldb.sh" "${CMAKE_BINARY_DIR}/bin/dart-lldb"
  
  # Copy Python modules
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
    "${PROJECT_PYTHON_DIR}/dart_lldb_init.py" "${CMAKE_BINARY_DIR}/bin/dart_lldb_init.py"
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
    "${PROJECT_PYTHON_DIR}/__init__.py" "${CMAKE_BINARY_DIR}/lib/dart_lldb/__init__.py"
  
  COMMENT "Copying dart-lldb scripts and Python modules into build directory"
)

add_dependencies(copy_dartLLDB_scripts DartJITPlugin)

# Install main script as executable
install(PROGRAMS
  "${PROJECT_SCRIPTS_DIR}/dart-lldb.sh"
  DESTINATION bin
  RENAME dart-lldb
)

# Install Python modules
install(FILES
  "${PROJECT_PYTHON_DIR}/dart_lldb_init.py"
  DESTINATION bin
)

# Install Python package
install(FILES
  "${PROJECT_PYTHON_DIR}/__init__.py"
  DESTINATION lib/dart_lldb
)

# Install version info
install(FILES
  "${CMAKE_BINARY_DIR}/bin/version_info.txt"
  DESTINATION bin
)

cmake_minimum_required(VERSION 3.10)
project(DartJITPlugin)

# Set C++ standard first
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Set project directories
set(PROJECT_SRC_DIR "${CMAKE_SOURCE_DIR}/src")
set(PROJECT_SCRIPTS_DIR "${CMAKE_SOURCE_DIR}/scripts")
set(PROJECT_PYTHON_DIR "${CMAKE_SOURCE_DIR}/python")

# Find LLVM package if provided
if(LLVM_DIR)
    find_package(LLVM REQUIRED CONFIG)
    message(STATUS "Using LLVMConfig.cmake in: ${LLVM_DIR}")
    include(AddLLVM)
    include(TableGen)
endif()

# Set up link directories if LLVM_BUILD_ROOT is provided
if(LLVM_BUILD_ROOT)
    link_directories(${LLVM_BUILD_ROOT}/)
endif()

# Find LLDB library - check build directory first, then system locations
if(LLVM_BUILD_ROOT)
    find_library(LLDB_LIBRARY
        NAMES lldb LLDB
        HINTS "${LLVM_BUILD_ROOT}/lib"
        PATHS "${LLVM_BUILD_ROOT}/lib"
        NO_DEFAULT_PATH
    )
endif()

if(NOT LLDB_LIBRARY)
    # Fall back to system LLDB
    find_library(LLDB_LIBRARY
        NAMES lldb-19 lldb19 liblldb-19 liblldb-19.so liblldb-19.1 liblldb.so.19 liblldb.so.19.1 lldb LLDB
        HINTS 
            /usr/lib
            /usr/local/lib
            /usr/lib/llvm-19/lib
            /usr/lib/x86_64-linux-gnu
            /opt/homebrew/opt/llvm@19/lib
        PATHS 
            /usr/lib
            /usr/local/lib
            /usr/lib/llvm-19/lib
            /usr/lib/x86_64-linux-gnu
            /opt/homebrew/opt/llvm@19/lib
    )
endif()

if(NOT LLDB_LIBRARY)
    message(FATAL_ERROR "Could not find LLDB library! Please install LLDB 19 development packages.")
endif()

message(STATUS "Found LLDB at: ${LLDB_LIBRARY}")

# Find LLDB executable
# Try to find lldb executable in the same directory structure as the library
get_filename_component(LLDB_LIB_DIR ${LLDB_LIBRARY} DIRECTORY)
get_filename_component(LLDB_PREFIX ${LLDB_LIB_DIR} DIRECTORY)

# Look for lldb executable in common locations
find_program(LLDB_EXECUTABLE
    NAMES lldb lldb-19
    HINTS 
        "${LLDB_PREFIX}/bin"
        "${LLVM_BUILD_ROOT}/bin"
        /opt/homebrew/opt/llvm@19/bin
        /usr/lib/llvm-19/bin
    PATHS
        "${LLDB_PREFIX}/bin"
        "${LLVM_BUILD_ROOT}/bin"
        /opt/homebrew/opt/llvm@19/bin
        /usr/lib/llvm-19/bin
        /usr/bin
        /usr/local/bin
)

if(NOT LLDB_EXECUTABLE)
    # Fallback to system lldb if we can't find the specific one
    set(LLDB_EXECUTABLE "lldb")
    message(WARNING "Could not find LLDB executable matching library. Using system default: ${LLDB_EXECUTABLE}")
else()
    message(STATUS "Found LLDB executable at: ${LLDB_EXECUTABLE}")
endif()

# Find Python executable and packages
find_package(Python3 COMPONENTS Interpreter Development)
if(Python3_FOUND)
    message(STATUS "Found Python3: ${Python3_EXECUTABLE} (version: ${Python3_VERSION})")
    include_directories(${Python3_INCLUDE_DIRS})
else()
    message(WARNING "Python3 not found. Python support might be limited.")
endif()

# Include directories - prioritize build/source directories if available
include_directories(${PROJECT_SRC_DIR})

# Add LLVM include directories if available
if(LLVM_INCLUDE_DIRS)
    include_directories(${LLVM_INCLUDE_DIRS})
endif()

# Add LLDB include directories from source and build if available
if(LLVM_SRC)
    include_directories(${LLVM_SRC}/lldb/include/)
endif()

if(LLVM_BUILD_ROOT)
    include_directories(${LLVM_BUILD_ROOT}/tools/lldb/include/)
    include_directories(${CMAKE_BINARY_DIR})
endif()

# Add system LLDB include directories
include_directories(
    /usr/lib/llvm-19/include
    /opt/homebrew/opt/llvm@19/include
    /usr/lib/llvm-19/include/lldb
    /usr/include/lldb-19
    /usr/include/lldb
    /usr/local/include/lldb
)

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

# Configure the dart-lldb script with the correct LLDB path
configure_file(
    "${PROJECT_SCRIPTS_DIR}/dart-lldb.sh.in"
    "${CMAKE_BINARY_DIR}/bin/dart-lldb"
    @ONLY
    FILE_PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE 
                     GROUP_READ GROUP_EXECUTE 
                     WORLD_READ WORLD_EXECUTE
)

# Copy scripts and Python modules to build directory
add_custom_target(copy_dartLLDB_scripts ALL
  # Create directories
  COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/bin"
  COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/lib/dart_lldb"
  
  # Copy Python modules
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
    "${PROJECT_PYTHON_DIR}/dart_lldb_init.py" "${CMAKE_BINARY_DIR}/bin/dart_lldb_init.py"
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
    "${PROJECT_PYTHON_DIR}/__init__.py" "${CMAKE_BINARY_DIR}/lib/dart_lldb/__init__.py"
  
  COMMENT "Copying dart-lldb scripts and Python modules into build directory"
)

add_dependencies(copy_dartLLDB_scripts DartJITPlugin)

# Install main script as executable (use the configured version)
install(PROGRAMS
  "${CMAKE_BINARY_DIR}/bin/dart-lldb"
  DESTINATION bin
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

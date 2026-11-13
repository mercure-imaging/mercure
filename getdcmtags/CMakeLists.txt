cmake_minimum_required(VERSION 3.10)
project(getdcmtags CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(DCMTK REQUIRED)

add_executable(getdcmtags main.cpp)
target_include_directories(getdcmtags PRIVATE ${DCMTK_INCLUDE_DIRS})

enable_testing()

# The atomic publish helper is DCMTK-free, so its test needs only a C++17 compiler. It runs at
# build time in every Dockerfile stage (see the getdcmtags-builder stage) and with "ctest".
add_executable(test_atomic_file test_atomic_file.cpp)
add_test(NAME atomic_file COMMAND test_atomic_file)

# Static linking requires strict dependency order (dependents before dependencies).
# dcmdata → oflog → ofstd → oficonv → system libs
target_link_libraries(getdcmtags
    dcmdata oflog ofstd oficonv
    z pthread dl
)

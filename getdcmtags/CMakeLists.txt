cmake_minimum_required(VERSION 3.10)
project(getdcmtags CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(DCMTK REQUIRED)

add_executable(getdcmtags main.cpp)
target_include_directories(getdcmtags PRIVATE ${DCMTK_INCLUDE_DIRS})

# Static linking requires strict dependency order (dependents before dependencies).
# dcmdata → oflog → ofstd → oficonv → system libs
target_link_libraries(getdcmtags
    dcmdata oflog ofstd oficonv
    z pthread dl
)

# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.16)

project(rs2_latency_lab VERSION 0.1.0 LANGUAGES CXX)

find_package(realsense2 2.51 REQUIRED)
find_package(OpenCV 4 REQUIRED COMPONENTS core highgui imgproc)

add_executable(rs2-latency-lab
    src/main.cpp
    src/latency_detector.cpp
)
target_compile_features(rs2-latency-lab PRIVATE cxx_std_17)
target_compile_options(rs2-latency-lab PRIVATE
    -Wall -Wextra -Wpedantic
)
target_link_libraries(rs2-latency-lab PRIVATE
    realsense2::realsense2
    ${OpenCV_LIBS}
)
target_include_directories(rs2-latency-lab PRIVATE ${OpenCV_INCLUDE_DIRS})

include(GNUInstallDirs)
install(TARGETS rs2-latency-lab RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

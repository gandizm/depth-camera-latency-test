// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <librealsense2/rs.hpp>

#include <algorithm>
#include <cctype>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace rs2_latency
{

struct profile_request
{
    std::string serial;
    int device_index = 0;
    std::string stream = "auto";
    int stream_index = -1;
    int width = 0;
    int height = 0;
    int fps = 0;
    std::string format = "auto";
    std::string policy = "low-latency";
};

struct selected_profile
{
    rs2::device device;
    rs2::sensor sensor;
    rs2::video_stream_profile profile;
};

struct depth_request
{
    bool enabled = false;
    int width = 0;
    int height = 0;
    int fps = 0;
};

inline std::string device_info(const rs2::device& device, rs2_camera_info key,
                               const std::string& fallback = "unknown")
{
    return device.supports(key) ? device.get_info(key) : fallback;
}

inline rs2_stream parse_stream(const std::string& value)
{
    if (value == "color") return RS2_STREAM_COLOR;
    if (value == "infrared" || value == "infra") return RS2_STREAM_INFRARED;
    if (value == "auto") return RS2_STREAM_ANY;
    throw std::runtime_error("Unsupported --stream: " + value);
}

inline rs2_format parse_format(const std::string& value)
{
    if (value == "auto") return RS2_FORMAT_ANY;
    if (value == "yuyv" || value == "yuy2") return RS2_FORMAT_YUYV;
    if (value == "bgr8") return RS2_FORMAT_BGR8;
    if (value == "rgb8") return RS2_FORMAT_RGB8;
    if (value == "y8") return RS2_FORMAT_Y8;
    throw std::runtime_error("Unsupported --format: " + value);
}

inline bool detector_supports(rs2_format format)
{
    return format == RS2_FORMAT_YUYV || format == RS2_FORMAT_BGR8
        || format == RS2_FORMAT_RGB8 || format == RS2_FORMAT_Y8;
}

inline int format_rank(rs2_format format)
{
    // Prefer native YUYV for color: it avoids an SDK RGB conversion buffer,
    // and the detector only needs luminance. Y8 is the native IR equivalent.
    switch (format)
    {
        case RS2_FORMAT_YUYV: return 4;
        case RS2_FORMAT_Y8: return 3;
        case RS2_FORMAT_BGR8: return 2;
        case RS2_FORMAT_RGB8: return 1;
        default: return 0;
    }
}

inline void print_devices(const rs2::device_list& devices, std::ostream& out)
{
    out << "Detected RealSense devices: " << devices.size() << "\n";
    for (std::size_t device_index = 0; device_index < devices.size(); ++device_index)
    {
        auto device = devices[device_index];
        out << "[" << device_index << "] "
            << device_info(device, RS2_CAMERA_INFO_NAME)
            << " serial=" << device_info(device, RS2_CAMERA_INFO_SERIAL_NUMBER)
            << " firmware=" << device_info(device, RS2_CAMERA_INFO_FIRMWARE_VERSION)
            << " product_line=" << device_info(device, RS2_CAMERA_INFO_PRODUCT_LINE)
            << "\n";

        int sensor_index = 0;
        for (auto&& sensor : device.query_sensors())
        {
            out << "  sensor[" << sensor_index++ << "] "
                << (sensor.supports(RS2_CAMERA_INFO_NAME)
                    ? sensor.get_info(RS2_CAMERA_INFO_NAME) : "unknown") << "\n";
            for (auto&& stream_profile : sensor.get_stream_profiles())
            {
                auto video = stream_profile.as<rs2::video_stream_profile>();
                if (!video) continue;
                const bool visual = (video.stream_type() == RS2_STREAM_COLOR
                    || video.stream_type() == RS2_STREAM_INFRARED)
                    && detector_supports(video.format());
                const bool depth = video.stream_type() == RS2_STREAM_DEPTH
                    && video.format() == RS2_FORMAT_Z16;
                if (!visual && !depth) continue;
                out << "    " << rs2_stream_to_string(video.stream_type())
                    << " index=" << video.stream_index()
                    << " " << video.width() << "x" << video.height()
                    << "@" << video.fps()
                    << " " << rs2_format_to_string(video.format()) << "\n";
            }
        }
    }
}

inline rs2::device select_device(const rs2::device_list& devices,
                                 const profile_request& request)
{
    if (devices.size() == 0)
        throw std::runtime_error("No RealSense device detected");

    if (!request.serial.empty())
    {
        for (auto&& device : devices)
        {
            if (device_info(device, RS2_CAMERA_INFO_SERIAL_NUMBER, "")
                == request.serial)
                return device;
        }
        throw std::runtime_error("No device matches serial " + request.serial);
    }

    if (request.device_index < 0
        || request.device_index >= static_cast<int>(devices.size()))
        throw std::runtime_error("--device-index is outside the detected device list");
    return devices[request.device_index];
}

inline selected_profile choose_profile(const rs2::device_list& devices,
                                       const profile_request& request)
{
    auto device = select_device(devices, request);
    auto requested_stream = parse_stream(request.stream);
    auto requested_format = parse_format(request.format);

    struct candidate
    {
        rs2::sensor sensor;
        rs2::video_stream_profile profile;
        std::tuple<int, int, int, int, int> score;
    };
    std::vector<candidate> candidates;

    for (auto&& sensor : device.query_sensors())
    {
        for (auto&& stream_profile : sensor.get_stream_profiles())
        {
            auto video = stream_profile.as<rs2::video_stream_profile>();
            if (!video || !detector_supports(video.format())) continue;

            auto stream = video.stream_type();
            if (stream != RS2_STREAM_COLOR && stream != RS2_STREAM_INFRARED)
                continue;
            if (requested_stream != RS2_STREAM_ANY && stream != requested_stream)
                continue;
            if (request.stream_index >= 0
                && video.stream_index() != request.stream_index) continue;
            if (request.width > 0 && video.width() != request.width) continue;
            if (request.height > 0 && video.height() != request.height) continue;
            if (request.fps > 0 && video.fps() != request.fps) continue;
            if (requested_format != RS2_FORMAT_ANY
                && video.format() != requested_format) continue;

            const int stream_rank = stream == RS2_STREAM_COLOR ? 2 : 1;
            const int pixels = video.width() * video.height();
            const int near_vga = -std::abs(pixels - 640 * 480);
            std::tuple<int, int, int, int, int> score;
            if (request.policy == "quality")
                score = {stream_rank, pixels, video.fps(),
                         format_rank(video.format()), near_vga};
            else if (request.policy == "low-latency")
                score = {stream_rank, video.fps(), near_vga,
                         format_rank(video.format()), pixels};
            else
                throw std::runtime_error("Unsupported --policy: " + request.policy);
            candidates.push_back({sensor, video, score});
        }
    }

    if (candidates.empty())
        throw std::runtime_error(
            "No compatible color/infrared profile matches the request; use --list");

    auto best = std::max_element(candidates.begin(), candidates.end(),
        [](const candidate& left, const candidate& right)
        {
            return left.score < right.score;
        });
    return {device, best->sensor, best->profile};
}

inline selected_profile choose_depth_profile(const rs2::device& device,
                                             const depth_request& request,
                                             const rs2::video_stream_profile& visual)
{
    struct candidate
    {
        rs2::sensor sensor;
        rs2::video_stream_profile profile;
        std::tuple<int, int, int, int> score;
    };
    std::vector<candidate> candidates;
    for (auto&& sensor : device.query_sensors())
    {
        for (auto&& stream_profile : sensor.get_stream_profiles())
        {
            auto video = stream_profile.as<rs2::video_stream_profile>();
            if (!video || video.stream_type() != RS2_STREAM_DEPTH
                || video.format() != RS2_FORMAT_Z16) continue;
            if (request.width > 0 && video.width() != request.width) continue;
            if (request.height > 0 && video.height() != request.height) continue;
            if (request.fps > 0 && video.fps() != request.fps) continue;

            const int fps_match = video.fps() == visual.fps() ? 1 : 0;
            const int dimensions_match =
                video.width() == visual.width() && video.height() == visual.height()
                ? 1 : 0;
            const int pixel_distance = -std::abs(
                video.width() * video.height() - visual.width() * visual.height());
            candidates.push_back({sensor, video,
                {fps_match, dimensions_match, video.fps(), pixel_distance}});
        }
    }
    if (candidates.empty())
        throw std::runtime_error(
            "No Z16 depth profile matches --with-depth request; use --list");
    auto best = std::max_element(candidates.begin(), candidates.end(),
        [](const candidate& left, const candidate& right)
        { return left.score < right.score; });
    return {device, best->sensor, best->profile};
}

inline std::string describe(const selected_profile& selected)
{
    auto profile = selected.profile;
    return device_info(selected.device, RS2_CAMERA_INFO_NAME) + " serial="
        + device_info(selected.device, RS2_CAMERA_INFO_SERIAL_NUMBER)
        + " | " + rs2_stream_to_string(profile.stream_type())
        + "[" + std::to_string(profile.stream_index()) + "] "
        + std::to_string(profile.width()) + "x" + std::to_string(profile.height())
        + "@" + std::to_string(profile.fps()) + " "
        + rs2_format_to_string(profile.format());
}

}  // namespace rs2_latency
